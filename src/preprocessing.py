import csv
import itertools
import json
import numpy as np
import os
import pickle
import random
import string

from scipy import sparse
from scipy.io import savemat, loadmat
from sklearn.feature_extraction.text import CountVectorizer

def preprocessing(data_path, docs, timestamps=[], stopwords=[], min_df=1, max_df=0.7, data_split=[0.85,0.1,0.05], seed=28):
    """
    data_path  : folder in which the files will be stored
    docs       : list of strings corresponding to the texts of the documents
    timestamps : list of strings corresponding to the timestamps of the documents
    min_df     : minimum document frequency (una parola deve comparire in al massimo il max_df% dei documenti)
    max_df     : maximum document frequency (una parola deve comparire in almeno min_df documenti)
    data_split : list of 3 numbers which sum to 1 specifying the dimension of train, test and validation set
    seed       : seed
    """
    print('***************')
    print('Preparing data:')
    # Set seed
    np.random.seed(seed)
    random.seed(seed)

    path_save = './' + str(data_path) + '/'
    if not os.path.exists(path_save):
        os.makedirs(path_save)
    else:
        raise ValueError('"path_save" not valid: the folder already exists.')

    # Check docs and timestamps
    if not timestamps:
        # If timestamps are not available, assign all documents to the same timestamp
        timestamps = ['no_timestamps'] * len(docs)
    elif len(docs) != len(timestamps):
        raise ValueError('"docs" and "timestamps" not valid: they must be lists of the same length.')

    # Create count vectorizer
    print('counting document frequency of words...')
    cvectorizer = CountVectorizer(min_df=min_df, max_df=max_df, stop_words=None)
    cvz = cvectorizer.fit_transform(docs).sign()  # (D, V) sparse matrix

    # Get vocabulary
    print('building the vocabulary...')
    sum_counts = cvz.sum(axis=0)  # (1, V) numpy matrix
    v_size = sum_counts.shape[1]  # V = v_size
    sum_counts_np = np.zeros(v_size, dtype=int)
    for v in range(v_size):
        sum_counts_np[v] = sum_counts[0,v]
    word2id = dict([(w, cvectorizer.vocabulary_.get(w)) for w in cvectorizer.vocabulary_])  # dict with V elements
    id2word = dict([(cvectorizer.vocabulary_.get(w), w) for w in cvectorizer.vocabulary_])  # dict with V elements
    del cvectorizer
    print('  initial vocabulary size: V={}'.format(v_size))

    # Sort elements in vocabulary
    idx_sort = np.argsort(sum_counts_np)
    vocab_aux = [id2word[idx_sort[cc]] for cc in range(v_size)]

    # Filter out stopwords (if any)
    vocab_aux = [w for w in vocab_aux if w not in stopwords]
    print('  vocabulary size after removing stopwords from list: V={}'.format(len(vocab_aux)))

    # Create dictionary and inverse dictionary
    vocab = vocab_aux
    del vocab_aux
    word2id = dict([(w, j) for j, w in enumerate(vocab)])
    id2word = dict([(j, w) for j, w in enumerate(vocab)])

    # Create mapping of timestamps
    all_times = sorted(set(timestamps))
    time2id = dict([(t, i) for i, t in enumerate(all_times)])  # dict with different observed times
    id2time = dict([(i, t) for i, t in enumerate(all_times)])  # dict with different observed times
    time_list = [id2time[i] for i in range(len(all_times))]    # list containing the different observed times

    # Split in train/test/valid
    print('tokenizing documents and splitting into train/test/valid...')
    num_docs = cvz.shape[0]
    trSize = int(np.floor(data_split[0]*num_docs))
    tsSize = int(np.floor(data_split[1]*num_docs))
    vaSize = int(num_docs - trSize - tsSize)
    del cvz
    idx_permute = np.random.permutation(num_docs).astype(int)

    # Remove words not in train corpus
    vocab = list(set([w for idx_d in range(trSize) for w in docs[idx_permute[idx_d]].split() if w in word2id]))
    word2id = dict([(w, j) for j, w in enumerate(vocab)])
    id2word = dict([(j, w) for j, w in enumerate(vocab)])
    print('  vocabulary after removing words not in train: {}'.format(len(vocab)))

    # Bag-of-Words (BoW) representation of the documents, i.e., docs_tr/docs_ts/docs_va are lists of lists of id
    docs_tr = [[word2id[w] for w in docs[idx_permute[idx_d]].split() if w in word2id] for idx_d in range(trSize)]
    docs_ts = [[word2id[w] for w in docs[idx_permute[idx_d+trSize]].split() if w in word2id] for idx_d in range(tsSize)]
    docs_va = [[word2id[w] for w in docs[idx_permute[idx_d+trSize+tsSize]].split() if w in word2id] for idx_d in range(vaSize)]

    # timestamps of the documents, i.e., timestamps_tr/timestamps_ts/timestamps_va are lists of id
    timestamps_tr = [time2id[timestamps[idx_permute[idx_d]]] for idx_d in range(trSize)]
    timestamps_ts = [time2id[timestamps[idx_permute[idx_d+trSize]]] for idx_d in range(tsSize)]
    timestamps_va = [time2id[timestamps[idx_permute[idx_d+trSize+tsSize]]] for idx_d in range(vaSize)]

    # indices of the documents, i.e., indices_tr/indices_ts/indices_va are lists of integers
    indices_tr = [int(idx_permute[idx_d]) for idx_d in range(trSize)]
    indices_ts = [int(idx_permute[idx_d+trSize]) for idx_d in range(tsSize)]
    indices_va = [int(idx_permute[idx_d+trSize+tsSize]) for idx_d in range(vaSize)]

    # Remove unused variables
    del docs

    print('  number of documents (train): {} [this should be equal to {} and {}]'.format(len(docs_tr), trSize, len(timestamps_tr)))
    print('  number of documents (test): {} [this should be equal to {} and {}]'.format(len(docs_ts), tsSize, len(timestamps_ts)))
    print('  number of documents (valid): {} [this should be equal to {} and {}]'.format(len(docs_va), vaSize, len(timestamps_va)))

    # Remove empty documents
    print('removing empty documents...')

    def remove_empty(in_docs, in_timestamps, in_indices):
        out_docs = []
        out_timestamps = []
        out_indices = []
        for ii, doc in enumerate(in_docs):
            if(doc!=[]):
                out_docs.append(doc)
                out_timestamps.append(in_timestamps[ii])
                out_indices.append(in_indices[ii])
        return out_docs, out_timestamps, out_indices

    def remove_by_threshold(in_docs, in_timestamps, in_indices, thr):
        out_docs = []
        out_timestamps = []
        out_indices = []
        for ii, doc in enumerate(in_docs):
            if(len(doc)>thr):
                out_docs.append(doc)
                out_timestamps.append(in_timestamps[ii])
                out_indices.append(in_indices[ii])
        return out_docs, out_timestamps, out_indices

    # Remove empty documents, i.e. they contain only words not in the vocabulary of train corpus
    docs_tr, timestamps_tr, indices_tr = remove_empty(docs_tr, timestamps_tr, indices_tr)
    docs_ts, timestamps_ts, indices_ts = remove_empty(docs_ts, timestamps_ts, indices_ts)
    docs_va, timestamps_va, indices_va = remove_empty(docs_va, timestamps_va, indices_va)
    # Remove test documents with length=1 (or less)
    docs_ts, timestamps_ts, indices_ts = remove_by_threshold(docs_ts, timestamps_ts, indices_ts, 1)

    # Split documents in test set in 2 halves
    print('splitting test documents in 2 halves...')
    docs_ts_h1 = [[w for i,w in enumerate(doc) if i<=len(doc)/2.0-1] for doc in docs_ts]
    docs_ts_h2 = [[w for i,w in enumerate(doc) if i>len(doc)/2.0-1] for doc in docs_ts]

    # ----------------------------------------------------------------
    # DOCUMENT PRE-PROCESSING ENDS HERE: NOW WE JUST HAVE TO SAVE THEM
    # ----------------------------------------------------------------
    
    print('saving indices...')
    # Write information useful for exploratory analysis
    info_json = {"indices_tr": indices_tr,
                 "indices_ts": indices_ts,
                 "indices_va": indices_va,
                 "docs_tr": docs_tr,
                 "vocab_tr": vocab}
    with open(path_save + 'info.json', 'w') as f:
        f.write(json.dumps(info_json, indent = 2))

    # Getting lists of words and doc_indices
    print('creating lists of words...')

    def create_list_words(in_docs):
        return [x for y in in_docs for x in y]

    words_tr = create_list_words(docs_tr)
    words_ts = create_list_words(docs_ts)
    words_ts_h1 = create_list_words(docs_ts_h1)
    words_ts_h2 = create_list_words(docs_ts_h2)
    words_va = create_list_words(docs_va)

    print('  len(words_tr):\t', len(words_tr))
    print('  len(words_ts):\t', len(words_ts))
    print('  len(words_ts_h1):\t', len(words_ts_h1))
    print('  len(words_ts_h2):\t', len(words_ts_h2))
    print('  len(words_va):\t', len(words_va))

    # Get doc indices
    print('getting doc indices...')

    def create_doc_indices(in_docs):
        aux = [[j for i in range(len(doc))] for j, doc in enumerate(in_docs)]
        return [int(x) for y in aux for x in y]

    doc_indices_tr = create_doc_indices(docs_tr)
    doc_indices_ts = create_doc_indices(docs_ts)
    doc_indices_ts_h1 = create_doc_indices(docs_ts_h1)
    doc_indices_ts_h2 = create_doc_indices(docs_ts_h2)
    doc_indices_va = create_doc_indices(docs_va)

    print('  len(np.unique(doc_indices_tr)): {} [this should be {}]'.format(len(np.unique(doc_indices_tr)), len(docs_tr)))
    print('  len(np.unique(doc_indices_ts)): {} [this should be {}]'.format(len(np.unique(doc_indices_ts)), len(docs_ts)))
    print('  len(np.unique(doc_indices_ts_h1)): {} [this should be {}]'.format(len(np.unique(doc_indices_ts_h1)), len(docs_ts_h1)))
    print('  len(np.unique(doc_indices_ts_h2)): {} [this should be {}]'.format(len(np.unique(doc_indices_ts_h2)), len(docs_ts_h2)))
    print('  len(np.unique(doc_indices_va)): {} [this should be {}]'.format(len(np.unique(doc_indices_va)), len(docs_va)))

    # Write raw texts of train/test/val set
    with open(path_save + 'text_tr.txt', 'w') as f:
        for doc in docs_tr:
            f.write(' '.join([id2word[idx] for idx in doc]) + '\n')

    with open(path_save + 'text_ts.txt', 'w') as f:
        for doc in docs_ts:
            f.write(' '.join([id2word[idx] for idx in doc]) + '\n')

    with open(path_save + 'text_va.txt', 'w') as f:
        for doc in docs_va:
            f.write(' '.join([id2word[idx] for idx in doc]) + '\n')

    # Number of documents in each set
    n_docs_tr = len(docs_tr)
    n_docs_ts = len(docs_ts)
    n_docs_ts_h1 = len(docs_ts_h1)
    n_docs_ts_h2 = len(docs_ts_h2)
    n_docs_va = len(docs_va)

    # Remove unused variables
    del docs_tr
    del docs_ts
    del docs_ts_h1
    del docs_ts_h2
    del docs_va

    # Create bow representation
    print('creating bow representation...')

    def create_bow(doc_indices, words, n_docs, vocab_size):
        return sparse.coo_matrix(([1]*len(doc_indices),(doc_indices, words)), shape=(n_docs, vocab_size)).tocsr()

    bow_tr = create_bow(doc_indices_tr, words_tr, n_docs_tr, len(vocab))
    bow_ts = create_bow(doc_indices_ts, words_ts, n_docs_ts, len(vocab))
    bow_ts_h1 = create_bow(doc_indices_ts_h1, words_ts_h1, n_docs_ts_h1, len(vocab))
    bow_ts_h2 = create_bow(doc_indices_ts_h2, words_ts_h2, n_docs_ts_h2, len(vocab))
    bow_va = create_bow(doc_indices_va, words_va, n_docs_va, len(vocab))

    # Write the vocabulary
    # with open(path_save + 'vocab.txt', 'w') as f:
    #     for v in vocab:
    #         f.write(v + '\n')
    with open(path_save + 'vocab.pkl', 'wb') as f:
        pickle.dump(vocab, f)
    del vocab

    # Write the timestamps
    # with open(path_save + 'timestamps.txt', 'w') as f:
    #     for t in time_list:
    #         f.write(t + '\n')
    # with open(path_save + 'timestamps.pkl', 'wb') as f:
    #     pickle.dump(time_list, f)

    # Remove unused variables
    del words_tr
    del words_ts
    del words_ts_h1
    del words_ts_h2
    del words_va
    del doc_indices_tr
    del doc_indices_ts
    del doc_indices_ts_h1
    del doc_indices_ts_h2
    del doc_indices_va

    # Save timestamps alone
    savemat(path_save + 'bow_tr_timestamps.mat', {'timestamps': timestamps_tr}, do_compression=True)
    savemat(path_save + 'bow_ts_timestamps.mat', {'timestamps': timestamps_ts}, do_compression=True)
    savemat(path_save + 'bow_va_timestamps.mat', {'timestamps': timestamps_va}, do_compression=True)

    # Split bow intro token/value pairs
    print('splitting bow intro token/value pairs and saving to disk...')

    def split_bow(bow_in, n_docs):
        indices = [[w for w in bow_in[doc,:].indices] for doc in range(n_docs)]
        counts = [[c for c in bow_in[doc,:].data] for doc in range(n_docs)]
        return indices, counts

    bow_tr_tokens, bow_tr_counts = split_bow(bow_tr, n_docs_tr)
    savemat(path_save + 'bow_tr_tokens.mat', {'tokens': bow_tr_tokens}, do_compression=True)
    savemat(path_save + 'bow_tr_counts.mat', {'counts': bow_tr_counts}, do_compression=True)
    del bow_tr
    del bow_tr_tokens
    del bow_tr_counts

    bow_ts_tokens, bow_ts_counts = split_bow(bow_ts, n_docs_ts)
    savemat(path_save + 'bow_ts_tokens.mat', {'tokens': bow_ts_tokens}, do_compression=True)
    savemat(path_save + 'bow_ts_counts.mat', {'counts': bow_ts_counts}, do_compression=True)
    del bow_ts
    del bow_ts_tokens
    del bow_ts_counts

    bow_ts_h1_tokens, bow_ts_h1_counts = split_bow(bow_ts_h1, n_docs_ts_h1)
    savemat(path_save + 'bow_ts_h1_tokens.mat', {'tokens': bow_ts_h1_tokens}, do_compression=True)
    savemat(path_save + 'bow_ts_h1_counts.mat', {'counts': bow_ts_h1_counts}, do_compression=True)
    del bow_ts_h1
    del bow_ts_h1_tokens
    del bow_ts_h1_counts

    bow_ts_h2_tokens, bow_ts_h2_counts = split_bow(bow_ts_h2, n_docs_ts_h2)
    savemat(path_save + 'bow_ts_h2_tokens.mat', {'tokens': bow_ts_h2_tokens}, do_compression=True)
    savemat(path_save + 'bow_ts_h2_counts.mat', {'counts': bow_ts_h2_counts}, do_compression=True)
    del bow_ts_h2
    del bow_ts_h2_tokens
    del bow_ts_h2_counts

    bow_va_tokens, bow_va_counts = split_bow(bow_va, n_docs_va)
    savemat(path_save + 'bow_va_tokens.mat', {'tokens': bow_va_tokens}, do_compression=True)
    savemat(path_save + 'bow_va_counts.mat', {'counts': bow_va_counts}, do_compression=True)
    del bow_va
    del bow_va_tokens
    del bow_va_counts

    print('Data ready!')
    print('***********')
