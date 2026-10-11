from copy import deepcopy
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import prototype_physics as p,protection_study as study,halo_store as store
from neuratwin.briefing_api import PhysicsOptions,PhysicsRequest,physics_result
from neuratwin.halo_api import LOCAL_TOKEN

BASE=datetime(2026,10,11,tzinfo=timezone.utc)


def samples(current=1.5,voltage=12,calibrated=True,count=12):
    return [dict(timestamp=(BASE+timedelta(seconds=i)).isoformat(),sample_key=str(i),boot_id='test',
        current_a=.6,observed_current_a=current,voltage_v=voltage,temperature_c=35,current_source='frontend_estimated',
        observed_current_source='measured',calibrated=calibrated,measurement_disagreement=True) for i in range(count)]


def test_mass_balance_stop_refill_and_forecast_keep_lost_oil():
    settings=p.Settings(clock_scale=1)
    actions=[dict(time=0,operation='leak',rate_l_min=2),dict(time=900,operation='stop')]
    ledger=p.oil_ledger(1000,settings,actions)
    assert ledger['missing_l']==30 and ledger['loss_rate_l_min']==0
    assert p.fluid(25,settings,ledger['missing_l'])['inventory_percent']==85
    forecast=p.trajectory(35,1,settings,leaked_l=30)
    assert all(v['inventory_l']==170 for v in forecast)
    actions.append(dict(time=1001,operation='refill',litres=10))
    ledger=p.oil_ledger(1100,settings,actions)
    assert ledger['missing_l']==20 and ledger['refilled_total_l']==10 and ledger['lost_total_l']==30
    actions.append(dict(time=1101,operation='refill',litres=100))
    assert p.oil_ledger(1102,settings,actions)['missing_l']==0


def test_reduced_capacity_changes_response_not_steady_state():
    settings=p.Settings()
    assert p.capacity(settings,170)<p.capacity(settings,200)
    assert p.oil_step(35,1,60,settings,inventory=170)>p.oil_step(35,1,60,settings,inventory=200)
    assert p.oil_step(35,1,1e9,settings,inventory=170)==pytest.approx(p.oil_step(35,1,1e9,settings,inventory=200))
    assert p.fluid(50,settings)['expanded_volume_l']>200
    assert p.fluid(50,settings)['inventory_l']==200


def test_live_fault_requires_calibrated_measurement_not_resistor_estimate():
    settings=p.Settings();raw=samples(current=8,voltage=2);before=deepcopy(raw)
    r=study.electrical(raw,settings,live=True)
    assert r['stage']=='suspected_short' and r['current_a']==8 and raw==before
    assert study.electrical(samples(current=8,voltage=2,calibrated=False),settings,live=True)['stage']=='unavailable'
    assert study.electrical(raw,settings,live=False)['stage']=='unavailable'
    assert study.electrical(samples(current=8,voltage=12),settings,live=True)['stage']=='overload'
    assert study.electrical(samples(current=8,voltage=2,count=3),settings,live=True)['stage']!='suspected_short'


def test_exposure_excludes_duplicates_gaps_and_reboots():
    data=samples(current=2,count=12);settings=p.Settings()
    r=study.electrical(data+data,settings,live=True)
    assert r['i2t_a2s']==44 and r['covered_seconds']==11
    data[-1]['timestamp']=(BASE+timedelta(seconds=60)).isoformat()
    assert study.electrical(data,settings,live=True)['covered_seconds']==10
    data=samples(current=8,voltage=2);data[-1]['boot_id']='reboot'
    assert study.electrical(data,settings,live=True)['stage']!='suspected_short'


def test_simulated_isolation_and_recovery_never_need_hardware():
    settings=p.Settings(impedance_percent=5)
    r=study.electrical([],settings,scenario=dict(kind='short',elapsed_seconds=10,current_pu=8))
    assert r['stage']=='isolated' and r['current_a']==0 and r['peak_a']==8 and r['prospective_fault_a']==20
    assert any(v['current_a']==8 and v['voltage_v']==pytest.approx(2.4) for v in r['trace'])
    assert study.electrical([],settings,scenario=dict(kind='recovery',elapsed_seconds=5,current_pu=8))['stage']=='normal'
    assert study.electrical([],p.Settings(fault_pickup_pu=10),scenario=dict(kind='short',elapsed_seconds=10,current_pu=8))['stage']!='isolated'


def test_inventory_validation_and_conditional_limit():
    with pytest.raises(ValueError):p.Settings(oil_warning_percent=85,oil_critical_percent=90)
    with pytest.raises(ValueError):PhysicsOptions(oil_actions=[dict(at=BASE,operation='leak',rate_l_min=0)])
    rows=samples(current=.6);start=BASE.timestamp()
    r=p.assess(rows,p.Settings(clock_scale=1),oil_actions=[dict(time=start,operation='leak',rate_l_min=2)])
    assert r['oil_time_to_limit_min']==pytest.approx((r['inventory_l']-180)/2)
    assert r['curves'][-1]['inventory_l']==0
    assert r['mitigated'][-1]['inventory_l']==0 and not r['recommendation']['sufficient']


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'protection.sqlite3'));monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('HALO_ESP32_URL','');monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c


def body(elapsed=10,kind='short'):
    return dict(options=dict(demo=dict(started_at=BASE.isoformat(),elapsed_seconds=elapsed,steps=[dict(seconds=0,load_percent=65)]),
        electrical=dict(kind=kind,elapsed_seconds=elapsed,current_pu=8)))


def test_job_freezes_evidence_and_requires_action_then_new_followup(client):
    headers={'Authorization':'Bearer '+LOCAL_TOKEN};route='/api/halo/twin/protection-jobs/BENCH-001'
    before=store.frames('HALO-ESP32')
    response=client.post(route,headers=headers,json={**body(),'request_id':'protection-test-job'})
    assert response.status_code==200,response.text
    job=response.json();frozen=deepcopy(job['study']);assert len(frozen['calculations'])==10
    repeated=client.post(route,headers=headers,json={**body(),'request_id':'protection-test-job'}).json();assert repeated['id']==job['id']
    endpoint=route+'/'+job['id']
    assert client.post(endpoint,headers=headers,json={**body(20,'recovery'),'job_revision':0,'operation':'verify','note':'Retest'}).status_code==422
    job=client.post(endpoint,headers=headers,json={**body(),'job_revision':0,'operation':'action','note':'Simulated repair recorded'}).json()
    job=client.post(endpoint,headers=headers,json={**body(20,'recovery'),'job_revision':job['revision'],'operation':'verify','note':'Follow-up under normal simulated load'}).json()
    assert job['status']=='model_recovered' and job['study']==frozen
    assert client.post(endpoint,headers=headers,json={**body(),'job_revision':0,'operation':'finding','note':'Stale update'}).status_code==409
    pdf=client.get(endpoint+'/report.pdf',headers=headers);assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    assert store.frames('HALO-ESP32')==before and not store.records('command')
    assert len(client.get(route,headers=headers).json())==1


def test_unqualified_high_current_keeps_fault_study_without_oil_fallback():
    r=study.electrical(samples(current=10),p.Settings(),live=True)
    assert r['stage']=='overload' and r['current_a']==10
