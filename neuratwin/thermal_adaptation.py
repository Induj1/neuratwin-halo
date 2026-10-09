"""Frozen winding-reference identification from a reviewed healthy prefix only.

The observed difference is reported hot-spot minus oil, never a surface sensor.
No online bias adaptation, fault labels, future samples or oil-only inference.
"""
import hashlib
import json
import math
from copy import deepcopy
import numpy as np
from scipy.optimize import least_squares

VERSION='reviewed-winding-reference-1'
FIELDS=('elapsed_s','oil_c','hotspot_c','winding_load_percent')
BOUNDS=((5.,1.),(60.,60.))


def rollout(rows,rise,tau):
    winding=rows[0]['hotspot_c']-rows[0]['oil_c'];result=[winding]
    for a,b in zip(rows,rows[1:]):
        target=rise*(a['winding_load_percent']/100)**1.6
        winding=target+(winding-target)*math.exp(-(b['elapsed_s']-a['elapsed_s'])/60/tau)
        result.append(winding)
    return result


def fit_winding(rows,baseline_settings=None,*,reviewed_healthy=False):
    """Identify rise/tau on first 70%, validate untouched final 30%.

    Callers must pass only the approved prefix. No refit on the validation part.
    Qualification compares observed winding-difference RMSE with the unchanged
    configured reference and constant measured difference, on identical samples.
    """
    if reviewed_healthy is not True:raise ValueError('A reviewed healthy reference prefix is required for winding identification.')
    if len(rows)<60:raise ValueError('Winding reference needs at least 60 samples.')
    for row in rows:
        if any(isinstance(row.get(k),bool) or not isinstance(row.get(k),(int,float)) or not math.isfinite(row[k]) for k in FIELDS):
            raise ValueError('Winding fitting requires finite elapsed_s, oil_c, reported hotspot_c and winding_load_percent in every row.')
        if not (-20<=row['oil_c']<=200 and -20<=row['hotspot_c']<=250 and 0<=row['winding_load_percent']<=150):
            raise ValueError('Winding reference exceeds the supported healthy calibration envelope.')
        if not -10<=row['hotspot_c']-row['oil_c']<=150:
            raise ValueError('Reported hot-spot/oil difference is implausible for this reference model.')
    if any(not 0<b['elapsed_s']-a['elapsed_s']<=120 for a,b in zip(rows,rows[1:])):
        raise ValueError('Winding reference requires ordered unique samples no more than 120 seconds apart.')
    if rows[-1]['elapsed_s']-rows[0]['elapsed_s']<1800:
        raise ValueError('Winding reference needs at least 30 minutes of response.')
    split=int(len(rows)*.7);train=rows[:split];validation=rows[split-1:]
    observed=np.array([r['hotspot_c']-r['oil_c'] for r in train])
    if np.ptp([r['winding_load_percent'] for r in train])<20 or np.ptp(observed)<2:
        raise ValueError('Training needs at least 20 percentage points of loading excitation and 2 C of winding response.')
    p=baseline_settings or {'rated_winding_rise_c':23.,'winding_tau_min':7.}
    baseline=(p['rated_winding_rise_c'],p['winding_tau_min'])
    if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(x) or x<=0 for x in baseline):
        raise ValueError('Configured winding reference parameters must be finite and positive.')
    initial=np.log(np.clip(baseline,np.array(BOUNDS[0])+1e-5,np.array(BOUNDS[1])-1e-5))
    optimum=least_squares(lambda x:np.array(rollout(train,*np.exp(x)))-observed,initial,
        bounds=(np.log(BOUNDS[0]),np.log(BOUNDS[1])),loss='soft_l1',f_scale=1.,max_nfev=300)
    rise,tau=map(float,np.exp(optimum.x))
    actual=np.array([r['hotspot_c']-r['oil_c'] for r in validation[1:]])
    prediction=np.array(rollout(validation,rise,tau)[1:])
    baseline_prediction=np.array(rollout(validation,*baseline)[1:])
    initial_difference=validation[0]['hotspot_c']-validation[0]['oil_c']
    def rmse(values):return float(np.sqrt(np.mean((np.array(values)-actual)**2)))
    error=rmse(prediction);baseline_error=rmse(baseline_prediction);persistence=rmse(np.full(len(actual),initial_difference))
    condition=float(np.linalg.cond(optimum.jac))
    boundary=any(value<=low*1.01 or value>=high*.99 for value,low,high in zip((rise,tau),*BOUNDS))
    train_errors=np.array(rollout(train,rise,tau))-observed
    outlier_count=int(np.sum(abs(train_errors)>4.))
    identified=bool(optimum.success and not boundary and math.isfinite(condition) and condition<1000 and outlier_count<=max(1,len(train)//10))
    beats_baseline=error<=baseline_error*.95 and baseline_error-error>=.05
    beats_persistence=error<=persistence*.95 and persistence-error>=.05
    holds=[]
    if not identified:holds.append('parameters_not_identified')
    if not beats_baseline:holds.append('no_validation_gain_over_configured_reference')
    if not beats_persistence:holds.append('no_validation_gain_over_persistence')
    if error>3.:holds.append('validation_error_exceeds_3_c')
    data=[{k:r[k] for k in FIELDS} for r in rows]
    return {'version':VERSION,'qualified':not holds,'holds':holds,'identified':identified,
        'rated_winding_rise_c':rise,'winding_tau_min':tau,'training_samples':len(train),
        'validation_samples':len(actual),'fit_start_s':rows[0]['elapsed_s'],'fit_end_s':rows[-1]['elapsed_s'],
        'training_end_s':train[-1]['elapsed_s'],'validation_rmse_c':error,
        'configured_reference_rmse_c':baseline_error,'persistence_rmse_c':persistence,
        'beats_configured_reference':bool(beats_baseline),'beats_persistence':bool(beats_persistence),
        'jacobian_condition':condition if math.isfinite(condition) else None,'at_parameter_boundary':boundary,
        'training_large_residual_count':outlier_count,'reviewed_healthy':True,
        'fit_input_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        'training_load_range_percent':[min(r['winding_load_percent'] for r in train),max(r['winding_load_percent'] for r in train)],
        'method':'Bounded robust first-order winding difference fit; previous-sample held maximum-phase loading; chronological 70/30 validation, no validation refit.',
        'scope':'Reported hot-spot minus identified oil only. Uploader/protocol healthy-prefix assertion, not independent verification or sensor calibration. No physical surface, online bias correction, confidence interval or lifetime claim.'}


def apply_winding(settings,fit):
    """Attach a frozen projection reference; never replace screening parameters.

    Development showed that replacing the diagnostic reference lost sensor-bias
    detections. This separate reference can improve an eligible forecast but
    cannot clear any baseline diagnostic or acquisition hold.
    """
    result=deepcopy(settings)
    if fit.get('qualified'):
        result['winding_forecast_reference']=deepcopy(fit)
    return result


def forecast_settings(settings,*,oil_only=False):
    """Return projection settings only; callers retain the base for screening."""
    result=dict(settings)
    if oil_only:return result,{'used':False,'basis':'oil_only_no_reported_hotspot_reference'}
    fit=settings.get('winding_forecast_reference')
    if fit is None:return result,{'used':False,'basis':'configured_winding_parameters'}
    if not isinstance(fit,dict) or fit.get('qualified') is not True or fit.get('reviewed_healthy') is not True or fit.get('version')!=VERSION:
        raise ValueError('Stored winding forecast reference lacks qualified reviewed evidence.')
    rise,tau=(fit.get(k) for k in ('rated_winding_rise_c','winding_tau_min'))
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not low<=x<=high
           for x,low,high in zip((rise,tau),*BOUNDS)):
        raise ValueError('Stored winding forecast parameters exceed the reviewed fitting envelope.')
    digest=fit.get('fit_input_sha256')
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Stored winding forecast reference has no valid reference-input digest.')
    result.update(rated_winding_rise_c=rise,winding_tau_min=tau)
    return result,{'used':True,'basis':'reviewed_prefix_projection_only','version':VERSION,
        'fit_input_sha256':digest,'rated_winding_rise_c':rise,'winding_tau_min':tau,
        'screening_reference_unchanged':True}
