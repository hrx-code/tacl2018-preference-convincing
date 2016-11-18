'''

For the list of tasks implemented here, see:

https://docs.google.com/spreadsheets/d/15LXSrCcaDURsIYmogt-NEwaakUiITFtiq993TLkflRQ/edit#gid=0

Created on 10 May 2016

@author: simpson
'''
import logging, os, datetime
logging.basicConfig(level=logging.DEBUG)
import numpy as np
from mpl_toolkits.mplot3d import Axes3D    
from sklearn.cross_validation import KFold

import classification_metrics
from pref_prediction_methods import PredictionTester
from preproc_raw_data import load_amt, load_synthetic



if __name__ == '__main__':
    # Experiment configuration ----------------------------------------------------------------------------------------
     
    import xmiparser

    xmiparser.parse(xschemaFileName, xschema, packages, generator, profile_dir)
     
    dataset = 'amt'
    split_results_by_no_annotations = True
    nruns = 1
    
#     dataset = 'synth' 
#     synth_worker_accs = [0.6, 0.7, 0.8, 0.9, 0.99]
#     nruns = len(synth_worker_accs)
#     split_results_by_no_annotations = False
    
    nfactors=5
    
    methods = ['Baseline_MostCommon', 'CombineAll_Averaging', 'GMM_Averaging', 'AffProp_Averaging', 'Agg_Averaging'] # list the names of methods to test here
    nmethods = len(methods) 
    #2 * len(nfactors_list) + 1 # need to increase nmethods if we are trying multiple numbers of factors 
    # -- new implementation will try to optimize the number of factors internally and return only the best results for each method

    # RUN THE VARIOUS PREFERENCE PREDICTION METHODS....
    k = 0 # count which fold we are in so we can save data    

    nfolds = 10

    metrics = {} # classification/pairwise preference performance metrics
    rank_metrics = {} #ordering of items 
    
    # Task A2 ---------------------------------------------------------------------------------------------------------
    for r in range(nruns): # Repeat everything!
     
        if dataset == 'synth':
            datadir, plotdir, nx, ny, data, pair1coords, pair2coords, pair1idxs, pair2idxs, xvals, yvals, prefs, personids,\
                npairs, nworkers, ntexts, f = load_synthetic(synth_worker_accs[r]) # use different params in each run
            xlabels = synth_worker_accs
            plotdir += '/synth/'
        else:
            datadir, plotdir, nx, ny, data, pair1coords, pair2coords, pair1idxs, pair2idxs, xvals, yvals, prefs, personids,\
                npairs, nworkers, ntexts, f = load_amt()
            plotdir += '/amt/'
            xlabels = None
        if not os.path.isdir(plotdir):
            os.mkdir(plotdir)
        
        kf = KFold(npairs, nfolds, shuffle=True, random_state=100)
          
        results = np.zeros((npairs, nmethods)) # the test results only
        rank_results = np.zeros((ntexts, nmethods)) # used by methods that rank items as well as predict pairwise labels
           
        for train, test in kf:
            logging.info('Running fold %i' % k)
            
            tester = PredictionTester(datadir, k, nx, ny, personids, pair1coords, pair2coords, prefs, train, test, results, 
                                      rank_results)
            
            for m, method in enumerate(methods):
                
                start = datetime.datetime.now()
                # baseline: assign most common class label
                if method=='Baseline_MostCommon':
                    logging.info('Baseline -- Assign most common class')
                    tester.run_baseline_most_common(m)
                    
                # baseline: treating all workers as the same but not considering features; averaging workers
                elif method=='CombineAll_Averaging':
                    logging.info('Treat all workers as same and average')
                    
                    tester.run_combine_avg(m)
                
                # clustering the raw preferences
                elif method=='AffProp_Averaging':
                    logging.info('Affinity Propagation, then averaging clusters to predict')
                    
                    tester.run_affprop_avg(m, gp_per_cluster=True)
                elif method=='Agg_Averaging':
                    logging.info('Agglomerative clustering, then averaging clusters to predict')
                    
                    tester.run_agglomerative_avg(m, gp_per_cluster=True)
                elif method=='GMM_Averaging':
                    logging.info('Gaussian mixture, then averaging clusters to predict')
                    
                    tester.run_raw_gmm_avg(m, nfactors, gp_per_cluster=True)  
                    
                # testing whether the smoothed, continuous GP improves clustering
                # the effect may only be significant once we have argument features
                # assuming no clustering at all, but using a GP to smooth 
                elif method=='SeparateGP':              
                    logging.info('Task C1 part II, Separate GPs (no FA)')
                    
                    tester.run_gp_separate(m)                
                # treating all workers as the same and using a GP to smooth
                elif method=='CombinedGP':
                    # Task C3: Baseline with no separate preference functions per user ----------------------------------------
                    logging.info('Task C3, Combined GP')
                     
                    tester.run_gp_combined(m) 
                # factor analysis + GP          
                elif method=='GPFA':
                    logging.info('Task C1, GPFA')
                 
                    # Run the GPFA with this fold
                    tester.run_gpfa(m, nfactors)                
                # clustering methods on top of the smoothed functions
                elif method=='GP_AffProp_Averaging':
                    logging.info('Preference GP, function means fed to Aff. Prop., then averaging clusters to predict')
                    
                    tester.run_gp_affprop_avg(m, gp_per_cluster=True)
                elif method=='GP_GMM_Averaging':
                    logging.info('Preference GP, function means fed to GMM, then averaging clusters to predict')
                    
                    tester.run_gp_gmm_avg(m, nfactors, gp_per_cluster=True)
                    
                end = datetime.datetime.now()
                duration = (end - start).total_seconds()
                logging.info("Method %i in fold %i took %.2f seconds" % (m, k, duration))
                               
            k += 1
              
        if split_results_by_no_annotations:
            # separate the data points according to the number of annotators    
            paircounts = np.sum(np.invert(np.isnan(tester.preftable)), axis=0)
            nanno_max = 10
            for nanno in range(2, nanno_max+1):
                if nanno==nanno_max:
                    pairs = np.argwhere(paircounts >= nanno)
                else:
                    pairs = np.argwhere(paircounts == nanno)
                if not pairs.size:
                    continue
                #ravel the pair1 and pair2 idxs
                pairidxs = np.in1d(tester.pairidxs_ravelled, pairs)
                gold = prefs[pairidxs]
                if len(np.unique(gold)) != 3:
                    # we don't have examples of all classes
                    continue
                
                res = results[pairidxs, :]
                
                metrics = classification_metrics.compute_metrics(nmethods, gold, res, metrics, nruns, r)
                if r == nruns - 1:
                    if nanno == nanno_max:  
                        classification_metrics.plot_metrics(plotdir, metrics, nmethods, methods, nfolds, nanno, 
                                                            nanno_is_min=True, xlabels=xlabels)
                    else:
                        classification_metrics.plot_metrics(plotdir, metrics, nmethods, methods, nfolds, nanno, 
                                                            xlabels=xlabels)
        
                if np.any(rank_results):
                    rank_metrics = classification_metrics.compute_ranking_metrics(nmethods, f, rank_results, 
                                                                                  rank_metrics, nruns, r)
                    if r == nruns - 1:
                        if nanno == nanno_max:  
                            classification_metrics.plot_metrics(plotdir, rank_metrics, nmethods, methods, nfolds, 
                                                                nanno, nanno_is_min=True, xlabels=xlabels)
                        else:
                            classification_metrics.plot_metrics(plotdir, rank_metrics, nmethods, methods, nfolds, 
                                                                nanno, xlabels=xlabels)
                        
        metrics = classification_metrics.compute_metrics(nmethods, prefs, results, metrics, nruns, r)
        if r == nruns - 1:    
            classification_metrics.plot_metrics(plotdir, metrics, nmethods, methods, nfolds, 1, nanno_is_min=True, 
                                                xlabels=xlabels)
        
        if np.any(rank_results):
            rank_metrics = classification_metrics.compute_ranking_metrics(nmethods, f, rank_results, rank_metrics, 
                                                                          nruns, r)
            if r == nruns - 1:
                classification_metrics.plot_metrics(plotdir, rank_metrics, nmethods, methods, nfolds, nanno, 
                                                nanno_is_min=True, xlabels=xlabels)