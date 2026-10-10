"""Asset-scoped evidence, intervention and maintenance records."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from . import twin_core as core, twin_studies as studies, halo_store as store
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from .twin_api import run_or_404
from .storage import now
from . import thermal_reference, twin_observer as observer

router=APIRouter(prefix='/api/halo/twin')


@router.get('/runs/{key}/observation-review')
def observation_review(key:str, revision:int=Query(...,ge=0)):
    """Inspect observed channels only; never give the assessor scenario labels."""
    s=deepcopy(run_or_404(key))
    if s['revision']!=revision:
        raise HTTPException(409,'Run changed. Refresh before reviewing its observations.')
    rows=observer.from_history(s)
    result=observer.assess(rows,s['settings'],30)
    return {'run_id':key,'revision':s['revision'],'source':'industrial_simulation_observations',
            'elapsed_s':s['elapsed_s'],'observation_count':len(rows),
            'input_sha256':studies.digest(rows),'model_version':observer.VERSION,
            'assessment':result,'scenario_labels_supplied':False,'hardware_action':False,
            'reference_basis':'Initial observation prefix is assumed healthy by the screening method; this is not a commissioned reference or independent field evidence.',
            'channels':['oil temperature','reported hot-spot','ambient','loading','voltage','optional phase RMS'],
            'excluded':['scenario name','declared cooling','fault type','future readings']}


@router.get('/external-forecast')
def external_forecast_status():
    from .external_forecast import public_status
    try:return public_status()
    except (ValueError,FileNotFoundError):
        raise HTTPException(409,'Public evaluation artifacts are missing or differ from the recorded source. Revalidation required.')


@router.get('/external-forecast/demo')
def external_forecast_demo(origin_index:int=Query(11520,ge=11520,le=14393)):
    from .external_forecast import demo
    try:return demo(origin_index=origin_index,history_hours=48)
    except FileNotFoundError:
        raise HTTPException(422,'Required public forecast artifacts are unavailable. Restore and verify the evidence package.')
    except ValueError as e:raise HTTPException(422,str(e))


class StudyRequest(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    revision:int=Field(ge=0)
    horizon_min:int=Field(30,ge=5,le=120)
    max_delay_min:int=Field(0,ge=0,le=20)


def existing(kind,key,payload):
    prior=store.get(kind,key)
    if prior and prior['request_digest']!=studies.digest(payload.model_dump(mode='json')):
        raise HTTPException(409,'Request ID was already used for different content.')
    return prior


def revision(s,value):
    if s['revision']!=value:raise HTTPException(409,'Run changed. Refresh its context before recording this decision.')


def scoped(kind,key):return [p for p in store.records(kind) if p['run_id']==key]


@router.get('/runs/{key}/case')
def case(key:str):
    s=run_or_404(key)
    return {'run':core.summary(s),'investigation':studies.investigation(s),
            'proofs':[{'proof':p,'score':studies.score(p,s)} for p in scoped('twin_proof',key)],
            'plans':scoped('twin_plan',key),'work_orders':[{**w,'verification':studies.closure_check(s,w)} for w in scoped('twin_work',key)],
            'inspections':[r for r in store.records('mobile_inspection') if r['asset_id']==key]}


@router.post('/runs/{key}/proofs')
def freeze(key:str,payload:StudyRequest,actor=Depends(operator)):
    with WRITE_LOCK:
        s=run_or_404(key);identifier=key+'-proof-'+payload.request_id
        prior=existing('twin_proof',identifier,payload)
        if prior:return prior
        revision(s,payload.revision)
        try:p=studies.freeze(s,payload.horizon_min)
        except ValueError as e:raise HTTPException(422,str(e))
        p.update(id=identifier,created_at=now(),created_by=actor,request_digest=studies.digest(payload.model_dump(mode='json')))
        store.put('twin_proof',identifier,p);store.event(key,'forecast_frozen',{'id':identifier,'sha256':p['sha256'],'origin':p['origin'],'actor':actor})
        return p


@router.post('/runs/{key}/plans')
def plan(key:str,payload:StudyRequest,actor=Depends(operator)):
    with WRITE_LOCK:
        s=run_or_404(key);identifier=key+'-plan-'+payload.request_id
        prior=existing('twin_plan',identifier,payload)
        if prior:return prior
        revision(s,payload.revision)
        result=studies.plan(s,payload.horizon_min,payload.max_delay_min)
        if not result['available']:raise HTTPException(422,' '.join(result['holds']))
        result.update(id=identifier,created_at=now(),created_by=actor,inputs=deepcopy(s['inputs']),
                      request_digest=studies.digest(payload.model_dump(mode='json')),applied=False)
        store.put('twin_plan',identifier,result);store.event(key,'intervention_compared',{'id':identifier,'actor':actor})
        return result


@router.get('/runs/{key}/intervention-preview')
def intervention_preview(key:str, revision:int=Query(...,ge=0),
                         horizon_min:int=Query(60,ge=5,le=120), max_delay_min:int=Query(0,ge=0,le=20)):
    """Read a run snapshot and compare interventions without storing a plan or event."""
    s=deepcopy(run_or_404(key))
    if s['revision']!=revision:raise HTTPException(409,'Run changed. Refresh its context before previewing this intervention.')
    return {**studies.plan(s,horizon_min,max_delay_min),'preview':True}


class ApplyPlan(Contract):
    plan_id:str=Field(max_length=180)
    revision:int=Field(ge=0)


@router.post('/runs/{key}/apply-plan')
def apply(key:str,payload:ApplyPlan,actor=Depends(operator)):
    with WRITE_LOCK:
        s=deepcopy(run_or_404(key));p=store.get('twin_plan',payload.plan_id)
        if not p or p['run_id']!=key:raise HTTPException(404,'Plan is not attached to this run.')
        if p['applied']:return core.summary(s)
        revision(s,payload.revision);revision(s,p['origin_revision'])
        candidate=p['recommendation']
        if p.get('version')!=studies.VERSION:raise HTTPException(409,'Planning model changed. Compare a new intervention before applying.')
        if not candidate:raise HTTPException(422,'No candidate meets the declared planning constraints.')
        if candidate['delay_min']!=0:raise HTTPException(422,'Delayed candidates are advisory. Recalculate with zero maximum delay to apply immediately.')
        if studies.qualification(s):raise HTTPException(423,'Run is no longer eligible for an energised intervention.')
        checked=studies.plan(s,p['horizon_min'],0)['recommendation']
        if not checked or checked['reduction_pct']!=candidate['reduction_pct']:
            raise HTTPException(409,'The proposal no longer passes the current model. Recalculate.')
        before=s['inputs']['load_percent'];outcome=core.reduce_demand(s,candidate['reduction_pct'])
        if abs(outcome['loading_percent']-candidate['post_load_percent'])>1e-6:
            raise HTTPException(409,'Applied demand does not match the proposed outcome.')
        for field in ('max_phase_loading_percent','thermal_loading_percent','phase_imbalance_percent','neutral_current'):
            if 'post_'+field in candidate and abs(outcome[field]-candidate['post_'+field])>1e-6:
                raise HTTPException(409,'Applied phase state does not match the proposed outcome.')
        core.log(s,'intervention_applied','Operator applied a simulated demand reduction. No hardware command.',
                 plan_id=p['id'],before_load_percent=before,after_load_percent=s['inputs']['load_percent'],actor=actor)
        s['revision']+=1;core.evaluate(s,0);core.remember(s)
        p['applied']=True;p['applied_revision']=s['revision'];p['applied_elapsed_s']=s['elapsed_s']
        store.put('twin_plan',p['id'],p);store.put('twin_run',key,s)
        return core.summary(s)


class AcceptanceRules(Contract):
    stable_minutes:int=Field(10,ge=5,le=60)
    max_load_percent:float=Field(99,ge=0,lt=100)
    max_temperature_c:float=Field(110,ge=20,le=125)
    forecast_horizon_min:int=Field(240,ge=120,le=240)
    require_cooling_restored:bool=True


class WorkRequest(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    revision:int=Field(ge=0)
    title:str=Field(min_length=5,max_length=180)
    owner:str=Field(min_length=2,max_length=100)
    priority:Literal['routine','soon','urgent']='soon'
    due_sim_min:int=Field(30,ge=0,le=10080)
    acceptance:str=Field(min_length=15,max_length=1500)
    acceptance_rules:AcceptanceRules=Field(default_factory=AcceptanceRules)


class WorkUpdate(Contract):
    status:Literal['in_progress','verification_pending','stabilized','closed']
    note:str=Field(min_length=15,max_length=2000)
    revision:int=Field(ge=0)


@router.post('/runs/{key}/work')
def work(key:str,payload:WorkRequest,actor=Depends(operator)):
    with WRITE_LOCK:
        s=run_or_404(key);identifier=key+'-work-'+payload.request_id
        prior=existing('twin_work',identifier,payload)
        if prior:return prior
        revision(s,payload.revision)
        value={**payload.model_dump(exclude={'request_id','revision'}),'id':identifier,'run_id':key,'source':'industrial',
               'origin_revision':s['revision'],'origin_elapsed_s':s['elapsed_s'],'origin':deepcopy(s['telemetry']),
               'due_elapsed_s':s['elapsed_s']+payload.due_sim_min*60,'created_at':now(),'created_by':actor,
               'status':'open','revision':0,'trail':[],'request_digest':studies.digest(payload.model_dump(mode='json'))}
        store.put('twin_work',identifier,value);store.event(key,'work_created',{'id':identifier,'actor':actor})
        return value


@router.post('/runs/{key}/work/{identifier}')
def update_work(key:str,identifier:str,payload:WorkUpdate,actor=Depends(operator)):
    with WRITE_LOCK:
        s=run_or_404(key);w=store.get('twin_work',identifier)
        if not w or w['run_id']!=key:raise HTTPException(404,'Work order is not attached to this run.')
        revision(w,payload.revision)
        allowed={'open':{'in_progress'},'in_progress':{'verification_pending'},'verification_pending':{'closed','stabilized'},'stabilized':{'verification_pending'}}
        if payload.status not in allowed.get(w['status'],set()):raise HTTPException(422,'Complete investigation, action and follow-up verification in order.')
        if payload.status=='closed':
            started=w['trail'][-1]['elapsed_s']
            if s['elapsed_s']<=started:raise HTTPException(422,'Advance the run and inspect later evidence before closing.')
            verification=studies.closure_check(s,w)
            if not verification['eligible']:raise HTTPException(423,' '.join(verification['holds']))
            w['closure_evidence']=verification
        w['status']=payload.status;w['revision']+=1
        w['trail'].append({'status':payload.status,'note':payload.note,'actor':actor,'elapsed_s':s['elapsed_s'],
                           'telemetry':deepcopy(s['telemetry']),'recorded_at':now()})
        store.put('twin_work',identifier,w);store.event(key,'work_updated',{'id':identifier,'status':w['status'],'actor':actor})
        return w


@router.get('/validation')
def validation():
    path=Path(__file__).resolve().parents[1]/'reports'/'submission-benchmark.json'
    if not path.exists():return {'available':False,'note':'Run scripts/benchmark_submission.py to generate the reproducible evaluation.'}
    result={'available':True,**json.loads(path.read_text(encoding='utf-8'))}
    pipeline=path.with_name('pipeline-benchmark.json')
    if pipeline.exists():
        result['pipeline']=json.loads(pipeline.read_text(encoding='utf-8'))
        import hashlib
        root=path.parents[1]
        result['pipeline']['source_matches']=all((root/n).exists() and hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in result['pipeline']['source_sha256'].items())
    release=next((v for v in ('v8','v7','v6','v5') if (path.parent/f'pipeline-{v}-fresh-protocol-run'/'manifest.json').exists()),'v5')
    fresh=path.parent/f'pipeline-{release}-fresh-protocol-run'/'benchmark.json'
    manifest=fresh.with_name('manifest.json')
    protocol=path.parent/f'pipeline-{release}-fresh-protocol.json'
    if fresh.exists() and manifest.exists() and protocol.exists():
        import hashlib
        proof=json.loads(manifest.read_text(encoding='utf-8'))
        frozen=json.loads(protocol.read_text(encoding='utf-8'))
        report=json.loads(fresh.read_text(encoding='utf-8'))
        claim_path=protocol.with_name(protocol.stem+'-claim.json')
        claim=json.loads(claim_path.read_text(encoding='utf-8')) if claim_path.is_file() else {}
        root=path.parents[1]
        result['fresh_evaluation']={**report,
            'source_matches':all((root/n).is_file() and hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in report['source_sha256'].items()),
            'artifact_integrity':proof.get('status')=='complete' and studies.digest({k:v for k,v in proof.items() if k!='sha256'})==proof.get('sha256')
                and studies.digest({k:v for k,v in frozen.items() if k!='sha256'})==frozen.get('sha256')
                and proof.get('protocol_sha256')==frozen.get('sha256')
                and claim.get('protocol_sha256')==frozen.get('sha256')
                and claim.get('run_id')==proof.get('run_id')
                and report.get('protocol_binding',{}).get('sha256')==frozen.get('sha256')
                and report.get('protocol_binding',{}).get('run_id')==proof.get('run_id')
                and report.get('source_sha256')==frozen.get('source_sha256')
                and set(proof.get('files',{}))=={'benchmark.json','forecasts.csv','decisions.csv'}
                and all((fresh.parent/n).is_file() and hashlib.sha256((fresh.parent/n).read_bytes()).hexdigest()==v
                        for n,v in proof.get('files',{}).items()),
            'proof':{'run_id':proof.get('run_id'),'protocol_sha256':proof.get('protocol_sha256'),
                     'started_at':proof.get('started_at'),'completed_at':proof.get('completed_at'),
                     'note':'Locally frozen synthetic evaluation; not external data or field validation. Results are now known.'}}
    return result


class ReferenceRequest(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    name:str=Field(min_length=3,max_length=120)
    reviewer:str=Field(min_length=3,max_length=120)
    source:Literal['synthetic','recorded_oil_reference']
    healthy_reviewed:Literal[True]
    temperature_kind:Literal['oil']
    csv_text:str=Field(min_length=80,max_length=1000000)
    core_fraction:float=Field(1000/7500,ge=0,lt=1)


@router.get('/references')
def references():return [{k:v for k,v in p.items() if k!='rows'} for p in store.records('twin_reference')]


@router.post('/references')
def fit_reference(payload:ReferenceRequest,actor=Depends(operator)):
    with WRITE_LOCK:
        identifier='OIL-REF-'+payload.request_id;prior=existing('twin_reference',identifier,payload)
        if prior:return {k:v for k,v in prior.items() if k!='rows'}
        try:
            reader=csv.DictReader(io.StringIO(payload.csv_text))
            fields=reader.fieldnames or []
            required={'elapsed_s','oil_c','ambient_c','load_percent'}
            if len(set(fields))!=len(fields) or set(fields) not in (required,required|{'voltage_pu'}):
                raise ValueError('CSV needs elapsed_s, oil_c, ambient_c, load_percent; voltage_pu is optional but must be complete if declared. Do not upload surface readings as oil.')
            rows=[]
            for row in reader:
                if len(rows)>=5000:raise ValueError('Reference limit is 5,000 rows.')
                rows.append({k:float(v) for k,v in row.items()})
            result=thermal_reference.fit(rows,payload.core_fraction)
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e))
        value={'id':identifier,'name':payload.name,'source':payload.source,'reviewer':payload.reviewer,
               'fit':result,'rows':rows,'data_sha256':studies.digest(rows),'created_by':actor,'created_at':now(),
               'request_digest':studies.digest(payload.model_dump(mode='json')),
               'eligible':result['identified'] and result['beats_persistence']}
        store.put('twin_reference',identifier,value)
        return {k:v for k,v in value.items() if k!='rows'}


class ReferenceRun(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')


@router.post('/references/{identifier}/run')
def reference_run(identifier:str,payload:ReferenceRun,actor=Depends(operator)):
    from .twin_api import new_run,NewRun,AssetProfile
    p=store.get('twin_reference',identifier)
    if not p:raise HTTPException(404,'Reference not found.')
    if not p['eligible']:raise HTTPException(422,'Reference has not passed identifiability and held-out baseline checks. It cannot initialize a run.')
    fit=p['fit'];fraction=fit['core_fraction'];total_loss=7500
    settings=core.Settings(rated_oil_rise_c=fit['rated_oil_rise_c'],oil_tau_min=fit['oil_tau_min'],
                           core_loss_w=total_loss*fraction,copper_loss_w=total_loss*(1-fraction))
    profile=AssetProfile(name=p['name'],basis='synthetic_reference' if p['source']=='synthetic' else 'lab_reference',
                         reviewer=p['reviewer'],reference=f"{identifier}; oil parameters only. Ratings, winding model and absolute losses remain illustrative. Data SHA256 {p['data_sha256']}")
    return new_run(NewRun(request_id=payload.request_id,settings=settings,profile=profile),actor)
