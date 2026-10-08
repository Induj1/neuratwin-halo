"""Submission regressions: source integrity, prospective evidence and recovery."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import zipfile
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import twin_core as core, twin_studies as studies, thermal_reference as thermal, halo_store as store
from neuratwin.halo_api import LOCAL_TOKEN

OP={'Authorization':'Bearer '+LOCAL_TOKEN}
BASE='/api/halo/twin/runs/'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'submission.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    for name in ('HALO_OPERATOR_TOKEN','HALO_ALLOW_CONTROL'):monkeypatch.delenv(name,raising=False)
    with TestClient(app) as c:yield c

def create(c,key='submission-test'):
    r=c.post(BASE[:-1],headers=OP,json={'request_id':key});assert r.status_code==200,r.text
    return r.json()

def act(c,s,name,**extra):
    r=c.post(BASE+s['id']+'/actions',headers=OP,json={'action':name,'revision':s['revision'],'request_id':f"cmd-{s['revision']:08d}",**extra})
    assert r.status_code==200,r.text
    return r.json()

def post(c,s,path,**extra):
    return c.post(BASE+s['id']+path,headers=OP,json={'request_id':'study-request-1','revision':s['revision'],**extra})

def test_active_warning_overrides_health_band_and_sensor_advice():
    s=core.create_state('audit');s['inputs']['load_percent']=125;core.evaluate(s,0)
    assert s['analysis']['health_index']>80
    assert 'Healthy' not in core.summary(s)['health_band']
    core.inject(s,'sensor')
    assert 'independent' in ' '.join(s['analysis']['maintenance']).lower()
    assert core.forecast(s)['available'] is False
    with pytest.raises(ValueError,match='disagreement'):studies.freeze(s,15)

def test_frozen_forecast_does_not_read_future_and_detects_tampering():
    s=core.create_state('immutable');p=studies.freeze(s,15)
    s['history'].append({'elapsed_s':60,'transformer_temperature':999})
    assert studies.freeze(s,15)==p
    assert studies.verify(p)
    p['points'][1]['temperature_c']+=1
    with pytest.raises(ValueError,match='integrity'):studies.score(p,s)

def test_score_separates_changed_inputs_unqualified_and_duplicate_instants():
    s=core.create_state('scope');p=studies.freeze(s,15)
    s['history']=[]
    for minute in (1,2,3):
        s['history'].append({'elapsed_s':minute*60,'transformer_temperature':p['initial_temperature_c'],
                             'input_signature':p['input_signature'],'channel_qualified':True})
    s['history']+=[deepcopy(s['history'][-1]),{'elapsed_s':240,'transformer_temperature':90,'input_signature':'changed','channel_qualified':True},
                    {'elapsed_s':300,'transformer_temperature':90}]
    result=studies.score(p,s)
    assert result['unchanged_inputs']['count']==3 and result['changed_input_samples']==1
    assert result['unqualified_samples']==1 and 'does not improve' in result['verdict']
    s['id']='wrong'
    with pytest.raises(ValueError,match='same run'):studies.score(p,s)

def test_api_proof_idempotence_and_source_scoping(client):
    s=create(client);other=create(client,'another-simulation')
    r=post(client,s,'/proofs',horizon_min=15);assert r.status_code==200,r.text
    p=r.json();assert studies.verify(p)
    assert post(client,s,'/proofs',horizon_min=15).json()==p
    assert post(client,s,'/proofs',horizon_min=30).status_code==409
    assert client.get(BASE+other['id']+'/case').json()['proofs']==[]
    s=act(client,s,'start');s=act(client,s,'step',seconds=300)
    result=client.get(BASE+s['id']+'/case').json()['proofs'][0]
    assert result['proof']==p and result['score']['unchanged_inputs']['count']>=3
    assert store.records('command')==[]

def test_plan_read_only_constraints_stale_and_simulation_only(client):
    s=create(client);s=act(client,s,'inputs',inputs={**s['inputs'],'load_percent':125})
    r=post(client,s,'/plans',horizon_min=30);assert r.status_code==200,r.text
    p=r.json();assert p['recommendation']['reduction_pct']>0
    assert any(not c['passes'] for c in p['candidates'])
    assert client.get(BASE+s['id']).json()['revision']==s['revision']
    other=create(client,'different-plan-asset')
    args={'plan_id':p['id'],'revision':s['revision']}
    assert client.post(BASE+other['id']+'/apply-plan',headers=OP,json=args).status_code==404
    applied=client.post(BASE+s['id']+'/apply-plan',headers=OP,json=args)
    assert applied.status_code==200,applied.text
    assert applied.json()['inputs']['load_percent']<125
    assert client.post(BASE+s['id']+'/apply-plan',headers=OP,json=args).json()==applied.json()
    assert store.records('command')==[]
    stale=post(client,applied.json(),'/plans',request_id='new-plan-request',horizon_min=30).json()
    newer=act(client,applied.json(),'start')
    assert client.post(BASE+s['id']+'/apply-plan',headers=OP,json={'plan_id':stale['id'],'revision':newer['revision']}).status_code==409

def test_no_feasible_plan_when_initial_thermal_state_exceeds_limit():
    s=core.create_state('too-hot');s['telemetry']['hotspot_temperature']=140
    result=studies.plan(s,30,0)
    assert result['recommendation'] is None

def test_workflow_needs_later_qualified_recovery(client):
    s=create(client)
    r=post(client,s,'/work',title='Review operating evidence',owner='Reviewer',acceptance='Compare later readings with the documented acceptance limits.')
    assert r.status_code==200,r.text
    w=r.json();path=BASE+s['id']+'/work/'+w['id']
    def update(status,rev):return client.post(path,headers=OP,json={'status':status,'revision':rev,'note':'Observed and recorded simulation evidence for review.'})
    assert update('closed',0).status_code==422
    assert update('in_progress',0).status_code==200
    assert update('verification_pending',1).status_code==200
    assert update('closed',2).status_code==422
    s=act(client,s,'start');s=act(client,s,'step',seconds=60)
    s=act(client,s,'inputs',inputs={**s['inputs'],'load_percent':115})
    assert update('closed',2).status_code==423
    s=act(client,s,'inputs',inputs={**s['inputs'],'load_percent':75})
    closed=update('closed',2)
    assert closed.status_code==200,closed.text
    assert len(closed.json()['trail'])==3 and closed.json()['trail'][-1]['elapsed_s']==60

def reference_csv():return Path('data/synthetic-oil-reference.csv').read_text()

def test_reference_rejects_surface_unknown_columns_and_insufficient_data(client):
    body={'request_id':'ref-request-001','name':'Synthetic fixture','reviewer':'Test reviewer','source':'synthetic','healthy_reviewed':True,
          'temperature_kind':'oil','csv_text':reference_csv()}
    url='/api/halo/twin/references'
    assert client.post(url,headers=OP,json={**body,'temperature_kind':'surface'}).status_code==422
    assert client.post(url,headers=OP,json={**body,'csv_text':body['csv_text'].replace('oil_c','surface_c')}).status_code==422
    r=client.post(url,headers=OP,json=body);assert r.status_code==200,r.text
    ref=r.json();assert ref['eligible'] and 'rows' not in ref and ref['source']=='synthetic'
    created=client.post(url+'/'+ref['id']+'/run',headers=OP,json={'request_id':'calibrated-run-1'})
    assert created.status_code==200,created.text
    assert created.json()['profile']['basis']=='synthetic_reference'
    assert 'remain illustrative' in created.json()['profile']['reference']
    with pytest.raises(ValueError,match='60 samples'):thermal.fit([])

def test_reference_fit_uses_training_only_and_chronological_validation():
    rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader(io.StringIO(reference_csv()))]
    fitted=thermal.fit(rows);changed=deepcopy(rows)
    for row in changed[int(len(rows)*.7):]:row['oil_c']+=10
    altered=thermal.fit(changed)
    assert fitted['rated_oil_rise_c']==altered['rated_oil_rise_c']
    assert fitted['oil_tau_min']==altered['oil_tau_min']
    assert altered['validation_rmse_c']>fitted['validation_rmse_c']
    changed[1]['elapsed_s']=changed[0]['elapsed_s']
    with pytest.raises(ValueError,match='chronological'):thermal.fit(changed)

def test_reference_detector_receives_observations_not_labels():
    rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader(io.StringIO(reference_csv()))]
    ref=thermal.fit(rows)
    for r in rows:r['hotspot_c']=r['oil_c']+23*(r['load_percent']/100)**1.6
    before=thermal.residual_screen(ref,rows)
    for r in rows:r['truth']='a different fault'
    assert thermal.residual_screen(ref,rows)==before
    rows[-1]['oil_c']=None
    assert thermal.residual_screen(ref,rows)=='missing_data'

def test_benchmark_keeps_misses_and_failures_visible(client):
    r=client.get('/api/halo/twin/validation').json()
    assert r['available'] and len(r['cases'])==30
    assert 0<r['detection']['events_detected']<r['detection']['events_total']
    assert r['detection']['false_alarm_minutes']>0
    assert any(c['scenario']!='healthy' and c['detection_delay_min'] is None for c in r['cases'])

def test_documented_profile_requires_provenance(client):
    assert client.post(BASE[:-1],headers=OP,json={'request_id':'missing-provenance','profile':{'basis':'manufacturer_document'}}).status_code==422


def test_changed_model_invalidates_comparable_window():
    s=core.create_state('changed-model');p=studies.freeze(s,15)
    s['settings']['oil_tau_min']*=1.3;s['running']=True;core.advance(s,180)
    result=studies.score(p,s)
    assert result['changed_input_samples']==3 and result['unchanged_inputs']['count']==0


def test_report_keeps_linked_proof_and_mixed_version_history(client):
    s=create(client);proof=post(client,s,'/proofs',horizon_min=15).json()
    saved=store.get('twin_run',s['id']);saved['history'][0].pop('input_signature');saved['history'][0].pop('channel_qualified')
    store.put('twin_run',s['id'],saved)
    s=act(client,s,'start');s=act(client,s,'step',seconds=180)
    r=client.get(BASE+s['id']+'/report');assert r.status_code==200,r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        report=json.loads(archive.read('run.json'));manifest=json.loads(archive.read('manifest.json'))
        assert report['forecasts'][0]['proof']==proof
        assert report['forecasts'][0]['score']['unchanged_inputs']['count']==3
        import hashlib
        for name,value in manifest.items():assert hashlib.sha256(archive.read(name)).hexdigest()==value
