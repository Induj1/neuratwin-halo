from copy import deepcopy
from datetime import datetime, timezone, timedelta
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import twin_core as core, halo_store as store
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.halo_contracts import BenchConfig, Frame

OP={'Authorization':'Bearer '+LOCAL_TOKEN};DEVICE={'Authorization':'Bearer twin-test-device'}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'twin.sqlite3'))
    monkeypatch.setenv('HALO_DEVICE_TOKEN','twin-test-device')
    for k in ('HALO_ALLOW_CONTROL','HALO_OPERATOR_TOKEN'):monkeypatch.delenv(k,raising=False)
    with TestClient(app) as c:yield c


def create(c,key='run-test-0001'):
    r=c.post('/api/halo/twin/runs',headers=OP,json={'request_id':key});assert r.status_code==200,r.text
    return r.json()


def action(c,s,name,**data):
    payload={'action':name,'revision':s['revision'],'request_id':f"action-{s['revision']:06d}",**data}
    return c.post('/api/halo/twin/runs/'+s['id']+'/actions',headers=OP,json=payload)


def test_normalized_source_contract_and_unknowns():
    t=core.Telemetry(timestamp=datetime.now(timezone.utc),source='prototype',transformer_id='BENCH-001',temperature_kind='surface')
    assert t.primary_current is None and t.oil_temperature is None
    with pytest.raises(ValueError):core.Telemetry(**{**t.model_dump(),'oil_temperature':45})
    with pytest.raises(ValueError):core.Telemetry(**{**t.model_dump(),'timestamp':datetime.now()})
    with pytest.raises(ValueError):core.Inputs(load_percent=float('nan'))


@pytest.mark.parametrize('kwargs',[{'load_critical':90},{'temperature_trip':100},{'recovery_temperature':115},{'voltage_trip_pu':.05},{'health_degraded':80}])
def test_threshold_ordering(kwargs):
    with pytest.raises(ValueError):core.Settings(**kwargs)


def test_electrical_conservation_and_thermal_inertia():
    s=core.create_state('TEST');before=deepcopy(s);s['running']=True;s['inputs']['load_percent']=100
    e=core.electrical(s)
    assert e['primary_voltage']*e['primary_current']*3**.5==pytest.approx(e['secondary_voltage']*e['secondary_current']*3**.5+e['losses_w'])
    core.advance(s,5)
    assert 0<s['oil_c']-before['oil_c']<1
    assert s['telemetry']['secondary_current']>before['telemetry']['secondary_current']


def test_determinism_and_integration_step_invariance():
    a=core.create_state('SAME');b=deepcopy(a)
    for s in (a,b):s['running']=True;s['inputs']['load_percent']=140
    core.advance(a,300)
    for _ in range(5):core.advance(b,60)
    assert a['oil_c']==pytest.approx(b['oil_c'])
    assert a['trip']['timestamp']==b['trip']['timestamp']
    assert a['trip']['before']==b['trip']['before']


def test_overload_delayed_trip_has_before_after_and_no_hardware(client):
    s=create(client);s=action(client,s,'scenario',scenario='overload').json()
    assert s['analysis']['status']=='CRITICAL' and s['breaker']=='CLOSED'
    s=action(client,s,'start').json();s=action(client,s,'step',seconds=120).json()
    assert s['breaker']=='OPEN' and s['trip_count']==1
    assert s['trip']['before']['loading_percent']==140
    assert s['trip']['after']['secondary_current']==0
    assert store.records('command')==[]
    assert any(e['kind']=='trip' for e in s['events'])
    assert 'Investigate' in s['analysis']['maintenance'][0]
    assert s['health_band']=='Trip review required'


def test_no_auto_reconnection_hysteresis_and_investigation():
    s=core.create_state('TRIP');s['running']=True;core.inject(s,'short_circuit')
    assert s['breaker']=='OPEN'
    s['fault']=None;core.advance(s,300)
    assert s['breaker']=='OPEN' and 'Record a fault investigation' in ' '.join(core.recovery_holds(s))
    core.maintain(s,'fault_investigation','Fault inspected; simulation only')
    assert core.recovery_holds(s)==[]
    s['inputs']['load_percent']=120
    assert core.recovery_holds(s)


def test_cooling_failure_forecast_and_history():
    healthy=core.create_state('H');failed=deepcopy(healthy)
    for s in (healthy,failed):s['running']=True;s['inputs']['load_percent']=100
    failed['inputs']['cooling']='failed'
    assert core.forecast(failed)['minutes_to_critical'] is not None
    core.advance(healthy,3600);core.advance(failed,3600)
    assert failed['oil_c']>healthy['oil_c']
    assert any(e['kind']=='trip' for e in failed['events'])


def test_low_storm_does_not_automatically_trip():
    s=core.create_state('STORM');s['running']=True;core.inject(s,'storm',1,120);core.advance(s,120)
    assert s['breaker']=='CLOSED' and s['trip_count']==0


@pytest.mark.parametrize('fault',['surge','short_circuit','overcurrent','overvoltage','undervoltage','low_oil','gas','combined'])
def test_severe_faults_trip(fault):
    s=core.create_state('FAULT');s['running']=True;core.inject(s,fault,3,300);core.advance(s,180)
    assert s['breaker']=='OPEN',fault


def test_sensor_fault_generates_residual_without_corrupting_physics():
    s=core.create_state('SENSOR');oil=s['oil_c'];core.inject(s,'sensor')
    assert s['oil_c']==oil
    assert any(a['code']=='sensor_residual' and a['category']=='trend_anomaly' for a in s['analysis']['alerts'])


def test_maintenance_cannot_rejuvenate_insulation():
    s=core.create_state('OLD');s['equivalent_age_hours']=90000;core.trip(s,'Maintenance isolation')
    s['inputs']['oil_condition']=30
    core.maintain(s,'oil_service','Synthetic oil replacement')
    assert s['equivalent_age_hours']==90000 and s['inputs']['oil_condition']==95
    assert s['breaker']=='OPEN'


def test_simulation_disable_cannot_disable_hardware(client):
    s=create(client);inputs={**s['inputs'],'protection_enabled':False,'load_percent':240}
    s=action(client,s,'inputs',inputs=inputs).json();s=action(client,s,'start').json();s=action(client,s,'step',seconds=120).json()
    assert s['breaker']=='CLOSED' and s['analysis']['status']=='TRIP'
    assert client.get('/api/halo/status').json()['hardware_control_enabled'] is False
    assert store.records('command')==[]


def test_auth_idempotence_conflicts_and_persistence(client):
    assert client.post('/api/halo/twin/runs',json={'request_id':'test-unauth'}).status_code==401
    s=create(client);assert create(client)['id']==s['id']
    first=action(client,s,'start');assert first.status_code==200
    assert action(client,s,'start').json()['revision']==first.json()['revision']
    assert action(client,s,'pause').status_code==409
    assert client.get('/api/halo/twin/runs/'+s['id']).json()['running']
    stale=client.post('/api/halo/twin/runs/'+s['id']+'/actions',headers=OP,json={'request_id':'different-id','revision':0,'action':'pause'})
    assert stale.status_code==409


def test_report_is_complete_escaped_and_hashed(client):
    s=create(client);s=action(client,s,'maintenance',maintenance='inspection',note='<script>bad()</script>').json()
    r=client.get('/api/halo/twin/runs/'+s['id']+'/report');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist())=={'run.json','report.html','telemetry.csv','manifest.json'}
        assert '<script>bad' not in z.read('report.html').decode()
        assert '&lt;script&gt;' in z.read('report.html').decode()
        d=json.loads(z.read('run.json'));assert d['full_events'] and d['metrics']['trip_count']==0


def test_prototype_never_falls_back_to_simulation(client):
    s=client.get('/api/halo/twin/prototype').json()
    assert s['source']=='prototype' and s['analysis']['health_index'] is None
    assert s['connection']=='disconnected' and s['telemetry']['oil_temperature'] is None
    assert s['telemetry']['primary_current'] is None and s['condition']['conditional_life_years'] is None


def test_optional_primary_current_pipeline(client):
    t=datetime.now(timezone.utc)-timedelta(seconds=1)
    payload={'source':'prototype','transformer_id':'BENCH-001','device_id':'HALO-ESP32','boot_id':'dual-current',
             'sequence':1,'uptime_ms':1000,'timestamp':t.isoformat(),'primary_current':.06,
             'primary_voltage':230,'secondary_voltage':12,'secondary_current':.6,'transformer_temperature':31}
    assert client.post('/api/halo/device/twin-telemetry',json=payload).status_code==401
    r=client.post('/api/halo/device/twin-telemetry',headers=DEVICE,json=payload);assert r.status_code==200,r.text
    s=client.get('/api/halo/twin/prototype').json();assert s['telemetry']['primary_current']==.06
    assert s['telemetry']['quality']=='unverified' and s['analysis']['health_index'] is None
    assert client.post('/api/halo/device/twin-telemetry',headers=DEVICE,json={**payload,'oil_temperature':42}).status_code==422
    assert store.records('command')==[]


def test_legacy_frames_retry_without_new_optional_channel(client):
    from test_halo import frame
    f=Frame.model_validate(frame())
    from neuratwin.storage import database,now
    old=f.model_dump(mode='json');old.pop('primary_current_a')
    with database() as db:
        store.initialise(db)
        db.execute('INSERT INTO halo_frames(device_id,boot_id,sequence,timestamp,received_at,content) VALUES (?,?,?,?,?,?)',
                   (f.device_id,f.boot_id,f.sequence,f.timestamp.isoformat(),now(),json.dumps(old)))
    r=client.post('/api/halo/telemetry',headers=DEVICE,json=old)
    assert r.status_code==200 and r.json()['duplicate']


def test_monitoring_mode_logs_decision_without_physical_command(client):
    from test_halo import configure,calibration,frame
    configure(client);calibration(client)
    r=client.post('/api/halo/telemetry',headers=DEVICE,json=frame(current_a=1.2,calibration_id='CAL-TEST'))
    assert r.status_code==200
    s=client.get('/api/halo/twin/prototype').json()
    assert s['latched'] and not s['control_enabled'] and not store.records('command')
    assert s['breaker'].startswith('UNKNOWN')
    assert s['protection_state']=='TRIP DECISION · no cutoff command'
    assert 'latched trip' in s['analysis']['maintenance'][0]


def test_primary_current_pin_must_be_unique_and_adc1():
    from test_halo import configure
    defaults=dict(board='ESP32',primary_adc_pin=32,secondary_adc_pin=33,current_adc_pin=34,temperature_pin=25,pinmap_verified=True)
    with pytest.raises(ValueError):BenchConfig(**defaults,primary_current_adc_pin=32)
    with pytest.raises(ValueError):BenchConfig(**defaults,primary_current_adc_pin=5)
    assert BenchConfig(**defaults,primary_current_adc_pin=35).primary_current_adc_pin==35


def test_unqualified_prototype_channels_cannot_create_healthy_state(client):
    from test_halo import configure,calibration,frame
    configure(client);calibration(client)
    client.post('/api/halo/telemetry',headers=DEVICE,json=frame(surface_c=None,calibration_id='CAL-TEST'))
    result=client.get('/api/halo/twin/prototype').json()
    assert result['analysis']['status']=='UNKNOWN' and result['analysis']['health_index'] is None


def test_automatic_off_is_opt_in_latched_and_never_reconnects(client,monkeypatch):
    from test_halo import configure,calibration,frame
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    config=client.get('/api/halo/config').json()['config'];config['automatic_cutoff_enabled']=True
    assert client.put('/api/halo/config',headers=OP,json=config).status_code==200
    f=frame(current_a=1.05,calibration_id='CAL-TEST')
    assert client.post('/api/halo/telemetry',headers=DEVICE,json=f).status_code==200
    commands=store.records('command');assert len(commands)==1 and commands[0]['states']==[False]*4
    assert store.get('twin_prototype','BENCH-001')['latched']
    assert client.post('/api/halo/telemetry',headers=DEVICE,json=f).status_code==200
    assert len(store.records('command'))==1
    assert client.post('/api/halo/relays',headers=OP,json={'states':[True,False,False,False],'request_id':'test-no-reclose'}).status_code==423
    assert client.post('/api/halo/twin/prototype/reset-latch',headers=OP,json={'note':'Review fixture only'}).status_code==423
    ack=client.post('/api/halo/device/commands/'+commands[0]['id']+'/ack',headers=DEVICE,json={'states':[False]*4,'accepted':True})
    assert ack.status_code==200
    s=client.get('/api/halo/twin/prototype').json()
    assert s['protection_state']=='OFF ACKNOWLEDGED · contacts unverified' and s['breaker'].startswith('UNKNOWN')
