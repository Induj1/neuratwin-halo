"""Commissioning diagnostics and acquisition-bound, immutable bench experiments.

This module never issues relay commands or changes a physical configuration.
Emulator records stay separate from halo_frames and active physical models.
"""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import math
import csv
import zipfile
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from . import halo_store as store, halo_engine as engine, halo_evidence as evidence, bench_emulator as emulator
from .storage import now

router=APIRouter(prefix='/api/halo/lab')
CHANNELS={'secondary_v':('secondary_rms_mv','secondary_v_per_mv','V RMS'),
          'current_a':('current_rms_mv','current_a_per_mv','A RMS'),
          'surface_c':('surface_raw_c','surface_offset_c','°C surface')}


def physical_rows():return store.frames(engine.config().device_id,20000)


def diagnostics(rows,source):
    r=rows[-1] if rows else {};raw=r.get('raw') or {};physical=source=='measured'
    age=max(0,(datetime.now(timezone.utc)-engine.timestamp(r['timestamp'])).total_seconds()) if physical and r else None
    state='disconnected' if not r else 'stale' if physical and age>5 else 'live' if physical else 'software emulator'
    gaps=sum(b['boot_id']==a['boot_id'] and b['sequence']>a['sequence']+1 for a,b in zip(rows,rows[1:]))
    checks=[]
    for channel,(key,scale,unit) in CHANNELS.items():
        sensor=key.split('_')[0];flags=[x for x in r.get('quality_flags',[]) if x.startswith(sensor) or x in ('adc_unverified','pinmap_unverified','sampling_overrun')]
        checks.append({'channel':channel,'unit':unit,'raw':raw.get(key),'raw_unit':'°C' if channel=='surface_c' else 'mV RMS (bias removed)',
                       'observed':r.get(channel),'bias_mv':raw.get(sensor+'_bias_mv'),'min_mv':raw.get(sensor+'_min_mv'),
                       'max_mv':raw.get(sensor+'_max_mv'),'flags':flags,'available':r.get(channel) is not None})
    return {'source':source,'connection':state,'age_s':age,'latest':r or None,'channels':checks,
            'sequence_gaps':gaps,'boot_changes':sum(b['boot_id']!=a['boot_id'] for a,b in zip(rows,rows[1:])),
            'frames':len(rows),'quality_flags':r.get('quality_flags',[]),
            'note':'Freshness uses acquisition time. GPIO reports are not electrical contact feedback. Surface is not oil or winding temperature.'}


@router.get('/commissioning')
def commissioning():
    rows=physical_rows();c=engine.config()
    return {'diagnostics':diagnostics(rows,'measured'),'config':c.model_dump(),'holds':engine.holds(c),
            'calibration':store.get('active_calibration','bench'),
            'references':store.records('bench_reference')[:30],
            'device_link':store.get('device_link',c.device_id),
            'commands':store.records('command')[:10]}


class Reference(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    evidence_id:str=Field(min_length=1,max_length=120)
    experiment_id:str|None=Field(default=None,max_length=120)
    channel:Literal['secondary_v','current_a','surface_c']
    reference:float
    tolerance_abs:float=Field(gt=0,le=100)
    instrument:str=Field(min_length=5,max_length=200)
    reviewer:str=Field(min_length=2,max_length=100)
    zero_current_noise_mv:float=Field(default=0,ge=0,le=1000)


def reference_result(payload,row,source):
    key,scale,unit=CHANNELS[payload.channel];raw=row.get('raw',{}).get(key)
    if raw is None or not math.isfinite(raw):raise HTTPException(422,'Selected acquisition has no usable raw channel.')
    if row.get('quality_flags'):raise HTTPException(422,'Resolve acquisition quality flags before a reference check.')
    value=payload.reference
    if payload.channel=='surface_c':
        if not -55<=value<=125:raise HTTPException(422,'Surface reference is outside the sensor range.')
        coefficient=value-raw
        if abs(coefficient)>10:raise HTTPException(422,'Offset exceeds 10 °C; inspect the sensor instead of masking the discrepancy.')
    else:
        maximum=60 if payload.channel=='secondary_v' else 30
        if not 0<value<=maximum:raise HTTPException(422,'Use a nonzero, in-range reference for a scale estimate.')
        denominator=math.sqrt(max(0,raw**2-payload.zero_current_noise_mv**2)) if payload.channel=='current_a' else raw
        if denominator<=0:raise HTTPException(422,'Signal is not above the recorded noise floor.')
        coefficient=value/denominator
        if coefficient>(10 if payload.channel=='secondary_v' else 1):raise HTTPException(422,'Scale is outside the supported calibration range.')
    observed=row.get(payload.channel);error=observed-value if observed is not None else None
    return {'channel':payload.channel,'unit':unit,'reference':value,'observed':observed,'raw':raw,
            'error':error,'tolerance_abs':payload.tolerance_abs,
            'within_tolerance':abs(error)<=payload.tolerance_abs if error is not None else None,
            'proposal':{scale:coefficient,**({'current_noise_mv':payload.zero_current_noise_mv} if payload.channel=='current_a' else {})},
            'source':source,'acquired_at':row['timestamp'],'calibration_id':row.get('calibration_id'),
            'evidence_id':row['evidence_id'],'instrument':payload.instrument,'reviewer':payload.reviewer,
            'note':'One-point proposal only. Check multiple operating points before explicitly saving a calibration version. The entered reference is an operator observation, not independently verified.'}


@router.post('/references')
def reference(payload:Reference,actor=Depends(operator)):
    with WRITE_LOCK:
        key='CHECK-'+payload.request_id;digest=evidence.digest(payload.model_dump())
        prior=store.get('bench_reference',key)
        if prior:
            if prior['request_sha256']!=digest:raise HTTPException(409,'Reference request ID reused with different data.')
            return prior
        exp=get_experiment(payload.experiment_id) if payload.experiment_id else None
        source=exp['source'] if exp else 'measured';rows=exp['rows'] if exp else physical_rows()
        row=next((r for r in rows if r['evidence_id']==payload.evidence_id),None)
        if not row:raise HTTPException(404,'The selected acquisition is unavailable. Capture it again.')
        result={**reference_result(payload,row,source),'id':key,'created_at':now(),'actor':actor,'request_sha256':digest}
        store.put('bench_reference',key,result);return result


def get_experiment(key):
    result=store.get('bench_experiment',key)
    if not result:raise HTTPException(404,'Experiment not found.')
    return result


def experiment_snapshot(exp):
    snap=engine.snapshot(exp['rows'],'simulated' if exp['source']=='software_emulator' else 'measured',exp['asset_id'])
    if exp['source']=='software_emulator':snap['model']=exp.get('model')
    return snap


def public(exp,include_rows=True):
    proofs=[]
    for proof in exp.get('proofs',[]):
        if evidence.digest({k:v for k,v in proof.items() if k!='sha256'})!=proof['sha256']:
            raise HTTPException(409,'Frozen forecast checksum mismatch.')
        proofs.append({'proof':proof,'score':evidence.score_prediction(proof,exp['rows'])})
    snap=experiment_snapshot(exp)
    reason=evidence.model_ready(snap)
    if not reason:
        try:
            preview=evidence.predict(snap,3)
            if preview.get('horizon_exceeds_validation'):reason='A three-minute forecast exceeds this surface model’s validation span.'
        except ValueError as error:reason=str(error)
    return {k:v for k,v in {**exp,'plant':None,'proofs':proofs,'diagnostics':diagnostics(exp['rows'],exp['source']),
            'forecast_hold':reason,'rows':exp['rows'] if include_rows else None,
            'control':'Recording and analysis only; this workflow never sends a physical relay command.',
            'scope':'Software workflow fixture' if exp['source']=='software_emulator' else 'Measured bench surface experiment; physical protection remains independent.'}.items() if k!='plant'}


class Create(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    source:Literal['measured','software_emulator']
    name:str=Field(min_length=3,max_length=120)


@router.post('/experiments')
def create(payload:Create,actor=Depends(operator)):
    with WRITE_LOCK:
        key='EXPERIMENT-'+payload.request_id;prior=store.get('bench_experiment',key)
        if prior:
            if prior['request_sha256']!=evidence.digest(payload.model_dump()):raise HTTPException(409,'Experiment request ID reused.')
            return public(prior)
        rows=[];plant=None;model=None;asset='BENCH-001'
        if payload.source=='software_emulator':
            asset='SOFTWARE-EMULATOR';plant,rows=emulator.initial()
            model=engine.fit_surface(rows,asset);model.update(id=key+'-MODEL',calibration_id=emulator.CALIBRATION['id'])
        else:
            current=physical_rows()
            if not current or diagnostics(current,'measured')['connection']!='live':raise HTTPException(409,'Connect the acquisition bridge and receive a fresh sample before recording.')
            rows=current[-1:]
        exp={'id':key,'name':payload.name,'source':payload.source,'asset_id':asset,'revision':0,'state':'recording',
             'created_at':now(),'created_by':actor,'request_sha256':evidence.digest(payload.model_dump()),
             'rows':rows,'plant':plant,'model':model,'proofs':[],
             'markers':[{'kind':'baseline','timestamp':rows[-1]['timestamp'],'recorded_at':now(),
                         'note':'Software-generated reference history; no hardware connected.' if plant else 'Recording started at this acquisition.'}]}
        store.put('bench_experiment',key,exp);return public(exp)


@router.get('/experiments')
def experiments():
    return {'experiments':[{k:v for k,v in e.items() if k in ('id','name','source','state','revision','created_at')} for e in store.records('bench_experiment')]}


@router.get('/experiments/{key}')
def read(key:str):return public(get_experiment(key))


class Action(Contract):
    revision:int=Field(ge=0)
    action:Literal['capture','advance','load','mark','freeze','stop']
    seconds:int=Field(default=60,ge=5,le=300)
    branches:int=Field(default=1,ge=0,le=3)
    horizon:int=Field(default=3,ge=1,le=5)
    kind:Literal['baseline','load_change','intervention','recovery','inspection']='inspection'
    note:str=Field(default='',max_length=1000)


def capture(exp,stopping=False):
    if exp['source']!='measured':return
    end=engine.timestamp(exp['rows'][-1]['timestamp'])
    new=[r for r in physical_rows() if engine.timestamp(r['timestamp'])>end]
    capacity=10000-len(exp['rows'])
    if len(new)>capacity:
        if not stopping:raise HTTPException(409,'Recording limit reached. Stop and export this experiment.')
        exp['uncaptured_samples_at_stop']=len(new)-max(0,capacity)
    exp['rows'].extend(new[:max(0,capacity)])


@router.post('/experiments/{key}/actions')
def action(key:str,payload:Action,actor=Depends(operator)):
    with WRITE_LOCK:
        exp=get_experiment(key)
        if exp['revision']!=payload.revision:raise HTTPException(409,'Experiment changed. Refresh before continuing.')
        if exp['state']!='recording':raise HTTPException(409,'Recording is stopped and immutable; start a new experiment.')
        if payload.action in ('advance','load') and exp['source']!='software_emulator':raise HTTPException(403,'Physical recordings cannot alter acquisition time or loads.')
        if payload.action in ('advance','load') and exp['plant'].get('version')!='bench-emulator-1':raise HTTPException(409,'Historical emulator version. Start a new experiment; existing evidence remains exportable.')
        if payload.action in ('mark','load') and len(payload.note.strip())<5:raise HTTPException(422,'Record an observation or action note of at least five characters.')
        if payload.action in ('capture','freeze','mark','stop'):capture(exp,stopping=payload.action=='stop')
        if payload.action=='load' and len(exp['rows'])>=10000:raise HTTPException(409,'Recording limit reached. Stop and export this experiment.')
        if payload.action=='advance':
            if len(exp['rows'])+payload.seconds//5>10000:raise HTTPException(409,'Recording limit reached.')
            for _ in range(payload.seconds//5):exp['rows'].append(emulator.step(exp['plant']))
        elif payload.action=='load':
            exp['plant']['branches']=payload.branches
            exp['rows'].append(emulator.step(exp['plant']))
        elif payload.action=='freeze':
            snap=experiment_snapshot(exp)
            try:proof=evidence.predict(snap,payload.horizon)
            except ValueError as err:raise HTTPException(422,str(err))
            if proof.get('horizon_exceeds_validation'):raise HTTPException(422,'Choose a horizon within the recorded surface-model validation span.')
            proof.update(horizon_min=payload.horizon,id=key+'-FORECAST-'+str(len(exp['proofs'])+1),source=exp['source'],
                         asset_id=exp['asset_id'],created_at=now(),actor=actor)
            proof['sha256']=evidence.digest(proof);exp['proofs'].append(proof)
            exp['markers'].append({'kind':'prediction','timestamp':proof['origin'],'recorded_at':now(),'note':'Frozen '+str(payload.horizon)+'-minute surface forecast.','proof_id':proof['id']})
        elif payload.action=='stop':exp['state']='stopped';exp['stopped_at']=now()
        if payload.action in ('mark','load'):
            exp['markers'].append({'kind':'load_change' if payload.action=='load' else payload.kind,
                'timestamp':exp['rows'][-1]['timestamp'],'recorded_at':now(),'note':payload.note,'actor':actor,
                'verification':'Operator annotation; not proof of physical recovery or contact state.'})
        exp['revision']+=1;store.put('bench_experiment',key,exp);return public(exp)


@router.get('/experiments/{key}/export')
def export(key:str):
    exp=get_experiment(key);result=public(exp);payload={'experiment.json':json.dumps(result,indent=2,allow_nan=False).encode()}
    stream=io.StringIO();cols=['timestamp','device_id','boot_id','sequence','secondary_v','current_a','surface_c','ambient_c','calibration_id','source']
    w=csv.DictWriter(stream,fieldnames=cols);w.writeheader()
    for row in exp['rows']:w.writerow({k:exp['source'] if k=='source' else row.get(k) for k in cols})
    payload['observations.csv']=stream.getvalue().encode()
    payload['replay.html']=replay_html(result).encode()
    import hashlib
    payload['manifest.json']=json.dumps({'scope':result['scope'],'files':{k:hashlib.sha256(v).hexdigest() for k,v in payload.items()}},indent=2).encode()
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in payload.items():z.writestr(name,value)
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{key}.zip"'})


def replay_html(result):
    # JSON is data inside script; escape HTML delimiters to prevent script breakout.
    data=json.dumps(result,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NeuraTwin recorded experiment</title>
<style>body{font:17px/1.6 system-ui;background:#f5f4ef;color:#172533;max-width:1040px;margin:32px auto;padding:20px}strong{font-variant-numeric:tabular-nums}input{width:100%}svg{width:100%;background:white;border:1px solid #ccd3d9}pre{white-space:pre-wrap}button{font:inherit;padding:10px}#source{padding:12px;background:#fff0c9}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #ccd3d9}</style>
<h1>NeuraTwin · recorded experiment</h1><p id="name"></p><p id="source"></p><p>Offline recording. No live connection and no hardware controls. Drag through retained acquisitions; forecasts remain frozen.</p>
<label for="cursor">Recorded acquisition</label><input type="range" id="cursor" min="0" value="0"><p id="reading"></p><svg id="chart" viewBox="0 0 900 280" role="img" aria-label="Surface readings and frozen prediction"></svg><p>Blue: recorded surface · orange dashed: frozen forecast. Forecasts first appear at their recorded origin.</p><h2>Recorded events</h2><pre id="events"></pre><h2>Forecast scores at end of recording</h2><div id="scores"></div>
<script type="application/json" id="data">'''+data+'''</script><script>
const e=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);$('name').textContent=e.name;$('source').textContent=e.source+' · '+e.scope;$('cursor').max=e.rows.length-1;
function paint(){const n=Number($('cursor').value),r=e.rows[n],time=new Date(r.timestamp).getTime();$('reading').textContent=r.timestamp+' | surface '+(r.surface_c??'unavailable')+' °C | current '+(r.current_a??'unavailable')+' A';
const rows=e.rows.slice(0,n+1),lo=new Date(e.rows[0].timestamp).getTime(),hi=Math.max(new Date(e.rows.at(-1).timestamp).getTime(),...e.proofs.map(({proof:p})=>new Date(p.origin).getTime()+p.horizon_min*60000));const ys=[...e.rows.map(r=>r.surface_c),...e.proofs.flatMap(({proof:p})=>p.points.map(v=>v.predicted_c))].filter(Number.isFinite),bottom=ys.length?Math.min(...ys)-2:0,top=ys.length?Math.max(...ys)+2:50;
const x=t=>40+(new Date(t).getTime()-lo)/Math.max(1,hi-lo)*840,y=v=>245-(v-bottom)/(top-bottom)*215;
let d='',connected=false,previous=null;rows.forEach(r=>{const t=new Date(r.timestamp).getTime();if(previous!==null&&t-previous>15000)connected=false;previous=t;if(!Number.isFinite(r.surface_c)||r.quality_flags?.length){connected=false;return}d+=(connected?'L':'M')+x(r.timestamp)+','+y(r.surface_c)+' ';connected=true});
$('chart').innerHTML='<path d="'+d+'" fill="none" stroke="#245daf" stroke-width="3"/>';
for(const {proof:p} of e.proofs)if(new Date(p.origin).getTime()<=time){const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',p.points.map((v,i)=>(i?'L':'M')+x(new Date(new Date(p.origin).getTime()+v.minute*60000))+','+y(v.predicted_c)).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#b85b20');path.setAttribute('stroke-dasharray','6 4');$('chart').append(path)}
$('events').textContent=e.markers.filter(m=>new Date(m.timestamp).getTime()<=time).map(m=>m.kind+' · '+m.note).join('\\n')}
$('cursor').oninput=paint;paint();for(const {proof:p,score:s} of e.proofs){const el=document.createElement('p');el.textContent=p.id+' | '+s.status+' | comparable MAE '+(s.assumptions_held.mae_c??'unavailable')+' °C | '+s.changed_input_samples+' changed-input samples | '+s.missing_samples+' missing samples';$('scores').append(el)}
</script></html>'''
