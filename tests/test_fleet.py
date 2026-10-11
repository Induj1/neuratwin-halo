from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import zipfile
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import fleet, fleet_api, halo_store as store, halo_evidence as evidence


@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'fleet.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('HALO_ESP32_URL','')
    monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    monkeypatch.setenv('HALO_AI_ENABLED','0')
    app.dependency_overrides[fleet_api.identity]=lambda:dict(user_id='local-owner',role='admin',mode='local rehearsal')
    with TestClient(app) as c:yield c
    app.dependency_overrides.pop(fleet_api.identity,None)


def post(c,path,body):
    return c.post('/api/halo/fleet'+path,json=body)


def create(c):
    r=post(c,'/runs',dict(request_id=str(uuid4()),seed=26));assert r.status_code==200,r.text
    return r.json()


def body(r,**kw):return dict(request_id=str(uuid4()),revision=r['revision'],**kw)
def tick(c,r,minutes=5):
    q=post(c,'/runs/'+r['id']+'/ticks',body(r,minutes=minutes));assert q.status_code==200,q.text
    return q.json()
def scenario(c,r,kind,asset='DEMO-R02'):
    q=post(c,'/runs/'+r['id']+'/scenarios',body(r,kind=kind,asset_id=asset));assert q.status_code==200,q.text
    return q.json()
def get(c,path):
    q=c.get('/api/halo/fleet'+path);assert q.status_code==200,q.text
    return q.json()


def test_deterministic_population_single_clock_and_duplicate_tick(client):
    a=create(client);b=create(client)
    assert len(a['assets'])==12 and sum(x['area']=='rural' for x in a['assets'])==6
    assert a['assets']==b['assets']
    assert any(f['rule']=='sensor_disagreement' for x in a['assets'] for f in x['findings'])
    request=body(a,minutes=15);first=post(client,'/runs/'+a['id']+'/ticks',request)
    again=post(client,'/runs/'+a['id']+'/ticks',request)
    assert first.json()==again.json()
    assert first.json()['minute']==15
    assert tick(client,b,15)['assets']==first.json()['assets']
    assert post(client,'/runs/'+a['id']+'/ticks',{**request,'minutes':30}).status_code==409
    assert post(client,'/runs/'+a['id']+'/ticks',body(a,minutes=5)).status_code==409


def test_unknown_never_healthy_and_disconnect_retains_finding(client):
    r=create(client);unknown=next(a for a in r['assets'] if a['tier']=='T0')
    assert unknown['condition']=='unknown' and unknown['coverage']['available']==0
    r=scenario(client,r,'disconnect');r=tick(client,r,60)
    a=next(a for a in r['assets'] if a['id']=='DEMO-R02')
    assert a['freshness']=='expired' and a['estimated_oil_c'] is None and a['findings']
    assert a['condition']=='warning' and a['priority']=='Inspect'
    assert post(client,'/runs/'+r['id']+'/forecasts',body(r,asset_id=a['id'])).status_code==422


def test_historical_recovery_does_not_reanimate_live_data(client):
    r=scenario(client,create(client),'disconnect');r=tick(client,r,30)
    path='/runs/'+r['id']+'/assets/DEMO-R02';before=get(client,path)['asset']
    batch=get(client,path+'/harvest');assert len(batch['rows'])==30
    # Browser JSON.stringify serializes integral-valued floats as integers.
    for row in batch['rows']:
        for channel in row['channels'].values():
            if isinstance(channel['value'],float) and channel['value'].is_integer():channel['value']=int(channel['value'])
    accepted=post(client,'/import-batches',batch);assert accepted.status_code==200,accepted.text
    assert accepted.json()['accepted']==30
    assert post(client,'/import-batches',batch).json()['duplicates']==30
    changed=deepcopy(batch);changed['rows'][0]['minute']=100
    assert post(client,'/import-batches',changed).status_code==409
    assert get(client,path)['asset']==before
    assert get(client,path+'/history')['total']==31
    batch['batch_id']=str(uuid4());batch['origin']='physical'
    assert post(client,'/import-batches',batch).status_code==422


def test_immutable_forecast_later_truth_and_changed_load_exclusions(client):
    r=create(client);f=post(client,'/runs/'+r['id']+'/forecasts',body(r,asset_id='DEMO-U02')).json()
    assert f['target']=='oil'
    frozen=deepcopy(store.get('fleet_forecast',f['id']))
    assert get(client,'/forecasts/'+f['id']+'/score')['status']=='unscored'
    r=get(client,'/runs/'+r['id']+'/snapshot');r=tick(client,r,5)
    score=get(client,'/forecasts/'+f['id']+'/score');assert len(score['samples'])==5 and score['persistence_mae_c'] is not None
    r=scenario(client,r,'reduce_load','DEMO-U02');r=tick(client,r,5)
    score=get(client,'/forecasts/'+f['id']+'/score');assert len(score['excluded'])==5
    assert store.get('fleet_forecast',f['id'])==frozen


def test_modelled_oil_not_scored_as_independent_truth(client):
    r=create(client);f=post(client,'/runs/'+r['id']+'/forecasts',body(r,asset_id='DEMO-R02')).json()
    r=get(client,'/runs/'+r['id']+'/snapshot');tick(client,r,15)
    score=get(client,'/forecasts/'+f['id']+'/score');assert score['status']=='unscored' and score['excluded']


def test_synthetic_scenarios_cannot_address_bench_or_issue_relays(client):
    r=create(client)
    assert post(client,'/runs/'+r['id']+'/scenarios',body(r,asset_id='BENCH-001',kind='disconnect')).status_code==404
    assert post(client,'/runs/'+r['id']+'/scenarios',body(r,asset_id='DEMO-U01',kind='trip_all')).status_code==422
    assert not store.records('command')


def make_job(c,r,asset='DEMO-U02'):
    q=post(c,'/runs/'+r['id']+'/jobs',body(r,asset_id=asset,title='Inspect thermal condition',assignee='local-owner',procedure='Synthetic test procedure'))
    assert q.status_code==200,q.text
    return q.json()


def update(c,j,operation,**kw):
    p=dict(request_id=str(uuid4()),revision=j['revision'],operation=operation,note='Recorded synthetic test evidence',**kw)
    q=post(c,'/jobs/'+j['id'],p);assert q.status_code==200,q.text
    return q.json()


def test_jobs_reviewer_roles_idempotent_visits_and_inconclusive_outcome(client):
    r=create(client);j=make_job(client,r)
    original=deepcopy(j['evidence'])
    j=update(client,j,'accept')
    visit=dict(request_id=str(uuid4()),revision=j['revision'],operation='visit',note='Inspection recorded',observed_at=datetime.now(timezone.utc).isoformat())
    first=post(client,'/jobs/'+j['id'],visit);assert first.status_code==200
    assert post(client,'/jobs/'+j['id'],visit).json()==first.json()
    j=first.json();assert len(j['visits'])==1
    app.dependency_overrides[fleet_api.identity]=lambda:dict(user_id='unassigned',role='operator',mode='test')
    assert post(client,'/jobs/'+j['id'],{**visit,'request_id':str(uuid4()),'revision':j['revision']}).status_code==403
    assert post(client,'/jobs/'+j['id'],{**visit,'request_id':str(uuid4()),'operation':'review','revision':j['revision']}).status_code==403
    app.dependency_overrides[fleet_api.identity]=lambda:dict(user_id='local-owner',role='admin',mode='local rehearsal')
    j=update(client,j,'review');assert j['outcome']['classification']=='inconclusive'
    assert j['evidence']==original


def test_mitigation_requires_later_observations_and_is_not_repair(client):
    r=create(client);j=make_job(client,r,'DEMO-R06');j=update(client,j,'accept')
    j=update(client,j,'visit',observed_at=datetime.now(timezone.utc).isoformat());j=update(client,j,'action')
    r=get(client,'/runs/'+r['id']+'/snapshot');tick(client,r,15)
    j=update(client,j,'review')
    assert j['outcome']['classification']=='mitigated'
    assert j['outcome']['basis']=='synthetic simulation acceptance'


def test_cost_unknowns_preserved_and_export_has_adverse_outcomes(client):
    r=create(client);j=make_job(client,r);update(client,j,'review')
    q=post(client,'/runs/'+r['id']+'/costs',dict(option='meter_only',source='Unpriced demo scenario'));assert q.status_code==200
    assert q.json()['annual_total'] is None
    q=client.get('/api/halo/fleet/runs/'+r['id']+'/export?format=zip');assert q.status_code==200,q.text
    with zipfile.ZipFile(io.BytesIO(q.content)) as z:
        d=json.loads(z.read('evidence.json'));assert d['jobs'][0]['outcome']['classification']=='inconclusive'
        assert set(z.namelist())=={'evidence.json','readings.csv','manifest.json'}
    pdf=client.get('/api/halo/fleet/runs/'+r['id']+'/export?format=pdf');assert pdf.content.startswith(b'%PDF')


def test_configuration_change_withholds_forecast_and_scoring():
    snap=dict(model={'beats_persistence':True,'calibration_id':'C1','config_id':'OLD'},source='measured',connection='live',
              quality={'calibration':'reference recorded'},configuration_binding={'state':'bound'},current={'calibration_id':'C1','config_id':'NEW'})
    assert 'configuration' in evidence.model_ready(snap)
    proof=dict(target='surface_c',origin='2026-10-11T00:00:00+00:00',horizon_min=5,initial_c=30,inputs={},
               points=[{'minute':0,'predicted_c':30},{'minute':5,'predicted_c':35}],calibration_id='C1',config_id='OLD',requires_config_binding=True)
    score=evidence.score_prediction(proof,[dict(timestamp='2026-10-11T00:01:00+00:00',surface_c=31,calibration_id='C1',config_id='NEW')])
    assert score['all_observations']['count']==0
