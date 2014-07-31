#
#   Copyright (c) 2010-2014, MIT Probabilistic Computing Project
#
#   Lead Developers: Jay Baxter and Dan Lovell
#   Authors: Jay Baxter, Dan Lovell, Baxter Eaves, Vikash Mansinghka
#   Research Leads: Vikash Mansinghka, Patrick Shafto
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
import matplotlib
matplotlib.use('Agg')

import sys
sys.path.insert(1, '/home/local_jay/BayesDB')

from bayesdb.client import Client
import experiment_utils as eu
import random
import numpy
import pylab
import time
import os
import sklearn.linear_model

def run_experiment(argin):
    num_iters       = argin["num_iters"]
    num_chains      = argin["num_chains"]
    num_rows        = argin["num_rows"]
    num_cols        = argin["num_cols"]
    num_views       = argin["num_views"]
    num_clusters    = argin["num_clusters"]
    prop_missing    = argin["prop_missing"]
    impute_samples  = argin["impute_samples"]
    separation      = argin["separation"]
    ct_kernel       = argin["ct_kernel"]
    seed            = argin["seed"]
    record_every_iters = argin["record_every_iters"]

    if seed > 0 :
        random.seed(seed)

    filename = "discriminative_ofile.csv"
    table_name = 'exp_discriminative'

    argin['cctypes'] = ['continuous']*num_cols
    discrim_cctype = dict(types=sklearn.linear_model.LogisticRegression,
                          params=dict(),
                          inputs=range(num_cols-1))
    argin['cctypes'][-1] = discrim_cctype

    argin['separation'] = [argin['separation']]*num_views

    eu.gen_data_discriminative(filename, argin, save_csv=True)

    # generate a new csv
    all_filenames = []
    all_indices = []

    for p in prop_missing:
        data_filename, indices, col_names, extra = eu.gen_missing_data_csv(filename,
                                        p, [], True)
        all_indices.append(indices)
        all_filenames.append(data_filename)

    # get the starting table so we can calculate errors
    T_array = extra['array_filled']
    num_rows, num_cols = T_array.shape

    # create a client
    client = Client()

    # set up a dict fro the different config data
    result = dict()
    result['iterations'] = range(0, num_iters+1, record_every_iters)
    result['cc'] = numpy.zeros(len(result['iterations']))
    result['crp'] = numpy.zeros(len(result['iterations']))
    result['nb'] = numpy.zeros(len(result['iterations']))
    result['rf'] = numpy.zeros(len(result['iterations']))
    result['lr'] = numpy.zeros(len(result['iterations']))
    print col_names

    # do analyses
    for p in range(len(prop_missing)):

        this_indices = all_indices[p]
        this_filename = all_filenames[p]
        for config in ['cc', 'crp', 'nb', 'rf', 'lr']:
            config_string = eu.config_map[config]
            table = table_name + '_' + config

            # drop old btable, create a new one with the new data and init models
            client('DROP BTABLE %s;' % table, yes=True)
            client('CREATE BTABLE %s FROM %s;' % (table, this_filename))
            if config == 'rf':
                client('UPDATE SCHEMA FOR %s set %s= discriminative type multi-class random forest' % (table, col_names[-1]))
            elif config == 'lr':
                client('UPDATE SCHEMA FOR %s set %s= discriminative type logistic regression' % (table, col_names[-1]))
            client('SELECT *, %s FROM %s;' % (table, col_names[-1]))
            client('INITIALIZE %i MODELS FOR %s %s;' % (num_chains, table, config_string))

            iters_done = 0
            for i in range(0, num_iters+1, record_every_iters):
                if i > 0:
                    client('ANALYZE %s FOR %i ITERATIONS WAIT;' % (table, i - iters_done) )

                MSE = 0.0
                count = 0.0
                # imput each index in indices and calculate the squared error
                #for col in range(0,num_cols):
                for col in [num_cols - 1]: # For now, only do last column
                    col_name = col_names[col]
                    # confidence is set to zero so that a value is always returned
                    out = client('INFER %s from %s WITH CONFIDENCE %f WITH %i SAMPLES;' % (col_name, table, 0, impute_samples), pretty=False, pandas_output=False )

                    data = out[0]['data']

                    # calcaulte MSE
                    for row, tcol in zip(this_indices[0], this_indices[1]):
                        if tcol == col:
                            # only works for continuous   MSE += ( T_array[row,col] - data[row][1] )**2.0
                            if T_array[row,col] != float(data[row][1]):
                                MSE += 1
                            count += 1.0

                result[config][i] = MSE/count
                print "error = %f" % result[config][p]

    retval = dict()
    retval['MSE_naive_bayes_indexer'] = result['nb']
    retval['MSE_crp_mixture_indexer'] = result['crp']
    retval['MSE_crosscat_indexer'] = result['cc']
    retval['MSE_random_forest_indexer'] = result['rf']
    retval['MSE_logistic_regression_indexer'] = result['lr']
    retval['prop_missing'] = prop_missing
    retval['iterations'] = result['iterations']
    retval['config'] = argin

    return retval

def gen_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--num_iters', default=5, type=int)
    parser.add_argument('--record_every_iters', default=1, type=int)
    parser.add_argument('--num_chains', default=4, type=int)
    parser.add_argument('--num_rows', default=300, type=int)
    parser.add_argument('--num_cols', default=4, type=int) #8
    parser.add_argument('--num_clusters', default=4, type=int)
    parser.add_argument('--impute_samples', default=50, type=int)  # samples for IMPUTE
    parser.add_argument('--num_views', default=2, type=int) # data generation
    parser.add_argument('--separation', default=.9, type=float) # data generation
    parser.add_argument('--prop_missing', nargs='+', type=float, default=[.3])  # list of missing proportions
    parser.add_argument('--seed', default=0, type=int)
    parser.add_argument('--ct_kernel', default=0, type=int) # 0 for gibbs, 1 for MH
    parser.add_argument('--no_plots', action='store_true')
    return parser

if __name__ == "__main__":
    """
    "discriminative fills in blanks":
    synthetic: CC + 1 column LR
    x: iterations
    y: INFER accuracy, 5 lines: NB, DPM, CC, CC+RF, CC+LR
    """
    import argparse
    import experiment_runner.experiment_utils as eru
    from experiment_runner.ExperimentRunner import ExperimentRunner, propagate_to_s3 

    parser = gen_parser()
    args = parser.parse_args()

    argsdict = eu.parser_args_to_dict(args)
    generate_plots = not argsdict['no_plots']

    results_filename = 'discriminative_results'
    dirname_prefix = 'discriminative'

    # this is where we actually run it.
    er = ExperimentRunner(run_experiment, dirname_prefix=dirname_prefix, bucket_str='experiment_runner', storage_type='fs')
    retval = er.do_experiments([argsdict], do_multiprocessing=False)

    if generate_plots:
        for i in er.frame.index:
            result = er._get_result(i)
            this_dirname = eru._generate_dirname(dirname_prefix, 10, result['config'])
            filename_img = os.path.join(dirname_prefix, this_dirname, results_filename+'.png')
            eu.plot_discriminative(result, filename=filename_img)
            pass
        pass
