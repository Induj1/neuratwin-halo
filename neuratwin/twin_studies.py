"""Read-only, reproducible studies of a specific saved industrial run.

These are conditional engineering studies, not calibrated failure probabilities.
Forecasts are frozen before subsequent observations and can fail their baseline.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math
from . import twin_core as core

VERSION = 'halo-study-1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def qualification(s):
    reasons=[]
    if s['breaker']!='CLOSED':reasons.append('The simulated breaker is open. Investigate recovery before planning energised operation.')
    if any(a['code']=='sensor_residual' for a in s['analysis']['alerts']):
        reasons.append('Temperature-channel disagreement: verify an independent reference before forecasting this channel.')
    if s['telemetry']['quality']!='qualified':reasons.append('The source is not qualified.')
    if core.electrical(s)['event'] in ('short_circuit','surge','storm','overvoltage','undervoltage','combined','gas','low_oil'):
        reasons.append('An electrical or internal-fault scenario is active; investigate protection before using thermal load planning.')
    return reasons


def projection(s, horizon_min, reduction_pct=0, delay_min=0, parameter_scale=1.):
    """Independent closed-form forecast from the origin. No future rows are read.

    Operating inputs and any thermal/cooling disturbance are held constant.
    Automatic protection is ignored so that the consequence of inaction is visible.
    """
    p=s['settings']; i=deepcopy(s['inputs']); e=core.electrical(s)
    oil=s['telemetry']['oil_temperature']
    winding=s['telemetry']['hotspot_temperature']-oil
    original_load=e['load_pu']; points=[]; energy=0.; exposure=0.
    for minute in range(horizon_min+1):
        load=original_load*(1-reduction_pct/100 if minute>=delay_min else 1)
        cooling={'normal':1.,'degraded':.6,'failed':.3}[i['cooling']]
        if e['event']=='cooling':cooling=.3
        losses=p['core_loss_w']*e['voltage_pu']**2+p['copper_loss_w']*load**2
        oil_target=i['ambient_c']+p['rated_oil_rise_c']*parameter_scale*(losses/(p['core_loss_w']+p['copper_loss_w']))**.8/cooling
        if e['event']=='thermal':oil_target+=70
        winding_target=p['rated_winding_rise_c']*parameter_scale*load**1.6
        kw=p['rated_kva']*load*e['voltage_pu']*(1-.035*load)
        points.append({'minute':minute,'temperature_c':oil+winding,'oil_c':oil,'load_percent':load*100,'served_kw':kw})
        if minute<horizon_min:
            oil+=(oil_target-oil)*(1-math.exp(-1/(p['oil_tau_min']*parameter_scale)))
            winding+=(winding_target-winding)*(1-math.exp(-1/p['winding_tau_min']))
            energy+=kw/60
            exposure+=max(0,oil+winding-p['temperature_warning'])
    return {'points':points,'served_kwh':energy,'thermal_exposure_c_min':exposure,
            'peak_c':max(x['temperature_c'] for x in points)}


def freeze(s, horizon):
    holds=qualification(s)
    if holds:raise ValueError(' '.join(holds))
    central=projection(s,horizon);low=projection(s,horizon,parameter_scale=.85);high=projection(s,horizon,parameter_scale=1.15)
    points=[{**p,'lower_c':min(lo['temperature_c'],hi['temperature_c'],p['temperature_c']),
             'upper_c':max(lo['temperature_c'],hi['temperature_c'],p['temperature_c'])}
            for p,lo,hi in zip(central['points'],low['points'],high['points'])]
    proof={'version':VERSION,'run_id':s['id'],'source':'industrial','origin':s['telemetry']['timestamp'],
           'origin_elapsed_s':s['elapsed_s'],'origin_revision':s['revision'],'horizon_min':horizon,
           'initial_temperature_c':s['telemetry']['transformer_temperature'],'input_signature':core.input_signature(s),
           'settings':deepcopy(s['settings']),'inputs':deepcopy(s['inputs']),'profile':core.summary(s)['profile'],
           'points':points,'target':'transformer_temperature',
           'assumptions':['Inputs and active cooling/heating disturbance held constant; protection ignored.',
                          'Shaded bounds vary thermal-rise parameters and oil time constant by ±15%; they are not confidence intervals.',
                          'Scoring against this simulated plant establishes internal consistency, not field accuracy.']}
    proof['sha256']=digest(proof)
    return proof


def verify(proof):
    return digest({k:v for k,v in proof.items() if k not in ('sha256','id','created_by','created_at','request_digest')})==proof['sha256']


def score(proof, s):
    if proof['run_id']!=s['id']:raise ValueError('Forecast and observations must belong to the same run.')
    if not verify(proof):raise ValueError('Frozen forecast integrity check failed.')
    origin=proof['origin_elapsed_s'];end=origin+proof['horizon_min']*60
    # Multiple operator actions may record the same instant. Score its final recorded state once.
    rows={r['elapsed_s']:r for r in s['history'] if origin<r['elapsed_s']<=end}
    observations=[];missing=0
    for elapsed,r in sorted(rows.items()):
        if r.get('transformer_temperature') is None or not r.get('channel_qualified',False):missing+=1;continue
        minute=(elapsed-origin)/60;left=int(math.floor(minute));right=min(left+1,len(proof['points'])-1)
        pred=proof['points'][left]['temperature_c']+(minute-left)*(proof['points'][right]['temperature_c']-proof['points'][left]['temperature_c'])
        observations.append({'minute':minute,'actual_c':r['transformer_temperature'],'predicted_c':pred,
                             'assumptions_held':r.get('input_signature')==proof['input_signature'],
                             'absolute_error_c':abs(r['transformer_temperature']-pred),
                             'persistence_error_c':abs(r['transformer_temperature']-proof['initial_temperature_c'])})
    held=[r for r in observations if r['assumptions_held']]
    def metrics(rows):
        return {'count':len(rows),'mae_c':sum(r['absolute_error_c'] for r in rows)/len(rows) if rows else None,
                'persistence_mae_c':sum(r['persistence_error_c'] for r in rows)/len(rows) if rows else None}
    measured=metrics(held)
    verdict='Awaiting future qualified observations' if not observations else 'Insufficient comparable observations'
    if len(held)>=3:
        verdict='Model improves on persistence in this window' if measured['mae_c']<measured['persistence_mae_c'] else 'Model does not improve on persistence in this window'
    return {'verdict':verdict,'complete':s['elapsed_s']>=end,'observations':observations,
            'all_observations':metrics(observations),'unchanged_inputs':measured,
            'changed_input_samples':len(observations)-len(held),'unqualified_samples':missing,
            'note':'No future rows were used when freezing. Changed inputs and unqualified channels are excluded from the comparable-window result.'}


def plan(s, horizon, max_delay):
    holds=qualification(s)
    if holds:return {'available':False,'holds':holds,'candidates':[],'recommendation':None}
    baseline=projection(s,horizon);candidates=[];p=s['settings']
    for reduction in (0,10,20,30,40,50,60,70,80,90,100):
        for delay in sorted(set((0,min(5,max_delay),max_delay))):
            if delay>=horizon:continue
            central=projection(s,horizon,reduction,delay)
            variants=[projection(s,horizon,reduction,delay,scale) for scale in (.85,1.15)]
            upper=max(central['peak_c'],*(v['peak_c'] for v in variants));reasons=[]
            post_load=s['telemetry']['loading_percent']*(1-reduction/100)
            if upper>=p['temperature_critical']:reasons.append('Thermal sensitivity envelope reaches the critical limit.')
            if post_load>=p['load_critical']:reasons.append('Post-action load remains at or above the critical level.')
            if s['analysis']['status'] in ('CRITICAL','TRIP') and delay*60>=max(0,p['critical_delay_s']-s['critical_s']):
                reasons.append('The configured protection delay expires before this action.')
            candidates.append({'reduction_pct':reduction,'delay_min':delay,'peak_c':central['peak_c'],
                'sensitivity_peak_c':upper,'curtailed_kwh':max(0,baseline['served_kwh']-central['served_kwh']),
                'served_kwh':central['served_kwh'],'thermal_exposure_c_min':central['thermal_exposure_c_min'],
                'passes':not reasons,'reasons':reasons,'points':central['points']})
    passing=[c for c in candidates if c['passes']]
    chosen=min(passing,key=lambda c:(c['curtailed_kwh'],c['reduction_pct'],c['delay_min'])) if passing else None
    return {'available':True,'run_id':s['id'],'origin_revision':s['revision'],'origin_elapsed_s':s['elapsed_s'],
            'horizon_min':horizon,'max_delay_min':max_delay,'baseline':baseline,'recommendation':chosen,'candidates':candidates,
            'note':'Selects the least curtailed simulated energy among enumerated candidates. Unity power factor, constant inputs and ±15% parameter sensitivity; no hardware commands or guaranteed safe operating limits.'}


def investigation(s):
    a=s['analysis']; t=s['telemetry'];codes={x['code'] for x in a['alerts']}
    if 'sensor_residual' in codes:
        title='Resolve a temperature-channel disagreement';next_check='Compare the suspect channel with an independent temperature reference; check wiring and calibration.'
        alternatives=['Sensor offset or connection problem','Reference-model error or an unobserved local thermal gradient']
    elif s['inputs']['cooling']!='normal' or core.electrical(s)['event']=='cooling':
        title='Cooling capability is reduced in this scenario';next_check='Compare temperature rise with loading and inspect the cooling path.'
        alternatives=['Configured cooling degradation','Load or ambient changes','Temperature measurement error']
    elif 'loading_percent' in codes:
        title='Loading is outside its configured operating band';next_check='Evaluate a demand reduction and record the resulting current and thermal response.'
        alternatives=['Sustained demand increase','Incorrect rating or current measurement']
    elif s['breaker']=='OPEN':
        title='Investigate the latched protection event';next_check='Read the pre-trip measurements, record the investigation and satisfy recovery holds.'
        alternatives=['Review recorded initiating condition; an open breaker does not identify root cause']
    elif codes:
        title='Review the active signals';next_check=a['maintenance'][0];alternatives=['Observed operating change','Sensor or model mismatch']
    else:
        title='No abnormality established in available channels';next_check='Freeze a forecast before advancing time, then compare it with subsequent observations.'
        alternatives=['Unobserved internal faults are not excluded by these channels']
    return {'title':title,'next_check':next_check,'alternatives':alternatives,'alerts':deepcopy(a['alerts']),
            'forecast_holds':qualification(s),'source':'industrial','run_id':s['id'],'timestamp':t['timestamp'],
            'provenance':'Deterministic evidence rules. Scenario settings are known; this is not a blind root-cause diagnosis.',
            'ai_status':'Laya is optional and is not used to make this protection or planning decision. The recorded five-case evaluation abstained on every case.'}
