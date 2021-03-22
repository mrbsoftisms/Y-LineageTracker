import os
import re
import sys
import time
import logging
import argparse
import tempfile
import subprocess
import numpy as np

from ete3 import Tree


'''
Description:
This module is used for estimating divergence time of NRY haplogroups.
PAML mcmctree is wrapped in Y-LineageTracker to run time estimation analysis by Bayesian MCMC algorithm.
The tree file containing haplogroup nodes can be generated by phylo command.
'''


def time_parser():

    # function to define filter argument
    def filter_type(x):
        x = float(x)
        if x < 0 or x > 1:
            raise argparse.ArgumentTypeError('Cutoff of missing rate should be a float between 0 and 1')
        return x

    parser = argparse.ArgumentParser('time', description='(c) Y-LineageTracker: Time estimation for NRY haplogroups')
    # function used for time estimation
    parser.add_argument('time',
                        help='Estimate divergence time of NRY haplogroups.')
    # required, sequence alignment file
    parser.add_argument('--seq',
                        required=True,
                        type=str,
                        action='store',
                        help='seq: The sequence alignment file used for analysis')
    # optional, format of sequence alignment
    parser.add_argument('--seq-format',
                        required=False,
                        type=str,
                        dest='format',
                        action='store',
                        choices=['fasta', 'phylip', 'nexus', 'meg', 'vcf'],
                        help='seq-format: The format of sequence alignment file.')
    # required, tree file in newick format
    parser.add_argument('--tree',
                        required=True,
                        type=str,
                        action='store',
                        help='tree: Tree file of NRY phylogeny. \
                             The tree should be a rooted bifurcating tree without branch length. \
                             It is recommended to annotate NRY haplogroup name in tree nodes.')
    # required, calibration information of haplogroups
    parser.add_argument('--cal',
                        required=False,
                        type=str,
                        dest='calibration',
                        action='store',
                        help='cal: Haplogroup calibration information. ')
    # optional, the substitution mode
    parser.add_argument('--model',
                        required=False,
                        type=str,
                        action='store',
                        default='hky85',
                        choices=['hky85', 'jc96', 'k80', 'f81', 'f84', 'gtr'],
                        help='model: the substitution model used for time estimation')
    # optional, mutation rate of NRY
    parser.add_argument('--mut-rate',
                        required=False,
                        type=float,
                        dest='rate',
                        action='store',
                        default=7.6e-10,
                        help='mut-rate: The general mutation rate across the NRY. The default value is 7.6e-10')
    # optional, set calibration information automatically
    parser.add_argument('--auto-cal',
                        required=False,
                        dest='auto',
                        action='store_true',
                        help='auto-cal: Automatically set calibration information for the root node. \
                              In order to make this option feasible, the root node should be a haplogroup in the main trunk of the NRY tree.')
    # optional, filter sites by misisng rate value
    parser.add_argument('--filter',
                        type=filter_type,
                        required=False,
                        action='store',
                        default=0.2,
                        help='filter: Filter sites with a missing rate value greater than a value in sequence alignment file.')
    # optional, mcmc step
    parser.add_argument('--mcmc',
                        type=int,
                        required=False,
                        action='store',
                        help='mcmc: Set iteration step to run MCMC. The default is 5000.')
    # optional, the prefix of output
    parser.add_argument('-o', '--output',
                        required=False,
                        type=str,
                        action='store',
                        help='output: The prefix of output files.')

    args = parser.parse_args()

    return args


# print program information and write to log file
def set_log(log_file, args_log):

    logger = logging.getLogger()
    logger.setLevel(level=logging.INFO)

    handler = logging.FileHandler(log_file, mode='w')
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] - [%(levelname)s]: %(message)s')
    handler.setFormatter(formatter)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)

    logger.addHandler(handler)
    logger.addHandler(console)

    log_info = ['[Y-LineageTracker] [Time]',
                '[Y-LineageTracker] Run Date: ' + time.asctime(time.localtime(time.time())),
                '[Y-LineageTracker] Tree File: %s' % args_log.tree,
                '[Y-LineageTracker] Sequence File: %s' % args_log.seq,
                '[Y-LineageTracker] Sequence File Format: %s' % args_log.format,
                '[Y-LineageTracker] Calibration Information: %s' % args_log.calibration,
                '[Y-LineageTracker] Mutation Rate: %s' % args_log.rate]

    if args_log.auto:
        log_info.append('[Y-LineageTracker] Perform Automatical Calibration')

    print('\n')
    for i in log_info:
        logger.info(i)


class EstimateTime(object):
    '''
    This class is used to estimate divergence time of NRY haplogroups
    PAML is wrapped in the program
    The program will generate control file of PAML mcmctree and perform analysis to estimate time
    After mcmctree is done, the program will summarize output result of mcmctree
    Three file is required for mcmctree analysis:
    1. sequence alignment file
    2. tree file in newick format
    3. calibration information file
    The tree should be a rooted bifurcating tree without branch length
    It is recommended to annotate NRY haplogroup name in tree nodes.
    '''

    def __init__(self, path):

        self.logger = logging.getLogger()
        self.path = path

    # read and clean sequence alignment file
    def _clean_alignment(self, seq_file, seq_format, filter):

        from ProcessData import ConvertData
        seq_tmp_file = tempfile.NamedTemporaryFile(mode='w')
        convert = ConvertData.ConvertData(seq_file)
        msa = convert.data_convert(seq_format, 'msa')
        seqs = [i.seq for i in msa]
        ids = [i.id for i in msa]

        if filter:
            new_seqs = []
            for i in range(len(seqs[0])):
                all_al = [s[i] for s in seqs]
                al = list(set(all_al))
                N_count = 0
                if 'N' in al:
                    N_count += all_al.count('N')
                if '-' in al:
                    N_count += all_al.count('-')
                N_rate = N_count / len(all_al)
                if N_rate < filter:
                    new_seqs.append(all_al)
            new_seqs = np.array(new_seqs).T.tolist()
        else:
            new_seqs = seqs

        max_length = max([len(i) for i in ids])
        with open(seq_tmp_file.name, 'w') as seq_tmp:
            seq_tmp.write('%d %d\n' % (len(ids), len(new_seqs[0])))
            for seq, id in zip(new_seqs, ids):
                seq_tmp.write(id+(max_length-len(id))*' '+'   '+''.join(seq)+'\n')

        return seq_tmp_file

    # read tree file
    def _read_tree_file(self, tree_file):

        tree_tmp_file = tempfile.NamedTemporaryFile(mode='w')
        tree = Tree(open(tree_file, 'r').read(), format=8)
        pruned_tree = Tree(tree.write(format=9), format=9)

        for node in pruned_tree.iter_descendants('preorder'):
            if (not node.is_leaf()) and len(node.children) == 1 and node.name == '':
                node.delete()
        taxa_num = len([leaf for leaf in pruned_tree])

        tmp_tree_info = pruned_tree.write(format=9)
        with open(tree_tmp_file.name, 'w') as tree_tmp:
            tree_tmp.write('%d 1\n\n%s' % (taxa_num, tmp_tree_info))

        return tree_tmp_file

    # read calibration information file
    def _get_calibration(self, calibration):

        if os.path.isfile(calibration):
            return open(calibration).readlines()
        else:
            return [calibration]

    # get calibration time from calibration information file
    def _haplogroup_calibration(self, calibration, tree_file):

        calibration_info = self._get_calibration(calibration)
        tree_tmp_file = tempfile.NamedTemporaryFile(mode='w')
        cal_tree = Tree(open(tree_file, 'r').read(), format=8)
        root_name = cal_tree.get_tree_root().name
        root_age = None

        used_nodes = []
        for i in calibration_info:
            used_node = i.split(':')[0]
            if re.match(r'^\w+:\d+$', i):
                cal_node, cal_time = i.split(':')
                cal_time = 'U(%s)' % cal_time
            elif re.match(r'^\w+:<\d+$', i):
                cal_node, cal_time = i.split(':<')
                cal_time = 'U(%s)' % cal_time
            elif re.match(r'^\w+:>\d+$', i):
                cal_node, cal_time = i.split(':>')
                cal_time = 'L(%s)' % cal_time
            elif re.match(r'^\w+:\d+-\d+$', i):
                cal_node, cal_time = i.split(':')
                cal_time = cal_time.split('-')[0] + ', ' + cal_time.split('-')[1]
                cal_time = 'B(%s)' % cal_time
            else:
                raise TypeError('format of calibration is incorrect')
            if used_node == root_name:
                root_age = cal_time
            else:
                try:
                    cal_tree.search_nodes(name=cal_node)[0].name = cal_time
                except:
                    raise TypeError('cannot find the haplogroup node in tree')
            used_nodes.append(used_node)

        for node in cal_tree.iter_descendants('preorder'):
            if (not node.is_leaf()):
                if len(node.children) == 1 and node.name == '':
                    node.delete()
                    continue
                if node.name not in used_nodes:
                    node.name = 'NoName'
        taxa_num = len([leaf for leaf in cal_tree])

        tmp_tree_info = cal_tree.write(format=8)
        tmp_tree_info = tmp_tree_info.replace('NoName', '')
        with open(tree_tmp_file.name, 'w') as tree_tmp:
            tree_tmp.write('%d 1\n\n%s' % (taxa_num, tmp_tree_info))

        return tree_tmp_file, root_age

    # calculate mutation rate for mcmc control file
    def _calculate_mutation_rate(self, rate):

        alpha = 1 # shape
        beta = alpha / rate
        alpha_d = 1

        return str(alpha)+' '+str(beta)+' '+str(alpha_d)

    # match model to mcmc control file
    def _get_model(self, name):

        if name == 'jc96':
            return '0'
        elif name == 'k80':
            return '1'
        elif name == 'f81':
            return '2'
        elif name == 'f84':
            return '3'
        elif name == 'hky85':
            return '4'
        elif name == 'gtr':
            return '7'

    # automatically get calibration time
    def _get_root_age(self, tree_file_name):

        from FilesIO import CommonData
        tree = Tree(open(tree_file_name, 'r').read(), format=8)
        root_name = tree.get_tree_root().name
        common_data = CommonData()
        prior_calibration = common_data.read_prior_calibration()
        if root_name in prior_calibration.index:
            lower = prior_calibration.at[root_name, 'Lower1']
            upper = prior_calibration.at[root_name, 'Upper1']
            calibration = 'B(%s, %s)' % (lower, upper)
        else:
            if root_name == '':
                self.logger.warning('[Y-LineageTracker] The root name does not exist, auto prior calibration will not be set')
            else:
                self.logger.warning('[Y-LineageTracker] Cannot find calibration time for root name %s, auto prior calibration will not be set' % root_name)
            calibration = None

        return calibration

    # get mcmc control file
    def _generate_mcmc_ctl(self, arguments, tree_file, seq_file, auto_calibration):

        if arguments.mcmc:
            if arguments.mcmc > 1000:
                mcmc = arguments.mcmc
            else:
                self.logger.warning('[Y-LineageTracker] Step for MCMC is too small, default value will be used')
                mcmc = 10000
        else:
            mcmc = 10000

        ctl_parameters={
        'seed': '-1',
        'seqfile': seq_file.name,
        'treefile': tree_file.name,
        'mcmcfile': self.path+'.mcmc.txt',
        'outfile': self.path+'.out.txt',
        'ndata': '1',
        'seqtype': '0',
        'usedata': '1',
        'clock': '1',
        'model': self._get_model(arguments.model),
        'alpha': '0',
        'ncatG': '5',
        'cleandata': '0',
        'BDparas': '1 1 0.1',
        'kappa_gamma': '6 2',
        'alpha_gamma': '1 1',
        'rgene_gamma': self._calculate_mutation_rate(arguments.rate),
        'print': '1',
        'burnin': '2000',
        'sampfreq': '5',
        'nsample': str(mcmc)}

        if auto_calibration:
            ctl_parameters['RootAge'] = auto_calibration

        max_length = max([len(i) for i in ctl_parameters.keys()])
        ctl_file = tempfile.NamedTemporaryFile(mode='w')
        with open(ctl_file.name, 'w') as ctl:
            for i in ctl_parameters.keys():
                length = len(i)
                ctl.write((max_length-length)*' '+i+' = '+ctl_parameters[i]+'\n')

        return ctl_file

    # summarize time from mcmc output
    def _summarize_result(self, orginal_tree):

        tree = Tree(orginal_tree, format=8)

        out_info = open(self.path+'.out.txt', 'r').readlines()
        for i in out_info:
            if i.startswith('Posterior mean'):
                head_num = out_info.index(i)
        time_info = out_info[head_num+2: -3]

        with open(self.path+'.haptime.txt', 'w') as time_file:
            time_file.write('NodeName\tNodeTime\tLower\tUpper\n')
            num = 0
            no_name_num = 0
            for node in tree.traverse('preorder'):
                children = node.children
                if not node.is_leaf() and len(children) > 1:
                    if node.name == '':
                        node_name = 'NoName' + str(no_name_num)
                        no_name_num += 1
                    else:
                        node_name = node.name
                    node_time_info = [i for i in time_info[num].strip().split(' ') if i != '']
                    node_time = node_time_info[1]
                    lower = node_time_info[4].strip('(').strip(',')
                    upper = node_time_info[5].strip(')')
                    num += 1
                    time_file.write(node_name+'\t'+node_time+'\t'+lower+'\t'+upper+'\n')

    # main function to run time estimation
    def run_mcmc(self, arguments):

        if not (arguments.auto or arguments.calibration):
            self.logger.error('[Y-LineageTracker] Stopped since no calibration information')
            sys.exit()

        # get calibration time
        self.logger.info('[Y-LineageTracker] Read tree file and calibration')
        if arguments.auto:
            auto_calibration = self._get_root_age(arguments.tree)
        else:
            auto_calibration = None
        if arguments.calibration:
            tree_file, auto_calibration = self._haplogroup_calibration(arguments.calibration, arguments.tree)
        else:
            tree_file = self._read_tree_file(arguments.tree)

        # get sequence alignment file
        self.logger.info('[Y-LineageTracker] Read seq file')
        seq_file = self._clean_alignment(arguments.seq, arguments.format, arguments.filter)

        # get control file
        ctl_file = self._generate_mcmc_ctl(arguments, tree_file, seq_file, auto_calibration)

        # get control file and run mcmctree
        self.logger.info('[Y-LineageTracker] Estimating divergence time, this may take some time')
        mcmc = os.path.split(os.path.realpath(__file__))[0] + '/src/mcmctree'
        cmd = mcmc + ' ' + ctl_file.name
        FNULL = open(os.devnull, 'w')
        process = subprocess.Popen(cmd, shell=True, stdout=FNULL, stderr=subprocess.STDOUT)
        process.wait()

        time.sleep(0.1)

        # summarize output result
        self.logger.info('[Y-LineageTracker] Summarizing output result')
        self._summarize_result(arguments.tree)


def main():

    start = time.perf_counter()
    arguments = time_parser()

    from FilesIO import time_count, get_out_path
    # get path of output files
    path = get_out_path(arguments.output, 'TimeEstimation')
    log_file = path + '.TimeLog.log'

    # set log file
    set_log(log_file, arguments)

    # estimate divergence time
    estimate = EstimateTime(path)
    estimate.run_mcmc(arguments)

    time_count(start)


if __name__ == '__main__':
    main()
