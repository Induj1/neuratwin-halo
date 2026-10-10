import base64
import io
from datetime import datetime, timezone
from copy import deepcopy
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin import halo_store as store, mobile_runtime, mobile_api

OP={'Authorization':'Bearer '+LOCAL_TOKEN}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'mobile.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    for key in ('HALO_OPERATOR_TOKEN','HALO_SERVER_CLOCK','HALO_PUSH_ENABLED','OPENAI_API_KEY','HALO_MOBILE_DEMO','HALO_ALLOW_CONTROL','HALO_LOCAL_OPERATOR'):
        monkeypatch.delenv(key,raising=False)
    with TestClient(app) as c:yield c


def run(c,name='mobile-test-run'):
    return c.post('/api/halo/twin/runs',headers=OP,json={'request_id':name}).json()


def inspection(s):
    return {'source':'industrial','run_id':s['id'],'request_id':'inspection-test-01','note':'Checked the surface probe mounting.',
            'component':'surface','captured_at':datetime.now(timezone.utc).isoformat()}


def test_mobile_code_verification_and_write_auth(client):
    assert client.post('/api/halo/mobile/verify').status_code==401
    assert client.post('/api/halo/mobile/verify',headers=OP).status_code==200
    assert client.post('/api/halo/mobile/inspections',json=inspection(run(client))).status_code==401


def test_hackathon_auto_session_is_scoped(client,monkeypatch):
    assert client.get('/api/halo/mobile/demo-session').status_code==404
    monkeypatch.setenv('HALO_MOBILE_DEMO','1')
    response=client.get('/api/halo/mobile/demo-session')
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    headers={'Authorization':'Bearer '+response.json()['access_token']}
    assert headers!=OP
    result=client.post('/api/halo/twin/runs',headers=headers,json={'request_id':'auto-session-run'})
    assert result.status_code==200
    assert client.post('/api/halo/mobile/inspections',headers=headers,json=inspection(result.json())).status_code==200
    assert client.put('/api/halo/config',headers=headers,json={}).status_code==403
    monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    assert client.get('/api/halo/mobile/demo-session').status_code==404
    assert client.post('/api/halo/mobile/verify',headers=headers).status_code==401


def test_hackathon_cloud_session_requires_explicit_local_operator(client,monkeypatch):
    monkeypatch.setenv('HALO_MOBILE_DEMO','1')
    monkeypatch.setattr(mobile_api.cloud,'enabled',lambda:True)
    from fastapi import HTTPException, Response
    with pytest.raises(HTTPException) as error: mobile_api.demo_session(Response())
    assert error.value.status_code==404


def test_inspection_retry_identity_and_run_scoping(client):
    s=run(client);other=run(client,'other-mobile-run');payload=inspection(s)
    first=client.post('/api/halo/mobile/inspections',headers=OP,json=payload)
    assert first.status_code==200
    assert client.post('/api/halo/mobile/inspections',headers=OP,json=payload).json()==first.json()
    assert client.post('/api/halo/mobile/inspections',headers=OP,json={**payload,'note':'Changed after submission'}).status_code==409
    assert len(client.get('/api/halo/mobile/inspections',params={'source':'industrial','run_id':s['id']}).json())==1
    assert client.get('/api/halo/mobile/inspections',params={'source':'industrial','run_id':other['id']}).json()==[]
    case=client.get('/api/halo/twin/runs/'+s['id']+'/case').json()
    assert case['inspections'][0]['note']==payload['note']
    assert case['run']['revision']==s['revision']


def test_inspection_photo_validation_and_storage(client):
    payload=inspection(run(client));payload['photo_base64']=base64.b64encode(b'not an image').decode()
    assert client.post('/api/halo/mobile/inspections',headers=OP,json=payload).status_code==422
    buffer=io.BytesIO();Image.new('RGB',(12,12),'green').save(buffer,format='PNG')
    payload['photo_base64']=base64.b64encode(buffer.getvalue()).decode()
    result=client.post('/api/halo/mobile/inspections',headers=OP,json=payload).json()
    assert result['photo']['mime']=='image/png'
    assert 'photo_base64' not in result and 'data' not in result['photo']
    photo=client.get('/api/halo/attachments/'+result['photo']['id'],headers=OP)
    assert photo.content==buffer.getvalue()


def test_assistant_reads_selected_evidence_without_mutation(client):
    s=run(client)
    response=client.post('/api/halo/mobile/assistant',headers=OP,json={'source':'industrial','run_id':s['id'],'question':'What is the temperature?'}).json()
    assert response['provider']=='evidence' and response['evidence']['asset_id']==s['id']
    assert str(round(s['telemetry']['transformer_temperature'],1)) in response['text']
    assert store.get('twin_run',s['id'])['revision']==s['revision']
    physical=client.post('/api/halo/mobile/assistant',headers=OP,json={'source':'prototype','question':'What is the temperature?'}).json()
    assert 'unavailable' in physical['text'].lower()
    assert physical['evidence']['asset_id']=='BENCH-001'


def test_clock_has_one_tick_for_two_clients_and_pause(client):
    s=run(client);state=store.get('twin_run',s['id']);state['running']=True;store.put('twin_run',s['id'],state)
    mobile_runtime.clock_tick(1000);first=store.get('twin_run',s['id'])
    mobile_runtime.clock_tick(1000);assert store.get('twin_run',s['id'])==first
    for _ in range(2):client.get('/api/halo/twin/runs/'+s['id'])
    assert store.get('twin_run',s['id'])==first
    assert first['elapsed_s']==60
    first['running']=False;store.put('twin_run',s['id'],first)
    mobile_runtime.clock_tick(1010);assert store.get('twin_run',s['id'])['elapsed_s']==60


def test_notifications_are_opt_in_and_queued_once(client,monkeypatch):
    s=run(client)
    payload={'source':'industrial','run_id':s['id'],'token':'ExpoPushToken[testdevice123]'}
    response=client.post('/api/halo/mobile/notifications',headers=OP,json=payload).json()
    assert response['delivery_enabled'] is False
    mobile_runtime.queue_notifications();assert store.records('mobile_outbox')==[]
    client.post('/api/halo/twin/runs/'+s['id']+'/actions',headers=OP,json={'action':'trip','revision':0,'request_id':'trip-test-001'})
    mobile_runtime.queue_notifications();mobile_runtime.queue_notifications()
    assert len(store.records('mobile_outbox'))==1
    client.post('/api/halo/mobile/notifications',headers=OP,json={**payload,'enabled':False})
    monkeypatch.setattr(mobile_runtime.httpx,'post',lambda *a,**k:pytest.fail('Disabled subscription must not send'))
    mobile_runtime.deliver_notifications();assert store.records('mobile_outbox')[0]['state']=='cancelled'


def test_unknown_source_and_missing_run_rejected(client):
    assert client.get('/api/halo/mobile/inspections?source=industrial').status_code==422
    assert client.get('/api/halo/mobile/inspections?source=industrial&run_id=unknown').status_code==404
    assert client.get('/api/halo/mobile/inspections?source=made-up').status_code==422


def test_manual_mobile_step_is_atomic_and_paused(client):
    s=run(client)
    result=client.post('/api/halo/twin/runs/'+s['id']+'/actions',headers=OP,json={
        'action':'advance_paused','seconds':300,'revision':s['revision'],'request_id':'mobile-step-atomic'}).json()
    assert result['elapsed_s']==300 and result['running'] is False
    mobile_runtime.clock_tick(1000)
    assert store.get('twin_run',s['id'])['elapsed_s']==300
