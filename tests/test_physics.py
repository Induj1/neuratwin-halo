from copy import deepcopy
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from neuratwin import prototype_physics as p,halo_store as store
from neuratwin.briefing_api import PhysicsRequest,PhysicsOptions,PDFRequest,physics_result,report_snapshot
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN

def rows(k=1,t=40,n=61):
    return [dict(timestamp=(datetime(2026,10,10,tzinfo=timezone.utc)+timedelta(seconds=i*2)).isoformat(),sample_key=str(i),boot_id='one',current_a=k,temperature_c=t,voltage_v=12,current_source='frontend_estimated') for i in range(n)]

def test_thermal_solution_and_demo_clock():
    a=p.Settings(clock_scale=1);b=p.Settings(clock_scale=60)
    assert p.oil_target(1,a)==80
    assert p.oil_step(40,1,5400,a)==pytest.approx(80+(40-80)/__import__('math').e)
    assert p.assess(rows(),b)['oil_c']>p.assess(rows(),a)['oil_c']

def test_pressure_expansion_reference_and_tank_types():
    a=p.Settings();assert p.fluid(25,a)['pressure_kpa']==pytest.approx(0)
    assert p.fluid(80,a)['pressure_kpa']>p.fluid(40,a)['pressure_kpa']
    assert p.fluid(80,p.Settings(gas_litres=30))['pressure_kpa']<p.fluid(80,a)['pressure_kpa']
    f=p.fluid(80,p.Settings(tank='conservator'));assert f['pressure_kpa'] is None
    assert f['level_percent']>40
    assert not p.fluid(200,p.Settings(gas_litres=1))['valid']

def test_duplicate_gap_and_source_hold_are_not_new_exposure():
    data=rows();copy=deepcopy(data);a=p.assess(data,p.Settings());b=p.assess(data+data,p.Settings())
    assert a==b and data==copy
    data[-1]['timestamp']='2026-10-11T00:00:00Z'
    assert p.assess(data,p.Settings())['skipped_seconds']>80000
    data[-1]['temperature_c']=None
    assert not p.assess(data,p.Settings())['available']
    assert not p.assess(rows(k=4),p.Settings())['available']

def test_minimum_discrete_shedding_and_lower_forecast():
    r=p.assess(rows(k=1.4,n=1),p.Settings(),branches=3)
    rec=r['recommendation'];assert rec['branches_to_shed']==1
    assert rec['sufficient'] and rec['peak_after_c']<rec['peak_before_c']
    assert rec['load_reduction_percent']==pytest.approx(100/3)

def test_injection_freezes_on_duplicate_samples_and_latches():
    data=rows(n=61);start=datetime(2026,10,10,tzinfo=timezone.utc).timestamp()
    gas=p.assess(data,p.Settings(tank='conservator'),fault='gas',fault_at=start)
    assert gas['gas_ml']==720 and gas['stage']=='trip'
    assert gas==p.assess(data+data,p.Settings(tank='conservator'),fault='gas',fault_at=start)
    surge=p.assess(data,p.Settings(),fault='surge',fault_at=start)
    assert surge['stage']=='trip' and not surge['recommendation']['sufficient']
    with pytest.raises(ValueError):PhysicsOptions(fault='gas',fault_at=datetime.now(timezone.utc))

def test_deenergized_model_cools_and_has_no_fem_heat():
    data=rows(k=0,t=60)
    for r in data:r['voltage_v']=0
    r=p.assess(data,p.Settings());assert r['oil_c']<60 and not r['energized']
    f=p.fem(0,energized=False);assert f['peak_c']==25 and f['heat_input_w']==0

def test_fem_conservation_response_and_mesh_refinement():
    a=p.fem(.5);b=p.fem(1);fine=p.fem(1,n=36)
    assert a['peak_c']<b['peak_c']
    assert b['balance_error_w']<1e-8
    assert abs(fine['peak_c']-b['peak_c'])/(fine['peak_c']-25)<.15
    assert len(b['triangles'])==648

def test_sensor_study_is_repeatable_and_accessible():
    a=p.sensor_study();assert a==p.sensor_study()
    for r in a['results']:
        assert len(r['node_ids'])==r['sensors']
        assert all(i in a['candidate_nodes'] for i in r['node_ids'])
        assert r['rmse_c']>=0

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'physics.sqlite3'));monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite');monkeypatch.setenv('HALO_ESP32_URL','');monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c

def test_readonly_revision_guard_pdf_and_auth(client):
    op={'Authorization':'Bearer '+LOCAL_TOKEN}
    run=client.post('/api/halo/twin/runs',headers=op,json={'request_id':'physics-test'}).json()
    original=deepcopy(store.get('twin_run',run['id']))
    route='/api/halo/twin/physics/'+run['id']
    r=client.post(route,headers=op,json={'revision':run['revision']});assert r.status_code==200,r.text
    assert r.json()['available'] and store.get('twin_run',run['id'])==original
    assert client.post(route,headers=op,json={'revision':run['revision']+1}).status_code==409
    snap=report_snapshot(run['id'],PDFRequest(physics_options=PhysicsOptions(),revision=run['revision']))
    result=snap['assessment']['physics_and_protection'];assert result['input_sha256']==r.json()['input_sha256']
    assert 'triangles' not in result['fem']
