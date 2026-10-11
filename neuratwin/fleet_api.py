"""Fleet evidence, historical recovery and assigned work. Synthetic-only mutations."""
from copy import deepcopy
import csv
import io
import json
import zipfile
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from . import fleet as core, halo_store as store, auth, cloud
from .halo_api import operator
from .storage import now

router=APIRouter(prefix='/api/halo/fleet')


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


def identity(request:Request):
    if cloud.enabled():return auth.identity(request,'viewer')
    operator(request)
    return dict(user_id='local-owner',role='admin',mode='local rehearsal')


def require(user, role='operator'):
    if auth.ROLES[user['role']]<auth.ROLES[role]:raise HTTPException(403,role+' access required')


def get_run(key):
    r=store.get('fleet_run',key)
    if r is None:raise HTTPException(404,'Fleet run not found')
    return r


def state_for(run,asset):
    if asset not in run['assets']:raise HTTPException(404,'Asset is not registered in this synthetic run')
    return run['assets'][asset]


class Create(Contract):
    request_id:str=Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    seed:int=Field(26,ge=0,le=100000)


class Mutation(Contract):
    request_id:str=Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    revision:int=Field(ge=0)


def mutate(key,payload,user,fn):
    require(user)
    with store.transaction():
        opkey=key+':'+payload.request_id; content=core.digest({'body':payload.model_dump(),'actor':user['user_id'],'operation':fn.__name__})
        prior=store.get('fleet_operation',opkey)
        if prior:
            if prior['digest']!=content:raise HTTPException(409,'Request ID already used with different content')
            return prior['result']
        r=get_run(key)
        if r['revision']!=payload.revision:raise HTTPException(409,'Fleet changed. Refresh before retrying.')
        result=fn(r)
        r['revision']+=1;store.put('fleet_run',key,r)
        result=result if result is not None else core.snapshot(r)
        store.put('fleet_operation',opkey,dict(digest=content,result=result))
        store.event(key,'fleet_'+fn.__name__,dict(actor=user['user_id'],revision=r['revision'],request_id=payload.request_id))
        return result


@router.get('/identity')
def who(user=Depends(identity)):
    return user


@router.get('/members')
def members(user=Depends(identity)):
    if not cloud.enabled() or user.get('mode') in ('local operator','local rehearsal'):
        return {'members':[dict(user_id=user['user_id'],label='Local operator',role=user['role'])]}
    rows=cloud.rows('halo_members',{'active':'eq.true','select':'user_id,role'},500)
    return {'members':[dict(user_id=r['user_id'],label=r['user_id'],role=r['role']) for r in rows if r['role']!='viewer']}


@router.get('/runs')
def runs(user=Depends(identity)):
    return {'runs':[{k:r[k] for k in ('id','seed','minute','revision','created_at')} for r in store.records('fleet_run')[:50]]}


@router.post('/runs')
def create(payload:Create,user=Depends(identity)):
    require(user)
    key='fleet-'+payload.request_id
    with store.transaction():
        old=store.get('fleet_run',key)
        if old:
            if old['seed']!=payload.seed or old['created_by']!=user['user_id']:raise HTTPException(409,'Run identity conflict')
            return core.snapshot(old)
        r=core.initial(payload.seed);r.update(id=key,created_at=now(),created_by=user['user_id'])
        store.put('fleet_run',key,r)
        store.put('fleet_tick',key+':0',dict(run_id=key,revision=0,rows=[dict(s['last'],delivered=True) for s in r['assets'].values() if s['last']]))
        return core.snapshot(r)


@router.get('/runs/{key}/snapshot')
def snapshot(key:str,user=Depends(identity)):
    return core.snapshot(get_run(key))


class Tick(Mutation):
    minutes:Literal[1,5,15,30,60]=5


@router.post('/runs/{key}/ticks')
def tick(key:str,payload:Tick,user=Depends(identity)):
    def advance(r):
        if r['minute']+payload.minutes>1440:raise HTTPException(422,'24-hour rehearsal complete. Create a new run; this evidence remains retained.')
        rows=core.advance(r,payload.minutes)
        store.put('fleet_tick',key+':'+str(r['revision']+1),dict(run_id=key,revision=r['revision']+1,rows=rows))
    return mutate(key,payload,user,advance)


class Scenario(Mutation):
    asset_id:str
    kind:Literal['disconnect','reconnect','reduce_load','restore_load','overload','cooling_loss','restore_cooling','acknowledge']


@router.post('/runs/{key}/scenarios')
def scenario(key:str,payload:Scenario,user=Depends(identity)):
    def scenario_change(r):
        s=state_for(r,payload.asset_id);kind=payload.kind
        if kind in ('disconnect','reconnect'):s['connected']=kind=='reconnect'
        elif kind=='reduce_load':s['control']['load_scale']=.65
        elif kind=='restore_load':s['control']['load_scale']=1
        elif kind=='overload':s['control']['load_scale']=1.8
        elif kind=='cooling_loss':s['control']['cooling']=.55
        elif kind=='restore_cooling':s['control']['cooling']=1
        else:
            for f in s['findings']:
                if f['status']=='unresolved':f.update(acknowledged_by=user['user_id'],acknowledged_at=now())
        store.event(key,'fleet_scenario',dict(asset_id=payload.asset_id,kind=kind,minute=r['minute'],actor=user['user_id'],origin='synthetic'))
    return mutate(key,payload,user,scenario_change)


def history(key,asset,include_buffer=False):
    rows={}
    for tick in store.records('fleet_tick'):
        if tick['run_id']==key:
            for r in tick['rows']:
                if r['asset_id']==asset and (include_buffer or r['delivered']):rows[r['sequence']]=r
    if not include_buffer:
        for batch in store.records('fleet_import'):
            if batch['run_id']==key and batch['asset_id']==asset:
                for r in batch['rows']:rows[r['sequence']]=dict(r,delivery='historical import')
    return [rows[k] for k in sorted(rows)]


@router.get('/runs/{key}/assets/{asset}')
def asset_detail(key:str,asset:str,user=Depends(identity)):
    r=get_run(key);s=state_for(r,asset)
    return dict(asset=core.public_asset(s,r['minute']),run_id=key,revision=r['revision'],
                forecasts=[f for f in store.records('fleet_forecast') if f['run_id']==key and f['asset_id']==asset],
                jobs=[j for j in store.records('fleet_job') if j['run_id']==key and j['asset_id']==asset])


@router.get('/runs/{key}/assets/{asset}/history')
def asset_history(key:str,asset:str,offset:int=Query(0,ge=0),limit:int=Query(180,ge=1,le=1441),user=Depends(identity)):
    state_for(get_run(key),asset);rows=history(key,asset)
    return dict(total=len(rows),rows=rows[offset:offset+limit],origin='synthetic')


@router.get('/runs/{key}/assets/{asset}/passport')
def passport(key:str,asset:str,request:Request,user=Depends(identity)):
    import base64
    import qrcode
    state_for(get_run(key),asset)
    link=str(request.base_url).rstrip('/')+'/app?fleetRun='+key+'&fleetAsset='+asset+'&fleetPanel=twin#fleet'
    output=io.BytesIO();qrcode.make(link).save(output,format='PNG')
    return dict(asset_id=asset,run_id=key,url=link,qr_png_base64=base64.b64encode(output.getvalue()).decode(),
                meaning='Asset identification only; does not grant access or transfer device logs')


class Forecast(Mutation):
    asset_id:str
    reduction:float=Field(35,ge=0,le=70)
    horizon:int=Field(60,ge=5,le=120)


@router.post('/runs/{key}/forecasts')
def freeze(key:str,payload:Forecast,user=Depends(identity)):
    def freeze_forecast(r):
        try:p=core.forecast(state_for(r,payload.asset_id),r['minute'],payload.reduction,payload.horizon)
        except ValueError as e:raise HTTPException(422,str(e))
        p.update(id=key+'-forecast-'+payload.request_id,run_id=key,revision=r['revision'],created_by=user['user_id'],created_at=now())
        p['sha256']=core.digest(p);store.put('fleet_forecast',p['id'],p)
        return p
    return mutate(key,payload,user,freeze_forecast)


@router.get('/forecasts/{key}/score')
def forecast_score(key:str,user=Depends(identity)):
    f=store.get('fleet_forecast',key)
    if f is None:raise HTTPException(404,'Forecast not found')
    return core.score(f,history(f['run_id'],f['asset_id']))


@router.get('/runs/{key}/assets/{asset}/harvest')
def harvest(key:str,asset:str,user=Depends(identity)):
    r=get_run(key);s=state_for(r,asset)
    known={v['sequence'] for v in history(key,asset)}
    rows=[v for v in history(key,asset,True) if v['sequence'] not in known]
    return dict(batch_id='harvest-'+str(uuid4()),run_id=key,asset_id=asset,origin='synthetic',
                device_id='demo-'+asset,parameter_version=core.VERSION,rows=rows,sha256=core.digest(rows),
                transport='Downloaded synthetic buffer; not NFC/BLE hardware transfer')


class Import(Contract):
    batch_id:str=Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')
    run_id:str
    asset_id:str
    origin:Literal['synthetic']
    device_id:str
    parameter_version:str
    rows:list[dict]=Field(max_length=1441)
    sha256:str
    transport:str=Field(max_length=200)


@router.post('/import-batches')
def import_batch(payload:Import,user=Depends(identity)):
    require(user)
    with store.transaction():
        r=get_run(payload.run_id);state_for(r,payload.asset_id)
        fingerprint=core.digest(payload.model_dump());key=payload.run_id+':'+payload.batch_id
        prior=store.get('fleet_import',key)
        if prior:
            if prior['digest']!=fingerprint:raise HTTPException(409,'Changed contents under the same batch ID; original preserved')
            return dict(accepted=0,duplicates=len(prior['rows']),historical=True)
        if payload.device_id!='demo-'+payload.asset_id or payload.parameter_version!=core.VERSION or payload.sha256!=core.digest(payload.rows):
            raise HTTPException(422,'Device, configuration or integrity mismatch')
        # Rehearsal imports are bound to retained generator records, not arbitrary fabricated physical data.
        expected={v['sequence']:v for v in history(payload.run_id,payload.asset_id,True)}
        seen=set();known={v['sequence'] for v in history(payload.run_id,payload.asset_id)};accepted=[]
        for row in payload.rows:
            seq=row.get('sequence')
            if not isinstance(seq,int) or seq in seen or row!=expected.get(seq):raise HTTPException(422,'Unknown, altered or duplicate acquisition; batch rejected')
            seen.add(seq)
            if seq not in known:accepted.append(row)
        store.put('fleet_import',key,dict(run_id=payload.run_id,asset_id=payload.asset_id,digest=fingerprint,rows=accepted,
                  received_at=now(),uploader=user['user_id'],batch_id=payload.batch_id,origin='synthetic'))
        # Never change last live acquisition, clock, findings or commands from historical rows.
        return dict(accepted=len(accepted),duplicates=len(payload.rows)-len(accepted),historical=True)


class JobCreate(Mutation):
    asset_id:str
    title:str=Field(min_length=3,max_length=180)
    assignee:str=Field(min_length=1,max_length=100)
    due_minutes:int=Field(30,ge=1,le=1440)
    procedure:str=Field(min_length=3,max_length=500)


@router.post('/runs/{key}/jobs')
def create_job(key:str,payload:JobCreate,user=Depends(identity)):
    require(user,'admin')
    allowed={v['user_id'] for v in members(user)['members']}
    if payload.assignee not in allowed:raise HTTPException(422,'Assign an active operator or reviewer')
    def assign_job(r):
        s=state_for(r,payload.asset_id)
        if any(f['severity']=='critical' and f['status']=='unresolved' for f in s['findings']) and payload.due_minutes>30:
            raise HTTPException(422,'Urgent unresolved work requires a due window of at most 30 model minutes')
        job=dict(id=key+'-job-'+payload.request_id,run_id=key,asset_id=payload.asset_id,title=payload.title,
                 assignee=payload.assignee,reviewer=user['user_id'],status='assigned',revision=0,origin='synthetic',
                 issued_minute=r['minute'],due_minute=r['minute']+payload.due_minutes,procedure=payload.procedure,
                 skills=s['asset']['skills'],access=s['asset']['access'],evidence=core.public_asset(s,r['minute']),
                 acceptance=dict(version=core.VERSION,oil_limit_c=s['asset']['oil_limit_c'],loading_pu=1.1,min_followup_minutes=5),
                 visits=[],actions=[],outcome=None,created_at=now(),trail=[dict(event='reviewed_and_assigned',actor=user['user_id'],at=now())])
        store.put('fleet_job',job['id'],job);return job
    return mutate(key,payload,user,assign_job)


class JobUpdate(Contract):
    request_id:str=Field(min_length=8,max_length=80)
    revision:int=Field(ge=0)
    operation:Literal['accept','visit','action','review','reopen']
    note:str=Field(min_length=3,max_length=3000)
    observed_at:str|None=None
    instrument_id:str|None=Field(None,max_length=120)
    temperature_c:float|None=Field(None,ge=-55,le=200)
    photo_base64:str|None=Field(None,max_length=5_400_000)


@router.get('/jobs/{key}')
def job_detail(key:str,user=Depends(identity)):
    j=store.get('fleet_job',key)
    if j is None:raise HTTPException(404,'Job not found')
    if user['role']!='admin' and j['assignee']!=user['user_id']:raise HTTPException(403,'This job is assigned to another technician')
    return j


@router.post('/jobs/{key}')
def update_job(key:str,payload:JobUpdate,user=Depends(identity)):
    require(user)
    with store.transaction():
        j=store.get('fleet_job',key)
        if j is None:raise HTTPException(404,'Job not found')
        if payload.operation in ('review','reopen'):require(user,'admin')
        elif user['user_id']!=j['assignee']:raise HTTPException(403,'Only the assigned technician can submit this job')
        opkey=key+':'+payload.request_id;fingerprint=core.digest(dict(body=payload.model_dump(),actor=user['user_id']))
        prior=store.get('fleet_job_operation',opkey)
        if prior:
            if prior['digest']!=fingerprint:raise HTTPException(409,'Submission identity conflict')
            return prior['result']
        if payload.revision!=j['revision']:raise HTTPException(409,'Job changed. Review the conflict before resubmitting.')
        if j['status']=='reviewed_outcome' and payload.operation!='reopen':raise HTTPException(409,'Reviewer must reopen this job first')
        r=get_run(j['run_id']);s=state_for(r,j['asset_id']);event=dict(event=payload.operation,note=payload.note,actor=user['user_id'],at=now(),minute=r['minute'])
        if payload.operation=='accept':
            if j['status']!='assigned':raise HTTPException(409,'Job has already been accepted')
            j['status']='accepted'
        elif payload.operation=='visit':
            if j['status'] not in ('accepted','visit_recorded','follow_up_required'):raise HTTPException(409,'Accept the assignment before recording a visit')
            from datetime import datetime,timezone
            try:
                t=datetime.fromisoformat((payload.observed_at or '').replace('Z','+00:00'))
                if t.tzinfo is None or t>datetime.now(timezone.utc):raise ValueError()
            except ValueError:raise HTTPException(422,'Visit acquisition time must include an offset and cannot be in the future')
            photo=None
            if payload.photo_base64:
                from .maintenance_api import photograph
                photo=photograph(payload.photo_base64,key,user['user_id'])
            event.update(observed_at=payload.observed_at,instrument_id=payload.instrument_id,temperature_c=payload.temperature_c,photo=photo)
            j['visits'].append(deepcopy(event));j['status']='visit_recorded'
        elif payload.operation=='action':
            if not j['visits']:raise HTTPException(409,'Record technician findings first')
            event['evidence']=core.public_asset(s,r['minute']);j['actions'].append(deepcopy(event));j['status']='follow_up_required'
        elif payload.operation=='review':
            outcome='inconclusive';reason='A recorded visit, action and suitable later observations are required.'
            if j['actions'] and j['visits']:
                action=j['actions'][-1];after=[x for x in history(j['run_id'],j['asset_id']) if x['minute']>action['minute']]
                a=s['asset'];rated=a['rated_kva']*1000/(3**.5*415)
                if core.freshness(s,r['minute'])=='fresh' and len(after)>=2 and after[-1]['minute']-action['minute']>=j['acceptance']['min_followup_minutes']:
                    good=all(x['channels']['current']['value']/rated<=j['acceptance']['loading_pu'] and (x['channels']['oil']['value'] is None or x['channels']['oil']['value']<=j['acceptance']['oil_limit_c']) for x in after[-5:])
                    oil_supported=all(x['channels']['oil']['value'] is not None for x in after[-5:])
                    outcome='mitigated' if good and oil_supported else 'inconclusive' if good else 'no_improvement'
                    reason='Synthetic loading/oil criteria met; physical repair is not established.' if outcome=='mitigated' else 'Independent oil reference missing.' if good else 'Follow-up still exceeds the frozen acceptance criteria.'
            j['outcome']=dict(classification=outcome,reason=reason,basis='synthetic simulation acceptance',reviewer=user['user_id'],at=now())
            j['status']='reviewed_outcome';event['outcome']=deepcopy(j['outcome'])
        else:
            if j['status']!='reviewed_outcome':raise HTTPException(409,'Only a reviewed job can be reopened')
            j['status']='accepted';j['outcome']=None
        j['trail'].append(event);j['revision']+=1;store.put('fleet_job',key,j)
        store.put('fleet_job_operation',opkey,dict(digest=fingerprint,result=deepcopy(j)))
        return j


class Cost(Contract):
    option:Literal['meter_only','selected_sensing','reference_sensing']
    population:int=Field(12,ge=1,le=100000)
    years:float=Field(5,ge=.1,le=50)
    hardware:float|None=Field(None,ge=0,le=1e10)
    installation:float|None=Field(None,ge=0,le=1e10)
    integration:float|None=Field(None,ge=0,le=1e10)
    annual_comms:float|None=Field(None,ge=0,le=1e10)
    annual_hosting:float|None=Field(None,ge=0,le=1e10)
    annual_support:float|None=Field(None,ge=0,le=1e10)
    annual_replacements:float|None=Field(None,ge=0,le=1e10)
    annual_visits:float|None=Field(None,ge=0,le=1e10)
    source:str=Field(min_length=3,max_length=500)
    basis:Literal['assumed','quoted','observed']='assumed'


@router.get('/runs/{key}/costs')
def costs(key:str,user=Depends(identity)):
    get_run(key)
    return [r for r in store.records('fleet_cost') if r['run_id']==key]


@router.post('/runs/{key}/costs')
def save_cost(key:str,payload:Cost,user=Depends(identity)):
    require(user);get_run(key)
    v=payload.model_dump();capital=[v[k] for k in ('hardware','installation','integration')]
    recurring=[v[k] for k in ('annual_comms','annual_hosting','annual_support','annual_replacements','annual_visits')]
    complete=all(x is not None for x in capital+recurring)
    v.update(run_id=key,id=str(uuid4()),recorded_at=now(),actor=user['user_id'],currency='INR',
             annual_total=(sum(capital)/payload.years+sum(recurring)) if complete else None,
             assumptions='All entered costs cover the stated population. Straight-line annualisation; no discounting or claimed failure savings.')
    store.put('fleet_cost',v['id'],v);return v


def export_data(key):
    run=get_run(key)
    return dict(snapshot=core.snapshot(run),forecasts=[f for f in store.records('fleet_forecast') if f['run_id']==key],
                jobs=[j for j in store.records('fleet_job') if j['run_id']==key],costs=[c for c in store.records('fleet_cost') if c['run_id']==key],
                observations={a:history(key,a) for a in run['assets']},events=store.events(key,10000),
                scope='Synthetic fleet evidence. Buffered, unharvested samples are not available observations. No physical outcome claims.')


@router.get('/runs/{key}/export')
def export(key:str,format:Literal['json','zip','pdf']='json',user=Depends(identity)):
    with store.transaction():data=export_data(key)
    for f in data['forecasts']:f['score']=core.score(f,data['observations'][f['asset_id']])
    encoded=json.dumps(data,indent=2,allow_nan=False).encode()
    if format=='json':return Response(encoded,media_type='application/json',headers={'Content-Disposition':'attachment; filename="fleet-evidence.json"'})
    if format=='pdf':
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from xml.sax.saxutils import escape
        stream=io.BytesIO();styles=getSampleStyleSheet();story=[]
        def p(text,style='BodyText'):story.append(Paragraph(escape(str(text)),styles[style]));story.append(Spacer(1,8))
        p('NeuraTwin | Fleet evidence','Title');p(data['scope']);p(f"Run {key} | seed {data['snapshot']['seed']} | {data['snapshot']['time']}")
        table=[['Asset','Condition','Freshness','Coverage','Priority']]+[[a['id'],a['condition'],a['freshness'],str(a['coverage']['available'])+'/4',a['priority']] for a in data['snapshot']['assets']]
        t=Table(table,repeatRows=1);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ADB6AE')),('GRID',(0,0),(-1,-1),.3,colors.grey)]));story.append(t)
        def number(value):return 'Unavailable' if value is None else f'{value:.2f}'
        for f in data['forecasts']:
            p(f"{f['asset_id']} - frozen forecast",'Heading2')
            p(f"Issued {f['issued_at']} | target {f['target']} | initial state {number(f['initial_c'])} C")
            p(f"Model MAE {number(f['score']['mae_c'])} C | persistence MAE {number(f['score']['persistence_mae_c'])} C | excluded windows {len(f['score']['excluded'])}")
            p(f['assumptions'])
        for j in data['jobs']:
            p(j['title'],'Heading2');p(f"{j['asset_id']} | {j['status'].replace('_',' ')}")
            if j['outcome']:p(j['outcome']['classification'].replace('_',' ')+': '+j['outcome']['reason'])
            for e in j['trail']:p(f"{e['at']} | {e['actor']} | {e['event']} | {e.get('note','')}")
        for c in data['costs']:p(f"{c['option']} | annual INR {c['annual_total']} | population {c['population']} | {c['basis']} | {c['source']}")
        p('All readings, curves, exclusions and input versions are available in the accompanying JSON/CSV evidence ZIP. Unknown values are not zero.')
        SimpleDocTemplate(stream).build(story)
        return Response(stream.getvalue(),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="fleet-report.pdf"'})
    stream=io.BytesIO();csvfile=io.StringIO();writer=csv.writer(csvfile);writer.writerow(['asset','sequence','acquired_at','delivery','origin','current_A','voltage_V','surface_C','oil_C'])
    for asset,rows in data['observations'].items():
        for r in rows:writer.writerow([asset,r['sequence'],r['acquired_at'],r['delivery'],'synthetic',*[r['channels'][k]['value'] for k in ('current','voltage','surface','oil')]])
    files={'evidence.json':encoded,'readings.csv':csvfile.getvalue().encode()}
    import hashlib
    manifest={'meaning':'Integrity checksums, not a signature or proof of measurement','files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()}}
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for n,v in files.items():z.writestr(n,v)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="fleet-evidence.zip"'})
