from copy import deepcopy
from datetime import datetime,timedelta,timezone
from io import BytesIO
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from neuratwin import maintenance_model as m, transient_fem as fem, halo_store as store
from neuratwin.maintenance_calibration import propose
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.briefing_api import report_snapshot,PDFRequest

OP={'Authorization':'Bearer '+LOCAL_TOKEN}


def row(i=0,current=.8,temperature=45):
    return {'timestamp':(datetime(2026,10,10,tzinfo=timezone.utc)+timedelta(seconds=i*2)).isoformat(),
        'sample_key':str(i),'boot_id':'one','current_a':current,'temperature_c':temperature,'voltage_v':12,
        'current_source':'measured','temperature_source':'measured','calibrated':True,'source':'test acquisition'}


def test_scenario_recommendation_and_cost_bound():
    p=m.Profile();options=m.DecisionOptions(site_kw=100,energy_cost_per_kwh=8,intervention_cost=0,inspection_cost=50,sensor_purchase_cost=200,sensor_install_cost=100,sensor_service_cost=0)
    data=[row(current=1.4)];copy=deepcopy(data);d=m.decision(data,p,options,live=True,channel='surface')
    assert data==copy and d['available'] and not d['agreement']
    assert d['robust_reduction_percent']>0
    assert all(d['robust_reduction_percent'] in s['safe_candidates'] for s in d['scenarios'])
    assert d['robust_action_cost']==pytest.approx(100*2*d['robust_reduction_percent']/100*8)
    for choice in d['measurements']:
        assert choice['maximum_avoidable_cost']>=0
        assert choice['net_benefit_upper_bound']==choice['maximum_avoidable_cost']-choice['total_cost']
    unknown=m.decision(data,p,m.DecisionOptions(),live=True,channel='surface')
    assert unknown['robust_action_cost'] is None and all(r['total_cost'] is None for r in unknown['measurements'])


def test_stale_out_of_domain_and_initial_exceedance():
    p=m.Profile();o=m.DecisionOptions()
    assert not m.decision([row()],p,o,live=False,channel='surface')['available']
    assert not m.decision([row(current=3)],p,o,live=True,channel='surface')['available']
    assert m.decision([row(temperature=90)],p,o,live=True,channel='surface')['robust_reduction_percent'] is None
    with pytest.raises(ValueError):m.DecisionOptions(cooling_min=1,cooling_max=.6)


def test_followup_requires_comparable_uninterrupted_observations():
    p=m.Profile();origin=row(temperature=65)
    job={'mode':'prototype','action':{'origin':origin,'profile':p.model_dump(),'horizon_min':120},'acceptance':{'temperature_limit_c':80,'stable_minutes':5},'findings':{'issue_resolved':True}}
    data=[row(i,temperature=65-i*.02) for i in range(151)]
    result=m.verification(job,data,live=True)
    assert result['outcome']=='improved' and len(result['points'])==150
    assert m.verification(job,data[:100],live=True)['outcome']=='insufficient_evidence'
    assert m.verification(job,data,live=False)['outcome']=='insufficient_evidence'
    for key,value in [('current_a',1.2),('boot_id','new'),('ambient_c',40),('current_source','frontend_estimated')]:
        changed=deepcopy(data);changed[100][key]=value
        assert m.verification(job,changed,live=True)['outcome']=='insufficient_evidence'
    gap=data[:10]+data[20:]
    assert m.verification(job,gap,live=True)['gap_detected']
    hot=[row(i,temperature=85) for i in range(151)]
    assert m.verification(job,hot,live=True)['outcome']=='unresolved'


def calibration_data():
    truth=m.Profile(rated_rise_c=55,tau_min=8);data=[];temperature=30
    for i in range(901):
        current=.4 if i<150 else 1.2 if i<450 else .7
        if data:temperature=m.step(temperature,data[-1]['current_a'],2,truth)
        data.append(row(i,current,temperature))
    return data


def test_calibration_heldout_recovery_and_evidence_gates():
    data=calibration_data();p=m.Profile();r=propose(data,p)
    assert r['available'],r
    assert r['proposed_profile']['tau_min']==pytest.approx(8,rel=.01)
    assert r['proposed_profile']['rated_rise_c']==pytest.approx(55,rel=.01)
    assert r['held_out_rmse_c']<.01
    assert not propose(data[:100],p)['available']
    for v in data:v['current_source']='frontend_estimated'
    assert not propose(data,p)['available']
    assert not propose([row(i) for i in range(901)],p)['available']
    changed=calibration_data()
    for v in changed[700:]:v['temperature_c']+=10
    assert not propose(changed,p)['available']


def test_transient_conservation_cooling_and_refinement():
    c=fem.checks();assert c['max_balance_error_w']<1e-8
    assert c['mesh_peak_difference_c']<.1 and c['time_step_peak_difference_c']<.01
    off=fem.solve(fem.Study(initial_c=45,segments=[fem.Segment(minute=0,loading_pu=0,energized=False)]))
    assert 25<off['frames'][-1]['peak_c']<45
    equilibrium=fem.solve(fem.Study(segments=[fem.Segment(minute=0,loading_pu=0,energized=False)]))
    assert all(v['peak_c']==25 for v in equilibrium['frames'])
    with pytest.raises(ValueError):fem.Study(segments=[fem.Segment(minute=20,loading_pu=1)])


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'maintenance.sqlite3'));monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite');monkeypatch.setenv('HALO_ESP32_URL','');monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c


def post(client,url,body):
    r=client.post(url,headers=OP,json=body);assert r.status_code==200,r.text;return r.json()


def test_job_lifecycle_freezes_forecasts_keeps_source_unchanged_and_exports(client):
    run=post(client,'/api/halo/twin/runs',{'request_id':'maintenance-test'})
    asset=run['id'];base='/api/halo/maintenance/assets/'+asset
    original=deepcopy(store.get('twin_run',asset))
    body={'request_id':'job-request-1','title':'Inspect cooling','owner':'Technician','revision':run['revision'],'stable_minutes':5}
    job=post(client,base+'/jobs',body)
    assert post(client,base+'/jobs',body)==job
    assert store.get('twin_run',asset)==original
    assert client.post(base+'/jobs',headers=OP,json={**body,'owner':'Other technician'}).status_code==409
    assert client.post(base+'/decision',headers=OP,json={'revision':999}).status_code==409
    jobpath=base+'/jobs/'+job['id']
    frozen=deepcopy(job['decision'])
    job=post(client,jobpath,{'job_revision':0,'operation':'findings','note':'Cooling path inspected','issue_resolved':True})
    assert client.post(jobpath,headers=OP,json={'job_revision':0,'operation':'action','note':'Action complete'}).status_code==409
    job=post(client,jobpath,{'job_revision':1,'operation':'action','note':'Load held steady after inspection'})
    job=post(client,jobpath,{'job_revision':2,'operation':'verify'})
    assert job['verification']['outcome']=='insufficient_evidence'
    run=post(client,'/api/halo/twin/runs/'+asset+'/actions',{'request_id':str(uuid4()),'revision':run['revision'],'action':'advance_paused','seconds':360})
    job=post(client,jobpath,{'job_revision':3,'operation':'verify','revision':run['revision']})
    assert job['verification']['outcome']=='stabilized',job['verification']
    assert job['decision']==frozen and job['verification']['scope'].startswith('Simulation')
    profile=client.get(base,headers=OP).json()['profile']
    updated=post(client,base+'/profile',{'revision':0,'profile':{**profile['profile'],'tau_min':100},'note':'Revised assumption'})
    assert updated['revision']==1
    assert store.get('maintenance_job',job['id'])['decision']==frozen
    assert client.post(base+'/decision',headers=OP,json={}).status_code==409
    assert 'simulated' in post(client,base+'/calibration',{'profile_revision':1})['reason']
    pdf=client.get(jobpath+'/report.pdf',headers=OP)
    assert pdf.status_code==200,pdf.text[:200] if pdf.status_code!=200 else ''
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert 'Inspect cooling' in text and 'stabilized' in text and 'Forecast' in text
    snap=report_snapshot(asset,PDFRequest())
    assert any(d.get('record_type')=='maintenance_job' for d in snap['decisions'])
    assert client.get('/api/halo/maintenance/assets/BENCH-001/jobs/'+job['id']+'/report.pdf',headers=OP).status_code==404


def display():
    channels={k:{'value':v,'raw':v,'unit':unit,'source':source,'method':'display','quality':'live'} for k,v,unit,source in [('primary_voltage',230,'V','measured'),('secondary_voltage',12,'V','measured'),('primary_current',.02,'A','frontend_estimated'),('secondary_current',12/(39/2),'A','frontend_estimated'),('surface_temperature',40,'C','measured')]}
    current=channels['secondary_current']['value']
    return {'timestamp':'2026-10-10T00:00:00Z','device_id':'HALO-ESP32','boot_id':'test','sequence':1,'version':'prototype-display-1','quality':'live','age_s':0,'active_branches':2,'calibrated':False,'probe_valid':True,'live':True,'channels':channels,'rating_a':1,'loading_percent':current*100,'demo_health':100,'demo_health_version':'current-only-1','scope':'display'}


def test_prototype_exact_current_stale_and_photo_validation(client):
    base='/api/halo/maintenance/assets/BENCH-001';s=display();copy=deepcopy(s)
    result=post(client,base+'/decision',{'display_current':s})
    assert result['origin']['current_a']==12/(39/2) and s==copy
    job=post(client,base+'/jobs',{'request_id':'physical-job','title':'Inspect surface','owner':'Technician','display_current':s})
    path=base+'/jobs/'+job['id']
    assert client.post(path,headers=OP,json={'job_revision':0,'operation':'findings','note':'Inspection note','photo_base64':'not an image'}).status_code==422
    assert store.get('maintenance_job',job['id'])['revision']==0
    stale={**s,'live':False,'loading_percent':None,'demo_health':None}
    assert not post(client,base+'/decision',{'display_current':stale})['available']
    assert client.post(path,headers=OP,json={'job_revision':0,'operation':'action','note':'Record action','display_current':stale}).status_code==409
    assert not post(client,base+'/calibration',{'display_current':s})['available']


def test_photo_preserved_and_embedded_with_revision_guard(client):
    import base64
    from PIL import Image
    buf=BytesIO();Image.new('RGB',(20,20),(100,110,100)).save(buf,format='PNG')
    base='/api/halo/maintenance/assets/BENCH-001';s=display()
    job=post(client,base+'/jobs',{'request_id':'photo-job-1','title':'Inspect surface','owner':'Technician','display_current':s})
    path=base+'/jobs/'+job['id']
    job=post(client,path,{'job_revision':0,'operation':'findings','note':'Surface checked','photo_base64':base64.b64encode(buf.getvalue()).decode()})
    attachment=job['findings']['photos'][0]
    image=client.get('/api/halo/attachments/'+attachment['id'],headers=OP)
    assert image.content==buf.getvalue()
    pdf=PdfReader(BytesIO(client.get(path+'/report.pdf',headers=OP).content))
    assert any(len(page.images)>0 for page in pdf.pages)
    assert len(pdf.pages)<15
    assert client.post(path,headers=OP,json={'job_revision':0,'operation':'findings','note':'Conflicting note'}).status_code==409


def test_calibration_acceptance_is_explicit_asset_bound_and_frozen(client):
    base='/api/halo/maintenance/assets/BENCH-001';s=display()
    job=post(client,base+'/jobs',{'request_id':'calibrate-job','title':'Collect surface response','owner':'Technician','display_current':s})
    data=calibration_data()
    for i,r in enumerate(data):r['sample_key']='one:'+str(i)
    retained=store.get('maintenance_job',job['id']);retained['initial_readings']=data;store.put('maintenance_job',job['id'],retained)
    s.update(timestamp=data[-1]['timestamp'],boot_id='one',sequence=900,calibrated=True)
    s['channels']['secondary_current'].update(value=.7,raw=.7,source='measured');s['channels']['surface_temperature']['value']=data[-1]['temperature_c']
    s['loading_percent']=70
    proposal=post(client,base+'/calibration',{'display_current':s})
    assert proposal['available'],proposal
    assert store.get('maintenance_profile','BENCH-001') is None
    accepted=post(client,base+'/calibration/accept',{'proposal_id':proposal['id'],'profile_revision':0})
    assert accepted['revision']==1 and accepted['evidence']['id']==proposal['id']
    assert client.post(base+'/calibration/accept',headers=OP,json={'proposal_id':proposal['id'],'profile_revision':0}).status_code==409
    assert store.get('maintenance_job',job['id'])['decision']['profile_revision']==0
