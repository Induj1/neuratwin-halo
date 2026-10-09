from datetime import datetime, timezone, timedelta
import copy
import io
import json
import zipfile
import hashlib
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin import halo_store as store, halo_engine as engine, halo_evidence as evidence
from neuratwin.halo_contracts import BenchConfig


@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'evidence.sqlite3'))
    monkeypatch.delenv('HALO_OPERATOR_TOKEN',raising=False)
    monkeypatch.delenv('HALO_AI_ENABLED',raising=False)
    with TestClient(app) as c:yield c


AUTH={'Authorization':'Bearer '+LOCAL_TOKEN}
CTX={'mode':'replay','scenario':'normal','cursor':400}
DT={'mode':'transformer','scenario':'overload','cursor':148}


def post(client,path,payload):return client.post('/api/halo/evidence'+path,json=payload,headers=AUTH)


def fit(client):
    r=client.post('/api/halo/models/fit',json={**CTX,'cursor':360,'qualified_healthy':True,'note':'Independent synthetic healthy reference for regression tests'},headers=AUTH)
    assert r.status_code==200,r.text
    assert r.json()['beats_persistence']
    return r.json()


def test_rendered_workspace_includes_lab(client):
    page=client.get('/app').text
    assert 'id="view-evidence"' in page and '<!-- HALO_EVIDENCE -->' not in page
    assert 'surface_reference' in page
    assert '°C' in page and 'Â°C' not in page and 'â†' not in page


def test_per_channel_calibration_and_current_alarm(client):
    store.put('calibration','C1',{'secondary_v_per_mv':.01,'current_a_per_mv':.001})
    row={'timestamp':datetime.now(timezone.utc).isoformat(),'calibration_id':'C1','evidence_id':'T1','secondary_v':12,'current_a':1.1,'surface_c':40,'primary_v':230,'ambient_c':25,'relay_states':[True]*3+[False]}
    config=BenchConfig(current_limit_a=1,surface_limit_c=55)
    # A current measurement remains visible without a binding, but today's limit
    # cannot be silently attributed to a legacy acquisition.
    unbound=engine.snapshot([row],c=config)
    assert unbound['current']['current_a']==1.1
    assert 'configuration_unbound' in [a['code'] for a in unbound['alerts']]
    assert unbound['limits']['current_a'] is None
    key=engine.config_identity(config)
    store.create_unique('config_version',key,{'config':config.model_dump(),'meaning':'Synthetic regression fixture only'})
    row.update(device_id=config.device_id,config_id=key,hardware_config_status='reported_match')
    snap=engine.snapshot([row],c=config)
    channels={e['channel']:e['calibrated'] for e in snap['evidence']}
    assert channels['current_a'] and channels['secondary_v']
    assert not channels['surface_c'] and not channels['primary_v'] and not channels['ambient_c']
    assert snap['metrics']['condition_index'] is None
    assert 'overcurrent' in [a['code'] for a in snap['alerts']]


def test_no_reference_no_investigation(client):
    r=post(client,'/overview',CTX).json()
    assert not r['investigation']['available'] and r['ledger']['remaining_life_years'] is None
    assert not r['ledger']['ageing_available']


def test_unverified_ambient_cannot_qualify_a_model(client):
    store.put('calibration','C1',{'secondary_v_per_mv':.01,'current_a_per_mv':.001,'surface_reference':'Checked independently'})
    row=engine.demonstration('normal',1)[-1]
    row.update(timestamp=datetime.now(timezone.utc).isoformat(),calibration_id='C1')
    snap=engine.snapshot([row]);snap['model']={'beats_persistence':True,'calibration_id':'C1'}
    assert snap['quality']['calibration']=='reference recorded'
    assert 'ambient' in evidence.model_ready(snap)
    assert not engine.futures(snap)['available']


def test_short_window_abrupt_reading_change(client):
    rows=engine.demonstration('normal',5);rows[-1]['surface_c']+=10
    snap=engine.snapshot(rows,'simulated','X')
    snap['model']={'beats_persistence':True,'coefficients':[.005,.05,.005]}
    result=evidence.investigation(snap)
    assert any(c['title']=='Abrupt temperature-reading change' for c in result['hypotheses'])


def test_imported_fit_stops_at_selected_frame(client):
    rows=engine.demonstration('normal',600)
    config=BenchConfig(device_id='SIM-BENCH',nominal_secondary_v=12,current_limit_a=1,surface_limit_c=55)
    key=engine.config_identity(config)
    store.create_unique('config_version',key,{'config':config.model_dump(),'meaning':'Synthetic recording fixture configuration, not physical commissioning'})
    for row in rows:row.update(config_id=key,hardware_config_status='reported_match')
    store.put('calibration','synthetic',{'secondary_v_per_mv':.01,'current_a_per_mv':.001,'surface_reference':'Test fixture','ambient_reference':'Test fixture'})
    store.put('bench_dataset','FIXTURE',{'rows':rows,'name':'Future leakage regression fixture'})
    result=client.post('/api/halo/models/fit',json={**CTX,'dataset_id':'FIXTURE','cursor':360,'qualified_healthy':True,'note':'Synthetic past-only fit regression'},headers=AUTH)
    assert result.status_code==200,result.text
    assert result.json()['data_end_at']==rows[360]['timestamp']
    assert result.json()['config_id']==key


def test_scoring_detects_unobserved_tail(client):
    start=datetime.now(timezone.utc)-timedelta(hours=1)
    proof={'origin':start.isoformat(),'horizon_min':3,'target':'surface_c','initial_c':30,'inputs':{},'calibration_id':None,'cadence_seconds':5,'points':[{'minute':0,'predicted_c':30},{'minute':3,'predicted_c':31}]}
    rows=[{'timestamp':(start+timedelta(seconds=s)).isoformat(),'surface_c':30} for s in (5,200)]
    score=evidence.score_prediction(proof,rows)
    assert score['status']=='complete' and score['gaps']==1
    assert score['all_observations']['count']==1


def test_forecast_that_loses_to_persistence_is_reported(client):
    start=datetime.now(timezone.utc)-timedelta(hours=1)
    proof={'origin':start.isoformat(),'horizon_min':1,'target':'surface_c','initial_c':30,'inputs':{},'calibration_id':None,'points':[{'minute':0,'predicted_c':30},{'minute':1,'predicted_c':35}]}
    rows=[{'timestamp':(start+timedelta(seconds=s)).isoformat(),'surface_c':30} for s in (5,10,15,60)]
    score=evidence.score_prediction(proof,rows)
    assert 'Persistence is as good or better' in score['baseline_comparison']
    assert score['assumptions_held']['persistence_mae_c']==0


def test_plan_requires_both_reviewed_limits(client):
    rows=engine.demonstration('normal',360);snap=engine.snapshot(rows,'simulated','X')
    snap['model']={'beats_persistence':True}
    snap['limits']['current_a']=None
    result=evidence.plan(snap,5,0,[])
    assert not result['available'] and 'current limits' in result['reason']


def test_persistent_reference_residual_without_fault_labels(client):
    model={'id':'FIXTURE','beats_persistence':True,'coefficients':[.005,.05,.005],'validation_rmse_c':.2}
    rows=[];temp=30;start=datetime.now(timezone.utc)-timedelta(minutes=10)
    for i in range(80):
        temp=engine.surface_step(temp,25,.3,5,model['coefficients'])
        rows.append({'timestamp':(start+timedelta(seconds=i*5)).isoformat(),'surface_c':temp+(8 if i>40 else 0),'ambient_c':25,'current_a':.3,'evidence_id':str(i),'relay_states':[False]*4})
    snap=engine.snapshot(rows,'simulated','X');snap['model']=model
    r=evidence.investigation(snap)
    assert r['persistent'] and r['duration_seconds']>=60
    assert 'Persistent excess' in ' '.join(x['title'] for x in r['hypotheses'])
    assert model['coefficients']==[.005,.05,.005]


def test_plan_auth_and_missing_data(client):
    assert client.post('/api/halo/evidence/plan',json=CTX).status_code==401
    r=post(client,'/plan',{'mode':'bench','horizon':5}).json()
    assert not r['available']


def test_discrete_plan_never_adds_or_keeps_k4(client):
    rows=engine.demonstration('overload',200);snap=engine.snapshot(rows,'simulated','X')
    snap['model']={'id':'FIXTURE','beats_persistence':True,'coefficients':[.001,.02,.005],'current_range_a':[0,2],'ambient_range_c':[20,40],'validation_span_s':3600}
    r=evidence.plan(snap,5,2,[1,2,3])
    assert r['available']
    assert all(not c['states'][3] and c['states'][:3]==[True]*3 for c in r['candidates'])
    assert all(not c['qualifies'] for c in r['candidates'] if c['delay_min'])


def test_distribution_plan_sensitivity_and_constraints(client):
    r=post(client,'/plan',{**DT,'horizon':60,'max_delay':3}).json()
    assert r['available'] and r['recommendation']
    assert r['recommendation']['qualifies']
    assert r['recommendation']['peak_c']<r['limit_c']
    assert 'not confidence' in r['note']


def test_freeze_and_score_without_rewriting_prediction(client):
    fit(client)
    p=post(client,'/forecasts',{**CTX,'horizon':3}).json()
    assert p.get('sha256'),p
    old=copy.deepcopy(p)
    pending=post(client,'/forecasts/'+p['id']+'/score',CTX).json()
    assert pending['all_observations']['count']==0 and pending['status'].startswith('awaiting')
    scored=post(client,'/forecasts/'+p['id']+'/score',{**CTX,'cursor':450}).json()
    assert scored['status']=='complete' and scored['all_observations']['count']==36
    assert store.get('forecast',p['id'])==old
    assert post(client,'/forecasts/'+p['id']+'/score',{**CTX,'scenario':'heating'}).status_code==409


def test_future_fitted_reference_rejected(client):
    fit(client)
    assert post(client,'/forecasts',{**CTX,'cursor':200,'horizon':3}).status_code==422


def test_forecast_tamper_detected(client):
    p=post(client,'/forecasts',{**DT,'horizon':15}).json()
    p['points'][0]['predicted_c']+=1;store.put('forecast',p['id'],p)
    assert post(client,'/forecasts/'+p['id']+'/score',DT).status_code==409


def test_changed_assumptions_and_missing_values_separate(client):
    start=datetime.now(timezone.utc)-timedelta(minutes=3)
    proof={'origin':start.isoformat(),'horizon_min':1,'target':'surface_c','initial_c':30,'calibration_id':'C1','inputs':{'current_a':.3,'ambient_c':25},'points':[{'minute':0,'predicted_c':30},{'minute':1,'predicted_c':31}]}
    rows=[{'timestamp':(start+timedelta(seconds=i*5)).isoformat(),'surface_c':30 if i<3 else None,'current_a':.8,'ambient_c':25,'calibration_id':'C1'} for i in range(1,13)]
    r=evidence.score_prediction(proof,rows)
    assert r['all_observations']['count']==2 and r['changed_input_samples']==2
    assert r['assumptions_held']['count']==0 and r['missing_samples']==10


def acceptance_payload():
    return {'asset_id':'BENCH-SIM','source':'manual_bench_observations','reviewer':'Tester','reference_instrument':'TEST reference','calibration_reference':'CAL test fixture','firmware_version':'test-1','note':'Synthetic input only','confirmed':True,'checks':[{'name':'Voltage','kind':'measurement','unit':'V','reference':100,'observed':90,'tolerance_pct':1}]}


def test_signed_error_cannot_pass_and_zero_reference_explicit(client):
    p=acceptance_payload();r=post(client,'/acceptance',p).json()['checks'][0]
    assert r['status']=='fail' and r['absolute_error_pct']==10
    p['checks'][0].update(reference=0,observed=0)
    assert post(client,'/acceptance',p).json()['checks'][0]['status']=='not demonstrated'
    p['checks'][0]['tolerance_abs']=.01
    assert post(client,'/acceptance',p).json()['checks'][0]['status']=='pass'


def test_reference_examples_do_not_certify_hardware(client):
    r=client.get('/api/halo/evidence/acceptance/reference').json()
    assert len(r['checks'])==12
    assert all(c['status']=='pass' for c in r['checks'][:6])
    assert all(c['status']=='threshold observation only' for c in r['checks'][6:])
    assert all(not c['physical_contact_opening_verified'] for c in r['checks'])


def test_acknowledgement_not_contact_feedback(client):
    p=acceptance_payload();t=datetime.now(timezone.utc)-timedelta(seconds=20)
    p['checks'][0].update(kind='threshold',event_at=t.isoformat(),response_at=(t+timedelta(seconds=1)).isoformat(),response_kind='command_acknowledgment',evidence='Recorded synthetic command acknowledgment')
    r=post(client,'/acceptance',p).json()['checks'][0]
    assert r['elapsed_s']==1 and not r['physical_contact_opening_verified']
    p['checks'][0]['response_at']=(t-timedelta(seconds=1)).isoformat()
    assert post(client,'/acceptance',p).status_code==422


def test_nonfinite_values_and_unconfirmed_checks_rejected(client):
    p=acceptance_payload();p['confirmed']=False
    assert post(client,'/acceptance',p).status_code==422
    p['confirmed']=True;p['checks'][0]['observed']='nan'
    assert post(client,'/acceptance',p).status_code==422


def lab_payload():
    return {'asset_id':'DT-SIM','report_reference':'SYN-001','laboratory':'Synthetic lab','sample_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),'reviewer':'Tester','note':'Synthetic fixture only','evidence_type':'demonstration_fixture','confirmed':True,'values':[{'analyte':'hydrogen','value':10,'unit':'ppm'}]}


def test_lab_units_confirmation_and_duplicate_analyte(client):
    p=lab_payload();p['values'][0]['unit']='ppb'
    assert post(client,'/lab-reports',p).status_code==422
    p=lab_payload();p['confirmed']=False
    assert post(client,'/lab-reports',p).status_code==422
    p=lab_payload();p['values']*=2
    assert post(client,'/lab-reports',p).status_code==422


def test_lab_trends_keep_real_and_synthetic_separate(client):
    p=lab_payload();post(client,'/lab-reports',p)
    p['evidence_type']='laboratory_report';p['values'][0]['value']=200
    post(client,'/lab-reports',p)
    r=post(client,'/records',{'asset_id':'DT-SIM'}).json()
    assert len(r['lab_trends'])==2 and all(t['change'] is None for t in r['lab_trends'])
    assert post(client,'/records',{'asset_id':'BENCH-SIM'}).json()['lab_report']==[]


def test_ageing_requires_explicit_distribution_scenario(client):
    p={**DT,'reviewer':'Tester','note':'Hypothetical test fixture, not insulation data','hypothetical_confirmed':True}
    assert post(client,'/ageing',{**p,'mode':'replay','scenario':'normal'}).status_code==422
    assert post(client,'/ageing',{**p,'hypothetical_confirmed':False}).status_code==422
    a=post(client,'/ageing',{**p,'cursor':148}).json()
    b=post(client,'/overview',{**DT,'cursor':155}).json()['ledger']
    assert b['equivalent_hours']>=a['equivalent_hours']>0
    assert b['remaining_life_years'] is None


def test_rolling_benchmark_runs_past_only_and_has_multiple_horizons(client):
    r=post(client,'/benchmark',{**CTX,'cursor':500})
    assert r.status_code==200,r.text
    data=r.json();assert len(data['summary'])==3 and len(data['results'])>3
    assert all(x['origin']<500 for x in data['results'])


def test_export_auth_manifest_and_html_escape(client):
    assert client.post('/api/halo/evidence/export',json=CTX).status_code==401
    p=lab_payload();p['note']='<script>alert(1)</script>';post(client,'/lab-reports',p)
    response=post(client,'/export',DT)
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert set(z.namelist())=={'case.json','report.html','manifest.json'}
        for name,sha in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
        assert b'<script>alert(1)</script>' not in z.read('report.html')
        assert b'&lt;script&gt;' in z.read('report.html')
