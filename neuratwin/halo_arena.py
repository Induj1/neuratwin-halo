"""Scoped judge capability, observation-only investigations and portable studies."""
import hashlib
import html
import io
import json
import secrets
import zipfile
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from .halo_api import operator, WRITE_LOCK
from .halo_contracts import Contract
from . import halo_store as store
from .storage import now
from . import halo_arena_model as model

router=APIRouter(prefix='/api/halo/arena')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def room(key):
    value=store.get('arena',key)
    if value is None:raise HTTPException(404,'Arena case not found.')
    return value


def judge(request, value):
    key=request.headers.get('X-Arena-Key','')
    if not key or not secrets.compare_digest(hashlib.sha256(key.encode()).hexdigest(),value['judge_hash']):
        raise HTTPException(403,'This judge link does not authorize this case.')


def mutable(value):
    if value['commit'] is not None:raise HTTPException(409,'Assessment is frozen. Start a new case to change the experiment.')


def public(value):
    rows=value.get('frozen_observations')
    if rows is None:rows,_=model.challenge_rows(value['seed'],value['events'],value['cursor'])
    result={'id':value['id'],'created_at':value['created_at'],'cursor':value['cursor'],'phase':'revealed' if value['revealed'] else 'frozen' if value['commit'] else 'investigating',
            'notice':model.NOTICE,'observations':rows,'checks':value['checks'],'assessment':value['commit']['assessment'] if value['commit'] else model.diagnose(rows,value['checks']),
            'commit':value['commit'],'studies':value['studies'],'truth':None}
    if value['revealed']:
        observed=[e for e in value['events'] if e['start']<=value['cursor']]
        onset=min((e['start'] for e in observed),default=None)
        detections=value.get('frozen_alert_minutes')
        if detections is None:detections=[r['minute'] for i,r in enumerate(rows) if model.diagnose(rows[:i+1],[])['alert']]
        first=next((t for t in detections if onset is not None and t>=onset),None)
        result['truth']={'events':observed,'first_injected_min':onset,'first_rule_alert_min':first,
                         'detection_delay_min':first-onset if first is not None else None,
                         'pre_injection_alert_minutes':[t for t in detections if onset is None or t<onset],
                         'scheduled_beyond_observation':sum(e['start']>value['cursor'] for e in value['events']),
                         'note':'Timing of an observation-only rule alert, not proof that every injected cause was identified. Future, unobserved events are not scored.'}
    return result


@router.post('/rooms')
def create(actor=Depends(operator)):
    key=secrets.token_hex(12);capability=secrets.token_urlsafe(32)
    value={'id':key,'created_at':now(),'seed':secrets.randbelow(1000000),'judge_hash':hashlib.sha256(capability.encode()).hexdigest(),
           'cursor':0,'events':[],'checks':[],'commit':None,'revealed':False,'studies':[]}
    store.put('arena',key,value)
    return {'room':public(value),'judge_key':capability}


@router.get('/rooms/{key}')
def get_room(key:str,response:Response):
    response.headers['Cache-Control']='no-store'
    return public(room(key))


@router.get('/rooms/{key}/judge')
def judge_state(key:str,request:Request,response:Response):
    value=room(key);judge(request,value)
    response.headers['Cache-Control']='no-store'
    return {'id':key,'cursor':value['cursor'],'frozen':value['commit'] is not None,'events':value['events'],'notice':model.NOTICE}


@router.post('/rooms/{key}/inject')
def inject(key:str,body:model.Injection,request:Request):
    with WRITE_LOCK:
        value=room(key);judge(request,value);mutable(value)
        if body.start<=value['cursor']:raise HTTPException(409,'Choose a start strictly after the current observation minute.')
        if len(value['events'])>=6:raise HTTPException(409,'Six disturbances per case. Start a new case for another experiment.')
        value['events'].append(body.model_dump());store.put('arena',key,value)
    return {'accepted':True,'events':value['events'],'cursor':value['cursor']}


class Advance(Contract):
    minutes:int=Field(default=5,ge=1,le=20)


@router.post('/rooms/{key}/advance')
def advance(key:str,body:Advance,actor=Depends(operator)):
    with WRITE_LOCK:
        value=room(key);mutable(value)
        if value['cursor']==120:raise HTTPException(409,'Observation horizon complete. Freeze and reveal this case.')
        value['cursor']=min(120,value['cursor']+body.minutes);store.put('arena',key,value)
    return public(value)


class Check(Contract):
    type:Literal['probe','clamp','inspection']


@router.post('/rooms/{key}/check')
def check(key:str,body:Check,actor=Depends(operator)):
    with WRITE_LOCK:
        value=room(key);mutable(value)
        existing=next((c for c in value['checks'] if c['minute']==value['cursor'] and c['type']==body.type),None)
        if not existing:
            if len(value['checks'])>=90:raise HTTPException(409,'Evidence limit reached; freeze this case or start another.')
            _,checks=model.challenge_rows(value['seed'],value['events'],value['cursor'])
            value['checks'].append({'type':body.type,**checks[value['cursor']][body.type],'requested_at':now()})
            store.put('arena',key,value)
    return public(value)


@router.post('/rooms/{key}/commit')
def commit(key:str,actor=Depends(operator)):
    with WRITE_LOCK:
        value=room(key)
        if value['commit']:return public(value)
        if value['cursor']<1:raise HTTPException(409,'Observe at least one simulated minute before committing.')
        state=public(value)
        evidence={'observations':state['observations'],'checks':state['checks']}
        value['frozen_observations']=state['observations']
        value['frozen_alert_minutes']=[r['minute'] for i,r in enumerate(state['observations']) if model.diagnose(state['observations'][:i+1],[])['alert']]
        value['commit']={'recorded_at':now(),'minute':value['cursor'],'assessment':state['assessment'],
                         'evidence_sha256':digest(evidence),'method':'observation-rules-v1'}
        store.put('arena',key,value);store.event('ARENA-'+key,'arena-assessment',value['commit'])
    return public(value)


@router.post('/rooms/{key}/reveal')
def reveal(key:str,actor=Depends(operator)):
    with WRITE_LOCK:
        value=room(key)
        if not value['commit']:raise HTTPException(409,'Freeze the assessment before revealing the scenario.')
        value['revealed']=True;store.put('arena',key,value)
    return public(value)


class LinkQR(Contract):
    url:str=Field(min_length=1,max_length=2048)


@router.post('/qr')
def qr(body:LinkQR,actor=Depends(operator)):
    import qrcode
    stream=io.BytesIO();qrcode.make(body.url).save(stream,format='PNG')
    return Response(stream.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})


def save_study(kind,body,result):
    result={**result,'id':secrets.token_hex(12),'kind':kind,'created_at':now()}
    with WRITE_LOCK:
        value=room(body.room_id) if body.room_id else None
        if value:
            if len(value['studies'])>=20:raise HTTPException(409,'Twenty studies already attached; start a new case or run an independent study.')
            value['studies'].append({'id':result['id'],'kind':kind,'created_at':result['created_at']})
        store.put('arena-study',result['id'],result)
        if value:store.put('arena',value['id'],value)
    return result


@router.post('/futures')
def future_study(body:model.Study,actor=Depends(operator)):
    return save_study('futures',body,model.futures(body))


@router.post('/capacity')
def capacity_study(body:model.Study,actor=Depends(operator)):
    return save_study('capacity',body,model.capacity(body))


@router.post('/neighbourhood')
def network_study(body:model.NetworkStudy,actor=Depends(operator)):
    return save_study('neighbourhood',body,model.neighbourhood(body))


def package(files,filename):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,content in files.items():archive.writestr(name,content)
        archive.writestr('manifest.json',json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in files.items()},indent=2))
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})


def report(title,payload):
    esc=lambda value:html.escape(str(value))
    def table(headers,rows):
        return '<div class="table"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def study_section(study):
        kind=study['kind'];body='<section><span class="label">SYNTHETIC STUDY / '+esc(study['id'])+'</span><h2>'+esc(kind.capitalize())+'</h2>'
        if kind=='futures':
            rows=[]
            for name in ('baseline','operator','planner'):
                branch=study[name]
                rows.append([name,'No qualifying candidate' if branch is None else 'Pass' if branch['passes'] else ', '.join(branch['violations']),
                             '—' if branch is None else f"{branch['reduction_pct']}% / {branch['delay_min']} min",
                             '—' if branch is None else f"{branch['peak_upper_c']:.2f}°C",
                             '—' if branch is None else f"{branch['curtailed_kwh']:.2f}"])
            body+=table(['Branch','Constraint result','Reduction / delay','Peak upper bound','Curtailed kWh'],rows)
        elif kind=='capacity':
            body+=table(['Window','Extra constant kVA','Binding constraint','Status'],[[f"{r['horizon_min']} min",r['extra_kva'],', '.join(r['binding']),r['status']] for r in study['rows']])
        else:
            body+=table(['Scenario','Served kW','Unmet kW','Clinic kW','Losses kW','Result'],[[name,'—' if r is None else round(r['served_kw'],2),'—' if r is None else round(r['unserved_kw'],2),'—' if r is None else r['clinic_served_kw'],'—' if r is None else round(r['loss_kw'],3),'No feasible candidate' if r is None else 'Pass' if r['passes'] else ', '.join(r['violations'])] for name,r in [('Before',study['baseline']),('Plan',study['plan'])]])
        body+='<h3>Declared assumptions</h3><ul>'+''.join('<li>'+esc(a)+'</li>' for a in study['assumptions'])+'</ul></section>'
        return body
    content=''
    if 'case' in payload:
        case=payload['case'];content='<section><span class="label">CASE / '+esc(case['id'])+'</span><h2>Investigation at minute '+str(case['cursor'])+'</h2><p>Status: <b>'+esc(case['phase'])+'</b></p><h3>Observation-only assessment</h3><ul>'+''.join('<li>'+esc(f)+'</li>' for f in case['assessment']['findings'])+'</ul>'
        if case['commit']:content+='<p>Committed evidence SHA-256:</p><code>'+esc(case['commit']['evidence_sha256'])+'</code>'
        if case['truth']:
            content+='<h3>Revealed disturbances</h3>'+table(['Type','Severity','Start','Duration'],[[e['kind'],f"{e['severity']*100:.0f}%",e['start'],e['duration']] for e in case['truth']['events']])
            content+='<p>'+esc(case['truth']['note'])+'</p>'
        else:content+='<p>Ground truth remains hidden. No injection schedule is included in this export.</p>'
        content+='</section>'+''.join(study_section(s) for s in payload['studies'] if s)
    else:content=study_section(payload)
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(title)+'</title><style>body{font:16px/1.65 system-ui;max-width:1120px;margin:40px auto;padding:24px;color:#203739;background:#f4f3ee}section{padding:28px;background:#fffefa;border:1px solid #d5d8ce;margin:20px 0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:24px;font:13px/1.6 monospace}h1{font-size:36px;line-height:1.15}h2{font-size:27px}.notice{border-left:4px solid #b84e1e;padding-left:16px}.label{font-size:12px;letter-spacing:1px;color:#a44b22}code{overflow-wrap:anywhere}.table{overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;font-size:14px}td,th{padding:12px 10px;border-bottom:1px solid #d5d8ce;vertical-align:top}summary{cursor:pointer;font-weight:bold}@media print{body{margin:0;background:white}section{break-inside:avoid}details{display:none}}</style><span class="label">NEURATWIN HALO / NEURA RANGERS</span><h1>'+esc(title)+'</h1><p class="notice">'+model.NOTICE+'</p>'+content+'<p>Keep manifest.json with the JSON files to verify SHA-256 integrity. An integrity hash is not a digital signature or proof of independent validation.</p><details><summary>Complete inputs, outputs and evidence</summary><pre>'+esc(json.dumps(payload,indent=2))+'</pre></details></html>').encode()


@router.post('/rooms/{key}/export')
def export_room(key:str,actor=Depends(operator)):
    state=public(room(key));studies=[store.get('arena-study',s['id']) for s in state['studies']]
    files={'case.json':json.dumps(state,indent=2).encode(),'studies.json':json.dumps(studies,indent=2).encode(),
           'readable-report.html':report('NeuraTwin / Grid Rescue Arena',{'case':state,'studies':studies})}
    return package(files,f'halo-arena-{key}.zip')


@router.post('/studies/{key}/export')
def export_study(key:str,actor=Depends(operator)):
    study=store.get('arena-study',key)
    if not study:raise HTTPException(404,'Study not found.')
    return package({'study.json':json.dumps(study,indent=2).encode(),'readable-report.html':report('NeuraTwin / '+study['kind'],study)},f'halo-study-{key}.zip')
