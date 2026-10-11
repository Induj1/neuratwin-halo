"""Source-bound maintenance records, frozen forecasts and technician follow-up."""
import base64
from copy import deepcopy
import hashlib
import io
import math
from typing import Literal
from uuid import uuid4
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from .briefing_api import LifetimeRequest
from .twin_api import run_or_404
from . import halo_store as store, lifetime_scenario as lifetime, maintenance_model as model
from .maintenance_calibration import propose
from .twin_studies import digest
from .storage import now
from . import transient_fem

router=APIRouter(prefix='/api/halo/maintenance')


@router.post('/fem')
def transient(payload:transient_fem.Study,actor=Depends(operator)):
    return transient_fem.solve(payload)


@router.get('/fem/checks')
def numerical_checks(actor=Depends(operator)):
    return transient_fem.checks()


class Context(LifetimeRequest):
    profile_revision:int=Field(0,ge=0)
    options:model.DecisionOptions=Field(default_factory=model.DecisionOptions)


def profile_for(asset, state=None):
    saved=store.get('maintenance_profile',asset)
    if saved:return saved
    p=model.Profile()
    if asset!='BENCH-001':
        s=(state or run_or_404(asset))['settings']
        rated=s['rated_kva']*1000/(math.sqrt(3)*s['secondary_v'])
        if not s['core_loss_w'] or not .1<=s['copper_loss_w']/s['core_loss_w']<=30 or rated>200000:
            raise HTTPException(422,'Industrial ratings or loss ratio are outside this maintenance model envelope.')
        p=model.Profile(rated_current_a=rated,
            rated_rise_c=s['rated_oil_rise_c'],tau_min=s['oil_tau_min'],loss_ratio=s['copper_loss_w']/s['core_loss_w'],temperature_limit_c=95)
    return {'asset_id':asset,'revision':0,'profile':p.model_dump(),'version':model.VERSION,
        'provenance':'assumed surface-response parameters' if asset=='BENCH-001' else 'declared industrial simulation parameters; oil limit assumed', 'history':[]}


def context(asset, payload):
    state=None
    if asset=='BENCH-001':
        samples=[v.model_dump(mode='json') for v in payload.display_history]
        current=payload.display_current.model_dump(mode='json') if payload.display_current else None
        if current:samples.append(current)
        rows=[]
        for v in samples:
            if not v.get('timestamp'):continue
            r=lifetime.from_display(v)
            r.update(calibrated=v['calibrated'],temperature_source=v['channels']['surface_temperature']['source'],
                primary_voltage_v=v['channels']['primary_voltage']['value'],primary_current_a=v['channels']['primary_current']['value'],
                primary_current_source=v['channels']['primary_current']['source'])
            rows.append(r)
        live=bool(current and current['live'] and current['probe_valid'] and current.get('age_s') is not None and current['age_s']<=10)
        mode='prototype';channel='Surface temperature'
    else:
        state=deepcopy(run_or_404(asset))
        if payload.revision is not None and state['revision']!=payload.revision:raise HTTPException(409,'Source changed. Refresh the decision.')
        rows=[{**lifetime.from_industrial(v),'temperature_c':v.get('oil_temperature'),'ambient_c':v.get('ambient_temperature',state['inputs']['ambient_c']),
            'primary_voltage_v':v.get('primary_voltage'),'primary_current_a':v.get('primary_current'),'primary_current_source':'industrial simulation','source':'industrial modelled top-oil'} for v in [*state['history'],state['telemetry']]]
        live=True;mode='industrial';channel='Modelled top-oil'
    record=profile_for(asset,state)
    if payload.profile_revision!=record['revision']:raise HTTPException(409,'Asset model changed. Refresh the profile.')
    profile=model.Profile(**record['profile'])
    rows=model.unique_rows(rows)
    # A client cannot append an older current sample and silently forecast a newer cached one.
    if asset=='BENCH-001' and rows and current and rows[-1]['timestamp']!=current['timestamp']:live=False
    if mode=='industrial' and rows:profile=profile.model_copy(update={'ambient_c':rows[-1]['ambient_c']})
    return rows,live,mode,channel,record,profile


def assess(asset,payload):
    rows,live,mode,channel,record,p=context(asset,payload)
    result=model.decision(rows,p,payload.options,live=live,channel=channel)
    result.update(asset_id=asset,mode=mode,profile_revision=record['revision'],profile_provenance=record['provenance'])
    result['input_sha256']=digest({'rows':rows,'profile':p.model_dump(),'options':payload.options.model_dump(),'version':model.VERSION})
    return result,rows


def history(asset):
    return [r for r in store.records('maintenance_job') if r['asset_id']==asset]


def model_card(record):
    evidence=record.get('evidence') or {}
    physical=record['asset_id']=='BENCH-001'
    qualified=bool(physical and evidence.get('available'))
    return {'target':'Measured surface temperature' if physical else 'Simulated top-oil temperature',
        'status':'accepted held-out surface fit' if qualified else 'assumed parameters' if physical else 'simulation study',
        'profile_revision':record['revision'],'provenance':record['provenance'],
        'held_out_rmse_c':evidence.get('held_out_rmse_c'),'persistence_rmse_c':evidence.get('persistence_rmse_c'),
        'train_samples':evidence.get('train_samples'),'held_out_samples':evidence.get('held_out_samples'),
        'input_sha256':evidence.get('input_sha256'),
        'scope':'Calibration evidence applies to its retained acquisition interval; live drift and new operating conditions require renewed checks. Oil, pressure, FEM and lifetime studies are separate models.',
        'accepted_interval_fit_available':qualified,
        'field_validated':False}


@router.get('/assets/{asset}')
def asset_record(asset:str,actor=Depends(operator)):
    if asset!='BENCH-001':run_or_404(asset)
    profile=profile_for(asset)
    return {'profile':profile,'model_card':model_card(profile),'jobs':history(asset),
        'inspections':[r for r in store.records('mobile_inspection') if r.get('asset_id')==asset],
        'previous_work':[r for r in store.records('twin_work') if r.get('run_id')==asset]}


@router.post('/assets/{asset}/decision')
def decision(asset:str,payload:Context,actor=Depends(operator)):
    return assess(asset,payload)[0]


class JobRequest(Context):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    title:str=Field(min_length=3,max_length=180)
    owner:str=Field(min_length=2,max_length=100)
    stable_minutes:int=Field(5,ge=1,le=60)


@router.post('/assets/{asset}/jobs')
def create_job(asset:str,payload:JobRequest,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        key=asset+'-maintenance-'+payload.request_id
        request_digest=digest(payload.model_dump(mode='json'))
        prior=store.get('maintenance_job',key)
        if prior:
            if prior['request_digest']!=request_digest or prior['created_by']!=actor:raise HTTPException(409,'Request ID already has different content.')
            return prior
        decision,rows=assess(asset,payload)
        if not decision['available']:raise HTTPException(409,'; '.join(decision['holds']))
        previous=history(asset)
        value={'id':key,'asset_id':asset,'mode':decision['mode'],'title':payload.title,'owner':payload.owner,
            'created_at':now(),'created_by':actor,'revision':0,'status':'open','request_digest':request_digest,
            'decision':decision,'initial_readings':rows,'profile_revision':decision['profile_revision'],
            'acceptance':{'temperature_limit_c':decision['profile']['temperature_limit_c'],'stable_minutes':payload.stable_minutes},
            'previous_maintenance':[{'id':r['id'],'title':r['title'],'status':r['status'],'findings':r['findings'],'verification':r.get('verification',{}).get('outcome')} for r in previous],
            'prior_inspections':[r for r in store.records('mobile_inspection') if r.get('asset_id')==asset],
            'prior_work':[r for r in store.records('twin_work') if r.get('run_id')==asset],
            'findings':{},'action':None,'observations':[],'followup_cycles':[],'trail':[{'time':now(),'event':'created','actor':actor}]}
        store.put('maintenance_job',key,value)
        store.event(asset,'maintenance_created',{'id':key,'actor':actor})
        return value


def get_job(asset,key,revision=None):
    job=store.get('maintenance_job',key)
    if not job or job['asset_id']!=asset:raise HTTPException(404,'Job not found for this asset.')
    if revision is not None and revision!=job['revision']:raise HTTPException(409,'Job changed. Refresh before saving.')
    return job


class Update(Context):
    job_revision:int=Field(ge=0)
    operation:Literal['findings','action','verify']
    note:str=Field('',max_length=3000)
    issue_resolved:bool=False
    photo_base64:str|None=Field(None,max_length=5_400_000)


def photograph(encoded,key,actor):
    try:
        data=base64.b64decode(encoded,validate=True)
        if len(data)>4_000_000:raise ValueError()
        picture=Image.open(io.BytesIO(data))
        if picture.format not in ('JPEG','PNG') or picture.width*picture.height>20_000_000:raise ValueError()
        mime='image/png' if picture.format=='PNG' else 'image/jpeg'
        picture.verify()
    except Exception:raise HTTPException(422,'Use a JPEG or PNG under 4 MB and 20 megapixels.')
    return store.photo({'id':str(uuid4()),'incident_id':key,'filename':'technician-findings','actor':actor,'created_at':now(),'mime':mime,'sha256':hashlib.sha256(data).hexdigest()},data)


@router.post('/assets/{asset}/jobs/{key}')
def update_job(asset:str,key:str,payload:Update,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        job=get_job(asset,key,payload.job_revision)
        event={'time':now(),'event':payload.operation,'actor':actor,'note':payload.note}
        if payload.operation=='findings':
            if len(payload.note.strip())<3:raise HTTPException(422,'Add technician findings.')
            photo=photograph(payload.photo_base64,key,actor) if payload.photo_base64 else None
            job['findings']={'note':payload.note,'issue_resolved':payload.issue_resolved,'recorded_at':now(),'actor':actor,
                'photos':job['findings'].get('photos',[])+([photo] if photo else [])}
            event['findings']=deepcopy(job['findings'])
            job['status']='verification_pending' if job.get('action') else 'in_progress'
            job.pop('verification',None)
        elif payload.operation=='action':
            if len(payload.note.strip())<3:raise HTTPException(422,'Record the action performed.')
            d,rows=assess(asset,payload)
            if not d['available']:raise HTTPException(409,'Fresh source readings are needed to freeze follow-up.')
            if job.get('action'):
                job.setdefault('followup_cycles',[]).append({'action':deepcopy(job['action']),'observations':deepcopy(job['observations']),'verification':deepcopy(job.get('verification'))})
                event['previous_action']=deepcopy(job['action'])
            job['action']={'note':payload.note,'recorded_at':now(),'actor':actor,'origin':d['origin'],
                'profile':d['profile'],'profile_revision':d['profile_revision'],'horizon_min':payload.options.horizon_min,
                'forecast':d['forecast'],'input_sha256':d['input_sha256'],'scope':'Recorded action; no command issued by this endpoint.'}
            job['observations']=[];job.pop('verification',None);job['status']='verification_pending'
            event['action']=deepcopy(job['action'])
        else:
            rows,live,*_=context(asset,payload)
            if job.get('action'):
                start=model.seconds(job['action']['origin']['timestamp'])
                job['observations']=model.unique_rows([*job['observations'],*[r for r in rows if start<model.seconds(r['timestamp'])<=start+job['action']['horizon_min']*60]])[-10000:]
            result=model.verification(job,job['observations'],live=live)
            result['recorded_at']=now();job['verification']=result
            job['status']=result['outcome'] if result['outcome']!='insufficient_evidence' else 'verification_pending'
            event['verification']=deepcopy(result)
        job['revision']+=1;job['trail'].append(event)
        store.put('maintenance_job',key,job)
        store.event(asset,'maintenance_'+payload.operation,{'id':key,'actor':actor,'revision':job['revision']})
        return job


class ProfileUpdate(Contract):
    revision:int=Field(ge=0)
    profile:model.Profile
    note:str=Field(min_length=5,max_length=1000)


def save_profile(asset,old,profile,provenance,note,actor,evidence=None):
    if asset=='BENCH-001' and profile.rated_current_a!=1:raise HTTPException(422,'Prototype rating remains 1 A.')
    saved={'asset_id':asset,'revision':old['revision']+1,'profile':profile.model_dump(),'version':model.VERSION,
        'provenance':provenance,'history':[*old['history'],{k:deepcopy(v) for k,v in old.items() if k!='history'}],
        'changed_at':now(),'actor':actor,'note':note,'evidence':evidence}
    store.put('maintenance_profile',asset,saved)
    store.event(asset,'maintenance_profile_changed',{'revision':saved['revision'],'note':note,'actor':actor})
    return saved


@router.post('/assets/{asset}/profile')
def update_profile(asset:str,payload:ProfileUpdate,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        old=profile_for(asset)
        if old['revision']!=payload.revision:raise HTTPException(409,'Profile changed. Refresh before saving.')
        return save_profile(asset,old,payload.profile,'operator-entered assumptions',payload.note,actor)


@router.post('/assets/{asset}/calibration')
def calibration(asset:str,payload:Context,actor=Depends(operator)):
    rows,live,mode,_,record,p=context(asset,payload)
    # Retained job evidence lets calibration span more than the browser's short rolling buffer.
    for job in history(asset):
        rows.extend(job['initial_readings']+job['observations'])
        for cycle in job.get('followup_cycles',[]):rows.extend(cycle['observations'])
    if mode!='prototype' or not live:return {'available':False,'reason':'Requires fresh physical measurements; simulated sources cannot calibrate the physical model.'}
    result=propose(rows,p)
    if result['available']:
        result.update(id=str(uuid4()),asset_id=asset,profile_revision=record['revision'],input_sha256=digest(model.unique_rows(rows)),created_at=now())
        store.put('maintenance_calibration',result['id'],result)
    return result


class Accept(Contract):
    proposal_id:str=Field(max_length=80)
    profile_revision:int=Field(ge=0)


@router.post('/assets/{asset}/calibration/accept')
def accept_calibration(asset:str,payload:Accept,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        old=profile_for(asset);proposal=store.get('maintenance_calibration',payload.proposal_id)
        if not proposal or proposal.get('asset_id')!=asset:raise HTTPException(404,'Proposal not found for this asset.')
        if old['revision']!=payload.profile_revision or proposal['profile_revision']!=old['revision']:raise HTTPException(409,'Profile changed since this fit. Refit before accepting.')
        return save_profile(asset,old,model.Profile(**proposal['proposed_profile']),'held-out surface fit; limited acquisition coverage','Explicitly accepted calibration proposal',actor,proposal)


@router.get('/assets/{asset}/jobs/{key}/report.pdf')
def job_report(asset:str,key:str,actor=Depends(operator)):
    from .maintenance_report import render
    return Response(render(get_job(asset,key)),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="maintenance-job.pdf"'})
