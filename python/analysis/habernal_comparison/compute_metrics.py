'''
Load a results file generated by "tests.py". Compute the key metrics for pairwise preference labeling:

- F1 score
- AUC (can also be computed from precision and recall, the total numbers of each class in the gold standard and the 
total number of instances marked as positive, if the method gives only discrete labels). 
- Cross entropy error

Compute key ranking metrics:

- Kendall's tau
- What was used in Habernal paper?

Plot results? Could show a bar chart to compare performance when we have a lot of methods. Mainly, we can use tables
with median and quartiles (check against habernal paper to ensure it is comparable).

Created on 18 May 2017

@author: edwin
'''
import sys
import os
from scipy.stats.stats import ttest_ind
from scipy.stats.morestats import wilcoxon

sys.path.append("./python")
sys.path.append("./python/analysis")

import numpy as np
import pandas as pd
import pickle
from sklearn.metrics import f1_score, accuracy_score, roc_auc_score, log_loss
from scipy.stats import pearsonr, spearmanr, kendalltau
from data_loader import data_root_dir, load_train_test_data, load_ling_features
import datetime, time

data_root_dir = os.path.abspath("./data/")
expt_root_dir = 'personalised_10_from_cluster'#'crowdsourcing_argumentation_opt/'
resultsfile_template = 'habernal_%s_%s_%s_%s_acc%.2f_di%.2f'

def get_fold_data(data, f, expt_settings, flip_labels=False):
    # discrete labels are 0, 1 or 2
    gold_disc = np.array(data[3])
    pred_disc = np.array(data[1]) * 2
    if pred_disc.ndim == 1:
        pred_disc = pred_disc[:, np.newaxis]
    #if expt_settings['method'] == 'SVM':
    #    pred_disc = 2 - pred_disc

    # probabilities
    gold_prob = gold_disc / 2.0
    pred_prob = np.array(data[0])
    if pred_prob.ndim == 1:
        pred_prob = pred_prob[:, np.newaxis]
    #if expt_settings['method'] == 'SVM':
    #    pred_prob = 1 - pred_prob

    # scores used to rank
    if data[4] is not None and len(data[4]) > 0:
        gold_rank = np.array(data[4])
    else:
        gold_rank = None

    if data[2] is not None and (len(data[2]) > 0):# or data[2].item() is not None):
        pred_rank = np.array(data[2])

        if pred_rank.ndim == 1:
            pred_rank = pred_rank[:, np.newaxis]
    else:
        gold_rank = None
        pred_rank = None

    if len(data) > 8 and data[8] is not None:
        pred_tr_disc = np.round(np.array(data[8])) * 2
        pred_tr_prob = np.array(data[8])
        pred_tr_rank = np.array(data[9])
    else:
        pred_tr_disc = None
        pred_tr_prob = None
        pred_tr_rank = None

    if flip_labels:
        pred_disc = 2 - pred_disc

        pred_prob = 1 - pred_prob
        if pred_rank is not None:
            pred_rank = -pred_rank
        if pred_tr_disc is not None:
            pred_tr_disc = 2 - pred_tr_disc
        if pred_tr_prob is not None:
            pred_tr_prob = 1 - pred_tr_prob

    #any postprocessing e.g. to remove errors when saving data
    postprocced = False

    if pred_rank is not None and gold_rank is not None and pred_rank.shape[0] == 1052 and gold_rank.shape[0] != 1052:
        # we predicted whole dataeset instead of the subset
        from tests import get_fold_regression_data
        if expt_settings['fold_order'] is not None:
            fold = expt_settings['fold_order'][f]
        else:
            fold = list(expt_settings['folds'].keys())[f]
        _, docids = load_ling_features(expt_settings['dataset'])
        _, _, _, item_idx_ranktest, _, _ = get_fold_regression_data(expt_settings['folds_regression'], fold, docids)
        pred_rank = pred_rank[item_idx_ranktest, :]
        postprocced = True
        print("Postprocessed: %i, %i" % (pred_rank.shape[0], gold_rank.shape[0]))

    # Considering only the labels where a confident prediction has been made... In this case the metrics should be
    # shown alongside coverage.
    #     gold_disc = gold_disc[np.abs(pred_prob.flatten() - 0.5) > 0.3]
    #     pred_disc = pred_disc[np.abs(pred_prob.flatten() - 0.5) > 0.3]
    #
    #     gold_prob = gold_prob[np.abs(pred_prob.flatten() - 0.5) > 0.3]
    #     pred_prob = pred_prob[np.abs(pred_prob.flatten() - 0.5) > 0.3]

    return gold_disc, pred_disc, gold_prob, pred_prob, gold_rank, pred_rank, pred_tr_disc, pred_tr_prob, pred_tr_rank, \
           postprocced

def collate_AL_results(AL_rounds, results, combined_labels, label):
    for r, AL_round in enumerate(AL_rounds):
        mean_results_round = pd.DataFrame(results[:, :, -1, r].reshape(1, results.shape[0]*results.shape[1]), 
                                          columns=combined_labels, index=[AL_round])
        if r == 0:
            mean_results = mean_results_round
        else:
            mean_results = mean_results.append(mean_results_round)
            
    print(label)
    for col in mean_results.columns:
        print(mean_results[col])
        
    return mean_results

def get_results_dir(data_root_dir, resultsfile_template, expt_settings, foldername=expt_root_dir):
    resultsdir = os.path.join(data_root_dir, 'outputdata', foldername, \
            resultsfile_template % (expt_settings['dataset'], expt_settings['method'], 
                expt_settings['feature_type'], expt_settings['embeddings_type'], expt_settings['acc'], 
                expt_settings['di']))
            
    print(expt_settings['foldorderfile'])
            
    if expt_settings['foldorderfile'] is not None:
        expt_settings['fold_order'] = np.genfromtxt(os.path.expanduser(expt_settings['foldorderfile']), 
                                                    dtype=str)
    elif os.path.isfile(resultsdir + '/foldorder.txt'):
        expt_settings['fold_order'] = np.genfromtxt(os.path.expanduser(resultsdir + '/foldorder.txt'), 
                                                    dtype=str)
    else:
        expt_settings['fold_order'] = None
        
    return resultsdir    

def load_results_data(data_root_dir, resultsfile_template, expt_settings, max_no_folds, foldername=expt_root_dir):
    # start by loading the old-style data
    resultsfile = os.path.join(data_root_dir, 'outputdata/', foldername, \
            resultsfile_template % (expt_settings['dataset'], expt_settings['method'], 
                expt_settings['feature_type'], expt_settings['embeddings_type'], expt_settings['acc'], 
                expt_settings['di']) + '_test.pkl')
    
    resultsdir = get_results_dir(data_root_dir, resultsfile_template, expt_settings, foldername)                       
    
    nFolds = max_no_folds
    if os.path.isfile(resultsfile): 
        
        with open(resultsfile, 'rb') as fh:
            data = pickle.load(fh, encoding='latin1')
                
        if nFolds < 1:
            nFolds = len(data[0])
    else:
        data = None
        
    return data, nFolds, resultsdir, resultsfile          

def compute_metrics(expt_settings, methods, datasets, feature_types, embeddings_types, accuracy=1.0, di=0, npairs=0,
                    tag='', remove_seen_from_mean=False, max_fold_no=32, min_fold_no=0,
                    compute_tr_performance=False, flip_labels=[], foldername=expt_root_dir, split_by_person=False):
        
    expt_settings['acc'] = accuracy
    expt_settings['di'] = di
    
    row_index = np.zeros(len(methods) * len(datasets), dtype=object)
    columns = np.zeros(len(feature_types) * len(embeddings_types), dtype=object)
    
    row = 0
    
    if expt_settings['di'] == 0 or np.ceil(np.float(npairs) / np.float(expt_settings['di'])) == 0:
        AL_rounds = np.array([0]).astype(int)
    else:
        AL_rounds = np.arange(expt_settings['di'], npairs+expt_settings['di'], expt_settings['di'], dtype=int)
        #np.arange( np.ceil(np.float(npairs) / np.float(expt_settings['di'])), dtype=int)    
    
    if tag == '':
        ts = time.time()
        tag = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d-%H-%M-%S') 
    
    for d, dataset_next in enumerate(datasets):
            
        docids = None
        
        if expt_settings['dataset'] != dataset_next or expt_settings['folds'] is None:
            expt_settings['dataset'] = dataset_next            
            expt_settings['folds'], expt_settings['folds_test'], expt_settings['folds_regression'], _, _, _ = \
                load_train_test_data(expt_settings['dataset'])


        for m, expt_settings['method'] in enumerate(methods):
        
            if d == 0 and m == 0:
                
                if expt_settings['di'] == 0:
                    results_shape = (len(methods) * len(datasets), 
                                 len(feature_types) * len(embeddings_types), 
                                 len(expt_settings['folds']) + 1,
                                 1)
                else:
                    results_shape = (len(methods) * len(datasets),
                                 len(feature_types) * len(embeddings_types), 
                                 len(expt_settings['folds']) + 1, 
                                 int(npairs / expt_settings['di']))
                
                results_f1      = np.zeros(results_shape)
                results_acc     = np.zeros(results_shape)
                results_logloss = np.zeros(results_shape)
                results_auc     = np.zeros(results_shape)
            
                results_pearson  = np.zeros(results_shape)
                results_spearman = np.zeros(results_shape)
                results_kendall  = np.zeros(results_shape)

                tr_results_f1      = np.zeros(results_shape)
                tr_results_acc     = np.zeros(results_shape)
                tr_results_logloss = np.zeros(results_shape)
                tr_results_auc     = np.zeros(results_shape)
                tr_results_tau     = np.zeros(results_shape)
            
            row_index[row] = expt_settings['method'] + ', ' + expt_settings['dataset']
            col = 0
            
            for expt_settings['feature_type'] in feature_types:
                if expt_settings['feature_type'] == 'ling':
                    embeddings_to_use = ['']
                else:
                    embeddings_to_use = embeddings_types
                for expt_settings['embeddings_type'] in embeddings_to_use:
                    data, nFolds, resultsdir, resultsfile = load_results_data(data_root_dir, resultsfile_template,
                                                                              expt_settings, max_fold_no, foldername)
                    min_folds = min_fold_no
                    foldrange = None

                    coverage = 0.0

                    for f in range(nFolds):
                        print("Processing fold %i" % f)
                        if expt_settings['fold_order'] is None: # fall back to the order on the current machine
                            fold = list(expt_settings['folds'].keys())[f]
                        else:
                            fold = expt_settings['fold_order'][f]
                            print('Processing fold %s' % fold)
                            if fold[-2] == "'" and fold[0] == "'":
                                fold = fold[1:-2]
                            elif fold[-1] == "'" and fold[0] == "'":
                                fold = fold[1:-1]  
                            expt_settings['fold_order'][f] = fold

                        # look for new-style data in separate files for each fold. Prefer new-style if both are found.
                        foldfile = resultsdir + '/fold%i.pkl' % f
                        if os.path.isfile(foldfile):
                            with open(foldfile, 'rb') as fh:
                                try:
                                    data_f = pickle.load(fh, encoding='latin1')
                                except:
                                    print('The pickle file could not be loaded, skipping this fold: %s' % foldfile)
                                    continue

                        else: # convert the old stuff to new stuff
                            if data is None:
                                min_folds = f+1
                                print('Skipping fold with no data %i' % f)
                                print("Skipping results for %s, %s, %s, %s" % (expt_settings['method'], 
                                                                               expt_settings['dataset'], 
                                                                               expt_settings['feature_type'], 
                                                                               expt_settings['embeddings_type']))
                                print("Skipped filename was: %s, old-style results file would be %s" % (foldfile, 
                                                                                                        resultsfile))
                                continue
                            
                            if not os.path.isdir(resultsdir):
                                os.mkdir(resultsdir)
                            data_f = []
                            for thing in data:
                                if f in thing:
                                    data_f.append(thing[f])
                                else:
                                    data_f.append(thing)
                            with open(foldfile, 'wb') as fh:
                                pickle.dump(data_f, fh)
                        
                        gold_disc, pred_disc, gold_prob, pred_prob, gold_rank, pred_rank, pred_tr_disc, \
                            pred_tr_prob, pred_tr_rank, postprocced = get_fold_data(data_f, f, expt_settings,
                                                                                          flip_labels=m in flip_labels)
                        if postprocced: # data was postprocessed and needs saving
                            with open(foldfile, 'wb') as fh:
                                pickle.dump(data_f, fh)
                        if pred_tr_disc is not None:                                                                         
                            print(str(pred_tr_disc.shape) + ', ' + str(pred_prob.shape) + ', ' + str(
                                                                    pred_tr_disc.shape[0]+pred_prob.shape[0]))

                        valididxs = gold_disc != 1
                        gold_prob = gold_prob[valididxs]
                        gold_disc = gold_disc[valididxs]
                        pred_disc = pred_disc[valididxs, :]
                        pred_prob = pred_prob[valididxs, :]

                        if split_by_person:
                            _, _, _, _, tr_turkers, _, _ = expt_settings['folds'].get(fold)["training"]
                            _, _, test_labels, _, test_turkers, _, _ = expt_settings['folds'].get(fold)["test"]

                            valid_turk_idxs = np.in1d(test_turkers, tr_turkers)
                            test_turkers = np.array(test_turkers)[valid_turk_idxs]

                            tr_turkers = np.array(tr_turkers)

                            turker_tr_counts = np.array([np.sum(tr_turkers == tid) for tid in test_turkers])[valididxs]
                            turker_conf_filter = 0
                            conflevel = 0
                            #confidxs = np.argsort(np.abs(pred_prob.flatten() - 0.5))[int(len(pred_prob)*conflevel):].flatten() #
                            confidxs = np.argwhere(turker_tr_counts > turker_conf_filter).flatten()
                            print('No. confident workers: %i ' % np.unique(test_turkers[valididxs][confidxs]).size)

                            gold_disc = gold_disc[confidxs]
                            pred_disc = pred_disc[confidxs, :]
                            gold_prob = gold_prob[confidxs]
                            pred_prob = pred_prob[confidxs, :]
                            #pred_prob = 0.5 + np.abs(pred_prob - 0.5)**0.4 * (pred_prob > 0.5) - np.abs(pred_prob - 0.5)**0.4 * (pred_prob < 0.5)

                            print(pred_prob.flatten()[:5])


                            # confidxs = (pred_prob[:, AL_round] > 0.7) | (pred_prob[:, AL_round] < 0.3)
                            print('Confident data points: %i / %i' % (len(confidxs), len(pred_prob.flatten())))

                            coverage += len(confidxs) / float(len(pred_prob.flatten()))

                        for AL_round, _ in enumerate(AL_rounds):
                            #print "fold %i " % f
                            #print AL_round
                            if AL_round >= pred_disc.shape[1]:
                                continue

                            if split_by_person:
                                # compute the metrics separately for each turker because the gold scores between
                                # turkers are not comparable.
                                test_turkers = np.array([tid.strip() for tid in test_turkers[valididxs][confidxs]])

                                valid_turker_count = 0

                                for tid in np.unique(test_turkers):
                                    tidxs = test_turkers == tid

                                    if np.sum(test_turkers == tid) < 2 or \
                                        np.sum(tr_turkers == tid) <= turker_conf_filter or \
                                        np.unique(gold_disc[tidxs]).size < 1:
                                        continue

                                    f1 = f1_score(gold_disc[tidxs], pred_disc[tidxs, AL_round], average='macro')
                                    acc = accuracy_score(gold_disc[tidxs], pred_disc[tidxs, AL_round])
                                    cee = log_loss(gold_prob[tidxs], pred_prob[tidxs, AL_round], labels=[0,1])
                                    if np.unique(gold_disc[tidxs]).size < 2:
                                        auc = 1
                                    else:
                                        auc = roc_auc_score(gold_prob[tidxs], pred_prob[tidxs, AL_round])  #

                                    if not np.isnan(f1) and not np.isnan(acc) and not np.isnan(cee) and not np.isnan(auc):

                                        results_f1[row, col, f, AL_round] += f1
                                        results_acc[row, col, f, AL_round] += acc
                                        results_logloss[row, col, f, AL_round] += cee
                                        results_auc[row, col, f, AL_round] += auc

                                        valid_turker_count += 1
                                    else:
                                        print('Invalid ranking metrics.')

                                if valid_turker_count > 0:

                                    results_f1[row, col, f, AL_round] /= valid_turker_count
                                    results_acc[row, col, f, AL_round] /= valid_turker_count
                                    results_logloss[row, col, f, AL_round] /= valid_turker_count
                                    results_auc[row, col, f, AL_round] /= valid_turker_count
                                else:
                                    results_f1[row, col, f, AL_round] = 1
                                    results_acc[row, col, f, AL_round] = 1
                                    results_logloss[row, col, f, AL_round] = 0
                                    results_auc[row, col, f, AL_round] = 1

                            else:
                                results_f1[row, col, f, AL_round] = f1_score(gold_disc,
                                                                             pred_disc[:, AL_round],
                                                                             average='macro')
                                #skip the don't knows
                                results_acc[row, col, f, AL_round] = accuracy_score(gold_disc,
                                                                                    pred_disc[:, AL_round])

                                results_logloss[row, col, f, AL_round] = log_loss(gold_prob,
                                                                                  pred_prob[:, AL_round])

                                results_auc[row, col, f, AL_round] = roc_auc_score(gold_prob,
                                                                                   pred_prob[:, AL_round]) # macro

                            print('Results for fold %i: acc=%f, cee=%f, AUC=%f' % (f,
                                                           results_acc[row, col, f, AL_round],
                                                           results_logloss[row, col, f, AL_round],
                                                           results_auc[row, col, f, AL_round])
                                  )

                            if gold_rank is None and expt_settings['folds_regression'] is not None:
                                if docids is None:
                                    _, docids = load_ling_features(expt_settings['dataset'])  
                                # ranking data was not saved in original file. Get it from the expt_settings['folds_regression'] here
                                _, rankscores_test, _, _, _ = expt_settings['folds_regression'].get(fold)["test"]
                                gold_rank = np.array(rankscores_test)

                            if gold_rank is not None and pred_rank is not None:

                                if split_by_person:
                                    # compute the metrics separately for each turker because the gold scores between
                                    # turkers are not comparable.
                                    _, _, _, test_turkers, _ = expt_settings['folds_regression'].get(fold)["test"]

                                    test_turkers = [tid.strip() for tid in test_turkers]

                                    valid_turk_idxs = np.in1d(test_turkers, tr_turkers)
                                    test_turkers = np.array(test_turkers)[valid_turk_idxs]

                                    valid_turker_count = 0

                                    for tid in np.unique(test_turkers):
                                        if np.sum(test_turkers == tid) < 2 or \
                                                np.sum(tr_turkers == tid) <= turker_conf_filter:
                                            continue

                                        tidxs = test_turkers == tid

                                        if np.unique(gold_rank[tidxs]).size == 1:
                                            continue

                                        r =  pearsonr(gold_rank[tidxs], pred_rank[tidxs, AL_round])[0]
                                        rho = spearmanr(gold_rank[tidxs], pred_rank[tidxs, AL_round])[0]
                                        tau = kendalltau(gold_rank[tidxs], pred_rank[tidxs, AL_round])[0]

                                        if not np.isnan(r) and not np.isnan(rho) and not np.isnan(tau):

                                            weight = 1#np.sum(tr_turkers == tid) # weight by total number of data points

                                            results_pearson[row, col, f, AL_round] += r * weight
                                            results_spearman[row, col, f, AL_round] += rho * weight
                                            results_kendall[row, col, f, AL_round] += tau * weight

                                            valid_turker_count += weight
                                        else:
                                            print('Invalid ranking metrics.')

                                    print('No. confident workers (ranking): %i ' % valid_turker_count)

                                    results_pearson[row, col, f, AL_round] /= valid_turker_count
                                    results_spearman[row, col, f, AL_round] /= valid_turker_count
                                    results_kendall[row, col, f, AL_round] /= valid_turker_count
                                else:
                                    results_pearson[row, col, f, AL_round]  = pearsonr(gold_rank,
                                                                                   pred_rank[:, AL_round])[0]
                                    results_spearman[row, col, f, AL_round] = spearmanr(gold_rank,
                                                                                    pred_rank[:, AL_round])[0]
                                    results_kendall[row, col, f, AL_round]  = kendalltau(gold_rank,
                                                                                     pred_rank[:, AL_round])[0]

                            def mean_unseen(result, remove_seen_from_mean):
                                
                                if not remove_seen_from_mean:
                                    return result       
                                
                                N = len(gold_tr)
                                Nseen = (AL_round +1) * expt_settings['di']
                                Nunseen = (N - Nseen)
                                return (result * N - Nseen) / Nunseen
                            
                            if pred_tr_prob is not None and AL_round < pred_tr_disc.shape[1] and compute_tr_performance:
                                _, _, gold_tr, _, _, _, _ = expt_settings['folds_test'].get(fold)["training"]
                                gold_tr = np.array(gold_tr)

                                _, gold_tr_rank, _, _, _ = expt_settings['folds_regression'].get(fold)["training"]

                                if (gold_tr!=1).shape[0] != pred_tr_disc.shape[0]:
                                    print("Mismatch in fold %s! %i, %i" % (fold, (gold_tr!=1).shape[0], pred_tr_disc.shape[0]))
                                
                                gold_tr_prob = gold_tr / 2.0

                                tr_results_f1[row, col, f, AL_round] = mean_unseen(f1_score(gold_tr[gold_tr!=1], 
                                                                             pred_tr_disc[gold_tr!=1, AL_round], 
                                                                             average='macro'), remove_seen_from_mean)
                                #skip the don't knows
                                tr_results_acc[row, col, f, AL_round] = mean_unseen(accuracy_score(gold_tr[gold_tr!=1], 
                                                                                pred_tr_disc[gold_tr!=1, AL_round]),
                                                                                remove_seen_from_mean) 
                                
                                tr_results_logloss[row, col, f, AL_round] = mean_unseen(log_loss(gold_tr_prob[gold_tr!=1], 
                                                                            pred_tr_prob[gold_tr!=1, AL_round]),
                                                                            remove_seen_from_mean)
                                
                                tr_results_auc[row, col, f, AL_round] = mean_unseen(roc_auc_score(gold_tr_prob[gold_tr!=1], 
                                                                                pred_tr_prob[gold_tr!=1, AL_round]),
                                                                                remove_seen_from_mean)

                                if pred_tr_rank is not None:
                                    if pred_tr_rank.ndim  == 1:
                                        pred_tr_rank = pred_tr_rank[:, None]

                                    tr_results_tau[row, col, f, AL_round] = mean_unseen(kendalltau(
                                        gold_tr_rank, pred_tr_rank[:, AL_round])[0])

                            elif pred_tr_prob is not None and AL_round >= pred_tr_disc.shape[1]:
                                tr_results_f1[row, col, f, AL_round] = 1
                                tr_results_acc[row, col, f, AL_round] = 1
                                tr_results_auc[row, col, f, AL_round] = 1
                                tr_results_logloss[row, col, f, AL_round] = 0
                                tr_results_tau[row, col, f, AL_round] = 1
                          
                        for AL_round in range(results_f1.shape[3]):
                            foldrange = np.arange(min_folds, max_fold_no) # skip any rounds that did not complete when taking the mean
                            foldrange = foldrange[results_f1[row, col, foldrange, AL_round] != 0]

                            results_f1[row, col, -1, AL_round] = np.mean(results_f1[row, col, foldrange, AL_round], axis=0)
                            results_acc[row, col, -1, AL_round] = np.mean(results_acc[row, col, foldrange, AL_round], axis=0)
                            results_logloss[row, col, -1, AL_round] = np.mean(results_logloss[row, col, foldrange, AL_round], axis=0)
                            results_auc[row, col, -1, AL_round] = np.mean(results_auc[row, col, foldrange, AL_round], axis=0)
                            
                            results_pearson[row, col, -1, AL_round] = np.mean(results_pearson[row, col, foldrange, AL_round], axis=0)
                            results_spearman[row, col, -1, AL_round] = np.mean(results_spearman[row, col, foldrange, AL_round], axis=0)
                            results_kendall[row, col, -1, AL_round] = np.mean(results_kendall[row, col, foldrange, AL_round], axis=0)
                            
                            tr_results_f1[row, col, -1, AL_round] = np.mean(tr_results_f1[row, col, foldrange, AL_round], axis=0)
                            tr_results_acc[row, col, -1, AL_round] = np.mean(tr_results_acc[row, col, foldrange, AL_round], axis=0)
                            tr_results_logloss[row, col, -1, AL_round] = np.mean(tr_results_logloss[row, col, foldrange, AL_round], axis=0)
                            tr_results_auc[row, col, -1, AL_round] = np.mean(tr_results_auc[row, col, foldrange, AL_round], axis=0)
                            tr_results_tau[row, col, -1, AL_round] = np.mean(tr_results_tau[row, col, foldrange, AL_round], axis=0)

                    print('Coverage = %f' % (coverage/nFolds))

                    if expt_settings['fold_order'] is not None:
                        sortidxs = np.argsort(expt_settings['fold_order'])

                        print(expt_settings['fold_order'][sortidxs])
                        for idx in sortidxs:
                            print('%f,' % results_acc[row, col, idx, 0])
                        print('----')

                    if foldrange is not None:
                        print('p-values for %s, %s, %s, %s:' % (expt_settings['dataset'], expt_settings['method'],
                                                expt_settings['feature_type'], expt_settings['embeddings_type']))

                        print(wilcoxon(results_f1[0, 0, foldrange, AL_round],
                                                                  results_f1[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_acc[0, 0, foldrange, AL_round],
                                                                  results_acc[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_logloss[0, 0, foldrange, AL_round],
                                                                  results_logloss[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_auc[0, 0, foldrange, AL_round],
                                                                  results_auc[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_pearson[0, 0, foldrange, AL_round],
                                                                  results_pearson[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_spearman[0, 0, foldrange, AL_round],
                                                                  results_spearman[row, col, foldrange, AL_round])[1])
                        print(wilcoxon(results_kendall[0, 0, foldrange, AL_round],
                                                                  results_kendall[row, col, foldrange, AL_round])[1])
                        
                    if row == 0: # set the column headers    
                        columns[col] = expt_settings['feature_type'] + ', ' + expt_settings['embeddings_type']
                    
                    col += 1
                    
            row += 1

    combined_labels = []
    for row in row_index:
        for col in columns:
            combined_labels.append(str(row) + '_' + str(col))

    mean_results = []
    mean_results.append(collate_AL_results(AL_rounds, results_f1, combined_labels, "Macro-F1 scores for round %i: "))
    mean_results.append(collate_AL_results(AL_rounds, results_acc, combined_labels, 
           "Accuracy (excl. don't knows), round %i:")) # for UKPConvArgStrict don't knows are already ommitted)
    mean_results.append(collate_AL_results(AL_rounds, results_auc, combined_labels, "AUC ROC, round %i:"))
    #if AUC is higher than accuracy and F1 score, it suggests that decision boundary is not calibrated or that 
    #accuracy may improve if we exclude data points close to the decision boundary
    mean_results.append(collate_AL_results(AL_rounds, results_logloss, combined_labels, 
      "Cross Entropy classification error, round %i: "))
    #(quality of the probability labels is taken into account)
    mean_results.append(collate_AL_results(AL_rounds, results_pearson, combined_labels, 
                                              "Pearson's r for round %i: "))
    mean_results.append(collate_AL_results(AL_rounds, results_spearman, combined_labels, 
                                               "Spearman's rho for round %i: "))
    mean_results.append(collate_AL_results(AL_rounds, results_kendall, combined_labels, 
                                              "Kendall's tau for round %i: "))
        
    if np.any(tr_results_acc):
        mean_results.append(collate_AL_results(AL_rounds, tr_results_f1, combined_labels,
                                                 "(TR) Macro-F1 scores for round %i: "))
        mean_results.append(collate_AL_results(AL_rounds, tr_results_acc, combined_labels, 
            "(TR) Accuracy for round %i: "))
        mean_results.append(collate_AL_results(AL_rounds, tr_results_auc, combined_labels, 
            "(TR) AUC ROC for round %i: "))
        mean_results.append(collate_AL_results(AL_rounds, tr_results_logloss, combined_labels, 
            "(TR) Cross Entropy Error for round %i: "))
        mean_results.append(collate_AL_results(AL_rounds, tr_results_tau, combined_labels,
            "(TR) Kendall's tau for round %i: "))

#     metricsfile = data_root_dir + 'outputdata/expt_root_dir' + \
#                     'metrics_%s.pkl' % (tag)    
#     with open(metricsfile, 'w') as fh:
#         pickle.dump((results_f1, results_acc, results_auc, results_logloss, results_pearson, results_spearman, 
#                      results_kendall), fh)
    
    # TODO: Correlations between reasons and features?
    
    # TODO: Correlations between reasons and latent argument features found using preference components?
    
    return results_f1, results_acc, results_auc, results_logloss, results_pearson, results_spearman, results_kendall,\
            tr_results_f1, tr_results_acc, tr_results_auc, tr_results_logloss, mean_results, combined_labels

if __name__ == '__main__':
    
    if 'expt_settings' not in globals():
        expt_settings = {}
        expt_settings['dataset'] = None
        expt_settings['folds'] = None 

    expt_settings['foldorderfile'] = None
    data_root_dir = os.path.expanduser("~/data/personalised_argumentation/")

    resultsfile_template = 'habernal_%s_%s_%s_%s_acc%.2f_di%.2f'

    npairs = 0
    di = 0
    max_no_folds = 32

    methods = ['SinglePrefGP_weaksprior_1904']#['SinglePrefGP_weaksprior_2107', 'SinglePrefGP_weaksprior_0308', 'SinglePrefGP_weaksprior_0901']#, 'SVM', 'BI-LSTM'] #'SinglePrefGP_weaksprior', 'SingleGPC_noOpt_weaksprior', 'GP+SVM']
    datasets = ['UKPConvArgStrict']
    feature_types = ['both']#, 'ling']
    embeddings_types = ['word_mean']#['word_mean', 'skipthoughts', 'siamese-cbow']

    results_f1, results_acc, results_auc, results_logloss, results_pearson, results_spearman, results_kendall, \
    tr_results_f1, tr_results_acc, tr_results_auc, tr_results_logloss, mean_results, combined_labels \
    = compute_metrics(expt_settings, methods, datasets, feature_types, embeddings_types, di=di, npairs=npairs,
                      max_fold_no=max_no_folds)

    print(results_acc)

    print("Completed compute metrics")

    # matrix to map back from different fold order:
    #mapidxs = np.genfromtxt('/home/local/UKP/simpson/git/crowdsourcing_argumentation/mapidxs.txt').astype(int)
    #print("Reordered: ")
    #print(results_acc.flatten()[mapidxs.flatten()][:, None])
