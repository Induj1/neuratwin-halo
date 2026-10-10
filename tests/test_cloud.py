import json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import uuid
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient
from neuratwin import cloud,auth,halo_store
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv('HALO_STORAGE_BACKEND','supabase');monkeypatch.setenv('SUPABASE_URL','https://project.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','test-secret');monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','test-public')
    monkeypatch.delenv('SUPABASE_JWKS_URL',raising=False);monkeypatch.delenv('HALO_OPERATOR_TOKEN',raising=False)
    monkeypatch.setenv('HALO_LOCAL_OPERATOR','0');monkeypatch.setenv('HALO_DEVICE_TOKEN','device-test')
    records={};calls=[]
    def transport(request):
        calls.append(request)
        if request.url.path=='/rest/v1/halo_records':
            kind=request.url.params.get('kind','')[3:];key=request.url.params.get('id','')[3:]
            rows=[{'id':i,'content':v['content'],'revision':v['revision']} for (k,i),v in records.items() if k==kind and (not key or i==key)]
            return httpx.Response(200,json=rows)
        if request.url.path=='/rest/v1/rpc/halo_commit':
            data=json.loads(request.content)
            for r in data['p_reads']:
                if records.get((r['kind'],r['id']),{}).get('revision')!=r['revision']:return httpx.Response(409,json={})
            for r in data['p_records']:
                key=r['kind'],r['id'];records[key]={'revision':records.get(key,{}).get('revision',0)+1,'content':r['content']}
            return httpx.Response(200,json={'committed':True})
        if request.url.path=='/rest/v1/rpc/halo_health':return httpx.Response(200,json={'schema_version':2,'database':'connected','storage':'private'})
        if request.url.path=='/rest/v1/halo_kind_revisions':return httpx.Response(200,json=[])
        if request.url.path=='/rest/v1/halo_members':return httpx.Response(200,json=[{'role':'viewer'}])
        return httpx.Response(500,json={})
    client=httpx.Client(transport=httpx.MockTransport(transport));monkeypatch.setattr(cloud,'client',lambda:client)
    yield records,calls
    client.close()


def test_atomic_records_and_read_your_writes(backend):
    records,calls=backend
    with cloud.transaction():
        halo_store.put('incident','I1',{'state':'open'})
        assert halo_store.get('incident','I1')['state']=='open'
        halo_store.event('B1','opened',{})
        assert not records
    commits=[json.loads(r.content) for r in calls if r.url.path.endswith('halo_commit')]
    assert len(commits)==1 and len(commits[0]['p_events'])==1
    assert halo_store.get('incident','I1')['state']=='open'


def test_failed_request_discards_writes(backend):
    with pytest.raises(ValueError),cloud.transaction():
        halo_store.put('x','a',{'n':1});raise ValueError('abort')
    assert not backend[0]


def test_concurrent_revision_rejects_lost_update(backend):
    first=cloud.UnitOfWork();second=cloud.UnitOfWork()
    first.put('x','a',{'n':1});second.put('x','a',{'n':2});first.commit()
    with pytest.raises(HTTPException) as e:second.commit()
    assert e.value.status_code==409 and halo_store.get('x','a')['n']==1


def test_anonymous_legacy_and_halo_routes_protected(backend):
    with TestClient(app) as client:
        assert client.get('/api/catalog').status_code==401
        assert client.get('/api/halo/config').status_code==401
        assert client.get('/api/halo/twin/catalog').status_code==401
        assert client.get('/api/halo/twin/prototype').status_code==401
        assert client.get('/api/halo/twin/validation').status_code==401
        assert client.get('/api/halo/twin/references').status_code==401
        assert client.post('/api/halo/twin/runs/none/proofs',json={}).status_code==401
        assert client.post('/api/halo/twin/runs',json={'request_id':'unauthenticated'}).status_code==401
        assert client.post('/api/import',json={}).status_code==401
        assert client.get('/api/health').status_code==200
        assert client.get('/api/halo/session').json()['token'] is None
        assert client.post('/api/halo/telemetry',json={}).status_code==401


def test_mobile_cloud_demo_is_explicit_and_scoped(backend,monkeypatch):
    monkeypatch.setenv('HALO_MOBILE_DEMO','1')
    monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as client:
        assert client.get('/api/halo/mobile/demo-session').status_code==404
        monkeypatch.setenv('HALO_LOCAL_OPERATOR','1')
        session=client.get('/api/halo/mobile/demo-session')
        assert session.status_code==200
        headers={'Authorization':'Bearer '+session.json()['access_token']}
        assert client.get('/api/halo/twin/catalog',headers=headers).status_code==200
        response=client.post('/api/halo/twin/runs',headers=headers,json={'request_id':'cloud-mobile-demo'})
        assert response.status_code==200
        assert ('twin_run',response.json()['id']) in backend[0]
        assert client.get('/api/auth/members',headers=headers).status_code==403
        assert client.put('/api/halo/config',headers=headers,json={}).status_code==403
        assert client.post('/api/halo/telemetry',headers=headers,json={}).status_code==401
        monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
        assert client.get('/api/halo/mobile/demo-session').status_code==404


def test_local_owner_is_explicit_and_cross_origin_denied(backend,monkeypatch):
    monkeypatch.setenv('HALO_LOCAL_OPERATOR','1')
    with TestClient(app) as client:
        assert client.get('/api/halo/session').json()['token']==LOCAL_TOKEN
        headers={'Authorization':'Bearer '+LOCAL_TOKEN}
        assert client.get('/api/auth/backend',headers=headers).json()['database']=='connected'
        assert client.put('/api/halo/config',json={},headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert client.get('/api/halo/config',headers={'Authorization':'Bearer test-secret'}).status_code==401


def test_signed_jwt_claims_roles_and_revocation(backend,monkeypatch):
    private=ec.generate_private_key(ec.SECP256R1());user=str(uuid.uuid4());now=datetime.now(timezone.utc)
    monkeypatch.setattr(auth,'jwks',lambda _:SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=private.public_key())))
    payload={'sub':user,'iat':now,'exp':now+timedelta(minutes=5),'iss':'https://project.supabase.co/auth/v1','aud':'authenticated'}
    def signed(**changes):return jwt.encode({**payload,**changes},private,algorithm='ES256')
    assert auth.claims(signed())['sub']==user
    for changes in ({'aud':'wrong'},{'iss':'https://wrong.example'},{'exp':now-timedelta(minutes=1)}):
        with pytest.raises(HTTPException):auth.claims(signed(**changes))
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+signed()}
        assert client.get('/api/auth/me',headers=headers).json()['role']=='viewer'
        assert client.post('/api/halo/arena/rooms',headers=headers).status_code==403
        assert client.post('/api/halo/twin/runs',headers=headers,json={'request_id':'viewer-no-write'}).status_code==403
        assert client.post('/api/halo/twin/runs/none/proofs',headers=headers,json={'request_id':'viewer-no-write','revision':0}).status_code==403
        assert client.post('/api/halo/twin/runs/none/work',headers=headers,json={'request_id':'viewer-no-write','revision':0,'title':'Cannot write','owner':'Viewer','acceptance':'Must not create this work order.'}).status_code==403
        monkeypatch.setattr(cloud,'rows',lambda *a,**k:[])
        assert client.get('/api/auth/me',headers=headers).status_code==403


def test_cloud_outage_does_not_fall_back(backend,monkeypatch):
    monkeypatch.setattr(cloud,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(500,json={'message':'secret internals'}))))
    with pytest.raises(HTTPException) as e:halo_store.get('config','bench')
    assert e.value.status_code==503 and 'secret internals' not in e.value.detail


def test_transport_keeps_service_key_out_of_bearer(backend):
    cloud.health();request=backend[1][-1]
    assert request.headers['apikey']=='test-secret' and 'authorization' not in request.headers


def test_rejected_endpoint_does_not_commit(backend,monkeypatch):
    monkeypatch.setenv('HALO_LOCAL_OPERATOR','1')
    with TestClient(app) as client:
        result=client.put('/api/halo/config',json={'pinmap_verified':True},headers={'Authorization':'Bearer '+LOCAL_TOKEN})
        assert result.status_code==422
    assert not backend[0]


def test_member_directory_requires_admin(backend,monkeypatch):
    user=str(uuid.uuid4());called=[]
    monkeypatch.setattr(auth,'claims',lambda _: {'sub':user})
    monkeypatch.setattr(cloud,'rpc',lambda name,payload=None:called.append(name) or [])
    with TestClient(app) as client:
        assert client.get('/api/auth/members',headers={'Authorization':'Bearer viewer'}).status_code==403
        assert called==[]
        monkeypatch.setenv('HALO_LOCAL_OPERATOR','1')
        result=client.get('/api/auth/members',headers={'Authorization':'Bearer '+LOCAL_TOKEN})
        assert result.status_code==200 and result.json()=={'members':[]}
        assert called==['halo_team_directory']


def test_membership_email_lookup_and_missing_account(backend,monkeypatch):
    user=str(uuid.uuid4());writes=[]
    monkeypatch.setenv('HALO_LOCAL_OPERATOR','1')
    monkeypatch.setattr(cloud,'rpc',lambda name,payload=None:[{'user_id':user}] if payload['p_email']=='colleague@example.com' else [])
    monkeypatch.setattr(cloud,'rows',lambda *a,**kw:[])
    monkeypatch.setattr(cloud,'request',lambda method,path,**kw:writes.append((method,path,kw['payload'])) or httpx.Response(201,json={}))
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+LOCAL_TOKEN}
        result=client.put('/api/auth/members',headers=headers,json={'email':'colleague@example.com','role':'viewer'})
        assert result.status_code==200 and result.json()['user_id']==user
        assert writes==[('POST','/rest/v1/halo_members',{'user_id':user,'role':'viewer','active':True})]
        assert client.put('/api/auth/members',headers=headers,json={'email':'missing@example.com','role':'viewer'}).status_code==404
        assert len(writes)==1


def test_membership_identifier_is_unambiguous():
    from pydantic import ValidationError
    for identifiers in ({},{'user_id':str(uuid.uuid4()),'email':'colleague@example.com'},{'email':'not an email'}):
        with pytest.raises(ValidationError):auth.Membership(role='viewer',**identifiers)
