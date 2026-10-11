"""Deterministic synthetic fleet. No physical device or control dependencies."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random

VERSION = 'fleet-1'
EPOCH = '2026-10-11T06:00:00+00:00'


def digest(value):
    # Browser JSON reserialisation changes 415.0 to 415; both mean the same number.
    def canonical(v):
        if isinstance(v,float) and v.is_integer():return int(v)
        if isinstance(v,dict):return {k:canonical(x) for k,x in v.items()}
        if isinstance(v,list):return [canonical(x) for x in v]
        return v
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


def stamp(minute):
    return (datetime.fromisoformat(EPOCH) + timedelta(minutes=minute)).isoformat()


def registry(seed=26):
    result = []
    names = ['Civic centre', 'Hospital feeder', 'Market square', 'Workshop district', 'Housing estate', 'Transit depot',
             'North village', 'Irrigation feeder', 'Hill settlement', 'Farm cluster', 'River crossing', 'Remote school']
    for i, name in enumerate(names):
        rural = i >= 6
        tier = [2, 3, 1, 2, 0, 3, 2, 2, 1, 0, 1, 3][i]
        a = dict(id=f'DEMO-{"R" if rural else "U"}{i % 6 + 1:02}', name=name,
                 sector='Rural north' if rural else 'Urban south', area='rural' if rural else 'urban',
                 origin='synthetic', geography='Illustrative schematic; not utility GIS',
                 x=[15, 30, 45, 20, 37, 50, 62, 80, 91, 65, 83, 94][i],
                 y=[24, 17, 31, 58, 72, 54, 21, 13, 38, 65, 75, 59][i], tier=f'T{tier}',
                 rated_kva=[100, 250, 160, 100, 63, 250, 63, 100, 25, 63, 100, 25][i],
                 secondary_v=415., ambient_c=30., rated_rise_c=55., tau_min=90., oil_limit_c=95.,
                 parameter_version=VERSION, parameter_basis='Declared synthetic parameters',
                 connectivity=['regular', 'intermittent', 'scheduled', 'visit_only'][0 if not rural else [1, 1, 2, 3, 3, 1][i-6]],
                 cadence_min=1 if not rural else 5, validity_min=30, clock_quality='synthetic exact',
                 consequence='Essential service' if i in (1, 11) else 'General service',
                 skills=['transformer inspection'], access='Illustrative rural access' if rural else 'Illustrative roadside access',
                 seed=seed, index=i)
        result.append(a)
        if a['connectivity']=='scheduled':a['cadence_min']=15
    return result


def temperature_step(temp, ambient, load, rated_rise, tau, minutes=1):
    target = ambient + rated_rise * ((load * load * 5 + 1) / 6) ** .8
    return target + (temp - target) * math.exp(-minutes / tau)


def metric(value, unit, basis, minute, asset, reason=None):
    return dict(schema_version=1,value=value, unit=unit, basis=basis if value is not None else 'unavailable',
                origin='synthetic', asset_id=asset['id'], acquired_at=stamp(minute), minute=minute,
                validity='available' if value is not None else 'unavailable', reason=reason,
                model_version=VERSION, calibration='synthetic sensor model; not physical calibration')


def sample(asset, minute, temp, demand):
    tier = int(asset['tier'][1]); current = asset['rated_kva'] * 1000 / (math.sqrt(3) * 415) * demand
    vals = {'current': (current if tier else None, 'A', 'simulated measurement'),
            'voltage': (415. if tier else None, 'V L-L', 'simulated measurement'),
            'surface': (30 + (temp-30)*.65 if tier >= 2 else None, '°C', 'simulated measurement'),
            'oil': (temp if tier >= 3 else None, '°C', 'simulated reference measurement')}
    channels = {k: metric(v, u, b, minute, asset, 'Not instrumented at this tier' if v is None else None)
                for k, (v, u, b) in vals.items()}
    reference=metric(current*1.35,'A','independent synthetic reference',minute,asset) if asset['index']==5 else None
    return dict(asset_id=asset['id'], origin='synthetic', delivery='live simulation', boot_id='synthetic-'+str(asset['seed']),
                sequence=minute, minute=minute, acquired_at=stamp(minute), parameter_version=VERSION,
                channels=channels, independent_current_reference=reference,record_id=f"{asset['id']}:{asset['seed']}:{minute}")


def initial(seed):
    assets = {}
    for a in registry(seed):
        hot = a['index'] in (1, 7)
        temp = 99. if hot else 58. + a['index']
        demand = 1.35 if hot else .65 + (a['index'] % 3)*.1
        row = sample(a, 0, temp, demand) if a['tier'] != 'T0' else None
        assets[a['id']] = dict(asset=a, connected=True, last=row, estimated_oil_c=temp,
                               findings=[], control={'load_scale':1., 'cooling':1.},
                               plant={'oil_c':temp, 'base_load':demand}, buffered=0)
        assess(assets[a['id']], 0)
    return dict(version=VERSION, seed=seed, minute=0, revision=0, origin='synthetic', assets=assets)


def freshness(state, minute):
    a = state['asset']; row = state['last']
    if row is None: return 'unavailable'
    age = minute-row['minute']
    if age > a['validity_min']: return 'expired'
    if age > a['cadence_min']*2: return 'forecast_only'
    if not state['connected']: return 'disconnected'
    return 'fresh' if age <= a['cadence_min'] else 'delayed'


def assess(state, minute):
    """Only delivered observations and declared model state; never plant fault labels."""
    row=state['last']; a=state['asset']; fresh=freshness(state,minute)
    if row is None or fresh != 'fresh': return
    current=row['channels']['current']['value']
    rated=a['rated_kva']*1000/(math.sqrt(3)*a['secondary_v'])
    candidates=[]
    reference=row.get('independent_current_reference')
    if reference and current is not None and abs(reference['value']-current)>max(1.,current*.2):
        candidates.append(('sensor_disagreement','Current channels disagree; investigate both','warning',
                           abs(reference['value']-current),'A difference','two synthetic observations'))
    if current is not None and current/rated>1.1:
        candidates.append(('loading','High loading','warning',current/rated,'per unit','simulated measurement'))
    oil=row['channels']['oil']['value']
    if oil is not None and oil>a['oil_limit_c']:
        candidates.append(('oil','Oil temperature above configured limit','critical',oil,'°C','simulated reference measurement'))
    surface=row['channels']['surface']['value']
    if surface is not None and surface>70:
        candidates.append(('surface','Elevated surface temperature','warning',surface,'°C','simulated measurement'))
    for rule,title,severity,value,unit,basis in candidates:
        old=next((f for f in state['findings'] if f['rule']==rule and f['status']=='unresolved'),None)
        if old: old.update(last_at=row['acquired_at'],value=value,evidence=deepcopy(row))
        else: state['findings'].append(dict(id=f"{a['id']}:{rule}:{minute}",rule=rule,version=VERSION,
            title=title,severity=severity,status='unresolved',value=value,unit=unit,basis=basis,
            first_at=row['acquired_at'],last_at=row['acquired_at'],evidence=deepcopy(row),acknowledged_by=None))


def advance(run, minutes):
    rows=[]
    for m in range(run['minute']+1,run['minute']+minutes+1):
        for state in run['assets'].values():
            a=state['asset']; rng=random.Random(a['seed']*100000+a['index']*2000+m)
            load=max(.1,state['plant']['base_load']*state['control']['load_scale']+.025*math.sin(m/15+a['index'])+rng.uniform(-.006,.006))
            state['plant']['oil_c']=temperature_step(state['plant']['oil_c'],a['ambient_c'],load,a['rated_rise_c']/state['control']['cooling'],a['tau_min'])
            if a['tier']=='T0': continue
            row=sample(a,m,state['plant']['oil_c'],load)
            due=a['connectivity']!='visit_only' and m % (15 if a['connectivity']=='scheduled' else a['cadence_min'])==0
            delivered=state['connected'] and due
            row['delivered']=delivered;rows.append(row)
            if delivered:
                previous=state['last'];dt=m-previous['minute'] if previous else 1
                rated=a['rated_kva']*1000/(math.sqrt(3)*415)
                # A declared model, distinct from the synthetic hidden plant temperature.
                state['estimated_oil_c']=temperature_step(state['estimated_oil_c'],a['ambient_c'],load,a['rated_rise_c'],a['tau_min'],min(dt,a['validity_min']))
                state['last']=row;assess(state,m)
            else: state['buffered']+=1
    run['minute']+=minutes
    return rows


def capabilities(state, minute):
    f=freshness(state,minute); row=state['last']; a=state['asset']
    fresh=f=='fresh'; instrumented=bool(row)
    return {
        'electrical':dict(state='available' if fresh and instrumented else 'held' if instrumented else 'unavailable',reason='Synthetic RMS screening' if fresh and instrumented else 'Fresh current and voltage required'),
        'oil_forecast':dict(state='scenario_only' if instrumented and f!='expired' else 'held',reason='Declared oil parameters and initial state; no physical qualification'),
        'surface':dict(state='available' if fresh and int(a['tier'][1])>=2 else 'unavailable',reason='Synthetic surface probe' if int(a['tier'][1])>=2 else 'No surface probe'),
        'pressure':dict(state='unavailable',reason='No pressure sensor or configured sealed-tank study for this asset'),
        'neutral_earth':dict(state='unavailable',reason='No neutral-current or earthing evidence'),
        'remaining_life':dict(state='unavailable',reason='Lifetime history and validated model absent'),
        'physical_control':dict(state='unavailable',reason='Synthetic fleet cannot operate physical relays')}


def public_asset(state, minute):
    a=state['asset']; f=freshness(state,minute); row=deepcopy(state['last'])
    if row:
        for key,channel in row['channels'].items():
            channel.update(component={'current':'windings','voltage':'bushings','surface':'tank','oil':'oil/cooling'}[key],
                           record_id=row['record_id'],age_min=minute-row['minute'])
            if channel['value'] is not None:channel['validity']=f
    findings=[deepcopy(v) for v in state['findings'] if v['status']=='unresolved']
    for v in findings:v.pop('evidence',None)
    qualified=0 if f!='fresh' or not row else sum(v['value'] is not None for v in row['channels'].values())
    severity='critical' if any(v['severity']=='critical' for v in findings) else 'warning' if findings else 'normal' if qualified else 'unknown'
    priority='Urgent' if severity=='critical' else 'Inspect' if findings else 'Restore data' if f!='fresh' else 'Routine'
    return dict(**a, last=row, freshness=f, age_min=minute-row['minute'] if row else None, connected=state['connected'],
                coverage=dict(available=qualified,total=4),condition=severity,priority=priority,findings=findings,
                capabilities=capabilities(state,minute),buffered=state['buffered'],
                estimated_oil_c=state['estimated_oil_c'] if row and f not in ('expired','unavailable') else None,
                estimate_basis='Conditional model; assumed initial state',control=deepcopy(state['control']))


def snapshot(run):
    assets=[public_asset(s,run['minute']) for s in run['assets'].values()]
    return dict(id=run['id'],version=VERSION,seed=run['seed'],revision=run['revision'],minute=run['minute'],
                time=stamp(run['minute']),origin='synthetic',assets=assets,
                counts=dict(total=len(assets),fresh=sum(a['freshness']=='fresh' for a in assets),
                            assessed=sum(a['coverage']['available']>0 for a in assets),
                            unresolved=sum(len(a['findings']) for a in assets)))


def forecast(state, minute, reduction, horizon=60):
    a=state['asset']; row=state['last']; f=freshness(state,minute)
    if not row or f!='fresh': raise ValueError('Fresh evidence required to issue a new forecast. Historical and expired observations cannot initialise a current prediction.')
    rated=a['rated_kva']*1000/(math.sqrt(3)*415); load=row['channels']['current']['value']/rated
    start=row['channels']['oil']['value']
    target='oil' if start is not None else 'modelled_oil'
    if start is None:start=state['estimated_oil_c']
    initial_age=minute-row['minute']
    if initial_age:start=temperature_step(start,a['ambient_c'],load,a['rated_rise_c'],a['tau_min'],initial_age)
    curves=[]
    for t in range(horizon+1):
        curves.append(dict(minute=minute+t,continue_c=temperature_step(start,a['ambient_c'],load,a['rated_rise_c'],a['tau_min'],t),
                           reduce_c=temperature_step(start,a['ambient_c'],load*(1-reduction/100),a['rated_rise_c'],a['tau_min'],t)))
    return dict(asset_id=a['id'],origin='synthetic',target=target,issue_minute=minute,input_cutoff=row['minute'],
                issued_at=stamp(minute),input=deepcopy(row),initial_c=start,parameters=deepcopy(a),model_version=VERSION,
                initial_extrapolation_minutes=initial_age,
                reduction_percent=reduction,horizon_min=horizon,curves=curves,load_pu=load,
                qualification='scenario_only',assumptions='Constant load and ambient; declared oil model. Reduced-load alternative is unexecuted until recorded.')


def score(proof, rows):
    samples=[]; excluded=[]
    for r in rows:
        m=r['minute']
        if not proof['issue_minute']<m<=proof['issue_minute']+proof['horizon_min']:continue
        if proof['target']!='oil' or r['channels']['oil']['value'] is None:
            excluded.append(dict(minute=m,reason='No independent synthetic oil reference for the forecast target'));continue
        if r['parameter_version']!=proof['model_version']:
            excluded.append(dict(minute=m,reason='Parameter version changed'));continue
        a=proof['parameters']; rated=a['rated_kva']*1000/(math.sqrt(3)*415)
        if abs(r['channels']['current']['value']/rated-proof['load_pu'])>.08:
            excluded.append(dict(minute=m,reason='Load differs from issued continue scenario'));continue
        actual=r['channels']['oil']['value'];pred=proof['curves'][m-proof['issue_minute']]['continue_c']
        samples.append(dict(minute=m,actual_c=actual,predicted_c=pred,error_c=actual-pred,baseline_error_c=actual-proof['initial_c']))
    mae=lambda k:sum(abs(x[k]) for x in samples)/len(samples) if samples else None
    return dict(status='scored synthetic observations' if samples else 'unscored',samples=samples,excluded=excluded,
                mae_c=mae('error_c'),persistence_mae_c=mae('baseline_error_c'),
                alternative='Unexecuted alternatives are not validated',scope='Synthetic reference only; not physical validation')
