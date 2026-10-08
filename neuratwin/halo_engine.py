"""Bench-specific monitoring; surface is never relabelled as oil or hot-spot."""
from datetime import datetime, timedelta, timezone
import math
import hashlib
import numpy as np
from scipy.optimize import lsq_linear
from .halo_contracts import BenchConfig
from . import halo_store as store

CHANNELS = {'primary_current_a':'A RMS primary', 'primary_v':'V RMS', 'secondary_v':'V RMS', 'current_a':'A RMS',
            'surface_c':'°C surface', 'ambient_c':'°C ambient'}


def config():
    return BenchConfig.model_validate(store.get('config','bench',BenchConfig(board='ESP32').model_dump()))


def holds(c):
    reasons = []
    for key,label in [('primary_verified','Transformer primary identity'),
                      ('secondary_verified','12 V pair and current rating'),
                      ('protection_reviewed','Enclosure, protection and independent cutoff'),
                      ('pinmap_verified','Actual chip and pin assignments'),
                      ('relay_polarity_verified','Relay polarity and reset behaviour'),
                      ('adc_interfaces_verified','All ADC interfaces and sensor isolation')]:
        if not getattr(c,key): reasons.append(label+' not verified')
    if any(getattr(c,k) is None for k in ('nominal_secondary_v','current_limit_a','surface_limit_c','active_low')):
        reasons.append('Operating limits or relay polarity are unassigned')
    if not c.reviewer or not c.review_note: reasons.append('Commissioning review not recorded')
    return reasons


def demonstration(scenario='normal', cursor=180, seed=17):
    """Independent synthetic bench plant. Labels never enter diagnosis."""
    if scenario not in ('normal','overload','heating','sensor','dropout'):
        raise ValueError('Unknown bench scenario')
    rng=np.random.default_rng(seed)
    case_id=hashlib.sha256(f'{scenario}:{seed}'.encode()).hexdigest()[:10]
    surface=29.; core=30.; rows=[]
    start=datetime(2026,10,6,9,tzinfo=timezone.utc)
    for i in range(min(cursor+1,721)):
        branches=1 if i<80 else 2 if i<140 else 3
        if scenario=='overload' and i>=140: branches=4
        voltage=12.2-.06*branches
        current=branches*voltage/39
        ambient=28+math.sin(i/130)*.2
        core+=(ambient+9+23*current**2-core)/90
        surface+=(core-2-surface)/55
        measured=surface+float(rng.normal(0,.035))
        if i>=140 and scenario=='heating': measured+=(i-140)*.035
        if i>=140 and scenario=='sensor': measured+=9
        missing=scenario=='dropout' and i>=140
        rows.append({'device_id':'SIM-BENCH', 'boot_id':'simulation', 'sequence':i,
                     'uptime_ms':i*5000,'timestamp':(start+timedelta(seconds=5*i)).isoformat(),
                     'primary_v':None if missing else 230., 'secondary_v':None if missing else voltage,
                     'current_a':None if missing else current, 'surface_c':None if missing else measured,
                     'ambient_c':None if missing else ambient,'ambient_source':'probe',
                     'relay_states':[j<branches for j in range(4)],'relay_output_configured':True, 'quality_flags':['missing_channels'] if missing else [],
                     'calibration_id':'synthetic','evidence_id':f'SIM-{case_id}-{i}'})
    return rows


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def snapshot(rows, source='measured', asset_id='BENCH-001', c=None):
    c=c or config()
    simulated=source=='simulated'
    if simulated:
        c=c.model_copy(update={'nominal_secondary_v':12.,'current_limit_a':1.,'surface_limit_c':55.})
    latest=rows[-1] if rows else None
    age=max(0,(datetime.now(timezone.utc)-timestamp(latest['timestamp'])).total_seconds()) if latest else None
    fresh=bool(latest) and (source!='measured' or age<=5)
    connection='replay' if source!='measured' else 'live' if fresh else 'stale' if latest else 'disconnected'
    calibration=store.get('calibration',latest.get('calibration_id','')) if latest else None
    calibration = calibration or {}
    channel_calibration = {
        key: simulated or bool(calibration.get(field))
        for key, field in [('primary_current_a','primary_current_a_per_mv'), ('primary_v','primary_v_per_mv'), ('secondary_v','secondary_v_per_mv'),
                           ('current_a','current_a_per_mv'), ('surface_c','surface_reference'),
                           ('ambient_c','ambient_reference')]
    }
    calibrated = all(channel_calibration[k] for k in ('secondary_v','current_a','surface_c'))
    alerts=[]; evidence=[]
    def warn(code,title,detail,severity='warning',component='transformer'):
        alerts.append({'code':code,'title':title,'evidence':detail,'severity':severity,'component':component})
    if not fresh: warn('telemetry','Waiting for fresh telemetry','No recent measurement is available. Last values are historical.','warning','controller')
    for key,unit in CHANNELS.items():
        value=latest.get(key) if latest else None
        evidence.append({'id':f'{latest["evidence_id"]}:{key}' if latest else f'NO-DATA:{key}',
                         'channel':key,'value':value,'unit':unit,'timestamp':latest.get('timestamp') if latest else None,
                         'source':source if key!='ambient_c' or not latest else ('manual observation' if latest.get('ambient_source')=='manual' else source),
                         'calibrated':channel_calibration[key],
                         'verification': 'synthetic fixture' if simulated else 'reference recorded' if channel_calibration[key] else 'manual observation' if key=='ambient_c' and latest and latest.get('ambient_source')=='manual' else 'unverified',
                         'available':value is not None})
    values=latest or {}
    if latest and not calibrated: warn('calibration','Calibration not recorded','Physical units require a recorded reference check before interpreting magnitudes.')
    if latest and values.get('quality_flags'): warn('quality','Acquisition quality warning',', '.join(values['quality_flags']),'warning','controller')
    for key in ('secondary_v','current_a','surface_c'):
        if latest and values.get(key) is None: warn('missing_'+key,'Missing '+key.replace('_',' '),'Channel is unassigned, uncalibrated or invalid.','warning', 'surface' if key=='surface_c' else 'current' if key=='current_a' else 'voltage')
    v=values.get('secondary_v'); current=values.get('current_a'); surface=values.get('surface_c')
    load=100*current/c.current_limit_a if current is not None and c.current_limit_a else None
    margin=c.surface_limit_c-surface if surface is not None and c.surface_limit_c else None
    if fresh and channel_calibration['current_a'] and current is not None and c.current_limit_a and current>c.current_limit_a:
        warn('overcurrent','Current exceeds configured limit',f'{current:.3f} A > {c.current_limit_a:.3f} A. Request all loads off; independent protection is required.','critical','current')
    if fresh and channel_calibration['surface_c'] and margin is not None and margin<=0:
        warn('surface_limit','Surface temperature exceeds configured limit',f'{surface:.1f} °C surface; limit {c.surface_limit_c:.1f} °C. This is not winding temperature.','critical','surface')
    temperatures=[r for r in rows[-60:] if r.get('surface_c') is not None]
    slope=None
    if len(temperatures)>2:
        dt=(timestamp(temperatures[-1]['timestamp'])-timestamp(temperatures[0]['timestamp'])).total_seconds()/60
        if dt>=.25: slope=(temperatures[-1]['surface_c']-temperatures[0]['surface_c'])/dt
    if fresh and channel_calibration['surface_c'] and slope is not None and slope>2:
        warn('temperature_change','Rapid surface-reading change',f'{slope:.2f} °C/min in the visible window. Compare with an independent probe before attributing a fault.','warning','surface')
    branches=values.get('relay_states',[False]*4)
    expected=sum(v/r for on,r in zip(branches,c.resistor_ohms) if on) if v is not None and (source!='measured' or values.get('relay_output_configured')) else None
    mismatch=current-expected if expected is not None and current is not None else None
    if fresh and channel_calibration['current_a'] and channel_calibration['secondary_v'] and mismatch is not None and abs(mismatch)>.12:
        warn('load_mismatch','Load-bank current differs from expected',f'Observed minus ideal resistor-bank current: {mismatch:+.3f} A. GPIO states do not prove contact closure.','warning','relay')
    if branches[3] and source=='measured':
        warn('k4','K4 reported active','K4 is prohibited in physical control. Disconnect the load source through the approved procedure.','critical','relay')
    score=None
    if fresh and calibrated and load is not None and margin is not None and not values.get('quality_flags') and all(values.get(k) is not None for k in ('secondary_v','current_a','surface_c')):
        score=round(max(0,min(100,100-max(max(0,load-80),max(0,10-margin)*3))))
    model=store.get('active_model',asset_id)
    return {'asset_id':asset_id,'name':c.name if not simulated else 'Halo bench • synthetic replay',
            'source':source,'clock':'5 seconds per replay frame' if simulated else 'Recorded time' if source=='replayed' else 'Real acquisition time',
            'connection':connection,'age_s':age if source=='measured' else None,'current':latest,
            'history':rows[-240:],'evidence':evidence,'alerts':alerts,
            'status':'critical' if any(a['severity']=='critical' for a in alerts) else 'attention' if alerts else 'normal',
            'metrics':{'load_pct':load,'apparent_va':v*current if v is not None and current is not None else None,
                       'surface_margin_c':margin,'surface_slope_c_min':slope,'condition_index':score,
                       'expected_current_a':expected,'current_residual_a':mismatch},
            'quality':{'freshness':connection,'coverage':sum(values.get(k) is not None for k in CHANNELS),
                       'total_channels':len(CHANNELS),'calibration':'synthetic' if simulated else 'reference recorded' if calibrated else 'unverified',
                       'agreement':'independent probe not connected','model_validity':'fitted surface model' if model else 'surface model not fitted'},
            'limits':{'current_a':c.current_limit_a,'surface_c':c.surface_limit_c,'nominal_secondary_v':c.nominal_secondary_v},
            'holds':holds(c) if not simulated else [],'model':model,
            'notes':['The surface channel represents outer-case temperature; oil, winding hot-spot and remaining life are not measured on this bench.',
                     'VA is apparent power, not measured watts or efficiency. THD is unavailable.',
                     'Condition index is a screening heuristic, not a failure probability.',
                     'Relay states report commanded GPIO levels, not electrical contact feedback.']}


def fit_surface(rows, asset_id):
    valid=[r for r in rows if all(r.get(k) is not None for k in ('surface_c','ambient_c','current_a')) and not r.get('quality_flags')]
    if len(valid)<60: raise ValueError('At least 60 complete, quality-qualified samples are required.')
    if (timestamp(valid[-1]['timestamp'])-timestamp(valid[0]['timestamp'])).total_seconds()<300:
        raise ValueError('Record at least five minutes across heating/cooling and multiple loads.')
    if np.ptp([r['current_a'] for r in valid])<.15:
        raise ValueError('Current variation is insufficient to identify the load response.')
    split=int(len(valid)*.7); training=valid[:split]; testing=valid[split:]
    x=[]; y=[]
    for a,b in zip(training,training[1:]):
        dt=(timestamp(b['timestamp'])-timestamp(a['timestamp'])).total_seconds()
        if dt<=0 or dt>15: continue
        x.append([1,a['current_a']**2,-(a['surface_c']-a['ambient_c'])])
        y.append((b['surface_c']-a['surface_c'])/dt)
    if len(x)<25: raise ValueError('Insufficient contiguous training samples (maximum interval 15 seconds).')
    fit=lsq_linear(x,y,bounds=([0,0,.00001],[1,2,.1]))
    coeff=[float(x) for x in fit.x]
    predicted=testing[0]['surface_c']; errors=[]; persistent=[]
    for a,b in zip(testing,testing[1:]):
        dt=(timestamp(b['timestamp'])-timestamp(a['timestamp'])).total_seconds()
        if dt<=0 or dt>15: raise ValueError('Validation period contains a gap; use an uninterrupted run.')
        predicted=surface_step(predicted,a['ambient_c'],a['current_a'],dt,coeff)
        errors.append(predicted-b['surface_c']); persistent.append(testing[0]['surface_c']-b['surface_c'])
    rmse=float(np.sqrt(np.mean(np.square(errors)))); baseline=float(np.sqrt(np.mean(np.square(persistent))))
    return {'asset_id':asset_id,'coefficients':coeff,'training_count':split,'validation_count':len(testing),
            'validation_rmse_c':rmse,'persistence_rmse_c':baseline,'beats_persistence':rmse<baseline,
            'method':'bounded first-order surface model; chronological 70/30 split; free-running validation',
            'validation_span_s':(timestamp(testing[-1]['timestamp'])-timestamp(testing[0]['timestamp'])).total_seconds(),
            'current_range_a':[min(r['current_a'] for r in training),max(r['current_a'] for r in training)],
            'ambient_range_c':[min(r['ambient_c'] for r in training),max(r['ambient_c'] for r in training)],
            'data_end_at':valid[-1]['timestamp'], 'training_end_at':training[-1]['timestamp'],
            'training_evidence':[valid[0]['evidence_id'],valid[-1]['evidence_id']]}


def surface_step(temp,ambient,current,seconds,coeff):
    a,b,c=coeff
    target=ambient+(a+b*current**2)/c
    return target+(temp-target)*math.exp(-c*seconds)


def ambient_qualified(snap):
    return snap['source']=='simulated' or any(e['channel']=='ambient_c' and e['available'] and e.get('verification') in ('reference recorded','manual observation') for e in snap['evidence'])


def futures(snap,reduction=25,delay=0,horizon=10,ambient=None):
    model=snap.get('model'); row=snap.get('current') or {}
    if not model or not model.get('beats_persistence'):
        return {'available':False,'reason':'A qualified surface model that beats persistence on a held-out period is required.','baseline':[],'alternative':[]}
    if snap['source']!='simulated' and (snap['quality']['calibration']!='reference recorded' or not model.get('calibration_id') or row.get('calibration_id')!=model['calibration_id']):
        return {'available':False,'reason':'The current calibration must match the reviewed model training data. Refit after changing calibration.','baseline':[],'alternative':[]}
    if snap['connection'] in ('stale','disconnected') or row.get('quality_flags'):
        return {'available':False,'reason':'Restore fresh, valid measurements first.','baseline':[],'alternative':[]}
    if not ambient_qualified(snap):
        return {'available':False,'reason':'Verify the ambient probe or record an independent ambient observation.','baseline':[],'alternative':[]}
    if any(row.get(k) is None for k in ('surface_c','ambient_c','current_a')):
        return {'available':False,'reason':'Surface, current and an explicit ambient reference are required.','baseline':[],'alternative':[]}
    ambient=row['ambient_c'] if ambient is None else ambient
    base=alternative=row['surface_c']; baseline=[]; changed=[]
    for t in range(horizon*12+1):
        minute=t/12
        baseline.append({'minute':minute,'temperature_c':base})
        changed.append({'minute':minute,'temperature_c':alternative})
        base=surface_step(base,ambient,row['current_a'],5,model['coefficients'])
        alternative=surface_step(alternative,ambient,row['current_a']*(1-reduction/100) if minute>=delay else row['current_a'],5,model['coefficients'])
    low,high=model['current_range_a']; alow,ahigh=model['ambient_range_c']
    outside=not(low<=row['current_a']*(1-reduction/100)<=high and low<=row['current_a']<=high and alow<=ambient<=ahigh)
    return {'available':True,'baseline':baseline,'alternative':changed,
            'peak_baseline_c':max(x['temperature_c'] for x in baseline),'peak_alternative_c':max(x['temperature_c'] for x in changed),
            'assumptions':f'Surface estimate only. Ambient held at {ambient:g} °C. Current reduced {reduction:g}% after {delay:g} minutes. No relay command is sent.',
            'extrapolation':outside,'model_id':model['id'],'validation_rmse_c':model['validation_rmse_c'],
            'horizon_exceeds_validation':horizon*60>model['validation_span_s']}
