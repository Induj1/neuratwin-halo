"""Inspectable analysis. These functions never send equipment commands."""
from datetime import timedelta
import hashlib
import itertools
import json
import math
import numpy as np
from . import halo_engine as bench, halo_store as store


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def rows_for(context):
    if context.mode == 'bench':
        return store.frames(bench.config().device_id, 20000)
    if context.mode == 'transformer':
        from .app import get_readings
        rows, _ = get_readings('NR-104', context.scenario, context.dataset_id)
        return [r.model_dump(mode='json') for r in rows[:context.cursor+1]]
    if context.dataset_id:
        data = store.get('bench_dataset', context.dataset_id)
        if not data:
            raise ValueError('Recording no longer exists.')
        return data['rows'][:context.cursor+1]
    return bench.demonstration(context.scenario, context.cursor)


def model_ready(snap):
    model = snap.get('model')
    if not model or not model.get('beats_persistence'):
        return 'Qualify a healthy reference in Action Lab and fit a model first.'
    if snap['connection'] in ('stale','disconnected'):
        return 'Fresh measurements are required; cached readings cannot qualify this analysis.'
    if snap['source'] != 'simulated':
        if snap['quality']['calibration'] != 'reference recorded':
            return 'Verify each required voltage, current and surface channel first.'
        if model.get('calibration_id') != (snap.get('current') or {}).get('calibration_id'):
            return 'Calibration changed since the reference fit. Review a new model.'
    if (snap.get('current') or {}).get('quality_flags'):
        return 'Resolve acquisition quality flags before modelling.'
    if not bench.ambient_qualified(snap):
        return 'Verify the ambient probe or record an independent ambient observation.'
    return None


def investigation(snap):
    dt = 'transformer' in snap
    history = snap['history']
    reason = None if dt else model_ready(snap)
    trace = []
    model = snap.get('model') or {}
    threshold = snap['transformer']['asset']['residual_limit_c'] if dt else max(1.5, 3*model.get('validation_rmse_c',0))
    predicted = None
    previous = None
    if not reason:
        for row in history:
            observed = row.get('oil_c' if dt else 'surface_c')
            if dt:
                expected = row.get('expected_oil_c')
                if row.get('flags'): expected = None
            else:
                valid = all(row.get(k) is not None for k in ('surface_c','ambient_c','current_a')) and not row.get('quality_flags')
                delta = (bench.timestamp(row['timestamp'])-bench.timestamp(previous['timestamp'])).total_seconds() if previous else 0
                if not valid or delta > 15 or delta < 0:
                    predicted = None; previous = None; expected = None
                else:
                    predicted = observed if predicted is None else bench.surface_step(predicted, previous['ambient_c'], previous['current_a'], delta, model['coefficients'])
                    expected = predicted; previous = row
            trace.append({'timestamp':row['timestamp'],'observed_c':observed,'expected_c':expected,
                          'residual_c':observed-expected if observed is not None and expected is not None else None})
    tail = []
    for row in reversed(trace):
        if row['residual_c'] is None or row['residual_c'] <= threshold: break
        tail.append(row)
    duration = (bench.timestamp(tail[0]['timestamp'])-bench.timestamp(tail[-1]['timestamp'])).total_seconds() if len(tail)>1 else 0
    persistent = len(tail)>=3 and duration>=60
    jump = False
    if len(trace)>1:
        recent=trace[-12:]
        for a,b in zip(recent,recent[1:]):
            seconds=(bench.timestamp(b['timestamp'])-bench.timestamp(a['timestamp'])).total_seconds()
            if seconds>0 and a['observed_c'] is not None and b['observed_c'] is not None:
                jump |= abs(b['observed_c']-a['observed_c'])/seconds*60>2
    causes=[]
    if reason or snap['connection'] in ('stale','disconnected') or any(a['code'].startswith(('missing','quality','telemetry','measurement')) for a in snap['alerts']):
        causes.append({'title':'Measurement or reference unresolved','support':reason or 'Missing, stale or conflicting evidence is present.',
                       'check':'Restore the channel and compare against an independent reference before attributing an equipment fault.'})
    if jump:
        causes.append({'title':'Abrupt temperature-reading change','support':'A recent local slope exceeds the prototype 2 °C/min screening rule.',
                       'check':'Check probe attachment and an independent temperature reading; a jump alone cannot identify its cause.'})
    if persistent:
        causes.append({'title':'Persistent excess temperature','support':f'Residual above {threshold:.2f} °C for {duration/60:.1f} minutes. Reference coefficients remained frozen.',
                       'check':'Verify temperature and ambient, then inspect loading and heat rejection. Sensor bias and model mismatch remain alternatives.'})
    if snap['metrics'].get('load_pct') is not None and snap['metrics']['load_pct']>100:
        causes.append({'title':'Loading exceeds configured rating','support':f"Observed loading {snap['metrics']['load_pct']:.1f}%.",
                       'check':'Review feasible load removal and independent protection; this is not permission to overload.'})
    for alert in snap['alerts']:
        if alert['code']=='load_mismatch':
            causes.append({'title':'Branch response differs from expectation','support':alert['evidence'],
                           'check':'During a separately approved isolated branch test, compare current change with V/R. One current sensor cannot distinguish an open contact from a broken wire.'})
    if not causes:
        causes=[{'title':'Response consistent with this reference','support':'No persistent positive thermal residual in the qualified visible window.',
                 'check':'Continue observation. This does not exclude unobserved insulation or internal faults.'}]
    return {'available':not bool(reason),'reason':reason,'asset_id':snap['asset_id'],'source':snap['source'],
            'target':'oil temperature' if dt else 'surface temperature','model_id':model.get('id','distribution reference'),
            'trace':trace,'threshold_c':threshold,'persistent':persistent,'duration_seconds':duration,
            'hypotheses':causes,'method':'Frozen reference; persistent positive residual, minimum 3 samples and 60 seconds. Screening rules, not fault probabilities.',
            'evidence_ids':[e['id'] for e in snap['evidence']]}


def plan(snap, horizon, max_delay, protected):
    """Enumerate removal-only plans. No additions and no physical K4 candidate."""
    dt='transformer' in snap
    current=snap.get('current') or {}
    if not current: return {'available':False,'reason':'No observed starting state.'}
    if not dt:
        reason=model_ready(snap)
        if reason: return {'available':False,'reason':reason}
        if any(current.get(k) is None for k in ('ambient_c','surface_c','current_a','secondary_v')):
            return {'available':False,'reason':'Surface, ambient, current and secondary voltage are required.'}
        if not current.get('relay_output_configured'):
            return {'available':False,'reason':'Reported branch states are unavailable.'}
    elif current.get('confidence')=='Low':
        return {'available':False,'reason':'Resolve low-confidence transformer inputs first.'}
    candidates=[]
    delays=sorted(set([0, *range(1,min(max_delay,horizon)+1)]))
    if dt:
        from .thermal import ThermalState, forecast
        from .domain import Asset
        asset=Asset.model_validate(snap['transformer']['asset'])
        oil=current['oil_reference_c'] if current['source'].startswith('reference') else current['oil_c']
        if oil is None: return {'available':False,'reason':'No trusted oil reading.'}
        initial=ThermalState(oil,current['estimated_hotspot_c']-oil)
        limit=asset.hotspot_limit_c
        options=[{'reduction_pct':r,'label':f'{r}% demand reduction'} for r in range(0,51,5)]
    else:
        config=bench.config(); limit=snap['limits']['surface_c']; states=current['relay_states']
        if limit is None or snap['limits']['current_a'] is None: return {'available':False,'reason':'Reviewed surface and current limits are required.'}
        removable=[i for i in range(3) if states[i] and i+1 not in protected]
        options=[]
        for n in range(len(removable)+1):
            for removed in itertools.combinations(removable,n):
                kept=[on and i not in removed and i!=3 for i,on in enumerate(states)]
                amps=sum(current['secondary_v']/r for on,r in zip(kept,config.resistor_ohms) if on)
                options.append({'states':kept,'current_a':amps,'removed':[i+1 for i in removed]+([4] if states[3] else []),
                                'label':'Keep approved branches' if not removed and not states[3] else 'Remove '+', '.join('K'+str(i+1) for i in range(4) if states[i] and not kept[i])})
    for option in options:
        for delay in delays:
            reasons=[]
            if dt:
                series=forecast(asset,initial,current['load_pu'],current['ambient_c'],current['voltage_pu'],option['reduction_pct'],delay,horizon)
                peak=max(r['high_c'] for r in series)
                trace=[{'minute':r['minute'],'temperature_c':r['hotspot_c'],'upper_c':r['high_c']} for r in series]
                curtailed=current['load_pu']*asset.rated_kva*option['reduction_pct']/100*(horizon-delay)
                if current['load_pu']*(1-option['reduction_pct']/100)>1: reasons.append('Post-action load remains above nameplate in this conservative planner.')
                score=curtailed; unit='kVA·min curtailed (assumed constant demand)'
            else:
                coeff=snap['model']['coefficients']; temperatures=[current['surface_c']]*3;trace=[]
                for n in range(horizon*12+1):
                    minute=n/12
                    trace.append({'minute':minute,'temperature_c':temperatures[1],'upper_c':max(temperatures)})
                    amps=current['current_a'] if minute<delay else option['current_a']
                    temperatures=[bench.surface_step(t,current['ambient_c'],amps,5,[coeff[0]*f,coeff[1]*f,coeff[2]/f]) for t,f in zip(temperatures,[.9,1,1.1])]
                peak=max(r['upper_c'] for r in trace)
                low,high=snap['model']['current_range_a'];alow,ahigh=snap['model']['ambient_range_c']
                if not(low<=option['current_a']<=high and low<=current['current_a']<=high and alow<=current['ambient_c']<=ahigh): reasons.append('Outside reference training range.')
                if horizon*60>snap['model']['validation_span_s']: reasons.append('Horizon exceeds held-out validation duration.')
                if option['current_a']>snap['limits']['current_a']: reasons.append('Post-action current exceeds reviewed limit.')
                if delay and (current['current_a']>snap['limits']['current_a'] or states[3]): reasons.append('Delay retains excess current or prohibited K4.')
                expected=sum(current['secondary_v']/r for on,r in zip(states,config.resistor_ohms) if on)
                if abs(current['current_a']-expected)>.12: reasons.append('Load-bank mismatch; branch current prediction is unverified.')
                score=max(0,current['current_a']-option['current_a'])*current['secondary_v']*(horizon-delay)
                unit='VA·min curtailed (ideal resistors)'
            if peak>=limit: reasons.append('Sensitivity-envelope peak reaches the configured limit.')
            candidates.append({**option,'delay_min':delay,'peak_c':float(peak),'cost':float(score),'cost_unit':unit,
                               'qualifies':not reasons,'reasons':reasons,'trace':trace})
    qualifying=sorted((r for r in candidates if r['qualifies']),key=lambda r:(r['cost'],r['peak_c'],r['delay_min']))
    best=qualifying[0] if qualifying else None
    window=[r['delay_min'] for r in qualifying if best and r['label']==best['label']]
    result={'available':True,'asset_id':snap['asset_id'],'source':snap['source'],'limit_c':limit,'horizon_min':horizon,
            'recommendation':best,'latest_qualifying_delay_min':max(window) if window else None,
            'candidates':[{k:v for k,v in r.items() if k!='trace'} for r in candidates],
            'baseline':next((r['trace'] for r in candidates if r['delay_min']==0 and (r.get('reduction_pct')==0 if dt else not r.get('removed'))),[]),
            'note':'Advisory enumeration only; no commands. Constant ambient/voltage. Upper curves are ±10% parameter sensitivity, not confidence intervals. Delay is a conditional action window, not time to failure.'}
    return result


def predict(snap,horizon):
    """Freeze a measurable target, never score inferred winding temperature as truth."""
    row=snap.get('current') or {}
    times=[bench.timestamp(r['timestamp']) for r in snap['history']]
    intervals=[(b-a).total_seconds() for a,b in zip(times,times[1:]) if b>a]
    cadence=float(np.median(intervals)) if intervals else (300 if 'transformer' in snap else 5)
    if 'transformer' in snap:
        from .thermal import ThermalState,forecast
        from .domain import Asset
        if row.get('confidence')=='Low' or row.get('oil_c') is None or row.get('source')!='primary probe':
            raise ValueError('An available, unquarantined primary oil reading is required for forecast scoring.')
        asset=Asset.model_validate(snap['transformer']['asset'])
        series=forecast(asset,ThermalState(row['oil_c'],row['estimated_hotspot_c']-row['oil_c']),row['load_pu'],row['ambient_c'],row['voltage_pu'],horizon_min=horizon)
        return {'target':'oil_c','origin':row['timestamp'],'initial_c':row['oil_c'],
                'points':[{'minute':r['minute'],'predicted_c':r['oil_c']} for r in series],
                'inputs':{k:row[k] for k in ('load_pu','ambient_c','voltage_pu')},
                'model':asset.model_dump(),'model_id':'distribution-loading-model','cadence_seconds':cadence,'interval':'No calibrated probability interval.'}
    reason=model_ready(snap)
    if reason: raise ValueError(reason)
    model=snap['model']
    if not model.get('data_end_at') or bench.timestamp(model['data_end_at'])>bench.timestamp(row['timestamp']):
        raise ValueError('Reference fitting/validation must end before this forecast origin. Refit older model versions.')
    if any(row.get(k) is None for k in ('surface_c','current_a','ambient_c')): raise ValueError('Required forecast inputs are missing.')
    temp=row['surface_c'];points=[]
    for i in range(horizon*12+1):
        points.append({'minute':i/12,'predicted_c':temp})
        temp=bench.surface_step(temp,row['ambient_c'],row['current_a'],5,model['coefficients'])
    return {'target':'surface_c','origin':row['timestamp'],'initial_c':row['surface_c'],'points':points,
            'inputs':{k:row[k] for k in ('current_a','ambient_c')},'model':model,'model_id':model['id'],
            'calibration_id':row.get('calibration_id'),'cadence_seconds':cadence,'interval':'No calibrated probability interval.',
            'horizon_exceeds_validation':horizon*60>model['validation_span_s']}


def score_prediction(proof,rows):
    start=bench.timestamp(proof['origin']);end=start+timedelta(minutes=proof['horizon_min'])
    points=proof['points']; samples=[];missing=0; previous=start;gaps=0
    cadence=proof.get('cadence_seconds',5 if proof['target']=='surface_c' else 300)
    for row in rows:
        t=bench.timestamp(row['timestamp'])
        if t<=start or t>end: continue
        if (t-previous).total_seconds()>cadence*1.5:gaps+=1
        previous=t
        if row.get(proof['target']) is None or row.get('quality_flags') or (proof['target']=='oil_c' and (row.get('flags') or row.get('confidence')=='Low')):
            missing+=1;continue
        if proof['target']=='surface_c' and row.get('calibration_id')!=proof.get('calibration_id'):
            missing+=1;continue
        minute=(t-start).total_seconds()/60
        predicted=float(np.interp(minute,[p['minute'] for p in points],[p['predicted_c'] for p in points]))
        changes=[]
        for key,value in proof['inputs'].items():
            tolerance=1. if key=='ambient_c' else .02 if key=='voltage_pu' else max(.05,abs(value)*.05)
            if row.get(key) is None or abs(row[key]-value)>tolerance:changes.append(key)
        samples.append({'timestamp':row['timestamp'],'minute':minute,'actual_c':row[proof['target']],
                        'predicted_c':predicted,'error_c':predicted-row[proof['target']],
                        'persistence_error_c':proof['initial_c']-row[proof['target']], 'assumptions_changed':changes})
    qualified=[r for r in samples if not r['assumptions_changed']]
    summary=lambda values:{'count':len(values),'mae_c':float(np.mean([abs(r['error_c']) for r in values])) if values else None,
                            'rmse_c':float(np.sqrt(np.mean([r['error_c']**2 for r in values]))) if values else None,
                            'persistence_mae_c':float(np.mean([abs(r['persistence_error_c']) for r in values])) if values else None}
    reached=bool(rows) and bench.timestamp(rows[-1]['timestamp'])>=end
    if reached and (end-previous).total_seconds()>cadence*1.5:gaps+=1
    held=summary(qualified)
    comparison=('Too few unchanged-input observations for a baseline comparison.' if held['count']<3 else
                'The model beats persistence in this unchanged-input window; this is not field validation.' if held['mae_c']<held['persistence_mae_c'] else
                'Persistence is as good or better in this unchanged-input window. Review the model reference before relying on this forecast.')
    return {'status':'complete' if reached else 'awaiting future observations','all_observations':summary(samples),
            'assumptions_held':held,'baseline_comparison':comparison,'changed_input_samples':len(samples)-len(qualified),
            'missing_samples':missing,'gaps':gaps,'samples':samples,'expected_end_at':end.isoformat(),
            'coverage_note':'Metrics cover available observations only. Changed inputs are scored separately; missing channels are not interpolated.'}


def benchmark(context,rows,snapshot_fn):
    """Rolling chronological origins; each model fit sees only the past."""
    dt=context.mode=='transformer'; minimum=40 if dt else 150
    horizons=[5,15,30] if dt else [1,3,5]
    reserve=6 if dt else 60
    if len(rows)<minimum+reserve+3: raise ValueError(f'Need at least {minimum+reserve+3} recorded frames for rolling evaluation.')
    origins=sorted(set(int(i) for i in np.linspace(minimum,len(rows)-reserve-1,5)))
    results=[]; skipped=[]
    for index in origins:
        prefix=rows[:index+1]
        if dt:
            snap=snapshot_fn(context.model_copy(update={'cursor':index}))
        else:
            try:model=bench.fit_surface(prefix,'BENCHMARK')
            except ValueError as e: skipped.append({'origin':index,'reason':str(e)});continue
            if not model['beats_persistence']:
                skipped.append({'origin':index,'reason':'Past-only fit did not beat its internal persistence holdout.'});continue
            model.update(id='ROLLING-'+str(index),calibration_id=prefix[-1].get('calibration_id'))
            snap=bench.snapshot(prefix,'simulated' if context.mode=='replay' and not context.dataset_id else 'replayed','BENCHMARK')
            snap['model']=model
        for horizon in horizons:
            try:p=predict(snap,horizon)
            except ValueError as e:skipped.append({'origin':index,'reason':str(e)});break
            p['horizon_min']=horizon
            scored=score_prediction(p,rows)
            results.append({'origin':index,'at':rows[index]['timestamp'],'horizon_min':horizon,**{k:v for k,v in scored.items() if k!='samples'}})
    summaries=[]
    for horizon in horizons:
        values=[r['all_observations'] for r in results if r['horizon_min']==horizon and r['all_observations']['count']]
        n=sum(v['count'] for v in values)
        summaries.append({'horizon_min':horizon,'origin_count':len(values),'observations':n,
                          'mae_c':sum(v['mae_c']*v['count'] for v in values)/n if n else None,
                          'persistence_mae_c':sum(v['persistence_mae_c']*v['count'] for v in values)/n if n else None})
    return {'target':'oil_c' if dt else 'surface_c','results':results,'summary':summaries,'skipped':skipped,
            'method':'Up to five chronological forecast origins. Past-only fitting for the bench; distribution parameters fixed. Constant-input forecasts; no future operating inputs supplied. Overlapping origins are not independent trials.',
            'scope':'Forecasting only; no field fault-detection accuracy or calibrated probability claimed.'}


def ledger(snap,profile=None):
    history=snap['history'];current=snap.get('current') or {};dt='transformer' in snap
    result={'operating_index':snap['metrics'].get('condition_index'),'operating_note':'Reversible operating-stress screening; not insulation condition.',
            'verified_channels':sum(e.get('calibrated',False) and e['available'] for e in snap['evidence']),
            'available_channels':sum(e['available'] for e in snap['evidence']),'total_channels':len(snap['evidence']),
            'ageing_available':False,'remaining_life_years':None,'requirements':['Verified transformer/insulation profile','Historical loading and temperature coverage','Insulation-condition evidence','Validated remaining-life model'],
            'reason':'Bench surface temperature cannot establish oil-paper insulation ageing.' if not dt else 'Record explicit ageing-scenario assumptions first.'}
    if not dt or not profile: return result
    cumulative=0.; valid_seconds=0.; skipped=0;trace=[]
    rate=lambda t: math.exp(max(-60,min(60,profile['activation_k']*(1/(profile['reference_c']+273.15)-1/(t+273.15)))))
    for a,b in zip(history,history[1:]):
        seconds=(bench.timestamp(b['timestamp'])-bench.timestamp(a['timestamp'])).total_seconds()
        if not 0<seconds<=900 or any(r.get('confidence')=='Low' or r.get('estimated_hotspot_c') is None for r in (a,b)):
            skipped+=1;continue
        cumulative+=(rate(a['estimated_hotspot_c'])+rate(b['estimated_hotspot_c']))/2*seconds/3600
        valid_seconds+=seconds
        trace.append({'timestamp':b['timestamp'],'equivalent_hours':cumulative})
    result.update(ageing_available=bool(valid_seconds),reason='Conditional Arrhenius scenario using inferred hot-spot, not an insulation diagnosis or standards certification.',
                  equivalent_hours=cumulative,observed_hours=valid_seconds/3600,skipped_intervals=skipped,trace=trace,profile=profile)
    if profile.get('remaining_equivalent_hours') is not None:
        result['conditional_remaining_years']=profile['remaining_equivalent_hours']/profile['future_ageing_factor']/8760
        result['remaining_scenario_note']='Arithmetic scenario from user-supplied remaining equivalent hours and future ageing factor; NOT measured or predicted remaining useful life.'
    return result
