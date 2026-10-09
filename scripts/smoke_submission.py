"""Extract the submission allowlist and check it without private configuration."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'submission/Neura-Rangers-NeuraTwin-Halo-Submission.zip'


def main():
    with tempfile.TemporaryDirectory(prefix='halo-package-') as folder:
        target=Path(folder).resolve()
        with zipfile.ZipFile(ARCHIVE) as z:
            manifest=json.loads(z.read('MANIFEST.json'))['files']
            for name,meta in manifest.items():
                destination=(target/name).resolve()
                if not destination.is_relative_to(target):raise ValueError('Archive path outside extraction root')
                assert hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(z.read(name))
        assert not (target/'.env').exists()
        env=os.environ.copy()
        for key in list(env):
            if key.startswith(('SUPABASE_','HALO_','NEURATWIN_')):env.pop(key)
        env.update(HALO_STORAGE_BACKEND='sqlite',HALO_ALLOW_CONTROL='0',HALO_LOCAL_OPERATOR='1',
                   HALO_AI_ENABLED='0',NEURATWIN_DB=str(target/'smoke.sqlite3'))
        code="""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
with TestClient(app) as c:
    auth={'Authorization':'Bearer '+LOCAL_TOKEN}
    checks=0
    for url in ['/static/halo-evidence-workflow.js','/static/synthetic-review-before.csv','/static/synthetic-review-after.csv','/static/halo-command.js','/static/halo-command.css','/static/halo-waveform.js','/static/halo-waveform.css','/app','/static/halo-operator.css','/static/halo-case.js','/static/halo-lab.js','/static/halo-lab.css','/static/submission-guide.html','/static/hardware-guide.html']:
        assert c.get(url).status_code==200,url
        checks+=1
    v=c.get('/api/halo/twin/validation',headers=auth).json()
    assert v['pipeline']['source_matches']; checks+=1
    assert v['fresh_evaluation']['source_matches'] and v['fresh_evaluation']['artifact_integrity'];checks+=1
    assert v['fresh_evaluation']['paired_lead_time']['threshold_only']['overall']['critical_cases']>0;checks+=1
    recovery=c.get('/api/halo/analysis-recovery',headers=auth)
    assert recovery.status_code==200;checks+=1
    external=c.get('/api/halo/twin/external-forecast',headers=auth)
    assert external.status_code==200 and external.json()['integrity'] and external.json()['units']=='source units';checks+=1
    example=c.get('/api/halo/twin/external-forecast/demo?origin_index=11520',headers=auth)
    assert example.status_code==200 and len(example.json()['forecasts'])==2;checks+=1
    assert c.get('/static/halo-external.js').status_code==200;checks+=1
    r=c.post('/api/halo/twin/runs',headers=auth,json={'request_id':'extracted-package-run'})
    assert r.status_code==200; run=r.json(); checks+=1
    observation=c.get('/api/halo/twin/runs/'+run['id']+'/observation-review',params={'revision':run['revision']},headers=auth)
    assert observation.status_code==200 and not observation.json()['hardware_action'];checks+=1
    case=c.get('/api/halo/twin/runs/'+run['id']+'/case',headers=auth).json()
    assert case['investigation']['observation_assessment']; checks+=1
    b=c.post('/api/halo/twin/challenges',headers=auth,json={'request_id':'extracted-package-blind'})
    assert b.status_code==200 and 'reveal' not in b.json(); checks+=1
    assert c.get('/api/halo/twin/runs/'+run['id']+'/report',headers=auth).status_code==200; checks+=1
    e=c.post('/api/halo/lab/experiments',headers=auth,json={'request_id':'extracted-package-bench','source':'software_emulator','name':'Extracted kit rehearsal'})
    assert e.status_code==200 and e.json()['source']=='software_emulator'; checks+=1
    e=e.json();url='/api/halo/lab/experiments/'+e['id']
    for action in ('freeze','advance'):
        r=c.post(url+'/actions',headers=auth,json={'revision':e['revision'],'action':action,'seconds':180})
        assert r.status_code==200; e=r.json(); checks+=1
    assert e['proofs'][0]['score']['assumptions_held']['count']==36;checks+=1
    assert c.get(url+'/export').status_code==200;checks+=1
    r=c.post('/api/halo/twin/challenges/import',headers=auth,json={
        'request_id':'extracted-oil-recording','name':'Synthetic package recording',
        'temperature_mode':'oil_only','healthy_reference_reviewed':True,'origin_index':90,
        'csv_text':Path('web/synthetic-observation-recording.csv').read_text(encoding='utf-8')})
    assert r.status_code==200,r.text;checks+=1
    url='/api/halo/twin/challenges/'+r.json()['id']
    frozen=c.post(url+'/assess',headers=auth).json()
    assert frozen['assessment']['result']['available'];checks+=1
    revealed=c.post(url+'/reveal',headers=auth).json()
    assert revealed['commitment_verified'] and revealed['scores']['target']=='oil_c' and revealed['scores']['count']==30;checks+=1
    assert c.get(url).json()==revealed;checks+=1
    workflow=c.get(url+'/workflow',headers=auth)
    assert workflow.status_code==200 and workflow.json()['binding'] is None;checks+=1
    denied=c.post(url+'/work',headers=auth,json={'request_id':'unbound-package-work','title':'Unbound recording must not create work','owner':'Package reviewer','acceptance_note':'A source binding must exist before this request is accepted.'})
    assert denied.status_code in (409,422,423);checks+=1
    print(json.dumps({'status':'pass','archive_boot':'extracted application with isolated SQLite','private_env_loaded':False,'hardware_control':False,'checks':checks}))
"""
        done=subprocess.run([sys.executable,'-c',code],cwd=target,env=env,text=True,capture_output=True)
        if done.returncode:raise RuntimeError(done.stderr or done.stdout)
        result=json.loads(done.stdout.strip().splitlines()[-1])
        result['verified_manifest_files']=len(manifest)
        result['archive_sha256']=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        (ROOT/'reports/submission-package-smoke-current.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
