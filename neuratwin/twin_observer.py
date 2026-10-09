"""Observation-only assessment used by the UI, blind challenge and benchmark.

No scenario, fault, cooling setting or hidden plant state enters this contract.
Oil and reported hot-spot observations are synthetic/reference channels, never
substitutes for the physical bench's surface probe.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import statistics
from . import twin_core as core, thermal_reference as reference, twin_studies as studies, thermal_adaptation

VERSION='observation-pipeline-6'
FIELDS=('elapsed_s','oil_c','hotspot_c','ambient_c','load_percent','voltage_pu')
OPTIONAL_FIELDS=core.PHASE_FIELDS
BLOCKERS=('missing_data','outside_model_domain','invalid_timebase','channel_disagreement','insufficient_evidence','thermal_deviation',
          'missing_phase_data','unsupported_phase_model')


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def in_domain(row,oil_only=False):
    return (0<=row['load_percent']<=250 and .4<=row['voltage_pu']<=1.6 and
            -20<=row['ambient_c']<=60 and -20<=row['oil_c']<=250 and
            (oil_only or -20<=row['hotspot_c']<=300))


def phase_state(row,required=False):
    """Validate optional RMS magnitudes without inventing phase angles.

    Legacy aggregate observations assume balance without asserting measured
    balance. A declared phase channel never silently disappears or becomes zero.
    Complete currents use RMS-equivalent copper heating and maximum-phase
    winding loading. Aggregate load is declared mean-current loading. With
    imbalance alone, retain the labelled [1+u, 1, 1-u] simulator assumption.
    Neutral RMS is a separate measurement, never reconstructed from magnitudes.
    """
    declared=any(k in row for k in OPTIONAL_FIELDS)
    load=row.get('load_percent')
    load=load if finite(load) and 0<=load<=250 else None
    result={'declared':declared,'valid':True,'hold':None,'imbalance_percent':None,
            'model_imbalance_percent':0.,'max_load_percent':load,'thermal_load_percent':load,
            'basis':'aggregate_only_assumed_balanced','channels':[],
            'neutral_basis':'not_supplied','phase_angles_available':False}
    if not declared:
        if required:result.update(valid=False,hold='missing_phase_data',basis='declared_phase_data_missing')
        return result
    result['basis']='reported_fundamental_amplitude_model'
    supplied=[k for k in OPTIONAL_FIELDS if k in row]
    result['channels']=[k for k in supplied if finite(row[k]) and row[k]>=0]
    if any(not finite(row[k]) for k in supplied):
        result.update(valid=False,hold='missing_phase_data');return result
    if any(row[k]<0 for k in supplied):
        result.update(valid=False,hold='unsupported_phase_model');return result
    currents=('phase_current_a','phase_current_b','phase_current_c')
    has_currents=any(k in row for k in currents)
    if has_currents and not all(k in row for k in currents):
        result.update(valid=False,hold='missing_phase_data');return result
    u=row.get('phase_imbalance_percent')
    if has_currents:
        values=[row[k] for k in currents];mean=sum(values)/3
        # Remove arithmetic round-off at configured boundaries, not measurement
        # excursions: only the value inferred from ratios is rounded.
        inferred=round(100*max(abs(x-mean) for x in values)/mean,10) if mean else 0.
        if u is None:u=inferred
        elif not math.isclose(u,inferred,rel_tol=1e-5,abs_tol=1e-5):
            result.update(valid=False,hold='unsupported_phase_model');return result
        if load is not None and ((mean==0) != (load==0)):
            result.update(valid=False,hold='unsupported_phase_model');return result
        if 'neutral_current' in row:
            # Triangle bounds hold for RMS norms without assuming phase angles.
            low=max(0.,2*max(values)-sum(values));high=sum(values)
            if not low-1e-5<=row['neutral_current']<=high+1e-5:
                result.update(valid=False,hold='unsupported_phase_model');return result
        result['basis']='reported_rms_magnitudes_mean_current_loading'
    if u is None:
        result.update(valid=False,hold='missing_phase_data');return result
    if not 0<=u<=60:
        result.update(valid=False,hold='unsupported_phase_model');return result
    if load==0 and u:
        result.update(valid=False,hold='unsupported_phase_model');return result
    maximum=load*(1+u/100) if load is not None else None
    thermal=load*math.sqrt(1+2*(u/100)**2/3) if load is not None else None
    if has_currents and load is not None:
        maximum=load*max(values)/mean if mean else 0.
        thermal=load*math.sqrt(sum(x*x for x in values)/3)/mean if mean else 0.
    for key,value in (('max_phase_loading_percent',maximum),('thermal_loading_percent',thermal)):
        if key in row and value is not None and not math.isclose(row[key],value,rel_tol=1e-5,abs_tol=1e-5):
            result.update(valid=False,hold='unsupported_phase_model');return result
    result.update(imbalance_percent=u,model_imbalance_percent=u,max_load_percent=maximum,thermal_load_percent=thermal,
                  neutral_basis='reported_rms_only' if 'neutral_current' in row else 'not_supplied',
                  heating_scope='Equal phase winding resistances; RMS copper losses only. No harmonic eddy-loss correction, sequence or vector-group inference.')
    return result


def phase_of(row):
    return row.get('_phase') or phase_state(row)


def input_holds(rows,oil_only=False):
    """Shared acquisition/domain gates; no residual model or warm-up threshold."""
    if not rows:return ['missing_data']
    required=tuple(k for k in FIELDS if not (oil_only and k=='hotspot_c'))
    r=rows[-1];holds=[]
    if not all(finite(r[k]) for k in required):holds.append('missing_data')
    elif not in_domain(r,oil_only):holds.append('outside_model_domain')
    if not phase_of(r)['valid']:holds.append(phase_of(r)['hold'])
    if any(not finite(x.get('elapsed_s')) for x in rows) or any(b['elapsed_s']<=a['elapsed_s'] for a,b in zip(rows,rows[1:])):
        holds.append('invalid_timebase')
    return list(dict.fromkeys(holds))


def thermal_drift(rows,p,noise):
    """One-sided CUSUM on non-overlapping five-minute oil innovations.

    The first 60 minutes are an assumed healthy commissioning reference,
    never selected using fault labels. Baseline bias is estimated once there.
    This detects excess heating, not its cause; model mismatch remains possible.
    Integrates recorded sample intervals up to two minutes without interpolating
    measurements. Five-minute blocks use the first actual sample at/after their
    endpoint; innovations are normalised to five minutes.
    """
    unavailable={'available':False,'alarm':False,'reason':'60 contiguous reference minutes, cadence ≤2 min, and one monitoring block required.'}
    if not rows or rows[-1]['elapsed_s']-rows[0]['elapsed_s']<3900 or any(not 0<b['elapsed_s']-a['elapsed_s']<=120 for a,b in zip(rows,rows[1:])):
        return unavailable
    fraction=p['core_loss_w']/(p['core_loss_w']+p['copper_loss_w'])
    def blocks(start,end):
        result=[]
        while start<end:
            stop=next((j for j in range(start+1,end+1) if rows[j]['elapsed_s']-rows[start]['elapsed_s']>=300),None)
            if stop is None:break
            result.append((start,stop));start=stop
        return result
    def innovation(start,stop):
        oil=rows[start]['oil_c']
        for a,b in zip(rows[start:stop],rows[start+1:stop+1]):
            phase=phase_of(a)
            loss=fraction*a['voltage_pu']**2+(1-fraction)*(phase['thermal_load_percent']/100)**2
            target=a['ambient_c']+p['rated_oil_rise_c']*loss**.8
            oil=target+(oil-target)*math.exp(-(b['elapsed_s']-a['elapsed_s'])/60/p['oil_tau_min'])
        return (rows[stop]['oil_c']-oil)*300/(rows[stop]['elapsed_s']-rows[start]['elapsed_s'])
    reference_end=next(i for i,r in enumerate(rows) if r['elapsed_s']-rows[0]['elapsed_s']>=3600)
    reference_blocks=blocks(0,reference_end)
    baseline=[innovation(a,b) for a,b in reference_blocks]
    if len(baseline)<8:return unavailable
    center=statistics.mean(baseline)
    allowance=max(.15,.5*noise)
    threshold=max(3.,6*noise)
    accumulated=0.;trace=[]
    for a,b in blocks(reference_end,len(rows)-1):
        residual=innovation(a,b)-center
        accumulated=max(0.,accumulated+residual-allowance)
        trace.append({'elapsed_s':rows[b]['elapsed_s'],'innovation_c':residual,'cusum_c':accumulated})
    return {'available':True,'alarm':accumulated>threshold,'cusum_c':accumulated,
            'threshold_c':threshold,'allowance_c':allowance,'reference_bias_c':center,
            'reference_end_s':rows[reference_end]['elapsed_s'],'trace':trace,
            'method':'One-sided five-minute CUSUM; healthy-prefix assumption; screening, not a cooling-fault diagnosis.'}


def canonical(rows):
    required=any(any(k in r for k in OPTIONAL_FIELDS) for r in rows)
    result=[{**{k:r.get(k) for k in FIELDS},**{k:r[k] for k in OPTIONAL_FIELDS if k in r}} for r in rows]
    for row in result:row['_phase']=phase_state(row,required)
    return result


def reference_rows(rows):
    """Oil fitting uses RMS-equivalent loading when phase scope is supplied.

    This changes neither oil channel identity nor the independently assumed
    winding parameters. Recorded voltage informs the core-loss term.
    """
    result=canonical(rows)
    for row in result:
        phase=phase_of(row)
        if not phase['valid']:raise ValueError('Oil reference phase scope is invalid or incomplete: '+phase['hold'])
        row['load_percent']=phase['thermal_load_percent']
    return [{k:r[k] for k in FIELDS} for r in result]


def winding_reference_rows(rows):
    """Reported hot-spot/oil difference uses maximum, not RMS-equivalent, load."""
    result=canonical(rows)
    for row in result:
        phase=phase_of(row)
        if not phase['valid']:raise ValueError('Winding reference phase scope is invalid or incomplete: '+phase['hold'])
        row['winding_load_percent']=phase['max_load_percent']
    return [{k:r[k] for k in ('elapsed_s','oil_c','hotspot_c','winding_load_percent')} for r in result]


def from_history(s):
    rows={r['elapsed_s']:{'elapsed_s':r['elapsed_s'],'oil_c':r.get('oil_temperature'),
        'hotspot_c':r.get('transformer_temperature'),'ambient_c':r.get('ambient_temperature'),
        'load_percent':r.get('loading_percent'),
        'voltage_pu':r.get('primary_voltage',0)/s['settings']['primary_v'],
        **{k:r[k] for k in OPTIONAL_FIELDS if k in r}} for r in s['history']}
    t=s['telemetry'];rows[s['elapsed_s']]={'elapsed_s':s['elapsed_s'],'oil_c':t.get('oil_temperature'),
        'hotspot_c':t.get('transformer_temperature'),'ambient_c':t.get('ambient_temperature'),
        'load_percent':t.get('loading_percent'),'voltage_pu':t.get('primary_voltage',0)/s['settings']['primary_v'],
        **{k:t[k] for k in OPTIONAL_FIELDS if k in t}}
    return [rows[k] for k in sorted(rows)]


def residual_details(rows,p,use_drift=True,oil_only=False):
    """Noise-aware multi-sample checks with declared engineering margins.

    The first 60 available observations estimate instrument noise only; the
    protocol supplies a healthy commissioning period. No event labels are read.
    """
    if rows[-1].get('oil_c') is None or (not oil_only and rows[-1].get('hotspot_c') is None):return {'hypothesis':'missing_data'}
    valid=[r for r in rows if r.get('oil_c') is not None and (oil_only or r.get('hotspot_c') is not None)]
    if len(valid)<15:return {'hypothesis':'insufficient_evidence'}
    first=valid[:60]
    second=[b['oil_c']-2*a['oil_c']+z['oil_c'] for z,a,b in zip(first,first[1:],first[2:])]
    center=statistics.median(second)
    noise=max(.15,1.4826*statistics.median(abs(v-center) for v in second)/math.sqrt(6))
    winding=0 if oil_only else valid[0]['hotspot_c']-valid[0]['oil_c'];diff=[]
    for a,b in zip(valid,valid[1:]):
        dt=(b['elapsed_s']-a['elapsed_s'])/60
        if oil_only:break
        if not 0<dt<=2:diff=[];winding=b['hotspot_c']-b['oil_c'];continue
        target=p['rated_winding_rise_c']*(phase_of(a)['max_load_percent']/100)**1.6
        winding=target+(winding-target)*math.exp(-dt/p['winding_tau_min'])
        diff.append(b['hotspot_c']-b['oil_c']-winding)
    margin=max(6.,6*noise)
    disagreement=len(diff)>=3 and (all(x>margin for x in diff[-3:]) or all(x<-margin for x in diff[-3:]))
    window=valid[-13:]
    if len(window)<13 or any(not 0<b['elapsed_s']-a['elapsed_s']<=120 for a,b in zip(window,window[1:])):return {'hypothesis':'insufficient_evidence'}
    ref_fraction=p['core_loss_w']/(p['core_loss_w']+p['copper_loss_w'])
    predicted=[window[0]['oil_c']]
    for a,b in zip(window,window[1:]):
        phase=phase_of(a)
        loss=ref_fraction*a['voltage_pu']**2+(1-ref_fraction)*(phase['thermal_load_percent']/100)**2
        target=a['ambient_c']+p['rated_oil_rise_c']*loss**.8
        predicted.append(target+(predicted[-1]-target)*math.exp(-(b['elapsed_s']-a['elapsed_s'])/60/p['oil_tau_min']))
    residual=statistics.mean(b['oil_c']-a for a,b in zip(predicted[-3:],window[-3:]))
    drift=thermal_drift(valid,p,noise) if use_drift else {'available':False,'alarm':False,'reason':'Baseline comparison: CUSUM disabled.'}
    thermal=residual>max(3.,6*noise) or drift['alarm']
    hypotheses=(['channel_disagreement'] if disagreement else [])+(['thermal_deviation'] if thermal else [])
    return {'hypothesis':hypotheses[0] if hypotheses else 'no_anomaly_established',
            'hypotheses':hypotheses,'oil_residual_c':residual,'noise_c':noise,'drift':drift}


def residual_assessment(rows,p):
    return residual_details(rows,p)['hypothesis']


def observed_condition(row,p,oil_only=False):
    """Presentation of valid observed limits, independent of residual diagnosis.

    Assess each channel separately: a missing oil reference cannot conceal a
    valid reported hot-spot or loading breach. No inferred hot-spot is observed
    in oil-only mode. These fields never change forecast eligibility or labels.
    """
    row=row or {}
    bounds={'oil_c':(-20,250),'hotspot_c':(-20,300),'ambient_c':(-20,60),
            'load_percent':(0,250),'voltage_pu':(.4,1.6)}
    required=tuple(k for k in FIELDS if not (oil_only and k=='hotspot_c'))
    valid={k:finite(row.get(k)) and (k not in bounds or bounds[k][0]<=row[k]<=bounds[k][1])
           for k in required}
    alerts=[]
    def add(code,parameter,value,levels,detail):
        for severity,key in reversed(tuple(zip(('WARNING','CRITICAL','TRIP'),levels))):
            if p.get(key) is not None and value>=p[key]:
                alerts.append({'code':code,'severity':severity,'parameter':parameter,'value':value,
                    'threshold':p[key],'detail':detail,'category':'observed_threshold',
                    'elapsed_s':row.get('elapsed_s') if valid.get('elapsed_s') else None})
                break
    phase=phase_of(row)
    if valid.get('load_percent'):
        maximum=phase['max_load_percent'] if phase['valid'] else row['load_percent']
        parameter='max_phase_loading_percent' if phase['valid'] and phase['declared'] else 'loading_percent'
        add(parameter,parameter,maximum,('load_warning','load_critical','load_trip'),
            'Observed maximum phase loading exceeds the configured threshold.' if phase['declared'] and phase['valid'] else 'Observed aggregate loading exceeds the configured threshold.')
    if phase['valid'] and phase['imbalance_percent'] is not None and phase['imbalance_percent']>=core.PHASE_WARNING:
        severity='CRITICAL' if phase['imbalance_percent']>=core.PHASE_CRITICAL else 'WARNING'
        alerts.append({'code':'phase_imbalance','severity':severity,'parameter':'phase_imbalance_percent',
            'value':phase['imbalance_percent'],'threshold':core.PHASE_CRITICAL if severity=='CRITICAL' else core.PHASE_WARNING,
            'detail':'Reported fundamental phase-current imbalance exceeds the illustrative review threshold.',
            'category':'observed_threshold','elapsed_s':row.get('elapsed_s') if valid.get('elapsed_s') else None})
    if valid.get('hotspot_c'):
        add('transformer_temperature','hotspot_c',row['hotspot_c'],('temperature_warning','temperature_critical','temperature_trip'),
            'Reported hot-spot temperature exceeds the configured threshold.')
    if valid.get('voltage_pu'):
        add('voltage','voltage_deviation_pu',abs(row['voltage_pu']-1),('voltage_warning_pu','voltage_critical_pu','voltage_trip_pu'),
            'Observed voltage is outside the configured operating band.')
    if valid.get('ambient_c') and row['ambient_c']>45:
        alerts.append({'code':'ambient','severity':'WARNING','parameter':'ambient_c','value':row['ambient_c'],
            'threshold':45,'detail':'High observed ambient temperature; review cooling capability.',
            'category':'observed_threshold','elapsed_s':row.get('elapsed_s') if valid.get('elapsed_s') else None})
    rank={'WARNING':1,'CRITICAL':2,'TRIP':3}
    severity=max((rank[a['severity']] for a in alerts),default=0)
    unavailable=[k for k in required if not valid[k]]
    if not phase['valid']:unavailable+=['phase_current_model']
    status=('NORMAL','WARNING','CRITICAL','TRIP')[severity] if severity or not unavailable else 'UNKNOWN'
    return {'observed_status':status,'observed_alerts':alerts,
        'observed_channels':[k for k in required if valid[k]]+phase['channels'],'unavailable_observed_channels':unavailable,
        'phase_scope':{**phase,'note':'Optional phase observations use the declared fundamental amplitude family; no harmonics or phase-angle diagnosis.' if phase['declared'] else 'Aggregate loading only: balanced phase loading is a model assumption, not an observation of balance.'},
        'observed_scope':'Configured limits on valid recorded channels only. No threshold breach does not establish asset health or exclude faults. '+
            ('Hot-spot is not observed in oil-only mode; there is no observed winding threshold assessment.' if oil_only else 'Reported hot-spot is an observed reference channel; threshold severity does not establish the cause.')}


def present_observed_condition(result,condition):
    """Severity controls advice and headlines without changing evaluated outputs."""
    result.update(deepcopy(condition))
    status=condition['observed_status']
    if condition['observed_alerts']:
        result['presentation_headline']=f'Observed {status.lower()} threshold breach'
        urgent=status in ('CRITICAL','TRIP')
        result['next_action']=('Investigate the observed '+status.lower()+' threshold breach now; verify the affected reference channel and follow the configured operating response. Do not wait for a forecast or a diagnostic hypothesis.'
            if urgent else 'Review the observed warning and verify the affected channel; diagnostic hypotheses do not override the measured threshold.')
        if not result['available']:result['next_action']+=' Forecast remains withheld: '+result['reason']
        if condition['unavailable_observed_channels']:
            result['next_action']+=' Restore missing or invalid channels; the valid observed breach still requires attention.'
    elif not result['available']:
        result['presentation_headline']='Evidence hold: '+result['hypothesis'].replace('_',' ')
    elif status=='UNKNOWN':
        result['presentation_headline']='Observed condition unavailable'
    else:
        result['presentation_headline']='No threshold breach in available observed channels'
    return result


def threshold_assess(rows,settings=None,*,temperature_mode='oil_and_hotspot'):
    """Actual threshold-only comparator: observed limits and input validity.

    Never calls the residual, CUSUM or forecast routines. Missing oil cannot
    suppress an otherwise valid loading limit, just as in the full assessor.
    Instantaneous limits need no healthy prefix or residual warm-up period.
    """
    if temperature_mode not in ('oil_only','oil_and_hotspot'):raise ValueError('Declare oil_only or oil_and_hotspot.')
    p=settings or core.Settings().model_dump();oil_only=temperature_mode=='oil_only';rows=canonical(rows)
    if oil_only:
        for row in rows:row['hotspot_c']=None
    condition=observed_condition(rows[-1] if rows else None,p,oil_only)
    holds=input_holds(rows,oil_only)
    mapping={'loading_percent':'overload','max_phase_loading_percent':'overload','voltage':'voltage_deviation',
             'transformer_temperature':'observed_overtemperature','ambient':'high_ambient','phase_imbalance':'phase_imbalance'}
    signals=list(dict.fromkeys([*holds,*(mapping[a['code']] for a in condition['observed_alerts'])]))
    return {**condition,'method':'threshold_only','hypothesis':signals[0] if signals else 'no_threshold_breach',
            'hypotheses':signals,'input_eligible':not holds,'validity':{'input_eligible':not holds,'holds':holds},
            'any_warning':bool(condition['observed_alerts'] or holds),
            'diagnostic_scope':'Observed limits and acquisition validity only; no cooling-cause or sensor-bias diagnosis, residual/CUSUM, or forecast.'}


def assess(rows,settings=None,horizon=30,*,use_drift=True,temperature_mode='oil_and_hotspot'):
    if temperature_mode not in ('oil_only','oil_and_hotspot'):
        raise ValueError('Declare oil_only or oil_and_hotspot; a dropped channel never silently changes capability.')
    if not isinstance(horizon,int) or not 1<=horizon<=30:
        raise ValueError('Observation forecast horizon must be 1–30 minutes; longer studies are not validated here.')
    oil_only=temperature_mode=='oil_only'
    rows=canonical(rows);p=settings or core.Settings().model_dump()
    if oil_only:
        for row in rows:row['hotspot_c']=None
    condition=observed_condition(rows[-1] if rows else None,p,oil_only)
    capability={'temperature_mode':temperature_mode,'forecast_target':'oil_c' if oil_only else 'hotspot_c',
        'hotspot_basis':'inferred_from_oil_and_load' if oil_only else 'reported_reference_channel',
        'channel_agreement_tested':not oil_only,'hotspot_deadline_supported':not oil_only,
        'note':'Oil-only mode cannot independently verify winding temperature or diagnose a hot-spot sensor fault.' if oil_only else 'Reported hot-spot is checked against oil and the winding reference.'}
    def withheld(cause,reason,signals=None,**extra):
        return present_observed_condition({'available':False,'version':VERSION,'hypothesis':cause,
                'hypotheses':list(dict.fromkeys([cause,*(signals or [])])),
                'capability':capability,'minutes_to_critical':None,
                'validity':{'forecast_allowed':False,'holds':[cause]},'reason':reason,
                'next_action':'Verify the temperature reference and cooling; do not use a countdown to defer investigation.' if cause=='thermal_deviation' else 'Resolve the stated evidence hold before relying on a forecast.',**extra},condition)
    if not rows:return withheld('missing_data','No observations.')
    r=rows[-1]
    signals=[]
    phase=phase_of(r)
    protective_load=phase['max_load_percent'] if phase['valid'] else r['load_percent']
    if finite(protective_load) and protective_load>=p['load_warning']:signals.append('overload')
    if phase['valid'] and phase['imbalance_percent'] is not None and phase['imbalance_percent']>=core.PHASE_WARNING:signals.append('phase_imbalance')
    if finite(r['voltage_pu']) and .4<=r['voltage_pu']<=1.6 and abs(r['voltage_pu']-1)>=p['voltage_warning_pu']:signals.append('voltage_deviation')
    required=tuple(k for k in FIELDS if not (oil_only and k=='hotspot_c'))
    holds=input_holds(rows,oil_only)
    if holds:
        reasons={'missing_data':'Required reference channels are missing; forecast withheld.',
                 'outside_model_domain':'Observed inputs are outside the supported model domain; no clamping or forecast.',
                 'invalid_timebase':'Observations must have finite, strictly increasing elapsed times.',
                 'missing_phase_data':'Declared phase channels are incomplete; phase-dependent forecasts are withheld.',
                 'unsupported_phase_model':'Reported phase channels are inconsistent or exceed the supported RMS heating envelope; no balanced fallback or forecast.'}
        result=withheld(holds[0],' '.join(reasons[x] for x in holds),signals)
        result['validity']['holds']=holds
        return result
    # A missing or invalid earlier sample is a gap, not an observation to interpolate.
    gaps=[i for i,x in enumerate(rows) if not all(finite(x[k]) for k in required) or not in_domain(x,oil_only) or not phase_of(x)['valid']]
    gaps.extend(i-1 for i in range(1,len(rows)) if rows[i]['elapsed_s']-rows[i-1]['elapsed_s']>120)
    if gaps:rows=rows[max(gaps)+1:]
    def telemetry(x):
        load=x['load_percent']/100;secondary=p['secondary_v']*x['voltage_pu']*(1-.035*load)
        return {'timestamp':(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=x['elapsed_s'])).isoformat(),
            'source':'industrial','quality':'qualified','transformer_temperature':x['hotspot_c'],
            'hotspot_temperature':None,'oil_temperature':x['oil_c'],'ambient_temperature':x['ambient_c'],
            'loading_percent':x['load_percent'],'primary_voltage':p['primary_v']*x['voltage_pu'],
            'secondary_voltage':secondary,'secondary_current':load*p['rated_kva']*1000/(math.sqrt(3)*p['secondary_v']),
            'phase_imbalance_percent':phase_of(x)['imbalance_percent'],
            'max_phase_loading_percent':phase_of(x)['max_load_percent'],
            'thermal_loading_percent':phase_of(x)['thermal_load_percent']}
    t=telemetry(r);previous=None
    if len(rows)>1 and all(isinstance(rows[-2][k],(int,float)) and math.isfinite(rows[-2][k]) for k in required):previous=telemetry(rows[-2])
    analysis=core.analyse(t,{**p,'nominal_voltage':p['primary_v']},previous)
    # A post-gap monitoring window is not a new healthy commissioning reference.
    residual=residual_details(rows,p,use_drift and not gaps,oil_only)
    if gaps and residual.get('drift') is not None:
        residual['drift']['reason']='Commissioning continuity lost; CUSUM stays unavailable until a reviewed new reference is supplied.'
    signals=list(dict.fromkeys([*signals,*residual.get('hypotheses',[])]))
    holds=[x for x in residual.get('hypotheses',[residual['hypothesis']]) if x in BLOCKERS]
    if holds:
        reason=('Observed heating no longer agrees with the nominal thermal model. Forecast and time-to-limit are withheld until the discrepancy is resolved.'
                if 'thermal_deviation' in holds else 'Establish enough contiguous observations and independent channel agreement before forecasting.')
        result=withheld(holds[0],reason,signals,analysis=analysis,residual=residual)
        result['validity']['holds']=holds
        return result
    hypothesis=signals[0] if signals else 'no_anomaly_established'
    # An oil-only estimate never becomes an observed winding channel or a deadline.
    hotspot=r['hotspot_c']
    if oil_only:
        winding=p['rated_winding_rise_c']*(phase_of(rows[0])['max_load_percent']/100)**1.6
        for a,b in zip(rows,rows[1:]):
            target=p['rated_winding_rise_c']*(phase_of(a)['max_load_percent']/100)**1.6
            winding=target+(winding-target)*math.exp(-(b['elapsed_s']-a['elapsed_s'])/60/p['winding_tau_min'])
        hotspot=r['oil_c']+winding
    # A reviewed fit affects eligible projections only. Keep p unchanged above:
    # replacing the diagnostic reference lost sensor-bias signals in development.
    try:projection_settings,winding_reference=thermal_adaptation.forecast_settings(p,oil_only=oil_only)
    except ValueError as error:return withheld('invalid_winding_reference',str(error),signals,analysis=analysis,residual=residual)
    trajectory=studies.observation_projection(projection_settings,r,phase,hotspot,horizon)
    crossing=None if oil_only else next((x['minute'] for x in trajectory['points'] if x['temperature_c']>=p['temperature_critical']),None)
    return present_observed_condition({'available':True,'version':VERSION,'hypothesis':hypothesis,'hypotheses':signals,
        'capability':capability,'validity':{'forecast_allowed':True,'holds':[]},'residual':residual,'analysis':analysis,
        'forecast':trajectory,'minutes_to_critical':crossing,'winding_forecast_reference':winding_reference,
        'decision_scope':{'method':'observation_only','maximum_horizon_min':30,'scenario_inputs_used':False,
                          'safe_operating_deadline':False,'calibrated_prediction_interval':False,
                          'future_disturbances_known':False},
        'inferred_hotspot_c':hotspot if oil_only else None,
        'next_action':'Review active electrical signals and monitor measured oil; no validated hot-spot deadline is available.' if oil_only else 'Use the conditional trajectory with current alerts; reassess on each observation.',
        'assumptions':'Nominal cooling and constant observed inputs; no fault label or hidden state. '+
            ('Complete RMS currents use equal-resistance copper heating and maximum-phase winding loading; imbalance-only input retains the illustrative amplitude pattern. No harmonics or phase-angle inference. ' if phase['declared'] else 'No phase channels supplied: balanced phase loading is assumed, not established. ')+
            'A clear residual is not proof that every fault is absent. '+
            ('Only oil forecasts are scored. Hot-spot is inferred with an assumed initial winding equilibrium and uncalibrated winding parameters; it is not a measurement or a safe operating time.' if oil_only else 'Reported temperatures initialise the conditional forecast; parameter mismatch remains possible. '+('A reviewed prefix fitted the winding projection only; diagnostic screening retains the configured reference.' if winding_reference['used'] else 'Winding coefficients remain configured assumptions.'))},condition)
