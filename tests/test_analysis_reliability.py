"""Real local queue/transaction/lifespan tests; no serial ports or remote writes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
import threading
import time
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from neuratwin import halo_api as api,halo_store as store,twin_api,cloud
from neuratwin.halo_contracts import Frame,BenchConfig
from neuratwin.storage import now
from neuratwin.app import app


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'recovery.sqlite3'))
    monkeypatch.delenv('HALO_ALLOW_CONTROL',raising=False)
    monkeypatch.delenv('HALO_OPERATOR_TOKEN',raising=False)


def seed(count=1):
    start=datetime.now(timezone.utc)-timedelta(seconds=count+30)
    jobs=[]
    with store.transaction() as db:
        for i in range(count):
            f=Frame(device_id='HALO-ESP32',boot_id='reliability',sequence=i,uptime_ms=i*1000,
                    timestamp=start+timedelta(seconds=i),secondary_v=12,current_a=.3,surface_c=30).model_dump(mode='json')
            key=api.analysis_identity(f)
            db.execute('INSERT INTO halo_frames(device_id,boot_id,sequence,timestamp,received_at,content) VALUES (?,?,?,?,?,?)',
                (f['device_id'],f['boot_id'],i,f['timestamp'],now(),json.dumps(f)))
            job={'id':key,'frame':f,'status':'pending','created_at':f['timestamp'],'admission':'isolated test fixture'}
            store.put('analysis_job',key,job);jobs.append(job)
    return jobs


def make_due(key):
    job=store.get('analysis_job',key)
    job['next_attempt_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    store.put('analysis_job',key,job)


def test_continuous_worker_drains_more_than_100_oldest_first(monkeypatch):
    jobs=seed(153);order=[];original=twin_api.process_prototype
    def traced(frame,*,allow_control):
        assert allow_control is False
        order.append(frame.sequence)
        return original(frame,allow_control=False)
    monkeypatch.setattr(twin_api,'process_prototype',traced)
    async def exercise():
        worker=api.AnalysisRecoveryWorker(batch_size=17,poll_seconds=.01)
        await worker.start()
        try:
            # This checks eventual drain/order, not a 15-second hardware-specific
            # throughput SLA. SQLite commits on a busy Windows host can exceed it.
            # Keep a bounded failure deadline while preserving every queue assertion.
            deadline=time.monotonic()+60
            while worker.state['recovered']<153 and time.monotonic()<deadline:await asyncio.sleep(.02)
            assert worker.state['recovered']==153,worker.state
        finally:await worker.stop()
        assert worker.task.done() and worker.snapshot()['status']=='stopped'
    asyncio.run(exercise())
    assert order==list(range(153))
    assert all(store.get('analysis_job',j['id'])['attempts']==1 for j in jobs)
    assert store.get('analysis_job',jobs[-1]['id'])['status']=='complete'
    assert all(store.get('analysis_job',j['id'])['status']=='superseded' for j in jobs[:-1])
    assert not store.records('command')


def test_failure_backoff_does_not_starve_healthy_jobs_or_commit_partial_writes(monkeypatch):
    jobs=seed(3);original=twin_api.process_prototype
    def faulty(frame,*,allow_control):
        if frame.sequence==0:
            store.event('BENCH-001','must_rollback',{})
            raise RuntimeError('DO_NOT_EXPOSE private details')
        return original(frame,allow_control=False)
    monkeypatch.setattr(twin_api,'process_prototype',faulty)
    first=api.recover_pending_analyses(limit=2)
    assert first['failed']==1 and first['recovered']==1
    poison=store.get('analysis_job',jobs[0]['id'])
    assert poison['attempts']==1 and poison['last_error_code']=='analysis_failed'
    delay=(datetime.fromisoformat(poison['next_attempt_at'])-datetime.now(timezone.utc)).total_seconds()
    assert 0<delay<=api.ANALYSIS_BACKOFF_SECONDS
    assert 'DO_NOT_EXPOSE' not in json.dumps(store.analysis_queue_sample())
    assert not any(e['kind']=='must_rollback' for e in store.events('BENCH-001'))
    second=api.recover_pending_analyses(limit=2)
    assert second['recovered']==1 and second['failed']==0
    assert store.get('analysis_job',jobs[0]['id'])['attempts']==1
    monkeypatch.setattr(twin_api,'process_prototype',original);make_due(jobs[0]['id'])
    assert api.recover_pending_analyses()['recovered']==1
    assert store.get('analysis_job',jobs[0]['id'])['attempts']==2


def test_backoff_is_durable_and_capped(monkeypatch):
    job=seed()[0];job['attempts']=24;store.put('analysis_job',job['id'],job)
    def fail(*args,**kwargs):raise ValueError('invalid fixture')
    monkeypatch.setattr(twin_api,'process_prototype',fail)
    assert api.recover_pending_analyses()['failed']==1
    retry=store.get('analysis_job',job['id'])
    delay=(datetime.fromisoformat(retry['next_attempt_at'])-datetime.now(timezone.utc)).total_seconds()
    assert 59<delay<=60 and retry['attempts']==25
    assert api.recover_pending_analyses()['attempted']==0


def test_competing_threads_process_one_job_once(monkeypatch):
    key=seed()[0]['id'];barrier=threading.Barrier(8);calls=[];original=twin_api.process_prototype
    def traced(frame,*,allow_control):
        calls.append(frame.sequence);time.sleep(.02)
        return original(frame,allow_control=False)
    monkeypatch.setattr(twin_api,'process_prototype',traced)
    def attempt(_):barrier.wait();return api.analyse_acquisition(key,allow_control=False)
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(8)))
    assert calls==[0] and sum(r['_claimed'] for r in results)==1
    assert store.get('analysis_job',key)['attempts']==1
    assert len([e for e in store.events('BENCH-001') if e['kind']=='twin_condition'])==1
    assert not store.records('command')


def test_expired_owner_reclaimed_but_active_lease_is_not():
    a,b=seed(2)
    for job,seconds in ((a,-1),(b,60)):
        job.update(status='processing',attempts=1,claim_token='abandoned',
                   lease_until=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
        store.put('analysis_job',job['id'],job)
    assert api.recover_pending_analyses()['recovered']==1
    assert store.get('analysis_job',a['id'])['attempts']==2
    assert store.get('analysis_job',b['id'])['claim_token']=='abandoned'


def test_old_device_job_cannot_relabel_new_devices_same_boot_sequence():
    old=seed()[0]
    replacement={**old['frame'],'device_id':'HALO-REPLACEMENT'}
    with store.transaction() as db:
        db.execute('INSERT INTO halo_frames(device_id,boot_id,sequence,timestamp,received_at,content) VALUES (?,?,?,?,?,?)',
            (replacement['device_id'],replacement['boot_id'],replacement['sequence'],replacement['timestamp'],now(),json.dumps(replacement)))
        store.put('config','bench',BenchConfig(device_id=replacement['device_id']).model_dump())
    result=api.analyse_acquisition(old['id'],allow_control=False)
    assert result['status']=='superseded'
    assert store.get('twin_prototype','BENCH-001') is None and not store.events('BENCH-001')


def test_expired_lease_fences_derived_state_and_audit(monkeypatch):
    key=seed()[0]['id'];monkeypatch.setattr(api,'ANALYSIS_LEASE_SECONDS',.005)
    def slow(frame,*,allow_control):
        store.event('BENCH-001','partial',{})
        store.put('test','partial',{'changed':True})
        time.sleep(.02)
        return {'status':'complete'}
    monkeypatch.setattr(twin_api,'process_prototype',slow)
    assert api.recover_pending_analyses()['failed']==1
    assert store.get('test','partial') is None and not store.events('BENCH-001')
    assert store.get('analysis_job',key)['last_error_code']=='lease_lost'


def test_worker_keeps_polling_after_storage_outage_and_stops_sleep_promptly(monkeypatch):
    original=store.due_analysis_jobs;calls=[]
    def outage(*args,**kwargs):
        calls.append(1)
        if len(calls)<3:raise RuntimeError('backend unavailable')
        return original(*args,**kwargs)
    monkeypatch.setattr(store,'due_analysis_jobs',outage)
    async def exercise():
        worker=api.AnalysisRecoveryWorker(poll_seconds=.01,max_storage_backoff=.04)
        await worker.start()
        try:
            deadline=time.monotonic()+2
            while worker.state['cycles']<3 and time.monotonic()<deadline:await asyncio.sleep(.01)
            assert worker.state['storage_failures']==2 and worker.state['status']=='idle'
            assert worker.state['consecutive_storage_failures']==0
        finally:await worker.stop()
        stopped=len(calls);await asyncio.sleep(.03);assert len(calls)==stopped
        assert worker.task.done() and not worker.state['running']
    asyncio.run(exercise())


def test_write_outage_stops_batch_and_increases_storage_backoff(monkeypatch):
    seed(4);calls=[]
    def unavailable(*args,**kwargs):
        calls.append(1)
        raise HTTPException(503,'test unavailable')
    monkeypatch.setattr(api,'claim_analysis',unavailable)
    async def exercise():
        worker=api.AnalysisRecoveryWorker(batch_size=4,poll_seconds=.01,max_storage_backoff=.04)
        delays=[await worker.cycle() for _ in range(4)]
        assert delays==[.01,.02,.04,.04]
        assert len(calls)==4 and worker.state['failed']==4
        assert worker.state['status']=='storage_unavailable'
        assert worker.state['last_result']['storage_failed']
        await worker.stop()
    asyncio.run(exercise())


def test_shutdown_stops_after_current_job_not_rest_of_batch(monkeypatch):
    seed(5);entered=threading.Event();release=threading.Event();calls=[]
    def blocked(frame,*,allow_control):
        calls.append(frame.sequence)
        if frame.sequence==1:entered.set();assert release.wait(2)
        return {'status':'complete'}
    monkeypatch.setattr(twin_api,'process_prototype',blocked)
    async def exercise():
        worker=api.AnalysisRecoveryWorker(batch_size=5,poll_seconds=.01)
        await worker.start()
        assert await asyncio.to_thread(entered.wait,2)
        stopping=asyncio.create_task(worker.stop());await asyncio.sleep(.02)
        assert not stopping.done()
        release.set();await asyncio.wait_for(stopping,2)
        assert worker.task.done()
    asyncio.run(exercise())
    assert calls==[0,1]
    assert len(store.due_analysis_jobs(now()))==3


def test_lifespan_status_is_authenticated_and_reports_only_bounded_metadata():
    jobs=seed(3)
    for job in jobs:
        job['next_attempt_at']=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()
        store.put('analysis_job',job['id'],job)
    with TestClient(app) as client:
        assert client.get('/api/halo/analysis-recovery').status_code==401
        response=client.get('/api/halo/analysis-recovery',headers={'Authorization':'Bearer '+api.LOCAL_TOKEN})
        assert response.status_code==200
        payload=response.json()
        assert payload['worker']['running'] and not payload['worker']['hardware_commands_allowed']
        assert len(payload['oldest_unfinished_sample'])==3 and 'frame' not in json.dumps(payload)
    assert app.state.analysis_worker.task.done() and app.state.analysis_worker.state['status']=='stopped'


def test_physical_decision_and_events_retain_explicit_versions():
    job=seed()[0];api.analyse_acquisition(job['id'])
    p=store.get('twin_prototype','BENCH-001')['provenance']
    assert p['analyzer_version']==twin_api.PHYSICAL_ANALYZER_VERSION
    assert p['rule_version']==twin_api.PHYSICAL_RULE_VERSION
    event=next(e for e in store.events('BENCH-001') if e['kind']=='twin_condition')
    assert event['content']['provenance']==p
    assert store.get('analysis_job',job['id'])['result']['provenance']==p
