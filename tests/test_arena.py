"""Arena contracts and causal boundaries; these synthetic tests are not field validation."""
import hashlib
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin import halo_arena_model as m
from neuratwin import halo_store as store
from neuratwin.halo_arena import digest

AUTH={'Authorization':'Bearer '+LOCAL_TOKEN}
BASE='/api/halo/arena'


@pytest.fixture()
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'arena.sqlite3'))
    for name in ('HALO_OPERATOR_TOKEN','HALO_ALLOW_CONTROL','HALO_AI_ENABLED'):
        monkeypatch.delenv(name,raising=False)
    with TestClient(app) as c:yield c


def new(client):
    data=client.post(BASE+'/rooms',json={},headers=AUTH).json()
    return data['room']['id'],{'X-Arena-Key':data['judge_key']}


def post(client,key,path,body=None):
    return client.post(BASE+'/rooms/'+key+'/'+path,json=body or {},headers=AUTH)


def inject(client,key,cap,kind='bias',start=1,duration=20,severity=1.):
    return client.post(BASE+'/rooms/'+key+'/inject',json={'kind':kind,'start':start,'duration':duration,'severity':severity},headers=cap)


def test_capability_is_scoped_and_cannot_replace_operator(client):
    assert client.post(BASE+'/rooms',json={}).status_code==401
    a,cap=new(client);b,_=new(client)
    assert inject(client,b,cap).status_code==403
    assert client.post(BASE+'/futures',json={},headers=cap).status_code==401
    assert inject(client,a,AUTH).status_code==403
    assert inject(client,a,cap).status_code==200


def test_hidden_schedule_not_in_observation_or_export(client):
    key,cap=new(client);inject(client,key,cap)
    state=post(client,key,'advance',{'minutes':5}).json()
    assert state['truth'] is None and 'events' not in state
    assert not any(k in state for k in ('seed','judge_key','judge_hash'))
    data=post(client,key,'export')
    with zipfile.ZipFile(io.BytesIO(data.content)) as z:
        exported=json.loads(z.read('case.json'))
        assert exported['truth'] is None
        text=z.read('case.json').decode()
        assert '"kind": "bias"' not in text and 'judge_hash' not in text
        manifest=json.loads(z.read('manifest.json'))
        for name,checksum in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==checksum


def test_no_retroactive_injection_and_strict_bounds(client):
    key,cap=new(client);post(client,key,'advance',{'minutes':10})
    assert inject(client,key,cap,start=10).status_code==409
    assert inject(client,key,cap,start=119,duration=60).status_code==422
    assert inject(client,key,cap,severity=2).status_code==422
    assert inject(client,key,cap,start=11).status_code==200


def test_evidence_changes_diagnosis_without_exposing_truth(client):
    key,cap=new(client);inject(client,key,cap)
    state=post(client,key,'advance',{'minutes':5}).json()
    assert 'Unexpected physical heating' in state['assessment']['hypotheses']
    assert 'Temperature-channel discrepancy' in state['assessment']['hypotheses']
    checked=post(client,key,'check',{'type':'probe'}).json()
    assert 'Temperature-channel discrepancy' in checked['assessment']['hypotheses']
    assert 'Unexpected physical heating' not in checked['assessment']['hypotheses']
    assert checked['truth'] is None
    assert len(post(client,key,'check',{'type':'probe'}).json()['checks'])==1
    later=post(client,key,'advance',{'minutes':1}).json()
    assert 'Unexpected physical heating' in later['assessment']['hypotheses'] # stale check cannot certify the new minute


def test_freeze_is_immutable_and_required_before_reveal(client):
    key,cap=new(client);inject(client,key,cap)
    assert post(client,key,'reveal').status_code==409
    assert post(client,key,'commit').status_code==409
    post(client,key,'advance',{'minutes':5});state=post(client,key,'commit').json()
    fingerprint=digest({'observations':state['observations'],'checks':state['checks']})
    assert state['commit']['evidence_sha256']==fingerprint
    for path,body in [('advance',{'minutes':1}),('check',{'type':'probe'})]:
        assert post(client,key,path,body).status_code==409
    assert inject(client,key,cap,start=8).status_code==409
    again=post(client,key,'commit').json();assert again['commit']==state['commit']
    revealed=post(client,key,'reveal').json()
    assert revealed['truth']['events'][0]['kind']=='bias'
    assert revealed['truth']['detection_delay_min']==0
    assert revealed['commit']==state['commit']


def test_future_events_not_scored_and_healthy_case_not_fabricated(client):
    key,cap=new(client);inject(client,key,cap,start=30)
    post(client,key,'advance',{'minutes':5});post(client,key,'commit')
    truth=post(client,key,'reveal').json()['truth']
    assert truth['events']==[] and truth['first_injected_min'] is None
    assert truth['detection_delay_min'] is None and truth['scheduled_beyond_observation']==1


def test_frozen_observations_survive_a_generator_or_diagnosis_update(client,monkeypatch):
    key,_=new(client);post(client,key,'advance',{'minutes':5})
    before=post(client,key,'commit').json()
    def must_not_run(*args,**kwargs):raise AssertionError('Frozen evidence must not be regenerated')
    monkeypatch.setattr(m,'challenge_rows',must_not_run)
    monkeypatch.setattr(m,'diagnose',must_not_run)
    after=client.get(BASE+'/rooms/'+key).json()
    assert after['observations']==before['observations'] and after['assessment']==before['commit']['assessment']
    revealed=post(client,key,'reveal').json()
    assert revealed['observations']==before['observations'] and revealed['truth']['events']==[]


def test_mixed_events_and_missing_channels_remain_distinct(client):
    key,cap=new(client);inject(client,key,cap,'overload');inject(client,key,cap,'bias')
    state=post(client,key,'advance',{'minutes':5}).json()
    assert 'Excess loading' in state['assessment']['hypotheses']
    inject(client,key,cap,'dropout',start=6)
    missing=post(client,key,'advance',{'minutes':1}).json()
    assert missing['observations'][-1]['oil_c'] is None
    assert missing['assessment']['hypotheses']==['Telemetry interruption']


def test_injection_does_not_modify_previous_observations(client):
    key,cap=new(client);before=post(client,key,'advance',{'minutes':5}).json()['observations']
    inject(client,key,cap,'cooling',start=6)
    after=post(client,key,'advance',{'minutes':5}).json()['observations']
    assert after[:6]==before


def test_interpolation_and_shared_forecast_origin():
    st=m.Study();load,ambient=m.profile_at(st,7.5)
    assert load==pytest.approx(1.35) and ambient==pytest.approx(31.5)
    result=m.futures(st)
    assert result['baseline']['rows'][0]==result['operator']['rows'][0]==result['planner']['rows'][0]
    assert result['baseline']['rows'][10]==result['operator']['rows'][10]
    assert result['operator']['rows'][16]['load_pu']<result['baseline']['rows'][16]['load_pu']
    assert result['planner']['passes'] and not result['baseline']['passes']
    assert result['planner']['curtailed_kwh']>0


def test_mixed_heating_and_sensor_bias_cannot_be_explained_by_bias_alone():
    events=[{'kind':kind,'start':1,'duration':60,'severity':1} for kind in ('cooling','bias')]
    rows,checks=m.challenge_rows(42,events,50)
    evidence=[{'type':kind,**checks[50][kind]} for kind in ('probe','clamp','inspection')]
    diagnosis=m.diagnose(rows,evidence)
    assert set(diagnosis['hypotheses'])=={'Temperature-channel discrepancy','Unexpected physical heating','Cooling obstruction observed'}
    assert 'Independent load reference agrees within 0.08 pu.' in diagnosis['findings']


def test_capacity_declines_with_ambient_and_handles_unsafe_origin():
    cool=m.Study(profile=[m.Knot(minute=t,load_pu=.8,ambient_c=20) for t in (0,60)],load_limit_pu=2)
    hot=cool.model_copy(update={'profile':[m.Knot(minute=t,load_pu=.8,ambient_c=45) for t in (0,60)]})
    a=m.capacity(cool)['rows'][-1];b=m.capacity(hot)['rows'][-1]
    assert 0<b['extra_kva']<a['extra_kva']
    bad=m.Study(initial_oil_c=121)
    assert m.futures(bad)['planner'] is None
    assert all(r['extra_kva']==0 and r['status']=='Base profile violates constraints' for r in m.capacity(bad)['rows'])


@pytest.mark.parametrize('profile',[
    [{'minute':1,'load_pu':1,'ambient_c':30},{'minute':60,'load_pu':1,'ambient_c':30}],
    [{'minute':0,'load_pu':1,'ambient_c':30},{'minute':0,'load_pu':1,'ambient_c':30}],
    [{'minute':0,'load_pu':-1,'ambient_c':30},{'minute':60,'load_pu':1,'ambient_c':30}],
])
def test_malformed_profile_rejected(client,profile):
    assert client.post(BASE+'/futures',json={'profile':profile},headers=AUTH).status_code==422


def test_power_flow_conserves_real_power_and_open_circuit():
    row=m.radial_bus(70,100)
    assert row['converged'] and 0<row['voltage_pu']<1
    assert row['source_kw']==pytest.approx(row['load_kw']+row['loss_kw'],abs=1e-6)
    empty=m.radial_bus(0,100);assert empty['loss_kw']==0 and empty['voltage_pu']==1


def test_network_enforces_clinic_and_transfer_topology():
    result=m.neighbourhood(m.NetworkStudy(demand_scale=2))
    assert not result['baseline']['passes'] and result['plan']['passes']
    p=result['plan'];assert p['clinic_served_kw']==25 and p['unserved_kw']>0
    assert p['served_kw']+p['unserved_kw']==pytest.approx(sum(result['demand_kw'].values()))
    assert all(.95<=b['voltage_pu']<=1.05 and b['current_a']<=160 and b['source_kva']<=b['rating_kva'] for b in p['buses'])
    no_transfer=m.neighbourhood(m.NetworkStudy(demand_scale=2,transfer_allowed=False))
    assert no_transfer['plan']['transfer_to']=='none'
    outage=m.neighbourhood(m.NetworkStudy(outage='A'))
    assert outage['plan'] is None and outage['baseline']['clinic_served_kw']==0


@pytest.mark.parametrize('outage',['B','C'])
def test_network_outage_is_not_shown_as_energized(outage):
    result=m.neighbourhood(m.NetworkStudy(outage=outage))
    assert result['plan'] is not None
    row=next(b for b in result['plan']['buses'] if b['id']==outage)
    assert row['voltage_pu']==0 and row['current_a']==0 and not row['energized']
    assert result['plan']['transfer_to']!=outage


def test_studies_attach_and_export_reproducible_inputs(client):
    key,_=new(client)
    for path in ('futures','capacity','neighbourhood'):
        result=client.post(BASE+'/'+path,json={'room_id':key},headers=AUTH)
        assert result.status_code==200,result.text
        payload=result.json();assert payload['notice']==m.NOTICE
        data=client.post(BASE+'/studies/'+payload['id']+'/export',json={},headers=AUTH)
        with zipfile.ZipFile(io.BytesIO(data.content)) as z:
            assert json.loads(z.read('study.json'))==payload
    state=client.get(BASE+'/rooms/'+key).json();assert len(state['studies'])==3
    assert store.events('ARENA-'+key)==[] # studies cannot create a blind diagnosis retroactively


def test_workspace_contains_arena_and_judge_is_not_operator_page(client):
    assert 'id="view-arena"' in client.get('/app').text
    judge=client.get('/arena/judge')
    assert judge.status_code==200 and judge.headers['referrer-policy']=='no-referrer'
    assert '/static/halo.js' not in judge.text
