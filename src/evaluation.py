import pandas as pd
import numpy as np
from prettytable import PrettyTable

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


# Import warnings filter
from warnings import simplefilter
# Ignore all future warnings
simplefilter(action='ignore', category=FutureWarning)

from dirichletcal.calib.vectorscaling import VectorScaling
from dirichletcal.calib.tempscaling import TemperatureScaling
from dirichletcal.calib.fulldirichlet import FullDirichletCalibrator

def count_parameters(model):
    """Count parameters in a network model"""
    table = PrettyTable(["Modules", "Parameters"])
    total_params = 0
    
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad: continue
        param = parameter.numel()
        table.add_row([name, param])
        total_params+=param
    
    print(table)
    print(f"Total Trainable Params: {total_params}")
    
    return total_params
    
def f3mer_comp(data_and_prob):
    """Compare the observed and predicted frequencies of mutations in 3-mers"""
    obs_pred_freq = data_and_prob[['us1','ds1','mut_type','prob']].groupby(['us1','ds1']).mean()
    
    return obs_pred_freq['mut_type'].corr(obs_pred_freq['prob'])

def freq_kmer_comp_multi(data_and_prob, k, n_class):
    """Compare the observed and predicted frequencies of mutations in 3-mers"""
    
    # Generate the column names
    d = k//2
    mer_list = ['us'+str(i) for i in list(range(1, d+1))[::-1]] + ['ds'+str(i) for i in list(range(1, d+1))]
    
    prob_list = ['prob'+str(i) for i in range(n_class)]
    
    corr_list = []
    for i in range(0, n_class):
        obs_pred_freq = pd.concat([data_and_prob[ mer_list + [prob_list[i]]], data_and_prob['mut_type']==i ], axis=1)
        
        # Get average rates for each k-mer
        obs_pred_freq = obs_pred_freq.groupby(mer_list).mean()
        
        # Calcuate correlations 
        corr_list.append(obs_pred_freq['mut_type'].corr(obs_pred_freq[prob_list[i]]))
        
    return corr_list

def f3mer_comp_rand(df, n_rows):
    """Compare the frequencies of mutations in 3-mers in two randomly generated datasets"""
    mean_corr = 0
    
    # Sampling 10 times
    sampling_times = 10 
    
    for i in range(sampling_times):
        freq1 = df[['us1','ds1','mut_type']].sample(n = n_rows).groupby(['us1','ds1']).mean()
        freq2 = df[['us1','ds1','mut_type']].sample(n = n_rows).groupby(['us1','ds1']).mean()
        #print(freq1, freq2)
        
        corr = freq1['mut_type'].corr(freq2['mut_type'])
        print('corr of 3mer freq1 and freq2:', corr)
        
        mean_corr += corr
    
    print('mean corr:', mean_corr/sampling_times)

def f5mer_comp_rand(df, n_rows):
    """Compare the frequencies of mutations in 5-mers in two randomly generated datasets"""
    mean_corr = 0
    
    # Sampling 10 times
    sampling_times = 10 
   
    for i in range(sampling_times):
        freq1 = df[['us2','us1','ds1','ds2','mut_type']].sample(n = n_rows).groupby(['us2','us1','ds1','ds2']).mean()
        freq2 = df[['us2','us1','ds1','ds2','mut_type']].sample(n = n_rows).groupby(['us2','us1','ds1','ds2']).mean()
        
        corr = freq1['mut_type'].corr(freq2['mut_type'])
        print('corr of 5mer freq1 and freq2:', corr)
        
        mean_corr += corr
    
    print('mean corr:', mean_corr/sampling_times)

def f7mer_comp_rand(df, n_rows):
    """Compare the frequencies of mutations in 7mers in two randomly generated datasets"""
    mean_corr = 0
    
    # Sampling 10 times
    sampling_times = 10 
   
    for i in range(sampling_times):
        freq1 = df[['us3','us2','us1','ds1','ds2','ds3', 'mut_type']].sample(n = n_rows).groupby(['us3','us2','us1','ds1','ds2','ds3']).mean()
        freq2 = df[['us3','us2','us1','ds1','ds2','ds3','mut_type']].sample(n = n_rows).groupby(['us3','us2','us1','ds1','ds2','ds3']).mean()
        
        corr = freq1['mut_type'].corr(freq2['mut_type'])
        print('corr of 7mer freq1 and freq2:', corr)
        
        mean_corr += corr
    
    print('mean corr:', mean_corr/sampling_times)

def corr_calc_sub(data, window, prob_names):
    """Calculate regional correlations"""
    n_class = len(prob_names)
    obs = [0]*n_class
    pred = [0]*n_class
    
    count = 0
    n_sites = len(data) 
    
    avg_names = []
    for i in range(n_class):
        avg_names = avg_names +['avg_obs'+str(i), 'avg_pred'+str(i)]
    
    last_chrom = data.loc[0, 'chrom']
    last_start = data.loc[0, 'start']//window * window # Find the window start
    
    result = pd.DataFrame(columns=avg_names)
    for i in range(n_sites):
        # First, find the corresponding window
        start = data.loc[i, 'start']//window * window
        chrom = data.loc[i, 'chrom']
        
        if chrom != last_chrom or start != last_start:
            # Calculate avg of the last region  
            avg_list = []
            for j in range(n_class):
                avg_list += [obs[j]/count, pred[j]/count]

            result = result.append(pd.DataFrame([avg_list], columns=avg_names))

            obs = [0]*n_class
            pred = [0]*n_class
            count = 0
            last_chrom = chrom
            last_start = start
            
        # Count for observed type +1
        obs[int(data.loc[i, 'mut_type'])] += 1              
        
        # Add to the cumulative mutation probs
        for j in range(n_class):
            pred[j] += data.loc[i, prob_names[j]]

        count = count + 1
 
    # Add the data of last window
    avg_list = []
    for j in range(n_class):
        avg_list += [obs[j]/count, pred[j]/count]
    result = result.append(pd.DataFrame([avg_list], columns=avg_names))
    
    # Calculate correlation for each mutation subtype
    corr_list = []
    for i in range(n_class):  
        if sum(list(result['avg_obs'+str(i)] == 0) | (result['avg_obs'+str(i)] == 1))/result.shape[0] > 0.5:
            print('Warning: too many zeros/ones (>50%) in the obs windows of size', window, 'subtype', i)
    
        corr = result['avg_obs'+str(i)].corr(result['avg_pred'+str(i)])
        corr_list.append(corr)
    
    return corr_list

class ECELoss(nn.Module):
    """
    Compute ECE (Expected Calibration Error)
    
    Use code from https://github.com/torrvision/focal_calibration
    """
    def __init__(self, n_bins=15):
        super(ECELoss, self).__init__()
        bin_boundaries = torch.linspace(0, 1, n_bins + 1)
        self.bin_lowers = bin_boundaries[:-1]
        self.bin_uppers = bin_boundaries[1:]

    def forward(self, logits, labels):
        softmaxes = F.softmax(logits, dim=1)
        confidences, predictions = torch.max(softmaxes, 1)
        accuracies = predictions.eq(labels)

        ece = torch.zeros(1, device=logits.device)
        for bin_lower, bin_upper in zip(self.bin_lowers, self.bin_uppers):
            # Calculated |confidence - accuracy| in each bin
            in_bin = confidences.gt(bin_lower.item()) * confidences.le(bin_upper.item())
            prop_in_bin = in_bin.float().mean()
            if prop_in_bin.item() > 0:
                accuracy_in_bin = accuracies[in_bin].float().mean()
                avg_confidence_in_bin = confidences[in_bin].mean()
                ece += torch.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin

        return ece

class ClasswiseECELoss(nn.Module):
    """
    Compute Classwise ECE
    
    Use code from https://github.com/torrvision/focal_calibration
    """
    def __init__(self, n_bins=15):
        super(ClasswiseECELoss, self).__init__()
        bin_boundaries = torch.linspace(0, 1, n_bins + 1)
        self.bin_lowers = bin_boundaries[:-1]
        self.bin_uppers = bin_boundaries[1:]

    def forward(self, logits, labels):
        num_classes = int((torch.max(labels) + 1).item())
        softmaxes = F.softmax(logits, dim=1)
        per_class_sce = None

        for i in range(num_classes):
            class_confidences = softmaxes[:, i]
            class_sce = torch.zeros(1, device=logits.device)
            
            # one-hot vector of all positions where the label belongs to the class i
            labels_in_class = labels.eq(i) 

            for bin_lower, bin_upper in zip(self.bin_lowers, self.bin_uppers):
                in_bin = class_confidences.gt(bin_lower.item()) * class_confidences.le(bin_upper.item())
                prop_in_bin = in_bin.float().mean()
                if prop_in_bin.item() > 0:
                    accuracy_in_bin = labels_in_class[in_bin].float().mean()
                    avg_confidence_in_bin = class_confidences[in_bin].mean()
                    class_sce += torch.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin

            if (i == 0):
                per_class_sce = class_sce
            else:
                per_class_sce = torch.cat((per_class_sce, class_sce), dim=0)

        sce = torch.mean(per_class_sce)
        return sce

def calibrate_prob(y_prob, y, device, calibr_name='FullDiri'):
    """
    Fit the calibrator
    
    Use calibrators in dirichletcal package
    """
    if calibr_name == 'VectS':
        calibr = VectorScaling(logit_constant=0.0)
    elif calibr_name == 'TempS':
        calibr = TemperatureScaling(logit_constant=0.0)
    elif calibr_name == 'FullDiri':
        calibr = FullDirichletCalibrator()       
    elif calibr_name == 'FullDiriODIR':
        l2_odir = 1e-2
        calibr = FullDirichletCalibrator(reg_lambda=l2_odir, reg_mu=l2_odir, reg_norm=False)
    
    # Fit the calibrator
    calibr.fit(y_prob, y)
    prob_cal = calibr.predict_proba(y_prob)
    print('y_prob.head():', y_prob[0:6,])
    print('prob_cal:', prob_cal[0:6, ])
    print('calibr.coef_: ', calibr.coef_)
    print('calibr.weights_:', calibr.weights_)
    
    nll_criterion = nn.CrossEntropyLoss(reduction='mean').to(device)
    ece_criterion = ECELoss(n_bins=25).to(device)
    c_ece_criterion = ClasswiseECELoss(n_bins=25).to(device)

    # Generate pseudo-logits
    logits0 = torch.log(torch.from_numpy(y_prob)).to(device)
    logits = torch.log(torch.from_numpy(np.copy(prob_cal))).to(device)
    
    labels = torch.from_numpy(y).long().to(device)
    
    # Calculate metrics before and after calibration
    nll0 = nll_criterion(logits0, labels).item()
    nll = nll_criterion(logits, labels).item()
    ece0 = ece_criterion(logits0, labels).item()
    ece = ece_criterion(logits, labels).item()
    c_ece0 = c_ece_criterion(logits0, labels).item()
    c_ece = c_ece_criterion(logits, labels).item()
    print('Before ' + calibr_name + ' scaling - NLL: %.5f, ECE: %.5f, CwECE: %.5f,' % (nll0, ece0, c_ece0))
    print('After ' + calibr_name +  ' scaling - NLL: %.5f, ECE: %.5f, CwECE: %.5f,' % (nll, ece, c_ece))
    
    return calibr, nll
