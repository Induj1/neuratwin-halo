"""Exercise the submission workflow in disposable SQLite, never the live backend."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='halo-rehearsal-') as folder:
        os.environ.update(HALO_STORAGE_BACKEND='sqlite',NEURATWIN_DB=str(Path(folder)/'case.sqlite3'),
                          HALO_ALLOW_CONTROL='0',HALO_LOCAL_OPERATOR='1',HALO_AI_ENABLED='0')
        for key in ('HALO_OPERATOR_TOKEN','HALO_DEVICE_TOKEN'):os.environ.pop(key,None)
        from fastapi.testclient import TestClient
        from neuratwin.app import app
        from neuratwin.halo_api import LOCAL_TOKEN
        from neuratwin import halo_store
        checks=[]
        with TestClient(app) as c:
            headers={'Authorization':'Bearer '+LOCAL_TOKEN}
            def post(url,body,expected=200):
                r=c.post(url,headers=headers,json=body)
                assert r.status_code==expected,(url,r.status_code,r.text)
                return r.json()
            s=post('/api/halo/twin/runs',{'request_id':'submission-rehearsal-v2',
                'profile':{'name':'Reviewed software rehearsal · synthetic','basis':'illustrative',
                    'reviewer':'Automated workflow test','reference':'Synthetic demonstration, not hardware or field evidence'}})
            url='/api/halo/twin/runs/'+s['id']
            def act(action,**extra):
                nonlocal s
                s=post(url+'/actions',{'action':action,'revision':s['revision'],'request_id':str(uuid.uuid4()),**extra})
            def study(path,**extra):return post(url+path,{'request_id':str(uuid.uuid4()),'revision':s['revision'],**extra})
            act('inputs',inputs={**s['inputs'],'load_percent':110,'cooling':'degraded','ambient_c':35})
            assert s['analysis']['status']=='WARNING';checks.append('Forward risk overrides the condition index')
            proof=study('/proofs',horizon_min=15)
            act('start');act('step',seconds=900);act('pause')
            case=c.get(url+'/case',headers=headers).json()
            assert case['proofs'][0]['score']['complete'];checks.append('Frozen forecast scored on later observations')
            plan=study('/plans',horizon_min=60,max_delay_min=0)
            s=post(url+'/apply-plan',{'plan_id':plan['id'],'revision':s['revision']})
            assert abs(s['telemetry']['loading_percent']-plan['recommendation']['post_load_percent'])<1e-8
            checks.append('Applied load matches the selected proposal')
            w=study('/work',title='Restore simulated cooling and verify recovery',owner='Neura Rangers rehearsal',
                acceptance='Ten minutes of qualified normal operation, restored cooling and no projected critical thermal limit.')
            def work(status,note,expected=200):
                nonlocal w
                result=post(url+'/work/'+w['id'],{'status':status,'revision':w['revision'],'note':note},expected)
                if expected==200:w=result
            work('in_progress','Reviewed simulated cooling and loading; no physical inspection is claimed.')
            work('verification_pending','Demand reduction applied; cooling remains degraded, so this is mitigation only.')
            act('start');act('step',seconds=660);act('pause')
            work('closed','Attempt closure while the cooling defect remains.',423)
            work('stabilized','Demand reduced but cooling defect remains; retained as temporary stabilization.')
            checks.append('Continuing cooling defect prevents false closure')
            act('trip');act('maintenance',maintenance='fault_investigation',note='Synthetic inspection before isolated simulated service.')
            act('maintenance',maintenance='cooling_service',note='Simulated cooling restored while the model breaker is open.')
            act('start')
            for _ in range(12):
                act('step',seconds=300)
                if not s['recovery_holds']:break
            assert not s['recovery_holds']
            act('reconnect');act('pause')
            work('verification_pending','Simulated service complete and manually reconnected after recovery holds cleared.')
            act('start');act('step',seconds=660);act('pause')
            work('closed','Ten-minute stable response and 240-minute parameter-corner check passed after simulated repair.')
            assert w['closure_evidence']['eligible'];checks.append('Structured post-repair recovery window passes')
            response=c.get(url+'/report',headers=headers);assert response.status_code==200
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                manifest=json.loads(archive.read('manifest.json'))
                assert all(hashlib.sha256(archive.read(n)).hexdigest()==v for n,v in manifest.items())
                report=json.loads(archive.read('run.json'))
                assert report['work_orders'][0]['current_verification']['eligible']
            (ROOT/'reports/synthetic-rehearsal-case.zip').write_bytes(response.content)
            checks.append('Export retains forecasts, actions, closure evidence and valid manifest')
            blind=post('/api/halo/twin/challenges',{'request_id':str(uuid.uuid4())})
            base='/api/halo/twin/challenges/'+blind['id']
            post(base+'/reveal',{},409);post(base+'/assess',{})
            revealed=post(base+'/reveal',{});assert revealed['commitment_verified']
            (ROOT/'reports/synthetic-blind-case.json').write_text(json.dumps(revealed,indent=2),encoding='utf-8')
            checks.append('Blind assessment must precede verified ground-truth reveal')
            assert halo_store.records('command')==[];checks.append('No hardware commands were created')
        result={'status':'pass','scope':'Isolated synthetic workflow, no private environment loaded','checks':checks,
                'final_status':s['analysis']['status'],'work_status':w['status'],'stable_samples':w['closure_evidence']['samples']}
        (ROOT/'reports/workflow-rehearsal.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
