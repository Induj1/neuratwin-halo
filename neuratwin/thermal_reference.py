"""Bounded, data-identified oil thermal reference. No fault labels enter fitting.

Input load is percent of rated current. Oil must be an independently identified
oil-temperature channel; a surface probe must not be renamed to satisfy this API.
"""
import math
import numpy as np
from scipy.optimize import least_squares


def step(oil,ambient,load_percent,dt_min,rise,tau,core_fraction):
    target=ambient+rise*(core_fraction+(1-core_fraction)*(load_percent/100)**2)**.8
    return target+(oil-target)*math.exp(-dt_min/tau)


def rollout(rows,rise,tau,core_fraction):
    oil=rows[0]['oil_c'];result=[oil]
    for a,b in zip(rows,rows[1:]):
        oil=step(oil,a['ambient_c'],a['load_percent'],(b['elapsed_s']-a['elapsed_s'])/60,rise,tau,core_fraction)
        result.append(oil)
    return result


def fit(rows,core_fraction=1000/7500):
    if len(rows)<60:raise ValueError('At least 60 samples are required.')
    if not 0<=core_fraction<1:raise ValueError('Invalid core-loss fraction.')
    for r in rows:
        if not all(k in r and isinstance(r[k],(int,float)) and math.isfinite(r[k]) for k in ('elapsed_s','oil_c','ambient_c','load_percent')):
            raise ValueError('Every calibration row needs finite elapsed_s, oil_c, ambient_c and load_percent.')
        if not -20<=r['oil_c']<=200 or not -30<=r['ambient_c']<=65 or not 0<=r['load_percent']<=150:
            raise ValueError('Calibration readings exceed the supported reference envelope.')
    if any(not 0<b['elapsed_s']-a['elapsed_s']<=120 for a,b in zip(rows,rows[1:])):
        raise ValueError('Samples must be chronological, unique and no more than 120 seconds apart.')
    if rows[-1]['elapsed_s']-rows[0]['elapsed_s']<1800:raise ValueError('Record at least 30 minutes of thermal response.')
    split=int(len(rows)*.7);train=rows[:split];test=rows[split-1:]
    if np.ptp([r['load_percent'] for r in train])<20 or np.ptp([r['oil_c'] for r in train])<3:
        raise ValueError('Reference needs at least 20 percentage points of loading variation and 3 °C oil response in its training period.')
    observed=np.array([r['oil_c'] for r in train])
    fit=least_squares(lambda x:np.array(rollout(train,*x,core_fraction))-observed,[55,100],bounds=([15,10],[100,600]))
    rise,tau=map(float,fit.x);pred=rollout(test,rise,tau,core_fraction)
    errors=np.array(pred[1:])-np.array([r['oil_c'] for r in test[1:]])
    naive=np.array([r['oil_c']-test[0]['oil_c'] for r in test[1:]])
    rmse=float(np.sqrt(np.mean(errors**2)));persistence=float(np.sqrt(np.mean(naive**2)))
    condition=float(np.linalg.cond(fit.jac))
    boundary=rise<15.1 or rise>99.9 or tau<10.1 or tau>599.9
    return {'rated_oil_rise_c':rise,'oil_tau_min':tau,'core_fraction':core_fraction,
            'training_samples':len(train),'validation_samples':len(test)-1,'fit_end_s':rows[-1]['elapsed_s'],
            'validation_rmse_c':rmse,'persistence_rmse_c':persistence,'beats_persistence':rmse<persistence,
            'identified':bool(fit.success and not boundary and condition<1000),
            'jacobian_condition':condition,'at_parameter_boundary':boundary,
            'load_range_percent':[min(r['load_percent'] for r in train),max(r['load_percent'] for r in train)],
            'ambient_range_c':[min(r['ambient_c'] for r in train),max(r['ambient_c'] for r in train)],
            'method':'Bounded first-order oil reference; chronological 70/30 split. Validation uses recorded operating inputs; operational forecasts hold inputs constant.',
            'scope':'Reference-fit evidence only. Not a fault classifier, confidence interval, winding calibration or field-life estimate.'}


def forecast(reference,observation,horizon_min):
    if observation.get('oil_c') is None:return None
    return step(observation['oil_c'],observation['ambient_c'],observation['load_percent'],horizon_min,
                reference['rated_oil_rise_c'],reference['oil_tau_min'],reference['core_fraction'])


def residual_screen(reference,rows):
    """Observations only. Healthy oil-reference residual and cross-channel checks."""
    observed=[r for r in rows[-6:] if r.get('oil_c') is not None and r.get('hotspot_c') is not None]
    if not rows or rows[-1].get('oil_c') is None or rows[-1].get('hotspot_c') is None:return 'missing_data'
    if rows[-1]['load_percent']>=125:return 'overload'
    if len(observed)<4:return 'insufficient_evidence'
    # Winding offset is only an illustrative independent second-channel cross-check.
    differences=[r['hotspot_c']-r['oil_c']-23*(r['load_percent']/100)**1.6 for r in observed]
    if all(abs(v)>12 for v in differences[-3:]):return 'channel_disagreement'
    residuals=[]
    for a,b in zip(observed,observed[1:]):
        dt=(b['elapsed_s']-a['elapsed_s'])/60
        if not 0<dt<=2:continue
        expected=forecast(reference,a,dt)
        residuals.append((b['oil_c']-expected)/dt)
    if len(residuals)>=4 and sum(residuals[-4:])/4>.35:return 'thermal_deviation'
    return 'no_anomaly_established'
