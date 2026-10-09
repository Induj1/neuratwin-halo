"""Isolated physical-protocol fixtures; no ports, remote writes or hardware claims."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import uuid
import pytest
from test_halo import client,OP,DEVICE,configure,calibration,frame,post
from neuratwin import halo_api as api,halo_engine as engine,halo_store as store,halo_workflow as workflow,twin_api
from neuratwin.halo_contracts import Frame,Observation


def test_legacy_frame_never_inherits_current_limits(client):
    configure(client);calibration(client)
    legacy=frame(config_id=None,calibration_id='CAL-TEST')
    assert client.post('/api/halo/telemetry',json=legacy,headers=DEVICE).status_code==200
    s=client.get('/api/halo/snapshot').json();v=client.get('/api/halo/twin/prototype').json()
    assert s['configuration_binding']['state']=='unbound'
    assert s['current']['surface_c']==30 and s['metrics']['load_pct'] is None
    assert s['metrics']['expected_current_a'] is None and s['metrics']['condition_index'] is None
    assert v['telemetry']['quality']=='unverified' and v['settings']['temperature_trip'] is None
    assert not v['load_control_available'] and v['history'][0]['loading_percent'] is None
    assert any(a['code']=='configuration_unbound' for a in s['alerts'])


def test_old_acquisition_retains_immutable_limits_after_edit(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    original=client.get('/api/halo/config').json()
    f=frame(calibration_id='CAL-TEST')
    assert client.post('/api/halo/telemetry',json=f,headers=DEVICE).status_code==200
    before=client.get('/api/halo/twin/prototype').json()
    changed={**original['config'],'surface_limit_c':65,'current_limit_a':.5}
    update=client.put('/api/halo/config',json=changed,headers=OP).json()
    assert update['config_id']!=original['config_id']
    after=client.get('/api/halo/twin/prototype').json()
    assert after['settings']==before['settings'] and after['telemetry']['loading_percent']==before['telemetry']['loading_percent']
    assert after['history'][0]['loading_percent']==before['history'][0]['loading_percent']
    assert after['configuration_binding']['id']==original['config_id'] and not after['load_control_available']
    assert post(client,'/relays',{'states':[True,False,False,False],'request_id':'stale-config-on'}).status_code==423
    assert store.get('twin_prototype','BENCH-001')['provenance']['config_id']==original['config_id']
    assert store.get('config_version',original['config_id'])['config']==original['config']


def test_unknown_tampered_or_other_device_config_rejected(client):
    configure(client);calibration(client)
    assert client.post('/api/halo/telemetry',json=frame(config_id='CFG-'+'0'*64),headers=DEVICE).status_code==422
    key=client.get('/api/halo/config').json()['config_id'];record=store.get('config_version',key)
    record['config']['surface_limit_c']=62;store.put('config_version',key,record)
    assert client.post('/api/halo/telemetry',json=frame(config_id=key),headers=DEVICE).status_code==422
    assert not store.frames('HALO-ESP32') and not store.records('analysis_job')


def test_analysis_failure_survives_frame_commit_and_recovers_without_commands(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    c=client.get('/api/halo/config').json()['config'];c['automatic_cutoff_enabled']=True
    assert client.put('/api/halo/config',json=c,headers=OP).status_code==200
    f=frame(calibration_id='CAL-TEST',current_a=1.2)
    original=twin_api.process_prototype
    def failure(*args,**kwargs):
        store.event('BENCH-001','must_rollback',{})
        store.put('twin_prototype','BENCH-001',{'last_frame':'partial'})
        raise RuntimeError('Injected analysis failure')
    monkeypatch.setattr(twin_api,'process_prototype',failure)
    with pytest.raises(RuntimeError,match='Injected'):
        client.post('/api/halo/telemetry',json=f,headers=DEVICE)
    assert len(store.frames('HALO-ESP32'))==1
    assert store.records('analysis_job')[0]['status']=='pending'
    assert store.get('twin_prototype','BENCH-001') is None
    assert not any(e['kind']=='must_rollback' for e in store.events('BENCH-001'))
    monkeypatch.setattr(twin_api,'process_prototype',original)
    job=store.records('analysis_job')[0]
    job['next_attempt_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    store.put('analysis_job',job['id'],job)  # Simulate the durable backoff deadline passing.
    result=api.recover_pending_analyses()
    assert result['recovered']==1 and result['failed']==0
    state=store.get('twin_prototype','BENCH-001')
    assert state['latched'] and state['provenance']['config_id']==f['config_id']
    assert store.records('analysis_job')[0]['status']=='complete' and not store.records('command')
    count=len(store.events('BENCH-001'))
    assert api.recover_pending_analyses()['recovered']==0
    retry=client.post('/api/halo/telemetry',json=f,headers=DEVICE)
    assert retry.status_code==200 and retry.json()['duplicate']
    assert len(store.events('BENCH-001'))==count and not store.records('command')


def test_record_transaction_rolls_back_all_records_events_and_unique_conflict(client):
    with pytest.raises(ValueError):
        with store.transaction():
            store.put('test','one',{'revision':1});store.event('test','partial',{})
            raise ValueError('abort')
    assert store.get('test','one') is None and store.events('test')==[]
    assert store.create_unique('test','one',{'revision':1})=={'revision':1}
    assert store.create_unique('test','one',{'revision':1})=={'revision':1}
    with pytest.raises(ValueError):store.create_unique('test','one',{'revision':2})
    assert store.get('test','one')=={'revision':1}


def test_configuration_identity_survives_default_float_json_roundtrip(client):
    import json
    from neuratwin.halo_contracts import BenchConfig
    c=BenchConfig(current_limit_a=1,surface_limit_c=55)
    key=engine.config_identity(c)
    saved=json.loads(json.dumps(c.model_dump()))
    assert engine.config_identity(saved)==key
    store.create_unique('config_version',key,{'config':saved})
    assert engine.recorded_config({'config_id':key,'device_id':c.device_id})[1]['state']=='bound'


def comparison(client,*,after_cal='CAL-TEST',raw_before=50,raw_after=46,converted_after=None,missing_raw=False):
    configure(client);calibration(client)
    if after_cal!='CAL-TEST':
        new={k:v for k,v in store.get('calibration','CAL-TEST').items() if k not in ('created_at','actor')}
        new.update(id=after_cal,surface_offset_c=-4)
        assert post(client,'/calibrations',new).status_code==200
    current=datetime.now(timezone.utc);action=current-timedelta(seconds=105)
    def rows(raw,cal,ending,temp=None):
        out=[]
        for i in range(20):
            r=frame(sequence=i,uptime_ms=i*5000,timestamp=(ending-timedelta(seconds=5*(19-i))).isoformat(),
                surface_c=raw if temp is None else temp,current_a=.3,ambient_c=28,ambient_source='probe',calibration_id=cal,
                raw={} if missing_raw else {'surface_raw_c':raw,'current_rms_mv':300,'secondary_rms_mv':1200})
            r['evidence_id']=f'FIXTURE-{ending.isoformat()}-{i}';out.append(r)
        return out
    before=engine.snapshot(rows(raw_before,'CAL-TEST',action-timedelta(seconds=5)))
    before['alerts']=[{'code':'thermal_deviation','title':'Fixture','severity':'warning','evidence':'Synthetic'}]
    incident=workflow.open_incident(before,'test')
    for kind,dt in [('inspection',action-timedelta(seconds=1)),('action',action),('followup',current)]:
        incident=workflow.observe(incident,Observation(request_id=uuid.uuid4().hex,kind=kind,note='Software regression fixture',observed_at=dt),'test')
    after=engine.snapshot(rows(raw_after,after_cal,current,converted_after))
    assert after['connection']=='live' and after['quality']['calibration']=='reference recorded'
    return incident,after


def test_cal_a_cal_b_offset_cannot_receive_physical_repair_credit(client):
    incident,after=comparison(client,after_cal='CAL-B',raw_after=50,converted_after=46)
    assert {r['calibration_id'] for r in incident['baseline']['history']}=={'CAL-TEST'}
    assert {r['calibration_id'] for r in after['history']}=={'CAL-B'}
    assert not after['alerts']
    result=workflow.verify(incident,after,'test')['verification']
    assert result['result']=='insufficient_evidence' and 'Recalibration' in result['reason']
    assert result['surface_decrease_c'] is None
    # Public resolve route reruns verification; it cannot close a stale positive record.
    incident['verification']={'result':'improvement'};store.put('incident',incident['id'],incident)
    from unittest.mock import patch
    with patch.object(api,'obtain',return_value=after):
        r=post(client,f"/incidents/{incident['id']}/state",{'state':'resolved'})
    assert r.status_code==409
    assert store.get('incident',incident['id'])['state']=='verification_pending'


@pytest.mark.parametrize('missing_raw,raw_after,converted',[ (True,46,46),(False,50,46)])
def test_missing_or_inconsistent_raw_evidence_blocks_repair_credit(client,missing_raw,raw_after,converted):
    incident,after=comparison(client,missing_raw=missing_raw,raw_after=raw_after,converted_after=converted)
    result=workflow.verify(incident,after,'test')['verification']
    assert result['result']=='insufficient_evidence' and 'raw' in result['reason'].lower()


def test_comparable_raw_drop_under_one_reviewed_config_and_calibration(client):
    incident,after=comparison(client)
    result=workflow.verify(incident,after,'test')['verification']
    assert result['result']=='improvement' and result['surface_decrease_c']==4
    assert result['comparability']['raw_surface_decrease_c']==4
    assert result['comparability']['calibration_id']=='CAL-TEST'
    assert result['comparability']['config_id']==after['current']['config_id']
    assert len(result['comparability']['before_evidence_ids'])==20


def test_cloud_without_durable_migration_refuses_before_ingestion(client,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(api.engine,'config',lambda:engine.BenchConfig(board='ESP32'))
    monkeypatch.setattr(api.cloud,'enabled',lambda:True)
    calls=[]
    def rpc(name,payload):
        calls.append(name)
        raise HTTPException(503,'Migration missing')
    monkeypatch.setattr(api.cloud,'rpc',rpc)
    with pytest.raises(HTTPException) as error:api.ingest(Frame.model_validate(frame(config_id=None)),'test')
    assert error.value.status_code==503 and calls==['halo_hardware_health']


@pytest.mark.parametrize('status',['unverified','mismatch'])
def test_server_config_reference_cannot_override_unknown_or_mismatched_firmware(client,monkeypatch,status):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    f=frame(calibration_id='CAL-TEST',hardware_config_status=status)
    assert client.post('/api/halo/telemetry',json=f,headers=DEVICE).status_code==200
    s=client.get('/api/halo/snapshot').json();v=client.get('/api/halo/twin/prototype').json()
    assert s['configuration_binding']['state']=='bound'
    assert s['hardware_configuration']['state']==status and s['metrics']['condition_index'] is None
    assert v['telemetry']['quality']=='unverified' and not v['load_control_available']
    assert post(client,'/relays',{'states':[True,False,False,False],'request_id':'unknown-device-on'}).status_code==423


def test_bridge_configuration_report_and_outbox_retain_acquisition_identity(client,tmp_path):
    from test_recovery import bridge
    configure(client);calibration(client)
    configuration=client.get('/api/halo/device/config',headers=DEVICE).json();c=configuration['config']
    hello={**c,'chip':'ESP32','boot_id':'boot-test','protocol':1}
    assert bridge.hardware_config_status(hello,c)=='reported_match'
    assert bridge.hardware_config_status({**hello,'current_adc_pin':35},c)=='mismatch'
    assert bridge.hardware_config_status({},c)=='unverified'
    raw={'device_id':c['device_id'],'boot_id':'boot-test','sequence':1,'uptime_ms':1000,
         'secondary_rms_mv':1200,'current_rms_mv':300,'surface_raw_c':30,'relay_states':[False]*4}
    anchor={'boot_id':'boot-test','uptime_ms':1000,'utc':datetime.now(timezone.utc)-timedelta(seconds=1)}
    f=bridge.convert(raw,anchor,configuration['calibration'],config_id=configuration['config_id'],
                     hardware_config_status=bridge.hardware_config_status(hello,c))
    q=bridge.Outbox(tmp_path/'bridge.db');q.append(f);q.close()
    altered={**c,'surface_limit_c':63};client.put('/api/halo/config',json=altered,headers=OP)
    q=bridge.Outbox(tmp_path/'bridge.db');retained=q.next()[1];q.close()
    assert retained['config_id']==configuration['config_id'] and retained['hardware_config_status']=='reported_match'
    assert retained['timestamp']==f['timestamp'] and retained['raw']==f['raw']


def test_changed_config_or_missing_calibration_prevents_verification(client):
    incident,after=comparison(client)
    modified=deepcopy(after)
    for r in modified['history']:r.pop('calibration_id',None)
    assert workflow.verify(deepcopy(incident),modified,'test')['verification']['result']=='insufficient_evidence'
    c=client.get('/api/halo/config').json()['config'];c['surface_limit_c']=64
    key=client.put('/api/halo/config',json=c,headers=OP).json()['config_id']
    modified=deepcopy(after)
    for r in modified['history']:r['config_id']=key
    result=workflow.verify(deepcopy(incident),modified,'test')['verification']
    assert result['result']=='insufficient_evidence' and 'Configuration identity changed' in result['reason']


def test_old_pending_analysis_does_not_rewind_new_live_state(client):
    configure(client);calibration(client)
    start=datetime.now(timezone.utc)-timedelta(seconds=2)
    a=frame(calibration_id='CAL-TEST',timestamp=start.isoformat())
    b=frame(calibration_id='CAL-TEST',timestamp=(start+timedelta(seconds=1)).isoformat(),sequence=2,uptime_ms=2000)
    assert client.post('/api/halo/telemetry',json=a,headers=DEVICE).status_code==200
    assert client.post('/api/halo/telemetry',json=b,headers=DEVICE).status_code==200
    key=api.analysis_identity(a);job=store.get('analysis_job',key);job['status']='pending';store.put('analysis_job',key,job)
    before=store.get('twin_prototype','BENCH-001');events=len(store.events('BENCH-001'))
    assert api.recover_pending_analyses()['recovered']==1
    assert store.get('analysis_job',key)['status']=='superseded'
    assert store.get('twin_prototype','BENCH-001')==before and len(store.events('BENCH-001'))==events


def test_app_startup_recovers_pending_analysis_without_new_packet_or_control(client,monkeypatch):
    from fastapi.testclient import TestClient
    from neuratwin.app import app
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    c=client.get('/api/halo/config').json()['config'];c['automatic_cutoff_enabled']=True
    assert client.put('/api/halo/config',json=c,headers=OP).status_code==200
    f=frame(calibration_id='CAL-TEST',current_a=1.2)
    with monkeypatch.context() as patch:
        def fail(*args,**kwargs):raise RuntimeError('Accepted before process interruption')
        patch.setattr(twin_api,'process_prototype',fail)
        with pytest.raises(RuntimeError):client.post('/api/halo/telemetry',json=f,headers=DEVICE)
    assert store.records('analysis_job')[0]['status']=='pending'
    job=store.records('analysis_job')[0]
    job['next_attempt_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    store.put('analysis_job',job['id'],job)
    with TestClient(app):
        assert app.state.acquisition_recovery['recovered']==1
    assert store.records('analysis_job')[0]['status']=='complete'
    assert store.get('twin_prototype','BENCH-001')['latched'] and not store.records('command')
