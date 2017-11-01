'''
This module implements commonness-moderated t-test (Welch test) that uses the likelihood (commonness)
of variances compared to the lowess mean of all variances to calculate ( by weighted mean) the moderated 
variances and then augmented z-scores. 

Created on Jun 13, 2017

@author: Jiang-Nan Yang
'''

import scipy.stats as ss
from .lowess import loess_fit
import numpy as np, warnings
from scipy.optimize import minimize, fsolve
from scipy.special import gammaln, polygamma
from scipy.integrate import quad
warnings.filterwarnings("error", category=RuntimeWarning)
from .neutralstats import density, poisson_regression, neup

__all__ = ['ascertained_ttest', 'mean_median_norm', 'ttest']


def ttest(data, idxes, controls=None, paired=False, equalV=False):
    ms = {}; mvns = {}
    pvals = {}; zs = {}
    ctrls = controls; minn = 2
    if controls is None: ctrls = data.keys()
    for idx in idxes:
        ms[idx] = np.mean([np.mean(data[gene][idx]) for gene in data if len(data[gene][idx]) and gene in ctrls])
        pvals[idx] = {}; zs[idx] = {}
    if paired:
        for i in range(len(idxes[:-1])):
            idx0 = idxes[i]; idx1 = idxes[i+1]
            mvns[idx0] = {}
            for gene in data:
                d = np.array(data[gene][idx1]) - data[gene][idx0] - (ms[idx1] - ms[idx0])
                mvns[idx][gene] = [np.mean(d), np.var(d, ddof=1), len(d)]
        for idx in idxes[:-1]:
            for gene in data:
                m, v, n = mvns[idx][gene]
                t = m / (v/n)**0.5
                p = ss.t.cdf(-abs(t), n-1) * 2
                z = z_score_for_ttest_p_val(t, p)
                if v == 0:
                    p = np.nan; z = np.nan
                pvals[idx][gene] = p; zs[idx][gene] = z
    else:
        for idx in idxes: 
            mvns[idx] = {}
            for gene in data:
                d = data[gene][idx]; n = len(d)
                if n >= minn:
                    mvns[idx][gene] = [np.mean(d) - ms[idx], np.var(d, ddof=1), n]
                else: mvns[idx][gene] = [np.nan] * 3
        for gene in data:
            for i in range(len(idxes[:-1])):
                idx = idxes[i]; idx1 = idxes[i+1]
                m0, v0, n0 = mvns[idx ][gene]
                m1, v1, n1 = mvns[idx1][gene]
                dx = m1 - m0
                t, p = ttest2(dx, v0, n0, n0, v1, n1, n1, equalV)
                z = z_score_for_ttest_p_val(t, p)
                if v0 + v1 == 0: p = np.nan; z = np.nan
                pvals[idx][gene] = p; zs[idx][gene] = z
    if len(idxes)==2: pvals = pvals[idxes[0]]; zs = zs[idxes[0]]
    return pvals, zs, mvns

def ascertained_ttest(data, idxes=[0, 1], controls=None, paired=False, debug=False, equalV=False, pre_neutralize=True):
    """
    data is a dict with id (eg. shRNA, gene) as keys and a list of readouts of different experimental conditions indexed by idxes.
    eg.: 
    data = {'geneA':[[0.0, 1.1, 2.2], [3.3, 4.4], [5.5, 6.6]], 
            'geneB':[[1.2, 2.3], [3.4, 4.5], [5.6, 6.7, 8.9]]} 
    has two genes and three experimental conditions. Each condition has two or three replicates.
    data should have already been normalized (with normal distribution; Replicates should have the same mean or median).
     
    Only data specified by idxes (subset of [0, 1, 2] for the above data) will be analyzed. 
    Comparison is done step-wise, i.e., idxes[i] vs. idxes[i+1] for i in range(len(idxes)-1).
    controls: the genes (or seqids) that are supposed to have neutral effects and the mean of them will be used as controls.
    If controls is None, then the mean of all genes will be used as controls. 
    
    If paired is True, experimental conditions must have the same number of replicates in matched order for a gene. 
    
    Return dicts:
    p values, z-scores
    if debug is True, return an additional dict containing most intermediate variables.
    """
    vbs = {}
    pvals = {}; zs = {}; pops = {}
    tps, _, mvns = ttest(data, idxes, controls, paired, equalV)
    mns = [np.nanmean([mvns[idx][gene][2] for gene in mvns[idx]]) for idx in idxes]
    if len(idxes) == 2:
        _, _, pops[0] = neup(tps, with_plot=False, minr0=0)
    else:
        for i in range(len(idxes)-1): 
            _, _, pop = neup(tps, with_plot=False, minr0=0)
            pops[i] = pop
    if pre_neutralize: print(round(pops[0],2), end='; ')
#         print("Student's t-test power of p-values:", list(pops.values()))
    for i in range(len(mvns)): 
        idx = idxes[i]
        pvals[idx] = {}; zs[idx] = {}
        i0 = max(0, i-1)
        pop = pops[i0]
        if 0 < i < len(pops)-1: pop = (pop + pops[i]) / 2
        if pre_neutralize == False: pop = 1
        elif len(idxes) == 2:
            pop = pop ** (2*mns[i]/(sum(mns)))
        vbs[idx] = estimated_deviation(mvns[idx], min(pop, 1))
    if paired:
        for idx in mvns:
            for gene in data:
                v, n, En = vbs[idx ]['Es2s'][gene], vbs[idx]['ns'][gene], vbs[idx]['Ens'][gene]
                dx = mvns[idx][gene][0]
                t = dx / (v/n)**0.5
                p = ss.t.cdf(-abs(t), En-1) * 2
                z = z_score_for_ttest_p_val(t, p)
                pvals[idx][gene] = p
                zs[idx][gene] = z
                if vbs[idx]['Vs'][gene] == 0:
                    pvals[idx][gene] = np.nan; zs[idx][gene] = np.nan
    else:
        for gene in data:
            for i in range(len(idxes[:-1])):
                idx = idxes[i]; idx1 = idxes[i+1]
                dx = mvns[idx1][gene][0] - mvns[idx][gene][0]
                v0, n0, En0 = vbs[idx ]['Es2s'][gene], vbs[idx ]['ns'][gene], vbs[idx ]['Ens'][gene]
                v1, n1, En1 = vbs[idx1]['Es2s'][gene], vbs[idx1]['ns'][gene], vbs[idx1]['Ens'][gene]
                t, p = ttest2(dx, v0, n0, En0, v1, n1, En1, equalV)
                z = z_score_for_ttest_p_val(t, p)
                pvals[idx][gene] = p
                zs[idx][gene] = z
                if vbs[idx]['Vs'][gene] + vbs[idx1]['Vs'][gene] == 0:
                    pvals[idx][gene] = np.nan; zs[idx][gene] = np.nan
            
    if len(idxes)==2: pvals = pvals[idxes[0]]; zs = zs[idxes[0]]
    if debug: 
        vbs['mvns'] = mvns
        return pvals, zs, vbs
    return pvals, zs
    
def ttest2(dx, v1, n1, En1, v2, n2, En2, equalV=False):
    if n1 <= 1 or n2 <= 1: return np.NaN, np.NaN
    if equalV:
        df = En1 + En2 - 2
        sp = np.sqrt( ( (En1-1)*v1 + (En2-1)*v2 ) / df )
        t = dx / sp / np.sqrt(1/n1 + 1/n2)
    else:
        vn1 = v1 / En1; vn2 = v2 / En2
        df = ((vn1 + vn2)**2) / ((vn1**2) / (En1 - 1) + (vn2**2) / (En2 - 1))
        t = dx / np.sqrt(v1/n1 + v2/n2)
    p = ss.t.cdf(-abs(t), df) * 2
    return t, p

def z_score_for_ttest_p_val(t, p):
    z = -ss.norm.ppf(np.array(p)/2) * np.sign(t)
    return z

def estimated_deviation(mvn, pop, span = 0.9):
    ns = []; Ns = {}; ms = []; Vs = []; Ens = {}; Es2s = {}; Vars = {}; vbs = {}
    vbs['EVs'] = {}; vbs['Vmax'] = {}; vbs['means'] = {}
    genes = sorted(mvn)
    for gene in genes:
        m, v, n = mvn[gene]
        nn = 1 + (n-1)*pop
        ns.append(nn)
        Vs.append(v * (n-1)/n * nn / (nn-1))
        ms.append(m)
        Ns[gene] = n * pop; Vars[gene] = v; vbs['means'][gene] = m
    x = np.array(ns)/np.nanmax(ns) + np.array(ms)/np.nanmax(ms)
    x[np.array(Vs)==0] = np.NaN
    logVs = np.log(Vs)
    nx = sum(abs(x)>=0)
    if nx < 25000: ElogVs, SElogVs = loess_fit(x, logVs, w=ns, span=span, get_stderror=True) # Very slow and memory intensive.
    else: ElogVs = loess_fit(x, logVs, w=ns, span=span); SElogVs = None
    S2all = loess_fit(x, (logVs - ElogVs)**2, w=ns, span=span)
#     while np.nanmin(S2all) < 0 and span > 0.4: 
#         S2all = loess_fit(x, (logVs - ElogVs)**2, w=ns, span=span); span *= 0.9
    S2all[S2all<0] = 0
    meanns = loess_fit(x, ns, span=span)
    Vsmpls = polygamma(1, (meanns-1)/2)
    Vadj = Vsmpls * S2all / np.nanmax(S2all)
    if SElogVs is None: 
        xx, yy = density(x, nbins=int(50 * (nx/1000)**0.5))
        denx = poisson_regression(x, xx, yy, 7, symmetric=False)
        SElogVs = (S2all / (nx * span*0.5 * denx)) ** 0.5
    VlogV0s = SElogVs**2 + np.nanmean(np.maximum(0, S2all - Vadj)) * S2all / np.nanmean(S2all)
    def fVls2(V, s2, n, ElogV, VlogV0):
        return (1./V)**((n+1)/2) * np.exp( - (np.log(V)-ElogV)**2 / 2 / VlogV0  -  (n-1)*s2/2/V )
    def dVsigma(n, r):
#         return (n+1)/2 * (2/(n-3) - np.exp(gammaln(n/2-1) - gammaln((n-1)/2))**2) - r
        return 1 - (n-3) / 2 * np.exp(gammaln(n/2-1) - gammaln((n-1)/2))**2 - r
    def dfVls2(V, s2, n, ElogV, VlogV0): return (n-1) * s2 / 2 / V - (np.log(V) - ElogV) / VlogV0 - (n+1)/2
    # Oliphant, Travis E., "A Bayesian perspective on estimating mean, variance, and standard-deviation from data" (2006).All Faculty Publications. Paper 278.
    # http://scholarsarchive.byu.edu/facpub/278
    for i, gene in enumerate(genes):
        ElogV = ElogVs[i]; EV0 = np.exp(ElogV)
        if EV0 >= 0: # not NaN
            n = ns[i]; ElogV = ElogVs[i]; s2 = max(Vs[i], EV0/100); VlogV0 = VlogV0s[i]
            r = 0.999
            while True:
                try: 
                    Vmax = fsolve(dfVls2, min(EV0, s2)*r, args = (s2, n, ElogV, VlogV0))[0]
                    break
                except: 
                    r *= 0.9
                    if r<0.5: print('x0={}; s2={}; n={}; ElogV={}; VlogV0={}'.format(min(EV0, s2), s2, n, ElogV, VlogV0)); raise
            pts = [EV0, s2, Vmax]
            M = fVls2(Vmax, s2, n, ElogV, VlogV0)
            upperlim = max(pts); lowerlim = min(pts)
            while fVls2(upperlim, s2, n, ElogV, VlogV0) > 1e-20 * M: upperlim *= 1.1 + 10/n
            while fVls2(lowerlim, s2, n, ElogV, VlogV0) > 1e-20 * M: lowerlim /= 1.1 + 10/n
            try: M   *=     quad(lambda V:                      fVls2(V, s2, n, ElogV, VlogV0)/M, lowerlim, upperlim, points=pts)[0]
            except: print('EV0={}; s2={}; n={}; ElogV={}; VlogV0={}; M={}; upperlim={}; lowerlim={}; pts={}'.format(
                                EV0, s2, n, ElogV, VlogV0, M, upperlim, lowerlim, pts)); raise
            if n < 100 or M > 0:
                EV   = quad(lambda V:  V                 * fVls2(V, s2, n, ElogV, VlogV0)/M, lowerlim, upperlim, points=pts)[0]
                Esgm = quad(lambda V:  V**0.5            * fVls2(V, s2, n, ElogV, VlogV0)/M, lowerlim, upperlim, points=pts)[0]
                Vsgm = quad(lambda V: (V**0.5 - Esgm)**2 * fVls2(V, s2, n, ElogV, VlogV0)/M, lowerlim, upperlim, points=pts)[0]
                if Vsgm / EV < 1e-3: En = np.e + 0.5 * EV / Vsgm
                else:
                    try:  En = fsolve(dVsigma, 3.01, args=(Vsgm/EV,))[0]
                    except: 
                        try: En = fsolve(dVsigma, 6, args=(Vsgm/EV,))[0]
                        except: print('En Error: Vsgm={}; EV={}; EV0={}; s2={}; n={}; ElogV={}; VlogV0={}; M={}'.format(
                                Vsgm, EV, EV0, s2, n, ElogV, VlogV0, M))
            else:
                En = n; EV = EV0
            Ens[gene] = En
            Es2s[gene] = EV #* (En-3) / (En-1)
        else: Ens[gene] = np.nan; Es2s[gene] = np.nan; EV = np.nan; Vmax = np.nan
        vbs['EVs'][gene] = EV; vbs['Vmax'][gene] = Vmax
    vbs['Es2s'] = Es2s; vbs['Ens'] = Ens; vbs['ns'] = Ns; vbs['Vs'] = Vars
    vbs['S2all'] = S2all; vbs['Vsmpls'] = Vsmpls; vbs['ElogVs'] = ElogVs
    return vbs

def mean_median_norm(v, a0=0.1, only_positive=False):
    ''' 
    Normalize data by taking power a so that the difference between mean and median (divided by range) is minimized.
    a0 is the initial guess of a. 
    If only_positive is True, then only positive (and non-zero) values are used for the normalization. 
    But all values are returned.
    
    Returns:
    tuple: Initial values raised by the optimal power a, and a itself.
    '''
    v0 = np.array(v); v = v0 + 0.
    if only_positive: v = v[v>0]
    else: v = v[v>=0]
    v.sort()
    v = v[len(v)//10 : len(v)//10*9]
    md = np.nanmedian(v)
    def loss(a): 
        va = v ** a
        return abs(np.nanmean(va) - md**a) / (np.nanmax(va) - np.nanmin(va) + 1e-19)
    a = minimize(loss, a0, bounds=[(0.01, 10)]).x[0]
    return v0**a, float(a)
