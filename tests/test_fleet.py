from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from neuratwin import fleet_model as f, halo_store as store
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.twin_studies import digest

OP={'Authorization':'Bearer '+LOCAL_TOKEN}


@pytest.fixture(scope='module')
def portfolio():
    return f.demonstration()


@pytest.fixture(scope='module')
def report(portfolio):
    return f.analyse(portfolio)


def test_demo_qualifies_some_and_withholds_failures_without_mutation(portfolio,report):
    assert report['source']=='synthetic'
    assert report['summary']['assets']==25
    assert 0<report['summary']['qualified']<25
    by_id={r['asset']['asset_id']:r for r in report['assets']}
    for key in ('DT-18','DT-24'):
        assert by_id[key]['card']['status']=='withheld'
        assert not by_id[key]['card']['forecast']
    assert by_id['DT-24']['priority']['stale']
    for row in report['assets']:
        card=row['card']
        if card['status']=='qualified_for_recording':
            assert card['metrics']['mae_c']<card['metrics']['persistence_mae_c']*.95
            assert card['metrics']['test_trajectory_coverage']>=.8
            assert not card['holds']


def test_test_data_never_selects_parameters_or_calibration_band(portfolio):
    asset=portfolio.assets[0]; first=f.qualify(asset)
    changed=deepcopy(asset)
    for row in changed.samples[int(len(changed.samples)*.8):]: row.oil_c+=12
    second=f.qualify(changed)
    assert first['parameters']==second['parameters']
    assert first['metrics']['band_radius_c']==second['metrics']['band_radius_c']
    assert first['data_sha256']!=second['data_sha256']
    assert second['status']=='withheld'


def test_quality_identity_and_excitation_holds(portfolio):
    sample=f.Sample(timestamp='2026-10-08T00:00:00Z',load_pu=.5,ambient_c=28,oil_c=50)
    assert sample.voltage_pu is None  # Absence must never become a fabricated healthy voltage.
    asset=deepcopy(portfolio.assets[0])
    for row in asset.samples:row.load_pu=.5
    assert 'span' in ' '.join(f.qualify(asset)['holds'])
    asset=deepcopy(portfolio.assets[0]);asset.samples[40].timestamp+=timedelta(seconds=50)
    assert 'regular' in ' '.join(f.qualify(asset)['holds'])
    payload=portfolio.assets[0].model_dump(mode='json');payload['samples'][1]['timestamp']=payload['samples'][0]['timestamp']
    with pytest.raises(ValueError):f.Asset(**payload)
    payload=portfolio.assets[0].model_dump(mode='json');payload['samples'][0]['timestamp']='2026-10-08T00:00:00'
    with pytest.raises(ValueError):f.Asset(**payload)


def test_transfer_conserves_demand_and_rejects_unqualified_out_of_range_and_ties(report):
    members=[r for r in report['assets'] if r['card']['status']=='qualified_for_recording' and r['asset']['tie_group']=='TIE-1']
    donor,receiver=members[:2]
    request=f.Transfer(donor=donor['asset']['asset_id'],receiver=receiver['asset']['asset_id'],kva=1,tie_capacity_kva=10,topology_reviewed=True)
    result=f.transfer(report,request)
    assert result['balance_error_kva']==pytest.approx(0,abs=1e-10)
    assert result['feasible_in_study'],result
    result=f.transfer(report,request.model_copy(update={'receiver':'DT-18'}))
    assert not result['feasible_in_study']
    assert any('tie' in h for h in result['holds'])
    assert any('qualified' in h for h in result['holds'])
    assert not f.transfer(report,request.model_copy(update={'kva':1000}))['feasible_in_study']
    assert not f.transfer(report,request.model_copy(update={'topology_reviewed':False}))['feasible_in_study']
    without_voltage=deepcopy(report)
    next(r for r in without_voltage['assets'] if r['asset']['asset_id']==request.receiver)['current']['voltage_pu']=None
    assert any('voltage evidence' in h for h in f.transfer(without_voltage,request)['holds'])
    with pytest.raises(ValueError):f.transfer(report,request.model_copy(update={'receiver':request.donor}))


def test_lab_trend_and_complete_cost_accounting():
    a=f.LabSample(timestamp='2026-10-01T00:00:00Z',hydrogen=10,methane=2,ethane=3,ethylene=4,acetylene=1,carbon_monoxide=20,lab_reference='LAB-1')
    b=a.model_copy(update={'timestamp':a.timestamp+timedelta(days=2),'hydrogen':14})
    r=f.lab_trend([a,b]);assert r['points'][0]['total_combustible_ppm']==40
    assert r['rates_ppm_per_day']['hydrogen']==2
    with pytest.raises(ValueError):f.lab_trend([b,a])
    option=f.CostOption(hardware=100,installation=50,commissioning=20,annual_connectivity=12,annual_service=10,replacement_allowance=30)
    r=f.costs(f.Costs(asset_count=10,years=5,halo=option,comparison=option,avoided_incident_value=1000))
    assert r['halo']['fleet_total']==3100
    assert r['cost_difference']==0 and r['break_even_avoided_incidents']==4


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'fleet.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('HALO_ESP32_URL','')
    monkeypatch.setenv('HALO_ESP32_DISCOVERY','0')
    monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c


def test_persistent_recording_case_revision_and_export(client,portfolio):
    payload=portfolio.model_copy(update={'assets':portfolio.assets[:2]})
    response=client.post('/api/halo/fleet/recordings',json=payload.model_dump(mode='json'),headers=OP)
    assert response.status_code==200,response.text
    saved=response.json();path='/api/halo/fleet/recordings/'+saved['id'];sha=saved['sha256']
    catalog=client.get('/api/halo/fleet/recordings',headers=OP).json()['recordings']
    assert catalog[0]['id']==saved['id'] and 'portfolio' not in catalog[0]
    assert len(saved['report']['implementation_sha256'])==64
    assert client.get(path,headers=OP).json()['sha256']==sha
    asset=saved['report']['assets'][0]['asset']['asset_id']
    case=client.post(path+'/cases',json={'asset_id':asset,'owner':'Operator','note':'Inspect thermal evidence'},headers=OP).json()
    original=deepcopy(case['frozen_evidence'])
    body={'revision':0,'status':'inspection_recorded','note':'Lab reference reviewed'}
    assert client.post(path+'/cases/'+asset,json=body,headers=OP).status_code==200
    assert client.post(path+'/cases/'+asset,json=body,headers=OP).status_code==409
    assert store.get('fleet_case',saved['id']+':'+asset)['frozen_evidence']==original
    transfer=client.post(path+'/transfer',json={'donor':'DT-01','receiver':'DT-02','kva':1,'tie_capacity_kva':10,'topology_reviewed':True},headers=OP)
    assert transfer.status_code==200,transfer.text
    assert transfer.json()['study_id'].startswith('STUDY-')
    option={'hardware':100,'installation':50,'commissioning':20,'annual_connectivity':12,'annual_service':10,'replacement_allowance':30}
    cost=client.post('/api/halo/fleet/costs',json={'recording_id':saved['id'],'asset_count':10,'years':5,'halo':option,'comparison':option},headers=OP)
    assert cost.status_code==200,cost.text
    export=client.get(path+'/export',headers=OP).json()
    assert export['sha256']==sha and len(export['cases'])==1
    assert len(export['studies'])==2
    export_hash=export.pop('export_sha256');export.pop('integrity_note')
    assert digest(export)==export_hash
    report=client.get(path+'/report.pdf',headers=OP)
    assert report.status_code==200
    assert 'Fleet evidence' in ''.join(p.extract_text() for p in PdfReader(BytesIO(report.content)).pages)
    assert not store.records('command')


def test_csv_validation_lab_append_and_asset_isolation(client):
    text=client.get('/api/halo/fleet/template.csv',headers=OP).text
    r=client.post('/api/halo/fleet/import',json={'name':'Test recording','source_note':'Lab reference, not verified','csv_text':text},headers=OP)
    assert r.status_code==200,r.text
    body=r.json();assert body['source']=='imported' and body['report']['summary']['withheld']==1
    path='/api/halo/fleet/recordings/'+body['id']+'/assets/'
    lab={'timestamp':'2026-10-10T12:00:00Z','hydrogen':1,'methane':2,'ethane':3,'ethylene':4,'acetylene':5,'carbon_monoxide':6,'lab_reference':'LAB-01'}
    assert client.post(path+'UNKNOWN/lab',json=lab,headers=OP).status_code==404
    assert client.post(path+'DT-01/lab',json=lab,headers=OP).status_code==200
    assert client.post(path+'DT-01/lab',json=lab,headers=OP).status_code==409
    assert client.get(path+'DT-01',headers=OP).json()['lab_trend']['points'][0]['total_combustible_ppm']==21
    bad=text.replace('2026-10-08T00:05:00+05:30','2026-10-08T00:00:00+05:30')
    assert client.post('/api/halo/fleet/import',json={'name':'Bad recording','source_note':'Duplicate timestamps','csv_text':bad},headers=OP).status_code==422


def test_physical_lifetime_defaults_inherit_saved_maintenance_profile(client):
    from neuratwin.maintenance_model import Profile
    from neuratwin.briefing_api import lifetime_result
    store.put('maintenance_profile','BENCH-001',{'revision':3,'profile':Profile(tau_min=42,rated_rise_c=40,temperature_limit_c=70).model_dump()})
    r=lifetime_result('BENCH-001',None)
    assert r['assumptions']['thermal_tau_min']==42
    assert r['assumptions']['limit_temperature_c']==70
    assert 'revision 3' in r['assumption_origin']
