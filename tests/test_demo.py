"""Synthetic fixtures test screening policy; none are field validation."""
import copy
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin import halo_engine as engine, halo_store as store, halo_demo
from neuratwin.halo_qualification import qualify

AUTH={'Authorization':'Bearer '+LOCAL_TOKEN}
DT={'mode':'transformer','scenario':'overload','cursor':148}


@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'demo.sqlite3'))
    monkeypatch.setenv('HALO_DEVICE_TOKEN','demo-test-device')
    for name in ('HALO_OPERATOR_TOKEN','HALO_ALLOW_CONTROL','HALO_AI_ENABLED'):
        monkeypatch.delenv(name,raising=False)
    with TestClient(app) as c:yield c


def plant():
    start=datetime(2026,1,1,tzinfo=timezone.utc); temp=30.;rows=[]
    for i in range(121):
        rows.append({'timestamp':(start+timedelta(seconds=5*i)).isoformat(),'surface_c':temp,
                     'ambient_c':25.,'current_a':.8,'secondary_v':12.,'evidence_id':str(i),
                     'relay_states':[True,True,False,False],'relay_output_configured':True,'calibration_id':'synthetic'})
        temp=engine.surface_step(temp,25,.8,5,[.005,.05,.005])
    snap=engine.snapshot(rows,'simulated','FIXTURE')
    snap['model']={'id':'EXACT-SYNTHETIC','beats_persistence':True,'coefficients':[.005,.05,.005],
                   'data_end_at':rows[0]['timestamp'],'current_range_a':[0,1],
                   'ambient_range_c':[20,30],'validation_span_s':600,'calibration_id':'synthetic'}
    return snap


def test_qualification_uses_three_disjoint_past_windows(client):
    snap=plant();q=qualify(snap,3)
    assert q['status']=='qualified' and q['recommendations_allowed']
    assert len(q['windows'])==3
    assert all(w['count']==36 and w['beats_persistence'] for w in q['windows'])
    assert q['windows'][1]['end']==q['windows'][0]['origin']
    assert q['windows'][0]['end']==snap['current']['timestamp']


def test_latest_failure_cannot_hide_behind_older_wins(client):
    snap=plant();cut=len(snap['history'])-37;temp=snap['history'][cut]['surface_c']
    for row in snap['history'][cut:]:row['surface_c']=temp
    snap['current']=snap['history'][-1]
    q=qualify(snap,3)
    assert q['status']=='degraded' and not q['recommendations_allowed']
    assert q['windows'][0]['persistence_mae_c']==0
    assert all(w['beats_persistence'] for w in q['windows'][1:])


@pytest.mark.parametrize('problem',['missing','gap','changed_input','future_model','range','horizon','stale','calibration'])
def test_unqualified_conditions_withhold_recommendations(client,problem):
    snap=plant()
    if problem=='missing':snap['history'][-3]['surface_c']=None
    if problem=='gap':del snap['history'][-4:-1]
    if problem=='changed_input':
        for row in snap['history'][-20:]:row['current_a']=.4
    if problem=='future_model':snap['model']['data_end_at']=snap['current']['timestamp']
    if problem=='range':snap['model']['current_range_a']=[0,.5]
    if problem=='horizon':snap['model']['validation_span_s']=60
    if problem=='stale':snap['connection']='stale'
    if problem=='calibration':
        snap['source']='measured';snap['quality']['calibration']='reference recorded';snap['model']['calibration_id']='OLD'
    q=qualify(snap,3)
    assert not q['recommendations_allowed']


def test_unseen_future_samples_cannot_affect_qualification(client):
    snap=plant();before=qualify(snap,3)
    future=copy.deepcopy(snap['current']);future['timestamp']='2026-01-02T00:00:00+00:00';future['surface_c']=999
    snap['history'].append(future)
    assert qualify(snap,3)==before


def test_no_oil_check_certifies_hotspot_interventions(client):
    snap=client.get('/api/halo/snapshot',params=DT).json()
    q=qualify(snap,15)
    assert not q['recommendations_allowed'] and 'Oil forecast' in q['scope']


def test_both_planners_block_degraded_model(client,monkeypatch):
    snap=plant()
    for row in snap['history']:row['surface_c']=30
    snap['current']=snap['history'][-1]
    monkeypatch.setattr('neuratwin.halo_api.obtain',lambda **kwargs:snap)
    monkeypatch.setattr('neuratwin.halo_evidence_api.obtain',lambda **kwargs:snap)
    payload={'mode':'replay','horizon':3}
    plan=client.post('/api/halo/evidence/plan',json=payload,headers=AUTH).json()
    assert plan['qualification']['status']=='degraded'
    assert plan['recommendation'] is None and all(not c['qualifies'] for c in plan['candidates'])
    envelope=client.post('/api/halo/envelope',json=payload,headers=AUTH).json()
    assert not envelope['available'] and envelope['qualification']['status']=='degraded'


def test_readiness_is_authenticated_source_specific_and_command_free(client):
    assert client.post('/api/halo/demo/readiness',json=DT).status_code==401
    before=engine.config().model_dump();commands=store.records('command')
    r=client.post('/api/halo/demo/readiness',json=DT,headers=AUTH).json()
    assert r['ready'] and r['source']=='simulated'
    physical=client.post('/api/halo/demo/readiness',json={'mode':'bench'},headers=AUTH).json()
    assert not physical['ready'] and physical['k4_locked']
    assert any(c['name']=='Sensor freshness' and c['status']=='fail' for c in physical['checks'])
    assert store.records('command')==commands and engine.config().model_dump()==before


def test_missing_assets_fail_readiness_and_kit(client,monkeypatch,tmp_path):
    monkeypatch.setattr(halo_demo,'ROOT',tmp_path)
    r=client.post('/api/halo/demo/readiness',json=DT,headers=AUTH).json()
    assert not r['ready']
    assert client.post('/api/halo/demo/kit',headers=AUTH).status_code==409


def test_recording_does_not_substitute_simulation_for_hardware(client):
    client.get('/api/halo/snapshot',params=DT)
    assert client.post('/api/halo/demo/recording',headers=AUTH).status_code==409
    assert client.post('/api/halo/demo/recording').status_code==401
    row={'device_id':'HALO-ESP32','boot_id':'test-fixture','sequence':1,'uptime_ms':1000,
         'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),
         'secondary_v':12.,'current_a':.3,'surface_c':30.,'relay_states':[True,False,False,False],
         'relay_output_configured':True}
    assert client.post('/api/halo/telemetry',json=row,headers={'Authorization':'Bearer demo-test-device'}).status_code==200
    r=client.post('/api/halo/demo/recording',headers=AUTH)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        frame=json.loads(z.read('frames.json'))[0]
        assert frame['sequence']==1 and frame['secondary_v']==12.
        assert json.loads(z.read('provenance.json'))['count']==1
        for name,digest in json.loads(z.read('manifest.json')).items():assert hashlib.sha256(z.read(name)).hexdigest()==digest


def test_complete_demo_kit_and_self_contained_fallback(client):
    r=client.post('/api/halo/demo/kit',headers=AUTH)
    assert r.status_code==200,r.text[:100]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert len(manifest)==6 and 'halo-rehearsal.mp4' in manifest and 'halo-arena-guide.html' in manifest
        for name,digest in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
        page=z.read('halo-fallback.html').decode()
        assert '<script src=' not in page and 'fetch(' not in page
        assert 'PRECOMPUTED SYNTHETIC' in page
    workspace=client.get('/app').text
    assert 'id="view-demo"' in workspace and '<!-- HALO_DEMO -->' not in workspace


def test_case_includes_qualification_and_older_communication_records(client):
    store.put('acceptance','OLD-COMMS',{'asset_id':'DT-SIM','reviewer':'Fixture reviewer',
              'source':'demonstration_fixture','reference_instrument':'Fixture clock','calibration_reference':'Fixture',
              'checks':[{'name':'Data loss','unit':'s','status':'pass','response_kind':'software_acknowledgment'}]})
    result=client.post('/api/halo/evidence/export',json=DT,headers=AUTH)
    assert result.status_code==200
    with zipfile.ZipFile(io.BytesIO(result.content)) as z:
        case=json.loads(z.read('case.json'))
        assert 'qualification' in case and not case['qualification']['recommendations_allowed']
        assert 'Automatic forecast qualification' in z.read('report.html').decode()
