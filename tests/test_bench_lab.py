from copy import deepcopy
from datetime import datetime,timezone,timedelta
import io
import json
import zipfile
import pytest
from test_halo import client,OP,DEVICE,configure,calibration,frame
from neuratwin import halo_store as store,twin_observer as observer,bench_lab
from neuratwin.validation_plant import generate

BASE='/api/halo/lab/experiments'


def create(client,source='software_emulator',key='new-experiment'):
    r=client.post(BASE,headers=OP,json={'request_id':key,'source':source,'name':'Surface response test'})
    assert r.status_code==200,r.text
    return r.json()


def act(client,e,action,**extra):
    r=client.post(BASE+'/'+e['id']+'/actions',headers=OP,json={'revision':e['revision'],'action':action,**extra})
    assert r.status_code==200,r.text
    return r.json()


@pytest.mark.parametrize('electrical',[{'load_percent':130},{'voltage_pu':1.25},{'load_percent':130,'voltage_pu':1.25}])
def test_competing_faults_never_override_measurement_validity(electrical):
    rows,_,_=generate(2101,'healthy');rows=rows[:141]
    for r in rows[-5:]:r['hotspot_c']+=30
    rows[-1].update(electrical)
    out=observer.assess(rows)
    assert not out['available'] and not out['validity']['forecast_allowed'] and 'forecast' not in out
    assert 'channel_disagreement' in out['hypotheses']
    if 'load_percent' in electrical:assert 'overload' in out['hypotheses']
    if 'voltage_pu' in electrical:assert 'voltage_deviation' in out['hypotheses']


@pytest.mark.parametrize('problem',['missing','short','gap','out_of_domain'])
def test_overload_with_bad_history_remains_blocked(problem):
    rows,_,_=generate(3301,'healthy');rows=rows[:90]
    if problem=='missing':rows[-1]['oil_c']=None
    if problem=='short':rows=rows[-2:]
    if problem=='gap':rows[-1]['elapsed_s']+=240
    if problem=='out_of_domain':rows[-2]['oil_c']=999
    rows[-1]['load_percent']=130
    out=observer.assess(rows)
    assert 'overload' in out['hypotheses'] and not out['available']


def test_experiment_forecast_is_frozen_before_future_and_survives_reopen(client):
    e=create(client);assert e['source']=='software_emulator' and not store.frames('HALO-ESP32')
    origin=e['rows'][-1]['timestamp'];count=len(e['rows'])
    e=act(client,e,'freeze');proof=deepcopy(e['proofs'][0]['proof'])
    assert proof['origin']==origin and e['proofs'][0]['score']['samples']==[]
    e=act(client,e,'advance',seconds=180)
    assert len(e['rows'])==count+36 and e['proofs'][0]['proof']==proof
    assert e['proofs'][0]['score']['status']=='complete' and e['proofs'][0]['score']['assumptions_held']['count']==36
    assert client.get(BASE+'/'+e['id']).json()['proofs'][0]['proof']==proof
    assert store.records('command')==[] and store.get('active_model','BENCH-001') is None


def test_changed_load_separate_scores_stop_and_offline_export(client):
    e=create(client);e=act(client,e,'freeze');e=act(client,e,'load',branches=1,note='Emulated demand reduction')
    e=act(client,e,'advance',seconds=180)
    assert e['proofs'][0]['score']['changed_input_samples']>0
    assert e['proofs'][0]['score']['assumptions_held']['count']==0
    e=act(client,e,'mark',kind='recovery',note='Surface trend observed; not a certified repair.')
    e=act(client,e,'stop')
    assert client.post(BASE+'/'+e['id']+'/actions',headers=OP,json={'revision':e['revision'],'action':'advance'}).status_code==409
    r=client.get(BASE+'/'+e['id']+'/export');assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist())=={'experiment.json','observations.csv','replay.html','manifest.json'}
        data=json.loads(z.read('experiment.json'));assert data['state']=='stopped'
        assert b'Offline recording' in z.read('replay.html')
        import hashlib
        for name,value in json.loads(z.read('manifest.json'))['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==value


def test_reference_proposal_is_bound_to_acquisition_and_cannot_activate_emulator(client):
    e=create(client);row=e['rows'][-1]
    p={'request_id':'new-reference-check','experiment_id':e['id'],'evidence_id':row['evidence_id'],'channel':'secondary_v',
       'reference':12.02,'tolerance_abs':.1,'instrument':'Synthetic fixture reference','reviewer':'Tester'}
    r=client.post('/api/halo/lab/references',headers=OP,json=p);assert r.status_code==200,r.text
    value=r.json();assert value['source']=='software_emulator' and value['within_tolerance']
    assert abs(value['proposal']['secondary_v_per_mv']-.02)<1e-9
    assert store.get('active_calibration','bench') is None
    assert client.post('/api/halo/lab/references',headers=OP,json=p).json()==value
    assert client.post('/api/halo/lab/references',headers=OP,json={**p,'reference':13}).status_code==409
    assert client.post('/api/halo/lab/references',headers=OP,json={**p,'request_id':'bad-reference','reference':0}).status_code==422


def test_physical_recording_requires_live_data_and_forbids_emulated_actions(client):
    assert client.post(BASE,headers=OP,json={'request_id':'physical-recording','source':'measured','name':'Actual capture'}).status_code==409
    f=frame(raw={'secondary_rms_mv':1200,'current_rms_mv':300,'surface_raw_c':30})
    assert client.post('/api/halo/telemetry',headers=DEVICE,json=f).status_code==200
    e=create(client,'measured','physical-recording')
    assert len(e['rows'])==1 and e['forecast_hold']
    for action in ('advance','load'):
        assert client.post(BASE+'/'+e['id']+'/actions',headers=OP,json={'revision':0,'action':action}).status_code==403
    assert client.post(BASE+'/'+e['id']+'/actions',headers=OP,json={'revision':0,'action':'freeze'}).status_code==422
    assert not store.records('command')


def test_experiment_revision_idempotency_and_checksum(client):
    e=create(client);again=create(client);assert e['id']==again['id']
    e=act(client,e,'freeze')
    assert client.post(BASE+'/'+e['id']+'/actions',headers=OP,json={'revision':0,'action':'advance'}).status_code==409
    record=store.get('bench_experiment',e['id']);record['proofs'][0]['points'][0]['predicted_c']+=1;store.put('bench_experiment',e['id'],record)
    assert client.get(BASE+'/'+e['id']).status_code==409


def test_export_does_not_execute_operator_note(client):
    e=create(client);e=act(client,e,'mark',note='</script><script>alert(1)</script>')
    html=bench_lab.replay_html(e)
    assert '</script><script>alert(1)' not in html and '\\u003c/script' in html


def test_device_link_requires_device_identity_and_authentication(client):
    p={'device_id':'HALO-ESP32','boot_id':'boot','chip':'UNKNOWN','protocol':1,'compatible':False,'permit':False,'pending_frames':10}
    assert client.post('/api/halo/device/link',json=p).status_code==401
    assert client.post('/api/halo/device/link',json=p,headers=DEVICE).status_code==200
    assert client.get('/api/halo/lab/commissioning').json()['device_link']['pending_frames']==10
    assert client.post('/api/halo/device/link',json={**p,'device_id':'EMULATOR'},headers=DEVICE).status_code==409


def test_full_physical_recording_can_still_stop_without_silent_truncation(monkeypatch):
    old={'timestamp':'2026-01-01T00:00:00Z'}
    new={'timestamp':'2026-01-01T00:00:05Z'}
    exp={'source':'measured','rows':[old.copy() for _ in range(10000)]}
    monkeypatch.setattr(bench_lab,'physical_rows',lambda:[new])
    with pytest.raises(bench_lab.HTTPException) as failure:bench_lab.capture(exp)
    assert failure.value.status_code==409
    bench_lab.capture(exp,stopping=True)
    assert len(exp['rows'])==10000 and exp['uncaptured_samples_at_stop']==1
