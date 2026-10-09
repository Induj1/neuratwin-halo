from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.halo_contracts import BenchConfig, Frame, Observation
from neuratwin import halo_engine as engine, halo_ai as ai, halo_store as store, halo_workflow as workflow


@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'test.sqlite3'))
    monkeypatch.setenv('HALO_DEVICE_TOKEN','test-device-only')
    monkeypatch.delenv('HALO_OPERATOR_TOKEN',raising=False)
    monkeypatch.delenv('HALO_ALLOW_CONTROL',raising=False)
    monkeypatch.delenv('HALO_AI_ENABLED',raising=False)
    with TestClient(app) as c: yield c


OP={'Authorization':'Bearer '+LOCAL_TOKEN}; DEVICE={'Authorization':'Bearer test-device-only'}
def post(c,path,data):return c.post('/api/halo'+path,json=data,headers=OP)
def ctx(scenario='normal',**more):return dict(mode='replay',scenario=scenario,cursor=180,**more)
def frame(**changes):
    t=datetime.now(timezone.utc)-timedelta(seconds=1)
    row={'device_id':'HALO-ESP32','boot_id':'boot-test','sequence':1,'uptime_ms':1000,'timestamp':t.isoformat(),
            'secondary_v':12.,'current_a':.3,'surface_c':30.,'relay_states':[True,False,False,False],'relay_output_configured':True,**changes}
    # Explicit software fixture provenance; unconfigured/legacy fixtures stay unbound.
    if 'config_id' not in changes and os.getenv('NEURATWIN_DB'):
        key=engine.config_identity(engine.config())
        if store.get('config_version',key):
            row['config_id']=key
            if 'hardware_config_status' not in changes:row['hardware_config_status']='reported_match'
    if 'raw' not in changes:
        row['raw']={k:v for k,v in {'surface_raw_c':row['surface_c'],
            'current_rms_mv':row['current_a']*1000 if row['current_a'] is not None else None,
            'secondary_rms_mv':row['secondary_v']*100 if row['secondary_v'] is not None else None}.items() if v is not None}
    return row
def calibration(c):
    assert post(c,'/calibrations',{'id':'CAL-TEST','reviewer':'Tester','note':'Synthetic test fixture only','references':['fixture reference'],
                                 'secondary_v_per_mv':.01,'current_a_per_mv':.001,'surface_reference':'Synthetic reference fixture','ambient_reference':'Synthetic ambient fixture'}).status_code==200
def configure(c):
    config=BenchConfig(board='ESP32',primary_adc_pin=32,secondary_adc_pin=33,current_adc_pin=34,temperature_pin=25,
                       active_low=True,nominal_secondary_v=12,current_limit_a=.95,surface_limit_c=55,
                       primary_verified=True,secondary_verified=True,protection_reviewed=True,pinmap_verified=True,
                       relay_polarity_verified=True,adc_interfaces_verified=True,reviewer='Test only',review_note='Synthetic commissioning fixture')
    assert c.put('/api/halo/config',json=config.model_dump(),headers=OP).status_code==200


def test_no_data_is_not_healthy(client):
    s=client.get('/api/halo/snapshot').json()
    assert s['connection']=='disconnected' and s['metrics']['condition_index'] is None
    assert all(e['value'] is None for e in s['evidence']) and len(s['holds'])>=6


@pytest.mark.parametrize('scenario',['normal','overload','heating','sensor','dropout'])
def test_synthetic_provenance(client,scenario):
    s=client.get('/api/halo/snapshot',params=ctx(scenario)).json()
    assert s['source']=='simulated' and s['connection']=='replay'
    assert not any(k in (s['current'] or {}) for k in ('oil_c','estimated_hotspot_c'))
    if scenario=='overload': assert 'overcurrent' in [a['code'] for a in s['alerts']]
    if scenario=='dropout': assert s['metrics']['condition_index'] is None


@pytest.mark.parametrize('scenario',['normal','overload','cooling','sensor','ambiguous','dropout'])
def test_distribution_regression(client,scenario):
    r=client.get('/api/halo/snapshot',params={'mode':'transformer','scenario':scenario,'cursor':180})
    assert r.status_code==200
    assert r.json()['asset_id']=='DT-SIM' and r.json()['source']=='simulated'


def test_pins_unknown_or_invalid_stay_blocked(client):
    c=client.get('/api/halo/config').json()['config'];c['pinmap_verified']=True
    assert client.put('/api/halo/config',json=c,headers=OP).status_code==422
    c.update(primary_adc_pin=4,secondary_adc_pin=5,current_adc_pin=34,temperature_pin=25,active_low=True)
    assert client.put('/api/halo/config',json=c,headers=OP).status_code==422


def test_telemetry_auth_duplicates_order_and_time(client):
    f=frame()
    assert client.post('/api/halo/telemetry',json=f).status_code==401
    assert client.post('/api/halo/telemetry',json=f,headers=DEVICE).status_code==200
    assert client.post('/api/halo/telemetry',json=f,headers=DEVICE).json()['duplicate']
    assert client.post('/api/halo/telemetry',json={**f,'surface_c':40},headers=DEVICE).status_code==409
    assert client.post('/api/halo/telemetry',json={**f,'sequence':0},headers=DEVICE).status_code==409
    assert client.post('/api/halo/telemetry',json={**f,'boot_id':'older'},headers=DEVICE).status_code==409
    assert client.post('/api/halo/telemetry',json=frame(timestamp=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),headers=DEVICE).status_code==422


def test_stale_calibration_and_channel_units(client):
    f=frame(timestamp=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat())
    client.post('/api/halo/telemetry',json=f,headers=DEVICE)
    s=client.get('/api/halo/snapshot').json();assert s['connection']=='stale' and s['metrics']['condition_index'] is None
    with pytest.raises(ValueError):Frame.model_validate(frame(ambient_c=30))
    with pytest.raises(ValueError):Frame.model_validate(frame(current_a=float('nan')))
    with pytest.raises(ValueError):Frame.model_validate(frame(timestamp='2026-10-01T12:00:00'))


def test_control_k4_and_uncommissioned_block(client):
    payload={'states':[True,False,False,False],'request_id':uuid.uuid4().hex}
    assert client.post('/api/halo/relays',json=payload).status_code==401
    assert post(client,'/relays',payload).status_code==423
    assert post(client,'/relays',{**payload,'states':[False,False,False,True]}).status_code==403
    off=post(client,'/relays',{'states':[False]*4,'request_id':uuid.uuid4().hex}).json()
    assert off['status']=='pending'
    assert post(client,'/relays',{'states':[False]*4,'request_id':off['id']}).json()['id']==off['id']


def test_commissioned_control_ack_and_expiry(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    client.post('/api/halo/telemetry',json=frame(calibration_id='CAL-TEST'),headers=DEVICE)
    p={'states':[True,True,False,False],'request_id':uuid.uuid4().hex}
    r=post(client,'/relays',p);assert r.status_code==200,r.text
    ack=client.post('/api/halo/device/commands/'+r.json()['id']+'/ack',headers=DEVICE,json={'states':[True,False,False,False],'accepted':True})
    assert ack.json()['status']=='rejected'
    p['request_id']=uuid.uuid4().hex;r=post(client,'/relays',p).json();r['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();store.put('command',r['id'],r)
    assert client.get('/api/halo/device/commands',headers=DEVICE).json()['commands']==[]
    assert store.get('command',r['id'])['status']=='expired'


def test_projected_current_limit(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    client.post('/api/halo/telemetry',json=frame(secondary_v=14,calibration_id='CAL-TEST'),headers=DEVICE)
    assert post(client,'/relays',{'states':[True,True,True,False],'request_id':uuid.uuid4().hex}).status_code==423


def test_partial_calibration_does_not_unlock(client):
    post(client,'/calibrations',{'id':'EMPTY','reviewer':'tester','note':'No scale factors provided','references':['test']})
    client.post('/api/halo/telemetry',json=frame(calibration_id='EMPTY'),headers=DEVICE)
    assert client.get('/api/halo/snapshot').json()['quality']['calibration']=='unverified'


def test_csv_selects_actual_import_and_rejects_unknown_columns(client):
    text='timestamp,secondary_v,current_a,surface_c\n2026-10-01T12:00:00Z,11,0.2,32\n2026-10-01T12:00:05Z,11,0.4,33\n'
    r=post(client,'/import',{'name':'bench fixture','csv_text':text});assert r.status_code==200,r.text
    assert client.get('/api/halo/datasets').json()['datasets'][0]['count']==2
    s=client.get('/api/halo/snapshot',params=ctx(dataset_id=r.json()['id'])).json()
    assert s['source']=='replayed' and s['current']['current_a']==.4 and s['current']['ambient_c'] is None
    assert post(client,'/import',{'name':'bad','csv_text':text.replace('surface_c','oil_c')}).status_code==422
    assert client.post('/api/import',json={'name':'bad','asset_id':'NR-104','csv_text':'timestamp,load_pu,ambient_c,oil_c,surface_c\n'}).status_code==422


def test_surface_fit_and_two_futures(client):
    r=post(client,'/models/fit',{**ctx(),'cursor':360,'qualified_healthy':True,'note':'Known healthy synthetic run for test'})
    assert r.status_code==200,r.text;m=r.json();assert m['training_count']>200 and m['validation_count']>100
    assert m['beats_persistence'] and m['validation_rmse_c']<m['persistence_rmse_c']
    f=post(client,'/compare',{**ctx(),'reduction':25,'horizon':10}).json();assert f['available'],f
    assert f['baseline'][0]==f['alternative'][0] and f['alternative'][-1]['temperature_c']<f['baseline'][-1]['temperature_c']
    assert post(client,'/compare',{'mode':'bench'}).json()['available'] is False


def test_distribution_compare_and_envelope(client):
    f=post(client,'/compare',{'mode':'transformer','scenario':'overload','cursor':180,'horizon':10}).json()
    assert f['available'] and f['baseline'][0]==f['alternative'][0]
    assert post(client,'/envelope',{'mode':'transformer','scenario':'overload','cursor':180,'horizon':10}).status_code==200


def test_workflow_cannot_resolve_from_ack_or_replay(client):
    i=post(client,'/incidents',ctx('overload')).json();key=i['id']
    assert post(client,f'/incidents/{key}/state',{'state':'resolved'}).status_code==409
    assert post(client,f'/incidents/{key}/state',{'state':'acknowledged'}).status_code==200
    for kind in ('inspection','action','followup'):
        payload={'request_id':uuid.uuid4().hex,'kind':kind,'note':'Synthetic workflow test record','observed_at':datetime.now(timezone.utc).isoformat()}
        r=post(client,f'/incidents/{key}/observations',payload);assert r.status_code==200,r.text
        assert post(client,f'/incidents/{key}/observations',payload).json()==r.json()
    r=post(client,f'/incidents/{key}/verify',ctx('overload'));assert r.json()['verification']['result']=='insufficient_evidence'
    assert post(client,f'/incidents/{key}/state',{'state':'resolved'}).status_code==409


def test_blind_challenge_hides_label(client):
    r=post(client,'/challenge',{'scenario':'sensor'}).json();key=r['id']
    snap=client.get('/api/halo/challenge/'+key).json()
    assert snap['label'] is None
    assert post(client,f'/challenge/{key}/reveal',{}).status_code==409
    a=post(client,f'/challenge/{key}/assess',{}).json()
    assert 'scenario' not in json.dumps(a['evidence_snapshot']) and 'label' not in a['evidence_snapshot']
    assert post(client,f'/challenge/{key}/reveal',{}).json()['label']=='sensor'


def test_laya_choices_and_invalid_response_fallback(client,monkeypatch):
    monkeypatch.setenv('HALO_AI_ENABLED','1')
    def fake(*args,**kwargs):
        assert 'scenario' not in kwargs['json']['state']
        return httpx.Response(200,request=httpx.Request('POST','http://127.0.0.1:8766'),json={'answers':{
            'hypothesis':{'choice':'expected_load_response','probabilities':dict.fromkeys(ai.HYPOTHESES,.25)},
            'inspection':{'choice':'check_load','probabilities':dict.fromkeys(ai.INSPECTIONS,.25)}}})
    monkeypatch.setattr(ai.httpx,'post',fake)
    a=ai.assess(engine.snapshot(engine.demonstration('overload'),'simulated','TEST'),[],True)
    assert a['provider']=='laya' and a['model_confidence'] is None and a['distributions']
    stale=engine.snapshot([]);a=ai.assess(stale,[],True)
    assert a['hypothesis']=='insufficient_evidence' and a['policy_override']
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:httpx.Response(200,request=httpx.Request('POST','http://local'),json={}))
    assert ai.assess(stale,[],True)['provider']=='rules'


def test_telegram_preview_never_sends_or_changes_state(client):
    i=post(client,'/incidents',ctx('overload')).json()
    r=post(client,'/telegram/preview',{'text':'/ack '+i['id']}).json()
    assert r['sent'] is False and store.get('incident',i['id'])['state']=='open'
    assert 'unavailable' in post(client,'/telegram/preview',{'text':'/status BENCH-001'}).json()['reply']


def test_command_rechecked_at_delivery(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    first=frame(calibration_id='CAL-TEST');client.post('/api/halo/telemetry',json=first,headers=DEVICE)
    r=post(client,'/relays',{'states':[True,True,False,False],'request_id':uuid.uuid4().hex});assert r.status_code==200
    next_frame=frame(sequence=2,uptime_ms=2000,surface_c=70,timestamp=datetime.now(timezone.utc).isoformat(),calibration_id='CAL-TEST')
    assert client.post('/api/halo/telemetry',json=next_frame,headers=DEVICE).status_code==200
    assert client.get('/api/halo/device/commands',headers=DEVICE).json()['commands']==[]
    assert store.get('command',r.json()['id'])['status']=='cancelled'


def test_manual_ambient_expires_and_is_labelled(client):
    old=(datetime.now(timezone.utc)-timedelta(minutes=12)).isoformat()
    assert post(client,'/ambient',{'value_c':29,'reference':'Reference thermometer','reviewer':'Tester','observed_at':old}).status_code==422
    with pytest.raises(ValueError):Frame.model_validate(frame(ambient_c=29,ambient_source='manual',ambient_observed_at=old))
    at=(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat()
    r=post(client,'/ambient',{'value_c':29,'reference':'Reference thermometer','reviewer':'Tester','observed_at':at});assert r.status_code==200
    assert client.get('/api/halo/device/config',headers=DEVICE).json()['ambient']['value_c']==29


def test_physical_verification_requires_comparable_conditions(client):
    configure(client);calibration(client)
    now=datetime.now(timezone.utc);action_at=now-timedelta(seconds=105)
    def rows(temp,current,ending):
        return [{**frame(sequence=i,uptime_ms=i*5000,timestamp=(ending-timedelta(seconds=5*(24-i))).isoformat(),
                         surface_c=temp,current_a=current,ambient_c=28,ambient_source='probe',calibration_id='CAL-TEST'),
                 'evidence_id':f'FIXTURE-{i}'} for i in range(25)]
    before=engine.snapshot(rows(50,.3,action_at-timedelta(seconds=5)))
    before['alerts']=[{'code':'thermal_deviation','title':'Fixture deviation','severity':'warning','evidence':'Synthetic fixture'}]
    incident=workflow.open_incident(before,'test')
    for kind,dt in [('inspection',action_at-timedelta(seconds=2)),('action',action_at),('followup',now-timedelta(seconds=1))]:
        incident=workflow.observe(incident,Observation(request_id=uuid.uuid4().hex,kind=kind,note='Test fixture evidence',observed_at=dt),'test')
    after=engine.snapshot(rows(46,.1,now));r=workflow.verify(incident,after,'test')
    assert r['verification']['result']=='insufficient_evidence'
    after=engine.snapshot(rows(46,.3,now));r=workflow.verify(incident,after,'test')
    assert r['verification']['result']=='improvement',r['verification']


def test_attachment_scoping_and_observation_idempotence(client):
    import base64,io
    from PIL import Image
    i=post(client,'/incidents',ctx('overload')).json();key=i['id'];out=io.BytesIO();Image.new('RGB',(8,8)).save(out,format='PNG')
    r=post(client,f'/incidents/{key}/attachments',{'filename':'proof.png','data_base64':base64.b64encode(out.getvalue()).decode()});assert r.status_code==200
    photo=r.json()['id'];assert client.get('/api/halo/attachments/'+photo).status_code==401
    assert client.get('/api/halo/attachments/'+photo,headers=OP).status_code==200
    p={'request_id':uuid.uuid4().hex,'kind':'inspection','note':'Reference check complete','observed_at':datetime.now(timezone.utc).isoformat(),'attachment_ids':[photo]}
    assert post(client,f'/incidents/{key}/observations',p).status_code==200
    assert post(client,f'/incidents/{key}/observations',{**p,'note':'Different evidence under same ID'}).status_code==409


def test_bridge_rms_bias_calibration_and_durable_queue(client,tmp_path):
    spec=importlib.util.spec_from_file_location('usb_bridge',Path(__file__).parents[1]/'scripts/usb_bridge.py');bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    raw={'type':'telemetry_raw','device_id':'HALO-ESP32','boot_id':'boot-test','sequence':1,'uptime_ms':2000,
         'primary_rms_mv':None,'secondary_rms_mv':1200,'current_rms_mv':300,'surface_raw_c':31,'relay_states':[True,False,False,False],'quality_flags':[]}
    anchor={'boot_id':'boot-test','uptime_ms':1000,'utc':datetime.now(timezone.utc)-timedelta(seconds=2)}
    r=bridge.convert(raw,anchor,{'id':'CAL','secondary_v_per_mv':.01,'current_a_per_mv':.001,'current_noise_mv':0,'surface_offset_c':.2})
    assert r['secondary_v']==12 and r['current_a']==.3 and r['surface_c']==31.2 and r['ambient_c'] is None
    queue=bridge.Outbox(tmp_path/'outbox.db');queue.append(r);queue.append(r);key,again=queue.next();assert again==r
    queue.finish(key,'delivered');assert queue.next() is None;queue.close()
    with pytest.raises(ValueError):bridge.convert({**raw,'uptime_ms':0},anchor,{})


@pytest.mark.parametrize('route',['/app','/judge','/sw.js','/static/halo.js','/static/halo-twin.js','/api/halo/passport/qr.png'])
def test_workspace_assets(client,route):assert client.get(route).status_code==200


def test_distribution_evidence_and_assistant_keep_study_identity(client):
    normal=client.get('/api/halo/snapshot',params={'mode':'transformer','scenario':'normal','cursor':180}).json()
    overload=client.get('/api/halo/snapshot',params={'mode':'transformer','scenario':'overload','cursor':180}).json()
    assert normal['evidence'][0]['id']!=overload['evidence'][0]['id']
    from neuratwin import halo_ai
    decision=halo_ai.assess(overload,[],True)
    reply=halo_ai.answer('What is the temperature?',overload,decision)
    assert 'inferred winding hot-spot' in reply['text'] and 'resistor' not in reply['text']
    assert reply['tool']['value']=='transformer'


def test_model_forecast_rejects_changed_measurement_calibration(client):
    snap=engine.snapshot(engine.demonstration('normal',180),'simulated','BENCH-SIM')
    model=engine.fit_surface(engine.demonstration('normal',360),'BENCH-001')
    snap.update(source='measured',connection='live',model={**model,'id':'MODEL-TEST','calibration_id':'OLD-CAL'})
    snap['quality']['calibration']='reference recorded'
    snap['current']['calibration_id']='NEW-CAL'
    result=engine.futures(snap)
    assert result['available'] is False and 'calibration' in result['reason']
