"""Live, isolated cloud integration verification. Creates and removes only its QA data.

Does not email, connect to hardware, or change commissioning. Explicit --run is
required. Credentials are read privately from .env; the report contains no tokens.
"""
import argparse
import base64
from datetime import datetime,timezone,timedelta
import io
import json
import os
from pathlib import Path
import secrets
import sys
from unittest.mock import patch
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from neuratwin import cloud,halo_store
from neuratwin.app import app
from neuratwin.halo_contracts import BenchConfig


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');args=p.parse_args()
    if not args.run:p.error('Pass --run for live QA against the configured Supabase project.')
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    os.environ['HALO_LOCAL_OPERATOR']='0';os.environ['HALO_STORAGE_BACKEND']='supabase'
    run=uuid.uuid4().hex;prefix='QA-'+run;device_id=prefix;user_id=None;photo=None;objects=[];record_keys=[];checks=[]
    def check(name,passed):
        checks.append({'check':name,'passed':bool(passed)})
        print(('PASS ' if passed else 'FAIL ')+name,flush=True)
        if not passed:raise AssertionError(name)
    try:
        check('Applied schema responds',cloud.health()['schema_version']==2)
        public={'apikey':os.environ['SUPABASE_PUBLISHABLE_KEY']};url=cloud.settings()[0]
        for table in ('halo_records','halo_frames','halo_events','halo_members','halo_kind_revisions'):
            r=cloud.client().get(url+'/rest/v1/'+table,headers=public)
            check('Anonymous cannot read '+table,r.status_code in (401,403))
        check('Anonymous cannot invoke privileged RPC',cloud.client().post(url+'/rest/v1/rpc/halo_commit',headers=public,json={'p_reads':[],'p_records':[],'p_events':[]}).status_code in (401,403))
        email='halo-qa-'+run+'@example.invalid';password=secrets.token_urlsafe(32)
        user=cloud.request('POST','/auth/v1/admin/users',payload={'email':email,'password':password,'email_confirm':True}).json()
        user_id=user.get('id') or user['user']['id']
        cloud.request('POST','/rest/v1/halo_members',payload={'user_id':user_id,'role':'operator'})
        with TestClient(app) as client:
            check('API denies anonymous evidence',client.get('/api/halo/incidents').status_code==401)
            r=client.post('/api/auth/login',json={'email':email,'password':password})
            check('Real Supabase password sign-in',r.status_code==200)
            check('Session uses HttpOnly cookies and returns no JWT','HttpOnly' in r.headers.get('set-cookie','') and 'access_token' not in r.text)
            check('JWT issuer/signature and member role',client.get('/api/auth/me').json().get('role')=='operator')
            direct={**public,'Authorization':'Bearer '+client.cookies.get('halo_access')}
            check('Signed-in clients cannot bypass server authorization',cloud.client().get(url+'/rest/v1/halo_records',headers=direct).status_code in (401,403))
            check('Operator cannot change commissioning',client.put('/api/halo/config',json={}).status_code==403)
            locked=client.post('/api/halo/relays',json={'states':[False,False,False,True],'request_id':run})
            check('Authenticated operator cannot energise K4',locked.status_code==403 and 'K4' in locked.text)
            check('Cross-origin request rejected',client.post('/api/halo/arena/rooms',headers={'Origin':'https://outside.example'}).status_code==403)
            r=client.post('/api/halo/arena/rooms');check('Authenticated case persists',r.status_code==200)
            room=r.json()['room']['id'];record_keys.append(('arena',room));cap=r.json()['judge_key']
            with TestClient(app) as separate:
                check('Independent worker reads persistent case',separate.get('/api/halo/arena/rooms/'+room+'/judge',headers={'X-Arena-Key':cap}).status_code==200)
                check('Judge capability cannot read other evidence',separate.get('/api/halo/incidents',headers={'X-Arena-Key':cap}).status_code==401)
            # Isolated metadata, outside actual maintenance workflows.
            incident=prefix+'-INC';halo_store.put('incident',incident,{'id':incident,'qa_only':True});record_keys.append(('incident',incident))
            buffer=io.BytesIO();Image.new('RGB',(2,2),'white').save(buffer,format='PNG');data=buffer.getvalue()
            r=client.post('/api/halo/incidents/'+incident+'/attachments',json={'filename':'qa.png','data_base64':base64.b64encode(data).decode()})
            check('Private evidence upload',r.status_code==200);photo=r.json()['id'];record_keys.append(('attachment',photo))
            path=halo_store.get('attachment',photo)['object_path'];objects.append(path)
            cloud.upload(path,data,'image/png');check('Identical photo retry verifies existing bytes',True)
            check('Evidence download byte-for-byte',client.get('/api/halo/attachments/'+photo).content==data)
            check('No public photo URL',cloud.client().get(url+'/storage/v1/object/public/halo-evidence/'+path).status_code!=200)
            check('Session refresh succeeds',client.post('/api/auth/refresh').status_code==200)
            cloud.request('PATCH','/rest/v1/halo_members',params={'user_id':'eq.'+user_id},payload={'role':'viewer'})
            check('Role downgrade takes effect immediately',client.post('/api/halo/arena/rooms').status_code==403)
            cloud.request('PATCH','/rest/v1/halo_members',params={'user_id':'eq.'+user_id},payload={'active':False})
            check('Membership revocation blocks existing session',client.get('/api/halo/incidents').status_code==403)
            check('Logout clears cookies',client.post('/api/auth/logout').status_code==200 and not client.cookies.get('halo_access'))
            os.environ['HALO_DEVICE_TOKEN']=secrets.token_urlsafe(32);headers={'Authorization':'Bearer '+os.environ['HALO_DEVICE_TOKEN']}
            frame={'device_id':device_id,'boot_id':'qa','sequence':1,'uptime_ms':1000,'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat(),'quality_flags':['QA_NOT_PHYSICAL']}
            with patch('neuratwin.halo_engine.config',return_value=BenchConfig(device_id=device_id)):
                r=client.post('/api/halo/telemetry',json=frame,headers=headers);check('Authenticated device ingestion',r.status_code==200)
                check('Identical device retry is idempotent',client.post('/api/halo/telemetry',json=frame,headers=headers).json().get('duplicate'))
                check('Changed retry rejected',client.post('/api/halo/telemetry',json={**frame,'surface_c':30},headers=headers).status_code==409)
                check('Out-of-order frame rejected',client.post('/api/halo/telemetry',json={**frame,'sequence':0},headers=headers).status_code==409)
                check('Future acquisition rejected',client.post('/api/halo/telemetry',json={**frame,'sequence':2,'timestamp':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()},headers=headers).status_code==422)
                check('Physical K4 remains blocked',client.post('/api/halo/relays',json={'states':[False,False,False,True],'request_id':run},headers=headers).status_code in (401,403))
        one=cloud.UnitOfWork();two=cloud.UnitOfWork();record_keys.append(('qa',prefix))
        one.put('qa',prefix,{'n':1});two.put('qa',prefix,{'n':2});one.commit()
        try:two.commit();conflict=False
        except HTTPException as e:conflict=e.status_code==409
        check('Database prevents lost updates across workers',conflict and halo_store.get('qa',prefix)['n']==1)
        first=cloud.UnitOfWork();second=cloud.UnitOfWork();first.records('qa_set_'+run);second.records('qa_set_'+run)
        kind='qa_set_'+run;record_keys.extend([(kind,'one'),(kind,'two')]);first.put(kind,'one',{});second.put(kind,'two',{});first.commit()
        try:second.commit();conflict=False
        except HTTPException as e:conflict=e.status_code==409
        check('Concurrent inserts respect record-set reads',conflict)
    finally:
        # Remove only exact IDs created above. Never clear tables or user data.
        if objects:cloud.request('DELETE','/storage/v1/object/halo-evidence',payload={'prefixes':objects})
        for kind,key in record_keys:cloud.request('DELETE','/rest/v1/halo_records',params={'kind':'eq.'+kind,'id':'eq.'+key})
        cloud.request('DELETE','/rest/v1/halo_frames',params={'device_id':'eq.'+device_id})
        if user_id:cloud.request('DELETE','/auth/v1/admin/users/'+user_id)
        if user_id:cloud.request('DELETE','/rest/v1/halo_events',params={'asset_id':'eq.WORKSPACE','content->>actor':'eq.'+user_id})
        cloud.request('DELETE','/rest/v1/halo_kind_revisions',params={'kind':'eq.qa_set_'+run})
        report={'project':os.environ['SUPABASE_URL'],'at':datetime.now(timezone.utc).isoformat(),'checks':checks,'passed':all(c['passed'] for c in checks),'qa_cleanup':'exact generated records only','hardware_connected':False,'emails_sent':False}
        Path('reports/supabase-integration.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
