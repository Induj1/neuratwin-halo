"""Local-first Halo API: physical bench, replay, commissioning and shared evidence."""
import base64
import asyncio
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import uuid
from urllib.parse import urlparse
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import Field, ValidationError
from .halo_contracts import Contract, Frame, BenchConfig, Calibration, RelayRequest, Observation
from . import halo_store as store, halo_engine as engine, halo_ai as ai, halo_workflow as workflow
from .storage import database, now
from . import cloud, auth

router=APIRouter(prefix='/api/halo')
LOCAL_TOKEN=secrets.token_urlsafe(32)
MOBILE_DEMO_TOKEN=secrets.token_urlsafe(32)
WRITE_LOCK=threading.RLock()
ANALYSIS_LEASE_SECONDS=120
ANALYSIS_BACKOFF_SECONDS=2
ANALYSIS_MAX_BACKOFF_SECONDS=60


def mobile_demo_enabled():
    return (os.getenv('HALO_MOBILE_DEMO')=='1' and os.getenv('HALO_ALLOW_CONTROL')!='1'
            and (not cloud.enabled() or os.getenv('HALO_LOCAL_OPERATOR')=='1'))


def mobile_demo_identity(request):
    supplied=request.headers.get('authorization','').removeprefix('Bearer ').strip()
    if not supplied or not hmac.compare_digest(supplied,MOBILE_DEMO_TOKEN) or not mobile_demo_enabled():
        return None
    path=request.url.path
    allowed=(path.startswith('/api/halo/mobile/') or path=='/api/halo/twin/runs'
             or path.startswith('/api/halo/twin/runs/')
             or (request.method in ('GET','HEAD') and path in ('/api/halo/twin/catalog','/api/halo/twin/prototype')))
    if not allowed: raise HTTPException(403,'This demo session cannot change hardware or configuration.')
    return {'user_id':'hackathon-demo','email':None,'role':'operator','mode':'mobile demo'}


def local_request(request):
    origin=request.headers.get('origin')
    host=request.url.hostname
    return request.client and request.client.host in ('127.0.0.1','::1','testclient') and host in ('127.0.0.1','localhost','::1','testserver') and (not origin or urlparse(origin).netloc==request.url.netloc)


def operator(request:Request):
    if cloud.enabled():
        user=auth.identity(request,"operator")
        return "user:"+user["user_id"]
    expected=os.getenv('HALO_OPERATOR_TOKEN') or LOCAL_TOKEN
    supplied=request.headers.get('authorization','').removeprefix('Bearer ')
    if mobile_demo_identity(request): return 'hackathon demo'
    if not supplied or not hmac.compare_digest(supplied,expected):
        raise HTTPException(401,'Operator authentication required. An asset tag is not a credential.')
    if not os.getenv('HALO_OPERATOR_TOKEN') and not local_request(request):
        raise HTTPException(403,'Remote writes require a configured operator token and HTTPS.')
    return 'authenticated operator'


def device(request:Request):
    expected=os.getenv('HALO_DEVICE_TOKEN','')
    supplied=request.headers.get('authorization','').removeprefix('Bearer ')
    if not expected or not supplied or not hmac.compare_digest(expected,supplied):
        raise HTTPException(401,'Configured device token required.')
    return 'device bridge'


@router.get('/session')
def session(request:Request):
    if cloud.enabled() and request.cookies.get(auth.ACCESS):
        return {'local':False,'token':None}
    if os.getenv('HALO_OPERATOR_TOKEN') or not local_request(request) or (cloud.enabled() and os.getenv('HALO_LOCAL_OPERATOR')!='1'):
        return {'local':False,'token':None}
    response=Response(json.dumps({'local':True,'token':LOCAL_TOKEN}),media_type='application/json',headers={'Cache-Control':'no-store'})
    if cloud.enabled(): response.set_cookie(auth.LOCAL,LOCAL_TOKEN,httponly=True,samesite='strict',secure=request.url.scheme=='https',path='/api',max_age=10800)
    return response


@router.get('/status')
def status():
    return {'storage_backend':'supabase' if cloud.enabled() else 'sqlite','version':'2.1.0','local_model_enabled':os.getenv('HALO_AI_ENABLED')=='1',
            'local_model':'convaiinnovations/laya','public_url':os.getenv('HALO_PUBLIC_URL'),
            'telegram_configured':bool(os.getenv('HALO_TELEGRAM_BOT_TOKEN') and os.getenv('HALO_TELEGRAM_ALLOWED_CHAT_IDS')),
            'device_token_configured':bool(os.getenv('HALO_DEVICE_TOKEN')),
            'esp32_configured':bool(os.getenv('HALO_ESP32_URL')),
            'hardware_control_enabled':os.getenv('HALO_ALLOW_CONTROL')=='1',
            'k4_physical_control':False,'holds':engine.holds(engine.config()),'hardware_ingestion':hardware_readiness(),
            'optional_extensions':{'AR':'not commissioned','vibration':'not installed','oil_level':'not installed','network_transfer':'no verified network model'}}


def hardware_readiness():
    if not cloud.enabled():return {'ready':True,'durable_analysis':True,'backend':'sqlite'}
    try:
        result=cloud.rpc('halo_hardware_health',{})
        if result.get('durable_analysis') is True:return {'ready':True,**result}
    except HTTPException:pass
    return {'ready':False,'durable_analysis':False,'reason':'Hardware ingestion is blocked until migration 202610080004 is applied and its pending-analysis trigger is enabled.'}


@router.get('/analysis-recovery')
def analysis_recovery_status(request:Request,actor=Depends(operator)):
    worker=getattr(request.app.state,'analysis_worker',None)
    try:queue=store.analysis_queue_sample();queue_available=True
    except Exception:queue=[];queue_available=False
    return {'worker':worker.snapshot() if worker else {'status':'not_started','hardware_commands_allowed':False},
            'queue_available':queue_available,'oldest_unfinished_sample':queue,'sample_limit':8,
            'note':'Bounded queue sample, not total backlog. Recovery never sends hardware commands.'}


@router.get('/config')
def get_config():
    c=engine.config();key=engine.config_identity(c)
    bound,_=engine.recorded_config({'config_id':key,'device_id':c.device_id})
    return {'config':c.model_dump(),'config_id':key if bound else None,'holds':engine.holds(c)}


@router.put('/config')
def set_config(payload:BenchConfig,actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        old=engine.config()
        for version in (old,payload):
            key=engine.config_identity(version)
            if not store.get('config_version',key):
                store.create_unique('config_version',key,{'id':key,'config':version.model_dump(),'at':now(),'actor':actor,
                    'meaning':'Reviewed server configuration; not independent verification of device wiring.'})
        store.put('config','bench',payload.model_dump())
        store.event('BENCH-001','commissioning_updated',{'actor':actor,'config_id':engine.config_identity(payload),'holds':engine.holds(payload)})
    return get_config()


@router.post('/calibrations')
def calibrate(payload:Calibration,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        if store.get('calibration',payload.id): raise HTTPException(409,'Calibration IDs are immutable; create a new version.')
        result={**payload.model_dump(),'created_at':now(),'actor':actor}
        store.put('calibration',payload.id,result); store.put('active_calibration','bench',result)
        store.event('BENCH-001','calibration_recorded',{'id':payload.id,'reviewer':payload.reviewer})
    return result


@router.get('/calibrations')
def calibrations():
    return {'active':store.get('active_calibration','bench'),'versions':store.records('calibration')}


@router.get('/device/config')
def device_config(actor=Depends(device)):
    return {**get_config(),'calibration':store.get('active_calibration','bench'),
            'control_enabled':os.getenv('HALO_ALLOW_CONTROL')=='1','ambient':store.get('ambient','bench')}


class DeviceLink(Contract):
    device_id:str=Field(pattern=r'^[\w-]{1,48}$')
    boot_id:str=Field(pattern=r'^[\w-]{1,64}$')
    chip:str=Field(min_length=1,max_length=60)
    protocol:int=Field(ge=0,le=100)
    compatible:bool
    permit:bool
    pending_frames:int=Field(ge=0)


@router.post('/device/link')
def device_link(payload:DeviceLink,actor=Depends(device)):
    if payload.device_id!=engine.config().device_id:raise HTTPException(409,'Bridge device does not match the configured asset.')
    row={**payload.model_dump(),'received_at':now(),'meaning':'Bridge-reported status only; not contact feedback or commissioning approval.'}
    store.put('device_link',payload.device_id,row);return {'accepted':True}


class Ambient(Contract):
    value_c:float=Field(ge=-30,le=80)
    observed_at:datetime
    reference:str=Field(min_length=5,max_length=200)
    reviewer:str=Field(min_length=2,max_length=100)


@router.post('/ambient')
def ambient_reference(payload:Ambient,actor=Depends(operator)):
    if payload.observed_at.utcoffset() is None or not 0<=(datetime.now(timezone.utc)-payload.observed_at).total_seconds()<=600:
        raise HTTPException(422,'Record an actual ambient observation from the last 10 minutes, including its timezone.')
    row=payload.model_dump(mode='json');row['recorded_at']=now();row['actor']=actor
    store.put('ambient','bench',row);store.event('BENCH-001','manual_ambient',row)
    return {**row,'valid_for_seconds':600,'note':'Manual reference, not an installed sensor. Expires 10 minutes after observation.'}


@router.post('/telemetry')
def ingest(payload:Frame,actor=Depends(device)):
    # Keep admission and the immediate analysis attempt together within this
    # process; durable DB claims also protect separate application processes.
    with WRITE_LOCK:return _ingest(payload,actor)


def _ingest(payload,actor):
    c=engine.config()
    content=payload.model_dump(mode="json")
    for optional in ('primary_current_a','config_id'):
        if content.get(optional) is None: content.pop(optional,None)
    if content.get('hardware_config_status')=='unverified':content.pop('hardware_config_status',None)
    if payload.device_id!=c.device_id: raise HTTPException(409,'Device identity does not match the commissioned asset.')
    if payload.timestamp>datetime.now(timezone.utc)+timedelta(seconds=5):
        raise HTTPException(422,'Future acquisition timestamp rejected.')
    if payload.calibration_id and not store.get('calibration',payload.calibration_id):
        raise HTTPException(422,'Unknown calibration version.')
    if payload.config_id and engine.recorded_config(content)[0] is None:
        raise HTTPException(422,'Unknown, modified or mismatched acquisition configuration.')
    if cloud.enabled():
        try: readiness=cloud.rpc('halo_hardware_health',{})
        except HTTPException:
            raise HTTPException(503,'Hardware ingestion requires migration 202610080004; no frame accepted.')
        if not isinstance(readiness,dict) or readiness.get('durable_analysis') is not True:
            raise HTTPException(503,'Durable hardware analysis is unavailable; no frame accepted.')
        result=cloud.rpc('halo_ingest_frame',{'p_frame':content})
        if result.get('duplicate'):
            with store.independent_transaction():
                key=analysis_identity(content)
                if not store.get('analysis_job',key):
                    store.put('analysis_job',key,{'id':key,'frame':content,'status':'pending','created_at':now(),
                        'config_id':content.get('config_id'),'admission':'legacy retry'})
        analyse_acquisition(analysis_identity(content),allow_control=True)
        return result
    with WRITE_LOCK, store.transaction() as db:
        duplicate=db.execute('SELECT content FROM halo_frames WHERE device_id=? AND boot_id=? AND sequence=?',
                             (payload.device_id,payload.boot_id,payload.sequence)).fetchone()
        if duplicate:
            prior_content=json.loads(duplicate['content'])
            for optional in ('primary_current_a','config_id'):
                if prior_content.get(optional) is None:prior_content.pop(optional,None)
            if prior_content.get('hardware_config_status')=='unverified':prior_content.pop('hardware_config_status',None)
            if prior_content!=content:
                raise HTTPException(409,'Sequence reused with different content.')
        previous=db.execute('SELECT content FROM halo_frames WHERE device_id=? AND boot_id=? ORDER BY sequence DESC LIMIT 1',
                            (payload.device_id,payload.boot_id)).fetchone()
        if previous and not duplicate:
            p=json.loads(previous['content'])
            if payload.sequence<=p['sequence'] or payload.uptime_ms<=p['uptime_ms'] or payload.timestamp<=engine.timestamp(p['timestamp']):
                raise HTTPException(409,'Out-of-order telemetry rejected; do not rewrite acquisition time on retry.')
        latest=db.execute('SELECT timestamp FROM halo_frames WHERE device_id=? ORDER BY id DESC LIMIT 1',(payload.device_id,)).fetchone()
        if latest and not duplicate and payload.timestamp<=engine.timestamp(latest['timestamp']):
            raise HTTPException(409,'Old boot/session data cannot overwrite the live state.')
        if not duplicate:
            db.execute('INSERT INTO halo_frames(device_id,boot_id,sequence,timestamp,received_at,content) VALUES (?,?,?,?,?,?)',
                       (payload.device_id,payload.boot_id,payload.sequence,payload.timestamp.isoformat(),now(),json.dumps(content,allow_nan=False)))
        key=analysis_identity(content)
        if not store.get('analysis_job',key):
            store.put('analysis_job',key,{'id':key,'frame':content,'status':'pending','created_at':now(),
                'config_id':content.get('config_id'),'admission':'legacy retry' if duplicate else 'atomic acquisition'})
    analyse_acquisition(key,allow_control=True)
    return {'accepted':True,'duplicate':bool(duplicate),'sequence':payload.sequence}


def analysis_identity(frame):
    return f"analysis:{frame['device_id']}/{frame['boot_id']}/{frame['sequence']}"


def analyse_acquisition(key,*,allow_control=False):
    """Durable claim plus fenced atomic result commit, including across workers."""
    from .twin_api import process_prototype
    claimed=claim_analysis(key)
    if not claimed.get('_claimed'):return claimed
    token=claimed['claim_token']
    try:
        with WRITE_LOCK,store.independent_transaction():
            job=store.get('analysis_job',key)
            if not owns_claim(job,token):raise AnalysisLeaseLost()
            result=process_prototype(Frame.model_validate(job['frame']),allow_control=allow_control)
            if not owns_claim(job,token):raise AnalysisLeaseLost()
            job.update(status=result.get('status','complete'),completed_at=now(),result=result)
            for field in ('claim_token','lease_until','next_attempt_at','last_error_code'):job.pop(field,None)
            store.put('analysis_job',key,job)
        return {**job,'_claimed':True}
    except Exception as error:
        try:record_analysis_failure(key,token,error)
        except Exception:pass  # A durable processing lease remains reclaimable after expiry.
        raise


class AnalysisLeaseLost(RuntimeError):
    """No derived state may commit after ownership expires or moves."""


def owns_claim(job,token):
    return bool(job and job.get('status')=='processing' and job.get('claim_token')==token and
                job.get('lease_until') and engine.timestamp(job['lease_until'])>datetime.now(timezone.utc))


def claim_analysis(key):
    with WRITE_LOCK,store.independent_transaction():
        job=store.get('analysis_job',key)
        if not job:raise HTTPException(503,'Accepted frame lacks durable analysis record; recovery required.')
        stamp=datetime.now(timezone.utc)
        if job['status']=='processing':
            ready=not job.get('lease_until') or engine.timestamp(job['lease_until'])<=stamp
        else:
            ready=job['status']=='pending' and (not job.get('next_attempt_at') or engine.timestamp(job['next_attempt_at'])<=stamp)
        if not ready:return {**job,'_claimed':False}
        job.update(status='processing',claim_token=uuid.uuid4().hex,
                   lease_until=(stamp+timedelta(seconds=ANALYSIS_LEASE_SECONDS)).isoformat(),
                   last_attempt_at=stamp.isoformat(),attempts=int(job.get('attempts',0))+1)
        store.put('analysis_job',key,job)
    return {**job,'_claimed':True}


def record_analysis_failure(key,token,error):
    with WRITE_LOCK,store.independent_transaction():
        job=store.get('analysis_job',key)
        if not job or job.get('claim_token')!=token or job.get('status')!='processing':return
        attempts=max(1,int(job.get('attempts',1)))
        delay=min(ANALYSIS_MAX_BACKOFF_SECONDS,ANALYSIS_BACKOFF_SECONDS*2**min(attempts-1,10))
        code='lease_lost' if isinstance(error,AnalysisLeaseLost) else 'record_conflict' if isinstance(error,HTTPException) and error.status_code==409 else 'analysis_failed'
        job.update(status='pending',last_error_code=code,
                   next_attempt_at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat())
        job.pop('claim_token',None);job.pop('lease_until',None)
        store.put('analysis_job',key,job)


def recover_pending_analyses(limit=25,stop_event=None):
    """One bounded oldest-due-first pass. Recovery never allows physical commands."""
    limit=max(1,min(int(limit),100))
    recovered=failed=skipped=attempted=0
    storage_failed=False
    pending=store.due_analysis_jobs(now(),limit)
    for job in pending:
        if stop_event is not None and stop_event.is_set():break
        try:
            result=analyse_acquisition(job['id'],allow_control=False)
            if result.get('_claimed'):recovered+=1
            else:skipped+=1
        except Exception as error:
            failed+=1
            storage_failed=(isinstance(error,HTTPException) and error.status_code in (429,503)) or isinstance(error,sqlite3.DatabaseError)
        attempted+=1
        if storage_failed:break  # Reads may work while durable claim/result writes do not.
    return {'recovered':recovered,'failed':failed,'skipped':skipped,'attempted':attempted,
            'remaining':None,'more_due_possible':len(pending)>=limit,'storage_failed':storage_failed,
            'hardware_commands_allowed':False}


class AnalysisRecoveryWorker:
    """Lifecycle-owned bounded polling. Stop waits for the current job, not a batch."""
    def __init__(self,*,batch_size=25,poll_seconds=2,max_storage_backoff=60):
        self.batch_size=max(1,min(int(batch_size),100));self.poll_seconds=max(.01,float(poll_seconds))
        self.max_storage_backoff=max(self.poll_seconds,float(max_storage_backoff))
        self.stop_event=threading.Event();self.wake=asyncio.Event();self.task=None
        self.state={'status':'starting','running':False,'cycles':0,'recovered':0,'failed':0,'skipped':0,
                    'attempted':0,'storage_failures':0,'consecutive_storage_failures':0,
                    'batch_size':self.batch_size,'poll_seconds':self.poll_seconds,'hardware_commands_allowed':False}

    def snapshot(self):return deepcopy(self.state)

    async def cycle(self,limit=None):
        from starlette.concurrency import run_in_threadpool
        self.state.update(last_cycle_started_at=now(),status='processing',running=True)
        try:
            result=await run_in_threadpool(recover_pending_analyses,limit or self.batch_size,self.stop_event)
            for key in ('recovered','failed','skipped','attempted'):self.state[key]+=result[key]
            self.state['last_result']=result
            if result['storage_failed']:raise RuntimeError('Durable queue write unavailable.')
            self.state.update(status='retrying' if result['failed'] else 'idle',last_success_at=now(),
                consecutive_storage_failures=0,last_error_code=None)
            delay=.05 if result['more_due_possible'] else self.poll_seconds
        except Exception:
            failures=self.state['consecutive_storage_failures']+1
            self.state.update(status='storage_unavailable',storage_failures=self.state['storage_failures']+1,
                              consecutive_storage_failures=failures,last_error_code='queue_unavailable')
            delay=min(self.max_storage_backoff,self.poll_seconds*2**min(failures-1,10))
        self.state.update(cycles=self.state['cycles']+1,last_cycle_finished_at=now(),
                          next_poll_at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat())
        return delay

    async def start(self):
        # A single bootstrap attempt preserves startup diagnostics without a
        # large backlog delaying service readiness. Remaining jobs drain in background.
        delay=await self.cycle(limit=1)
        self.task=asyncio.create_task(self.run(delay),name='halo-analysis-recovery')
        return self

    async def run(self,delay):
        try:
            while not self.stop_event.is_set():
                try:await asyncio.wait_for(self.wake.wait(),timeout=delay)
                except asyncio.TimeoutError:pass
                if self.stop_event.is_set():break
                delay=await self.cycle()
        finally:self.state.update(status='stopped',running=False,next_poll_at=None)

    async def stop(self):
        self.stop_event.set();self.wake.set()
        if self.task is not None:await self.task
        self.state.update(status='stopped',running=False,next_poll_at=None)


def transformer_snapshot(scenario,cursor,dataset_id=None):
    from .app import packet
    original=packet('NR-104',scenario,cursor,20,10,dataset_id)
    c=original['current']; source='replayed' if dataset_id else 'simulated'
    case=hashlib.sha256((dataset_id or 'simulation:'+scenario).encode()).hexdigest()[:10]
    evidence=[{'id':f'DT-{case}-{c["timestamp"]}:{key}','channel':key,'value':c.get(key),'unit':unit,
               'timestamp':c['timestamp'],'source':source if key in ('oil_c','load_pu','ambient_c') else 'inferred',
               'available':c.get(key) is not None,'calibrated':False}
              for key,unit in [('oil_c','°C oil'),('estimated_hotspot_c','°C estimate'),('load_pu','pu'),('ambient_c','°C ambient')]]
    return {'asset_id':'DT-REPLAY-'+dataset_id if dataset_id else 'DT-SIM','name':'Distribution transformer • model study','source':source,
            'connection':'replay','clock':'Recorded timestamps · imported CSV' if dataset_id else '5 minutes per replay frame','age_s':None,'current':c,'history':original['history'],
            'alerts':original['alerts'],'status':original['status'],'evidence':evidence,
            'metrics':{'load_pct':c['load_pu']*100 if c['load_pu'] is not None else None,'condition_index':c['condition_index'],
                       'surface_margin_c':None,'apparent_va':None},
            'quality':{'freshness':'replay','coverage':sum(e['available'] for e in evidence),'total_channels':len(evidence),
                       'calibration':source,'agreement':c['confidence'],'model_validity':'synthetic calibration; unvalidated hot-spot'},
            'holds':[],'limits':{'surface_c':None,'current_a':None},'model':None,
            'notes':original['limitations']+[original['index_note']],'transformer':original}


def obtain(mode='bench',scenario='normal',cursor=180,dataset_id=None):
    if mode=='transformer': return transformer_snapshot(scenario,cursor,dataset_id)
    if mode=='replay':
        if dataset_id:
            data=store.get('bench_dataset',dataset_id)
            if not data: raise HTTPException(404,'Bench replay not found.')
            result=engine.snapshot(data['rows'][:max(2,cursor+1)],'replayed','REPLAY-'+dataset_id)
            result['name']=data['name']+' • imported recording'
            return result
        try: return engine.snapshot(engine.demonstration(scenario,cursor),'simulated','BENCH-SIM')
        except ValueError as e: raise HTTPException(422,str(e))
    c=engine.config()
    return engine.snapshot(store.frames(c.device_id),c=c)


@router.get('/replay-history')
def replay_history(scenario:str='normal',dataset_id:str|None=None):
    """Chart-only replay samples; never reads the physical bench or blind cases."""
    if dataset_id:
        data=store.get('bench_dataset',dataset_id)
        if not data: raise HTTPException(404,'Bench replay not found.')
        rows=data['rows']
    else:
        try: rows=engine.demonstration(scenario,720)
        except ValueError as e: raise HTTPException(422,str(e))
    return {'rows':[{key:row.get(key) for key in ('timestamp','surface_c','ambient_c')} for row in rows]}


@router.get('/snapshot')
def get_snapshot(mode:Literal['bench','replay','transformer']='bench',scenario:str='normal',cursor:int=Query(180,ge=1,le=20000),dataset_id:str|None=None):
    result=obtain(mode,scenario,cursor,dataset_id)
    result['assessment']=store.get('assessment_latest',result['asset_id'])
    prior=result['assessment']
    if prior:
        old=prior['evidence_snapshot']
        old_prefix=old['evidence'][0]['id'].rsplit('-',1)[0]
        new_prefix=result['evidence'][0]['id'].rsplit('-',1)[0]
        if old_prefix!=new_prefix or old['quality']['freshness']!=result['quality']['freshness'] or {a['code'] for a in old['numerical_alerts']}!={a['code'] for a in result['alerts']}:
            result['assessment']=None
    result['incidents']=[r for r in store.records('incident') if r['asset_id']==result['asset_id']]
    result['events']=store.events(result['asset_id'])
    return result


class Context(Contract):
    mode:Literal['bench','replay','transformer']='bench'
    scenario:str='normal'
    cursor:int=Field(default=180,ge=1,le=20000)
    dataset_id:str|None=None


@router.post('/assess')
def assess(payload:Context,actor=Depends(operator)):
    snap=obtain(**payload.model_dump())
    observations=[o for i in store.records('incident') if i['asset_id']==snap['asset_id'] for o in i['observations']]
    return ai.assess(snap,observations)


class Question(Context):
    question:str=Field(min_length=1,max_length=1000)


@router.post('/assistant')
def assistant(payload:Question,actor=Depends(operator)):
    snap=obtain(**payload.model_dump(exclude={'question'}))
    observations=[o for i in store.records('incident') if i['asset_id']==snap['asset_id'] for o in i['observations']]
    decision=ai.assess(snap,observations)
    return ai.answer(payload.question,snap,decision)


def pending_commands():
    out=[]
    for cmd in store.records('command'):
        if cmd['status']=='pending':
            if engine.timestamp(cmd['expires_at'])<=datetime.now(timezone.utc):
                cmd['status']='expired';store.put('command',cmd['id'],cmd)
            else: out.append(cmd)
    return sorted(out,key=lambda c:c['created_at'])


@router.post('/relays')
def relay_command(payload:RelayRequest,actor=Depends(operator)):
    with WRITE_LOCK:
        prior=store.get('command',payload.request_id)
        if prior:
            if prior['states']!=list(payload.states): raise HTTPException(409,'Request ID reused with a different command.')
            return prior
        enabling=any(payload.states)
        snap=obtain();c=engine.config()
        if payload.states[3]: raise HTTPException(403,'K4 is locked in physical mode. Use a labelled overload simulation.')
        if enabling:
            if snap.get('configuration_binding',{}).get('state')!='bound' or (snap.get('current') or {}).get('config_id')!=engine.config_identity(c):
                raise HTTPException(423,'Latest acquisition must reference the current immutable configuration before enabling a load.')
            if store.get('twin_prototype','BENCH-001',{}).get('latched'):
                raise HTTPException(423,'Protection decision is latched. Investigate and reset the latch before requesting load ON.')
            if os.getenv('HALO_ALLOW_CONTROL')!='1' or engine.holds(c): raise HTTPException(423,'Physical control is locked pending commissioning and explicit local enablement.')
            if snap['connection']!='live' or snap['quality']['calibration']!='reference recorded': raise HTTPException(423,'Fresh calibrated telemetry is required.')
            row=snap['current']
            if row.get('hardware_config_status')!='reported_match':raise HTTPException(423,'Firmware configuration report must match the reviewed server configuration before enabling loads.')
            if not row.get('relay_output_configured'): raise HTTPException(423,'Firmware has not confirmed relay-output configuration.')
            if row['quality_flags'] or any(row.get(k) is None for k in ('secondary_v','current_a','surface_c')):
                raise HTTPException(423,'Required sensor channels are invalid.')
            if row['surface_c']>=c.surface_limit_c or row['current_a']>c.current_limit_a:
                raise HTTPException(423,'Configured operating limit is exceeded; only all-off is permitted.')
            projected=sum(row['secondary_v']/r for on,r in zip(payload.states,c.resistor_ohms) if on)
            if projected>c.current_limit_a: raise HTTPException(423,'Requested resistor branches exceed the configured current limit.')
        for pending in pending_commands():
            pending['status']='superseded'; store.put('command',pending['id'],pending)
        row={'id':payload.request_id,'states':list(payload.states),'status':'pending','created_at':now(),
             'expires_at':(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat(),'actor':actor,'device_id':c.device_id,'config_id':engine.config_identity(c)}
        store.put('command',row['id'],row); store.event('BENCH-001','relay_requested',row)
        return row


@router.get('/commands')
def commands():
    pending_commands()
    return {'commands':store.records('command')[:20]}


@router.get('/device/commands')
def device_commands(actor=Depends(device)):
    # Re-check authority at delivery time, not just at creation time.
    pending=pending_commands(); allowed=[]
    for cmd in pending:
        snap=obtain();c=engine.config();r=snap.get('current') or {}
        valid=(snap.get('configuration_binding',{}).get('state')=='bound' and r.get('config_id')==engine.config_identity(c) and cmd.get('config_id')==engine.config_identity(c) and r.get('hardware_config_status')=='reported_match' and
               r.get('relay_output_configured') and not r.get('quality_flags') and all(r.get(k) is not None for k in ('secondary_v','current_a','surface_c')))
        if valid and c.current_limit_a and c.surface_limit_c:
            valid=r['current_a']<=c.current_limit_a and r['surface_c']<c.surface_limit_c and sum(r['secondary_v']/ohm for on,ohm in zip(cmd['states'],c.resistor_ohms) if on)<=c.current_limit_a
        if any(cmd['states']) and (store.get('twin_prototype','BENCH-001',{}).get('latched') or os.getenv('HALO_ALLOW_CONTROL')!='1' or engine.holds(c) or snap['connection']!='live' or snap['quality']['calibration']!='reference recorded' or not valid):
            cmd['status']='cancelled';store.put('command',cmd['id'],cmd)
        else: allowed.append(cmd)
    return {'commands':allowed}


class Ack(Contract):
    states:tuple[bool,bool,bool,bool]
    accepted:bool
    reason:str=Field(default='',max_length=300)


@router.post('/device/commands/{command_id}/ack')
def acknowledge_command(command_id:str,payload:Ack,actor=Depends(device)):
    with WRITE_LOCK:
        pending_commands(); cmd=store.get('command',command_id)
        if not cmd: raise HTTPException(404,'Command not found.')
        if cmd['status']!='pending': raise HTTPException(409,'Command is no longer pending.')
        cmd['status']='acknowledged' if payload.accepted and list(payload.states)==cmd['states'] else 'rejected'
        cmd['reported_states']=list(payload.states);cmd['reason']=payload.reason;cmd['acknowledged_at']=now()
        store.put('command',cmd['id'],cmd);store.event('BENCH-001','relay_acknowledged',cmd)
        return cmd


class Compare(Context):
    reduction:float=Field(default=25,ge=0,le=50)
    delay:float=Field(default=0,ge=0,le=60)
    horizon:int=Field(default=10,ge=1,le=120)
    ambient:float|None=Field(default=None,ge=-20,le=60)


@router.post('/compare')
def compare(payload:Compare):
    snap=obtain(**payload.model_dump(include=set(Context.model_fields)))
    origin={'asset_id':snap['asset_id'],'source':snap['source'],'evidence_timestamp':(snap.get('current') or {}).get('timestamp')}
    if payload.mode!='transformer':
        from .halo_qualification import qualify
        result=engine.futures(snap,payload.reduction,payload.delay,payload.horizon,payload.ambient)
        q=qualify(snap,payload.horizon);result['qualification']=q
        if result.get('available'):result['assumptions']+=' Model check: '+q['reason']
        return {**result,**origin}
    from .thermal import ThermalState,forecast,forecast_metrics
    from .domain import Asset
    row=snap['current']; asset=Asset.model_validate(snap['transformer']['asset'])
    if row['confidence']=='Low': return {'available':False,'reason':'Resolve low-confidence inputs before forecasting.'}
    # Reconstruct from the selected measured channel, including probe quarantine.
    selected=row['oil_reference_c'] if row['source'].startswith('reference') else row['oil_c']
    if selected is None: return {'available':False,'reason':'No trusted oil-temperature channel.'}
    initial=ThermalState(selected,row['estimated_hotspot_c']-selected)
    ambient=row['ambient_c'] if payload.ambient is None else payload.ambient
    base=forecast(asset,initial,row['load_pu'],ambient,row['voltage_pu'],horizon_min=payload.horizon)
    alt=forecast(asset,initial,row['load_pu'],ambient,row['voltage_pu'],payload.reduction,payload.delay,payload.horizon)
    conv=lambda series:[{'minute':r['minute'],'temperature_c':r['hotspot_c'],'low_c':r['low_c'],'high_c':r['high_c']} for r in series]
    return {'available':True,**origin,'baseline':conv(base),'alternative':conv(alt),
            'peak_baseline_c':max(r['hotspot_c'] for r in base),'peak_alternative_c':max(r['hotspot_c'] for r in alt),
            'assumptions':'Distribution-model hot-spot estimate; constant ambient/voltage; ±10% parameter sensitivity, not a probability interval. No physical commands.',
            'limit_c':asset.hotspot_limit_c,'baseline_metrics':forecast_metrics(base,asset.hotspot_limit_c),'alternative_metrics':forecast_metrics(alt,asset.hotspot_limit_c)}


@router.post('/envelope')
def envelope(payload:Compare):
    from .halo_qualification import qualify
    q=qualify(obtain(**payload.model_dump(include=set(Context.model_fields))),payload.horizon)
    if not q.get('study_comparison_allowed',False):
        return {'available':False,'reason':q['reason'],'qualification':q}
    candidates=[]
    for reduction in range(0,51,5):
        result=compare(payload.model_copy(update={'reduction':reduction}))
        if not result['available']: return result
        limit=result.get('limit_c') or obtain(**payload.model_dump(include=set(Context.model_fields)))['limits']['surface_c']
        if limit is None: return {'available':False,'reason':'Configure a reviewed limit first.'}
        peak=max(p.get('high_c',p['temperature_c']) for p in result['alternative'])
        candidates.append({'reduction_pct':reduction,'peak_c':float(peak),'within_limit':bool(peak<limit),'extrapolation':bool(result.get('extrapolation',False) or result.get('horizon_exceeds_validation',False))})
    feasible=[r for r in candidates if r['within_limit'] and not r['extrapolation']]
    return {'available':True,'candidates':candidates,'recommendation':feasible[0] if feasible else None,
            'note':'Search over 5% load-reduction increments; not a certified safe operating envelope. No feasible result is a valid outcome.'}


class Fit(Context):
    qualified_healthy:bool=False
    note:str=Field(min_length=10,max_length=1000)


@router.post('/models/fit')
def fit(payload:Fit,actor=Depends(operator)):
    if payload.mode=='transformer': raise HTTPException(422,'Surface fitting is for the bench only.')
    if not payload.qualified_healthy: raise HTTPException(422,'Explicitly qualify the training period as healthy first.')
    snap=obtain(**payload.model_dump(include=set(Context.model_fields)))
    if snap['source']!='simulated' and snap['quality']['calibration']!='reference recorded': raise HTTPException(422,'Record sensor calibration first; unverified imported units cannot qualify a surface model.')
    if not engine.ambient_qualified(snap): raise HTTPException(422,'Verify the ambient probe or record an independent ambient observation before fitting.')
    rows=store.frames(engine.config().device_id,3600) if payload.mode=='bench' else engine.demonstration(payload.scenario,payload.cursor) if not payload.dataset_id else store.get('bench_dataset',payload.dataset_id)['rows'][:payload.cursor+1]
    calibration_id=(snap.get('current') or {}).get('calibration_id') if snap['source']!='simulated' else None
    config_id=(snap.get('current') or {}).get('config_id') if snap['source']!='simulated' else None
    if snap['source']!='simulated' and snap.get('configuration_binding',{}).get('state')!='bound':
        raise HTTPException(422,'An immutable acquisition configuration is required; legacy data cannot inherit current settings.')
    if calibration_id: rows=[r for r in rows if r.get('calibration_id')==calibration_id]
    if config_id:rows=[r for r in rows if r.get('config_id')==config_id]
    try: result=engine.fit_surface(rows,snap['asset_id'])
    except ValueError as e: raise HTTPException(422,str(e))
    result.update(id='MODEL-'+uuid.uuid4().hex[:10],source=snap['source'],calibration_id=calibration_id,config_id=config_id,created_at=now(),note=payload.note,actor=actor)
    store.put('surface_model',result['id'],result)
    if result['beats_persistence']: store.put('active_model',snap['asset_id'],result)
    store.event(snap['asset_id'],'model_fitted',result)
    return result


@router.get('/models')
def models(): return {'models':store.records('surface_model')}


@router.post('/models/{model_id}/activate')
def activate(model_id:str,actor=Depends(operator)):
    model=store.get('surface_model',model_id)
    if not model or not model['beats_persistence']: raise HTTPException(422,'Only a held-out baseline improvement can be activated.')
    store.put('active_model',model['asset_id'],model);store.event(model['asset_id'],'model_activated',{'id':model_id,'actor':actor})
    return model


class Import(Contract):
    name:str=Field(min_length=1,max_length=100)
    csv_text:str=Field(max_length=2_000_000)


@router.post('/import')
def import_bench(payload:Import,actor=Depends(operator)):
    reader=csv.DictReader(io.StringIO(payload.csv_text.lstrip('\ufeff')))
    allowed={'timestamp','primary_v','primary_current_a','secondary_v','current_a','surface_c','ambient_c','ambient_source','ambient_observed_at','relay_mask','calibration_id'}
    fields=set(reader.fieldnames or [])
    if not {'timestamp','secondary_v','current_a','surface_c'}.issubset(fields): raise HTTPException(422,'Required columns: timestamp,secondary_v,current_a,surface_c. Units are V RMS, A RMS and °C surface.')
    if fields-allowed: raise HTTPException(422,'Unsupported columns: '+', '.join(sorted(fields-allowed)))
    rows=[]; start=None
    try:
        for i,r in enumerate(reader):
            if i>=20000: raise ValueError('At most 20,000 rows.')
            t=engine.timestamp(r['timestamp']);start=start or t
            mask=int(r.get('relay_mask') or 0)
            if not 0<=mask<=15: raise ValueError('relay_mask must be 0–15.')
            row=Frame(device_id='CSV',boot_id='import',sequence=i,uptime_ms=max(0,int((t-start).total_seconds()*1000)),timestamp=t,
                      **{k:float(r[k]) if r.get(k,'').strip() else None for k in engine.CHANNELS},
                      ambient_source=r.get('ambient_source') or 'not_measured',relay_states=tuple(bool(mask&(1<<n)) for n in range(4)),
                      ambient_observed_at=r.get('ambient_observed_at') or None,
                      calibration_id=r.get('calibration_id') or None).model_dump(mode='json')
            if rows and engine.timestamp(row['timestamp'])<=engine.timestamp(rows[-1]['timestamp']): raise ValueError('Timestamps must strictly increase.')
            rows.append({**row,'evidence_id':f'CSV-{i}'})
        if len(rows)<2: raise ValueError('At least two readings are required.')
    except (ValueError,TypeError,ValidationError) as e: raise HTTPException(422,str(e)[:500])
    key=uuid.uuid4().hex[:12]
    for row in rows: row['evidence_id']=f'CSV-{key}-{row["sequence"]}'
    store.put('bench_dataset',key,{'id':key,'name':payload.name,'rows':rows,'source':'user-supplied replay','created_at':now()})
    return {'id':key,'count':len(rows),'name':payload.name}


@router.get('/datasets')
def datasets(): return {'datasets':[{**{k:r[k] for k in ('id','name','source','created_at')},'count':len(r['rows'])} for r in store.records('bench_dataset')]}


@router.get('/template.csv')
def template():
    return Response('timestamp,secondary_v,current_a,surface_c,ambient_c,ambient_source,relay_mask\n2026-10-06T09:00:00+05:30,12,0.308,31,,,1\n2026-10-06T09:00:05+05:30,12,0.309,31.1,,,1\n',media_type='text/csv')


@router.get('/incidents')
def incidents(): return {'incidents':store.records('incident')}


@router.post('/incidents')
def new_incident(payload:Context,actor=Depends(operator)):
    with WRITE_LOCK:
        try: return workflow.open_incident(obtain(**payload.model_dump()),actor)
        except ValueError as e: raise HTTPException(409,str(e))


def incident_or_404(key):
    row=store.get('incident',key)
    if not row: raise HTTPException(404,'Incident not found.')
    return row


@router.post('/incidents/{key}/observations')
def add_observation(key:str,payload:Observation,actor=Depends(operator)):
    with WRITE_LOCK:
        try: return workflow.observe(incident_or_404(key),payload,actor)
        except ValueError as e: raise HTTPException(409,str(e))


class Transition(Contract):
    state:Literal['acknowledged','resolved']


@router.post('/incidents/{key}/state')
def transition(key:str,payload:Transition,actor=Depends(operator)):
    with WRITE_LOCK:
        row=incident_or_404(key)
        if row['state']==payload.state: return row
        if payload.state=='acknowledged' and row['state']!='open': raise HTTPException(409,'Only an open incident can be acknowledged.')
        if payload.state=='resolved' and (row['state']!='verification_pending' or not row['verification'] or row['verification']['result']!='improvement'):
            raise HTTPException(409,'Resolution requires post-action evidence and verified improvement.')
        if payload.state=='resolved':
            row=workflow.verify(row,obtain('bench'),actor)
            if row['verification']['result']!='improvement': raise HTTPException(409,'Current evidence no longer supports verified improvement.')
        row['state']=payload.state;row['transitions'].append({'state':payload.state,'actor':actor,'at':now()})
        store.put('incident',key,row);return row


@router.post('/incidents/{key}/verify')
def verify(key:str,payload:Context,actor=Depends(operator)):
    with WRITE_LOCK:
        try: return workflow.verify(incident_or_404(key),obtain(**payload.model_dump()),actor)
        except ValueError as e: raise HTTPException(409,str(e))


class Attachment(Contract):
    filename:str=Field(max_length=100)
    data_base64:str=Field(max_length=5_600_000)


@router.post('/incidents/{key}/attachments')
def attach(key:str,payload:Attachment,actor=Depends(operator)):
    incident_or_404(key)
    try:
        from PIL import Image
        data=base64.b64decode(payload.data_base64,validate=True)
        if len(data)>4_000_000: raise ValueError('Image exceeds 4 MB.')
        pic=Image.open(io.BytesIO(data))
        if pic.format not in ('JPEG','PNG') or pic.width*pic.height>20_000_000: raise ValueError('Use a JPEG or PNG below 20 megapixels.')
        pic.verify()
    except Exception: raise HTTPException(422,'Invalid image; use a JPEG or PNG below 4 MB.')
    key_id='PHOTO-'+uuid.uuid4().hex
    value={'id':key_id,'incident_id':key,'filename':Path(payload.filename).name,'actor':actor,'created_at':now(),
           'sha256':hashlib.sha256(data).hexdigest(),'mime':'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg',
           'data':base64.b64encode(data).decode(),'interpretation':'Stored evidence only; no automatic image diagnosis.'}
    return store.photo(value,data)


@router.get('/attachments/{key}')
def attachment(key:str,actor=Depends(operator)):
    row=store.get('attachment',key)
    if not row: raise HTTPException(404)
    return Response(cloud.download(row['object_path']) if row.get('object_path') else base64.b64decode(row['data']),media_type=row['mime'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/passport/qr.png')
def qr(request:Request,asset:Literal['BENCH-001','BENCH-SIM','DT-SIM']='BENCH-001'):
    import qrcode
    base=os.getenv('HALO_PUBLIC_URL') or str(request.base_url).rstrip('/')
    image=qrcode.make(base+'/app?asset='+asset+'#passport');out=io.BytesIO();image.save(out,format='PNG')
    return Response(out.getvalue(),media_type='image/png')


@router.get('/export')
def export(mode:Literal['bench','replay','transformer']='bench',scenario:str='normal',cursor:int=Query(180,ge=1,le=20000),dataset_id:str|None=None):
    snap=get_snapshot(mode,scenario,cursor,dataset_id)
    return Response(json.dumps(snap,indent=2,allow_nan=False),media_type='application/json',headers={'Content-Disposition':'attachment; filename="halo-evidence.json"'})


class Challenge(Contract):
    scenario:Literal['normal','overload','heating','sensor','dropout']


@router.post('/challenge')
def challenge(payload:Challenge,actor=Depends(operator)):
    key=uuid.uuid4().hex[:12]
    store.put('challenge',key,{'id':key,'scenario':payload.scenario,'seed':secrets.randbelow(100000),'revealed':False,'created_at':now()})
    return {'id':key,'investigator_url':'/app?challenge='+key,'label_hidden':True}


@router.get('/challenge/{key}')
def challenge_snapshot(key:str):
    row=store.get('challenge',key)
    if not row: raise HTTPException(404)
    snap=engine.snapshot(engine.demonstration(row['scenario'],210,row['seed']),'simulated','CHALLENGE-'+key)
    snap['name']='Blind challenge '+key;snap['challenge_id']=key
    snap['label']=row['scenario'] if row['revealed'] else None
    snap['assessment']=store.get('assessment_latest',snap['asset_id'])
    return snap


@router.post('/challenge/{key}/assess')
def challenge_assess(key:str,actor=Depends(operator)):
    return ai.assess(challenge_snapshot(key),[],True)


@router.post('/challenge/{key}/reveal')
def reveal(key:str,actor=Depends(operator)):
    row=store.get('challenge',key)
    if not row: raise HTTPException(404)
    if not store.get('assessment_latest','CHALLENGE-'+key): raise HTTPException(409,'Record an assessment before revealing the label.')
    row['revealed']=True;store.put('challenge',key,row)
    return {'label':row['scenario'],'assessment':store.get('assessment_latest','CHALLENGE-'+key),'note':'Single demonstration case; not an accuracy benchmark.'}
