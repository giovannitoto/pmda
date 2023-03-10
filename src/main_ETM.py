#/usr/bin/python

from __future__ import print_function

import torch
import pickle
import numpy as np
import os
import math
import random
import sys
import matplotlib.pyplot as plt
import scipy.io

import src.data as data

from torch import nn, optim, save as torch_save
from torch.nn import functional as F
from pathlib import Path
from gensim.models.fasttext import FastText as FT_gensim
import tracemalloc

from src.etm import ETM
from src.file_io import load_embeddings
from src.utils import nearest_neighbors, get_topic_coherence, get_topic_diversity


def main_ETM(dataset, data_path, emb_file, save_path, model_file, batch_size=1000,
             num_topics=50, rho_size=300, emb_size=300, t_hidden_size=800, theta_act='relu', train_embeddings=0,
             lr=0.005, lr_factor=4.0, epochs=20, mode='train', optimizer='adam', seed=28, enc_drop=0.0, clip=0.0, nonmono=10, wdecay=1.2e-6, anneal_lr=0, bow_norm=1,
             num_words=10, log_interval=2, visualize_every=100000, eval_batch_size=1000, load_from='', tc=0, td=0):
    """
    Args:
    ----------------   data and file related arguments
    dataset          : name of corpus (str)
    data_path        : directory containing data (str)
    emb_file         : word embeddings file, used if train_embeddings=False (str)
    save_path        : path to save results (str)
    model_file       : model file, saved in save_path (str)
    batch_size       : input batch size for training (int)
    ----------------   model-related arguments
    num_topics       : number of topics (int)
    rho_size         : dimension of rho (int)
    emb_size         : dimension of embeddings (int)
    t_hidden_size    : dimension of hidden space of q(theta) (int)
    theta_act        : tanh, softplus, relu, rrelu, leakyrelu, elu, selu, glu (str)
    train_embeddings : whether to fix rho or train it (int)
    ----------------   optimization-related arguments
    lr               : learning rate (float)
    lr_factor        : divide learning rate by this... (float)
    epochs           : number of epochs to train...150 for 20ng 100 for others (int)
    mode             : train or eval model (str)
    optimizer        : choice of optimizer (str)
    seed             : random seed (default: 1) (int)
    enc_drop         : dropout rate on encoder (float)
    clip             : gradient clipping
    nonmono          : number of bad hits allowed
    wdecay           : some l2 regularization (float)
    anneal_lr        : whether to anneal the learning rate or not (int)
    bow_norm         : normalize the bows or not (int)
    ----------------   evaluation, visualization, and logging-related arguments
    num_words        : number of words for topic viz (int)
    log_interval     : when to log training (int)
    visualize_every  : when to visualize results (int)
    eval_batch_size  : input batch size for evaluation (int)
    load_from        : the name of the ckpt to eval from (str)
    tc               : whether to compute topic coherence or not (int)
    td               : whether to compute topic diversity or not (int)
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print('\n')
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)

    print('=*'*100)
    print('Training an Embedded Topic Model on ' + dataset.upper())
    print('=*'*100)

    ## get data
    # 1. vocabulary
    vocab, train, valid, test = data.get_data(os.path.join(data_path))
    vocab_size = len(vocab)

    # 1. training data
    train_tokens = train['tokens']
    train_counts = train['counts']
    num_docs_train = len(train_tokens)

    # 2. dev set
    valid_tokens = valid['tokens']
    valid_counts = valid['counts']
    num_docs_valid = len(valid_tokens)

    # 3. test data
    test_tokens = test['tokens']
    test_counts = test['counts']
    num_docs_test = len(test_tokens)
    test_1_tokens = test['tokens_1']
    test_1_counts = test['counts_1']
    num_docs_test_1 = len(test_1_tokens)
    test_2_tokens = test['tokens_2']
    test_2_counts = test['counts_2']
    num_docs_test_2 = len(test_2_tokens)

    embeddings = None
    if not train_embeddings:
        embeddings = load_embeddings(emb_file, emb_size, vocab)
        embeddings = torch.from_numpy(embeddings).to(device)
        embeddings_dim = embeddings.size()

    ## define checkpoint
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    if mode == 'eval':
        ckpt = load_from
    else:
        ckpt = Path.cwd().joinpath(save_path, model_file)

    ## define model and optimizer
    model = ETM(num_topics, vocab_size, t_hidden_size, rho_size, emb_size, theta_act, embeddings, train_embeddings, enc_drop).to(device)

    print('ETM architecture: {}'.format(model))

    optimizer = model.get_optimizer(optimizer, lr, wdecay)

    tracemalloc.start()
    if mode == 'train':
        ## train model on data
        best_epoch = 0
        best_val_ppl = 1e9
        all_val_ppls = []
        for epoch in range(0, epochs):
            print("I am training for epoch", epoch)
            model.train_for_epoch(epoch, num_docs_train, batch_size, train_tokens, train_counts, vocab_size, bow_norm, clip, log_interval)
            val_ppl = model.evaluate(eval_batch_size, num_docs_valid, num_docs_test, num_docs_test_1, test_1_tokens, test_1_counts,
                                     test_2_tokens, test_2_counts, vocab, bow_norm, train_tokens, 'val', tc, td)
            print("The validation scores", val_ppl)
            if val_ppl < best_val_ppl:
                with open(ckpt, 'wb') as f:
                    torch.save(model, f)
                best_epoch = epoch
                best_val_ppl = val_ppl
            else:
                ## check whether to anneal lr
                lr = optimizer.param_groups[0]['lr']
                if anneal_lr and (len(all_val_ppls) > nonmono and val_ppl > min(all_val_ppls[:-nonmono]) and lr > 1e-5):
                    optimizer.param_groups[0]['lr'] /= lr_factor
            if epoch > 0 and epoch % visualize_every == 0:
                model.visualize(batch_size, epochs, num_words, vocab, True)
            all_val_ppls.append(val_ppl)
        with open(ckpt, 'rb') as f:
            model = torch.load(f)
        model = model.to(device)
        val_ppl = model.evaluate(eval_batch_size, num_docs_valid, num_docs_test, num_docs_test_1, test_1_tokens, test_1_counts,
                                 test_2_tokens, test_2_counts, vocab, bow_norm, train_tokens, 'val', tc, td)
    else:
        with open(ckpt, 'rb') as f:
            model = torch.load(f)
        model = model.to(device)
        model.eval()

        with torch.no_grad():
            ## get document completion perplexities
            test_ppl = model.evaluate(eval_batch_size, num_docs_valid, num_docs_test, num_docs_test_1, test_1_tokens, test_1_counts,
                                      test_2_tokens, test_2_counts, vocab, bow_norm, train_tokens, 'val', False, False)
            ## get most used topics
            indices = torch.tensor(range(num_docs_train))
            indices = torch.split(indices, batch_size)
            theta_tr = np.array([], dtype=np.int64).reshape(0,num_topics)
            thetaAvg = torch.zeros(1, num_topics).to(device)
            theta_weighted_average = torch.zeros(1, num_topics).to(device)
            cnt = 0
            for idx, indice in enumerate(indices):
                data_batch = data.get_batch(train_tokens, train_counts, indice, vocab_size, device)
                sums = data_batch.sum(1).unsqueeze(1)
                cnt += sums.sum(0).squeeze().cpu().numpy()
                if bow_norm:
                    normalized_data_batch = data_batch / sums
                else:
                    normalized_data_batch = data_batch
                theta, _ = model.get_theta(normalized_data_batch)
                theta_tr = np.vstack([theta_tr, theta.cpu().numpy()])
                thetaAvg += theta.sum(0).unsqueeze(0) / num_docs_train
                weighed_theta = sums * theta
                theta_weighted_average += weighed_theta.sum(0).unsqueeze(0)
                if idx % 100 == 0 and idx > 0:
                    print('batch: {}/{}'.format(idx, len(indices)))
            theta_weighted_average = theta_weighted_average.squeeze().cpu().numpy() / cnt
            #print('\nThe 10 most used topics are {}'.format(theta_weighted_average.argsort()[::-1]))
            #print('The weighs are {}'.format(sorted(theta_weighted_average, reverse=True)))
            print('Most used topics:')
            for ttt in theta_weighted_average.argsort()[::-1]:
                print("Topic "+str(ttt).rjust(3)+" :  ", theta_weighted_average[ttt])

            ## show topics
            beta = model.get_beta()
            print('\nTop', num_words, 'words per topic:')
            for k in range(num_topics):
                gamma = beta[k]
                top_words = list(gamma.cpu().numpy().argsort()[-num_words+1:][::-1])
                topic_words = [vocab[a] for a in top_words]
                print('Topic {}: {}'.format(k, topic_words))

            # compute topic coherence and topic diversity
            beta = beta.data.cpu().numpy()
            if tc:
                TC, _ = get_topic_coherence(beta, train_tokens, vocab)
            else:
                TC = None
            if td:
                TD = get_topic_diversity(beta, 25)
            else:
                TD = None
            # convert torch.tensor to np.array
            rho = model.rho.cpu().numpy()
            alpha = model.alphas.weight.cpu().numpy()
            parameters = {'vocab': vocab, 'tc': TC, 'td': TD, 'rho': rho, 'alpha': alpha, "beta": beta, "theta": theta_tr}
            # save word/topic embeddings, beta, theta
            torch_save(parameters, ckpt + "_parameters.pt")


            if train_embeddings:
                ## show etm embeddings
                try:
                    rho_etm = model.rho.weight.cpu()
                except:
                    rho_etm = model.rho.cpu()
                queries = ['felix', 'covid', 'pprd', '100jours', 'beni', 'adf', 'muyembe', 'fally']
                print('\n')
                print('ETM embeddings...')
                for word in queries:
                    print('word: {} .. etm neighbors: {}'.format(word, nearest_neighbors(word, rho_etm, vocab, 20)))
                print('\n')

    current, peak = tracemalloc.get_traced_memory()
    print(f"Current memory usage is {current / 10**6}MB; Peak was {peak / 10**6}MB")
    tracemalloc.stop()
