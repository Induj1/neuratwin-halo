"""Portable bench-workflow rehearsal in disposable storage, with no hardware."""
from pathlib import Path
import os
import sys
import json
import tempfile
import zipfile
import io
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='halo-bench-') as folder:
        os.environ.update(HALO_STORAGE_BACKEND='sqlite',NEURATWIN_DB=str(Path(folder)/'lab.sqlite3'),HALO_ALLOW_CONTROL='0',HALO_AI_ENABLED='0')
        for name in ('HALO_OPERATOR_TOKEN','HALO_DEVICE_TOKEN'):os.environ.pop(name,None)
        from fastapi.testclient import TestClient
        from neuratwin.app import app
        from neuratwin.halo_api import LOCAL_TOKEN
        from neuratwin import halo_store
        checks=[]
        with TestClient(app) as client:
            def post(url,value):
                r=client.post(url,json=value,headers={'Authorization':'Bearer '+LOCAL_TOKEN});assert r.status_code==200,r.text;return r.json()
            e=post('/api/halo/lab/experiments',{'request_id':'portable-rehearsal','name':'Software-only bench rehearsal','source':'software_emulator'})
            url='/api/halo/lab/experiments/'+e['id'];checks.append('Emulator records isolated from physical acquisition')
            def act(action,**extra):
                nonlocal e
                e=post(url+'/actions',{'revision':e['revision'],'action':action,**extra})
            act('freeze');original=e['proofs'][0]['proof'];act('advance',seconds=180)
            assert e['proofs'][0]['proof']==original and e['proofs'][0]['score']['assumptions_held']['count']==36
            checks.append('Prospective surface forecast scored on 36 later observations')
            act('freeze');act('load',branches=1,note='Software demand reduction');act('advance',seconds=180)
            assert e['proofs'][1]['score']['changed_input_samples']>0;checks.append('Changed inputs separated from comparable forecast error')
            act('mark',kind='intervention',note='Emulated load response observed; no physical command.')
            act('mark',kind='recovery',note='Follow-up annotation only; does not certify a physical repair.');act('stop')
            data=client.get(url+'/export').content
            with zipfile.ZipFile(io.BytesIO(data)) as z:assert z.testzip() is None and 'replay.html' in z.namelist()
            (ROOT/'reports/bench-experiment-rehearsal.zip').write_bytes(data);checks.append('Stopped experiment exported with self-contained offline replay')
            assert not halo_store.records('command') and not halo_store.frames('HALO-ESP32')
            checks.append('Zero physical commands and zero physical telemetry frames created')
        report={'scope':'Software emulator workflow; not hardware validation','status':'passed','checks':checks,
                'forecasts':[x['score'] for x in e['proofs']]}
        (ROOT/'reports/bench-workflow-rehearsal.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps({'status':report['status'],'checks':checks},indent=2))


if __name__=='__main__':main()
