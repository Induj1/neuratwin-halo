"""Mock-transport cloud CAS and HTTP-UOW boundaries; no remote database writes."""
from datetime import datetime,timezone
import json
import pytest
from fastapi import HTTPException
from neuratwin import cloud,halo_api as api,halo_store as store,twin_api
from neuratwin.halo_contracts import Frame
from test_cloud import backend


def seed():
    frame=Frame(device_id='HALO-ESP32',boot_id='cloud-queue',sequence=0,uptime_ms=0,
                timestamp=datetime.now(timezone.utc)).model_dump(mode='json')
    key=api.analysis_identity(frame)
    store.put('analysis_job',key,{'id':key,'frame':frame,'status':'pending','created_at':frame['timestamp']})
    return key


def test_claim_and_outcome_survive_outer_http_uow_rollback(backend,monkeypatch):
    records,calls=backend;key=seed()
    def process(frame,*,allow_control):
        assert allow_control is False
        store.put('derived','result',{'sequence':frame.sequence})
        store.event('BENCH-001','decision',{'sequence':frame.sequence})
        return {'status':'complete'}
    monkeypatch.setattr(twin_api,'process_prototype',process)
    with pytest.raises(RuntimeError),cloud.transaction():
        store.put('unrelated','http-only',{'must':'rollback'})
        api.analyse_acquisition(key,allow_control=False)
        assert records['analysis_job',key]['content']['status']=='complete'
        raise RuntimeError('HTTP response failed after durable analysis')
    assert ('unrelated','http-only') not in records
    assert records['derived','result']['content']=={'sequence':0}
    commits=[json.loads(r.content) for r in calls if r.url.path.endswith('/halo_commit')]
    result_commit=next(c for c in commits if any(r['kind']=='derived' for r in c['p_records']))
    assert any(r['kind']=='analysis_job' and r['content']['status']=='complete' for r in result_commit['p_records'])
    assert len(result_commit['p_events'])==1


def test_competing_claim_uses_cloud_revision_compare_and_swap(backend,monkeypatch):
    records,_=backend;key=seed();original=cloud.rpc
    def competing(name,payload=None):
        if name=='halo_commit' and any(r['kind']=='analysis_job' and r['content']['status']=='processing' for r in payload['p_records']):
            records['analysis_job',key]['revision']+=1
            records['analysis_job',key]['content'].update(status='processing',claim_token='other-process')
        return original(name,payload)
    monkeypatch.setattr(cloud,'rpc',competing)
    with pytest.raises(HTTPException) as error:api.claim_analysis(key)
    assert error.value.status_code==409
    assert records['analysis_job',key]['content']['claim_token']=='other-process'


def test_new_cloud_owner_fences_stale_result_and_all_its_side_effects(backend,monkeypatch):
    records,calls=backend;key=seed()
    def stolen_during_compute(frame,*,allow_control):
        assert allow_control is False
        store.put('derived','stale',{'must':'rollback'})
        store.event('BENCH-001','stale_decision',{})
        # Simulate a separate application's successful expired-lease claim.
        records['analysis_job',key]['revision']+=1
        records['analysis_job',key]['content']['claim_token']='new-owner'
        return {'status':'complete'}
    monkeypatch.setattr(twin_api,'process_prototype',stolen_during_compute)
    with pytest.raises(HTTPException) as error:api.analyse_acquisition(key,allow_control=False)
    assert error.value.status_code==409
    assert ('derived','stale') not in records
    assert records['analysis_job',key]['content']['status']=='processing'
    assert records['analysis_job',key]['content']['claim_token']=='new-owner'
    assert 'next_attempt_at' not in records['analysis_job',key]['content']


def test_cloud_selection_is_bounded_and_filters_due_time_before_limit(backend,monkeypatch):
    seen=[]
    monkeypatch.setattr(cloud,'rows',lambda table,params,limit:seen.append((table,params,limit)) or [])
    stamp='2026-10-09T00:00:00+00:00'
    assert store.due_analysis_jobs(stamp,17)==[]
    table,params,limit=seen[-1]
    assert table=='halo_records' and limit==17 and params['kind']=='eq.analysis_job'
    assert params['order']=='content->>created_at.asc,id.asc'
    assert 'content->>next_attempt_at.lte.'+stamp in params['or']
    assert 'content->>lease_until.lte.'+stamp in params['or']
    assert 'status.eq.pending' in params['or'] and 'status.eq.processing' in params['or']
    store.analysis_queue_sample(1000)
    assert seen[-1][2]==25 and seen[-1][1]['content->>status']=='in.(pending,processing)'
