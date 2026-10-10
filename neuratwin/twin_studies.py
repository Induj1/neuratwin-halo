"""Read-only, reproducible studies of a specific saved industrial run.

These are conditional engineering studies, not calibrated failure probabilities.
Forecasts are frozen before subsequent observations and can fail their baseline.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math
from itertools import product
from . import twin_core as core

VERSION = 'halo-study-2'


def observation_projection(settings, observation, phase, initial_hotspot, horizon_min):
    """Short conditional forecast from observed channels, never scenario state.

    Equal-resistance RMS copper heating and maximum-phase winding rise. No
    knowledge of cooling faults, future inputs, phase angles or true plant state.
    Energy is deliberately unavailable: current magnitudes do not establish PF.
    """
    if not isinstance(horizon_min,int) or not 1<=horizon_min<=30:
        raise ValueError('Observation projection supports 1–30 minutes only.')
    if not phase['valid']:raise ValueError('Qualified phase scope is required.')
    p=settings;r=observation
    oil=r['oil_c'];winding=initial_hotspot-oil
    loss=p['core_loss_w']*r['voltage_pu']**2+p['copper_loss_w']*(phase['thermal_load_percent']/100)**2
    oil_target=r['ambient_c']+p['rated_oil_rise_c']*(loss/(p['core_loss_w']+p['copper_loss_w']))**.8
    winding_target=p['rated_winding_rise_c']*(phase['max_load_percent']/100)**1.6
    points=[];exposure=0.
    for minute in range(horizon_min+1):
        points.append({'minute':minute,'temperature_c':oil+winding,'oil_c':oil,
                       'load_percent':r['load_percent']})
        if minute<horizon_min:
            oil+=(oil_target-oil)*(1-math.exp(-1/p['oil_tau_min']))
            winding+=(winding_target-winding)*(1-math.exp(-1/p['winding_tau_min']))
            exposure+=max(0,oil+winding-p['temperature_warning'])
    return {'points':points,'peak_c':max(x['temperature_c'] for x in points),
            'thermal_exposure_c_min':exposure,'served_kwh':None,
            'method':'observed_rms_thermal_reference','scenario_inputs_used':False,
            'uncertainty':'No calibrated interval; future input changes and unmodelled faults are not bounded.'}


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


def projection(s, horizon_min, reduction_pct=0, delay_min=0, parameter_scale=1., scales=None):
    """Hold current inputs/disturbance; use the same demand action as execution.

    Independent scales are oil rise, winding rise, oil tau, winding tau.
    Protection is ignored only for this explicitly unprotected consequence study.
    """
    p=s['settings']; i=s['inputs']; e=core.electrical(s)
    changed={**s,'inputs':deepcopy(s['inputs'])};core.reduce_demand(changed,reduction_pct);after=core.electrical(changed)
    ro,rw,to,tw=scales or (parameter_scale,parameter_scale,parameter_scale,1.)
    oil=s['telemetry']['oil_temperature'];winding=s['telemetry']['hotspot_temperature']-oil
    points=[];energy=0.;exposure=0.
    for minute in range(horizon_min+1):
        active=after if minute>=delay_min else e
        load=active['load_pu'];cooling={'normal':1.,'degraded':.6,'failed':.3}[i['cooling']]
        if e['event'] in ('cooling','combined'):cooling=.3
        oil_target=i['ambient_c']+p['rated_oil_rise_c']*ro*(active['losses_w']/(p['core_loss_w']+p['copper_loss_w']))**.8/cooling
        if e['event'] in ('thermal','combined'):oil_target+=70
        winding_target=p['rated_winding_rise_c']*rw*active['max_phase_load_pu']**1.6
        kw=math.sqrt(3)*active['secondary_voltage']*active['secondary_current']/1000
        points.append({'minute':minute,'temperature_c':oil+winding,'oil_c':oil,'load_percent':load*100,'served_kw':kw,
                       **{k:active[k] for k in core.PHASE_FIELDS}})
        if minute<horizon_min:
            oil+=(oil_target-oil)*(1-math.exp(-1/(p['oil_tau_min']*to)))
            winding+=(winding_target-winding)*(1-math.exp(-1/(p['winding_tau_min']*tw)))
            energy+=kw/60;exposure+=max(0,oil+winding-p['temperature_warning'])
    return {'points':points,'served_kwh':energy,'thermal_exposure_c_min':exposure,
            'peak_c':max(x['temperature_c'] for x in points)}


def sensitivity(s,horizon,reduction=0,delay=0):
    return [projection(s,horizon,reduction,delay,scales=corner)
            for corner in product((.85,1.15),repeat=4)]


def freeze(s, horizon):
    holds=qualification(s)
    if holds:raise ValueError(' '.join(holds))
    central=projection(s,horizon);variants=sensitivity(s,horizon)
    points=[{**p,'lower_c':min(p['temperature_c'],*(v['points'][n]['temperature_c'] for v in variants)),
             'upper_c':max(p['temperature_c'],*(v['points'][n]['temperature_c'] for v in variants))}
            for n,p in enumerate(central['points'])]
    proof={'version':VERSION,'run_id':s['id'],'source':'industrial','origin':s['telemetry']['timestamp'],
           'origin_elapsed_s':s['elapsed_s'],'origin_revision':s['revision'],'horizon_min':horizon,
           'initial_temperature_c':s['telemetry']['transformer_temperature'],'input_signature':core.input_signature(s),
           'settings':deepcopy(s['settings']),'inputs':deepcopy(s['inputs']),'profile':core.summary(s)['profile'],
           'phase_model':deepcopy(core.PHASE_MODEL),
           'points':points,'target':'transformer_temperature',
           'assumptions':['Inputs and active cooling/heating disturbance held constant; protection ignored.',
                          'Bounds test all 16 independent ±15% corners of oil/winding rise and time constants. No probability coverage or unmodelled-fault guarantee.',
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
    context={'version':VERSION,'run_id':s['id'],'origin_revision':s['revision'],'origin_elapsed_s':s['elapsed_s'],
             'inputs':deepcopy(s['inputs']),'phase_model':deepcopy(core.PHASE_MODEL),
             'decision_scope':{'method':'scenario_sensitivity_study','declared_cooling_used':True,
                'observation_benchmark_max_horizon_min':30,'assessment_horizon_validated':False,
                'calibrated_prediction_interval':False,'physical_action':False,
                'note':'Declared scenario inputs inform this study. It is not observation-only diagnosis or a guaranteed safe operating window.'}}
    if holds:return {**context,'available':False,'holds':holds,'candidates':[],'recommendation':None}
    # A short energy-comparison window cannot conceal an imminent later breach.
    assessment=max(240,horizon);baseline=projection(s,horizon);candidates=[];p=s['settings']
    for reduction in range(0,101,10):
        for delay in sorted(set((0,min(5,max_delay),max_delay))):
            if delay>=horizon:continue
            central=projection(s,horizon,reduction,delay)
            variants=sensitivity(s,assessment,reduction,delay)
            check=projection(s,assessment,reduction,delay)
            upper=max(check['peak_c'],*(v['peak_c'] for v in variants));reasons=[]
            changed={**s,'inputs':deepcopy(s['inputs'])};outcome=core.reduce_demand(changed,reduction);post_load=outcome['loading_percent']
            if upper>=p['temperature_critical']:reasons.append('A tested thermal corner reaches the critical limit in the 240-minute assessment.')
            if outcome['max_phase_loading_percent']>=p['load_warning']:reasons.append('Post-action maximum phase loading does not recover below the warning level.')
            if outcome['phase_imbalance_percent']>=core.PHASE_CRITICAL:
                reasons.append('Critical phase imbalance remains after demand reduction; rebalance phases or remove the energised demand.')
            if s['analysis']['status'] in ('CRITICAL','TRIP') and delay*60>=max(0,p['critical_delay_s']-s['critical_s']):
                reasons.append('The configured protection delay expires before this action.')
            candidates.append({'reduction_pct':reduction,'delay_min':delay,'peak_c':central['peak_c'],
                'post_load_percent':post_load,'post_max_phase_loading_percent':outcome['max_phase_loading_percent'],
                'post_thermal_loading_percent':outcome['thermal_loading_percent'],
                'post_phase_imbalance_percent':outcome['phase_imbalance_percent'],
                'post_neutral_current':outcome['neutral_current'],
                'sensitivity_peak_c':upper,'assessment_horizon_min':assessment,
                'curtailed_kwh':max(0,baseline['served_kwh']-central['served_kwh']),
                'served_kwh':central['served_kwh'],'thermal_exposure_c_min':central['thermal_exposure_c_min'],
                'passes':not reasons,'reasons':reasons,'points':central['points']})
    passing=[c for c in candidates if c['passes']]
    chosen=min(passing,key=lambda c:(c['curtailed_kwh'],c['reduction_pct'],c['delay_min'])) if passing else None
    return {**context,'available':True,
            'horizon_min':horizon,'assessment_horizon_min':assessment,'max_delay_min':max_delay,
            'baseline':baseline,'recommendation':chosen,'candidates':candidates,
            'note':'Least curtailed energy among enumerated actions; energy horizon is shown separately from the 240-minute thermal check. All 16 independent parameter corners are tested. Phase-current ratios and current disturbance persist; reducing demand is mitigation, not rebalancing or repair. No hardware commands or guaranteed safe limits.'}


def closure_check(s,w):
    """Structured, inspectable acceptance rules; free text is never machine proof."""
    rules=w.get('acceptance_rules')
    if not rules:return {'eligible':False,'holds':['Legacy work order has no structured acceptance rules. Create a reviewed follow-up.'],'rules':None}
    holds=[];started=next((x['elapsed_s'] for x in reversed(w['trail']) if x['status']=='verification_pending'),None)
    if started is None:return {'eligible':False,'holds':['Record investigation and action before verification.'],'rules':rules}
    begin=s['elapsed_s']-rules['stable_minutes']*60
    rows={r['elapsed_s']:r for r in s['history'] if begin<=r['elapsed_s']<=s['elapsed_s']}
    rows[s['elapsed_s']]={**s['telemetry'],'elapsed_s':s['elapsed_s'],'status':core.summary(s)['analysis']['status'],
                         'breaker':s['breaker'],'channel_qualified':not qualification(s)}
    rows=[rows[k] for k in sorted(rows)]
    if begin<started or not rows or rows[0]['elapsed_s']>begin or any(b['elapsed_s']-a['elapsed_s']>65 for a,b in zip(rows,rows[1:])):
        holds.append(f"Collect an uninterrupted {rules['stable_minutes']}-minute recovery window after the action.")
    if any(r.get('status')!='NORMAL' or r.get('breaker')!='CLOSED' or not r.get('channel_qualified') or r.get('max_phase_loading_percent',r.get('loading_percent',999))>rules['max_load_percent'] or r.get('transformer_temperature',999)>rules['max_temperature_c'] for r in rows):
        holds.append('Recovery observations must remain normal, qualified and within the recorded load/temperature limits.')
    if qualification(s):holds.extend(qualification(s))
    if s['fault']:holds.append('An active disturbance remains. Stabilisation does not establish resolution.')
    if rules['require_cooling_restored'] and s['inputs']['cooling']!='normal':holds.append('Cooling has not been restored; record temporary stabilisation instead of closing.')
    worst=max(v['peak_c'] for v in sensitivity(s,rules['forecast_horizon_min']))
    if worst>=s['settings']['temperature_critical']:holds.append('The forward thermal corner check still reaches the critical limit.')
    return {'eligible':not holds,'holds':list(dict.fromkeys(holds)),'rules':rules,'worst_forecast_c':worst,
            'checked_at_elapsed_s':s['elapsed_s'],'samples':len(rows)}


def investigation(s):
    from . import twin_observer
    s=deepcopy(s);core.add_forward_risk(s)
    observed=twin_observer.assess(twin_observer.from_history(s),s['settings'])
    a=s['analysis']; t=s['telemetry'];codes={x['code'] for x in a['alerts']}
    if codes & {'tank_pressure','pressure_rise','pressure_sensor'}:
        title='Investigate the pressure scenario';next_check='Inspect the pressure channel, tank arrangement and protection/relief assumptions; retain the work order until the pressure finding and recovery checks are resolved.'
        alternatives=['Abnormal gas-space pressure scenario','Pressure instrumentation failure; pressure alone does not establish an internal fault']
    elif s['breaker']=='OPEN' and any((r.get('secondary_current') or 0)>2*core.terminal_fault(s['settings'])['rated_secondary_a'] for r in [(s.get('trip') or {}).get('before',{})]):
        title='Investigate a high-current clearing event';next_check='Review pre-trip evidence and protection coordination. RMS data alone cannot distinguish inrush from internal or external faults.'
        alternatives=['External fault','Internal fault','Inrush or instrumentation problem; independent waveform evidence required']
    elif 'sensor_residual' in codes or 'channel_disagreement' in observed.get('hypotheses',[]):
        title='Resolve a temperature-channel disagreement';next_check='Compare the suspect channel with an independent temperature reference; check wiring and calibration.'
        alternatives=['Sensor offset or connection problem','Reference-model error or an unobserved local thermal gradient']
    elif 'thermal_deviation' in observed.get('hypotheses',[]):
        title='Thermal response differs from the reference';next_check='Check cooling and confirm the temperature channels against an independent reference.'
        alternatives=['Cooling degradation','Reference parameter mismatch','Temperature measurement error']
    elif codes & {'loading_percent','max_phase_loading_percent'}:
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
            'observation_assessment':observed,
            'provenance':'Observation assessment excludes fault labels and cooling settings. Hypotheses need independent confirmation; the industrial operator forecast separately uses its declared inputs.',
            'ai_status':'Laya is optional and is not used to make this protection or planning decision. The recorded five-case evaluation abstained on every case.'}
