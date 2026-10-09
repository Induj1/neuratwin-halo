"""Create labelled synthetic review CSVs and rehearse the real API in an isolated DB.

No live database, credentials, serial port, network notification or hardware command.
"""
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules['readline'] = None


def main():
    # Deliberately select a disposable local backend before importing the app.
    with tempfile.TemporaryDirectory(prefix='halo-reference-review-') as directory:
        os.environ.update(NEURATWIN_DB=str(Path(directory)/'review.sqlite3'), HALO_STORAGE_BACKEND='sqlite',
                          HALO_OPERATOR_TOKEN='isolated-reference-rehearsal', HALO_ALLOW_CONTROL='0')
        from fastapi.testclient import TestClient
        from neuratwin.app import app
        from neuratwin.validation_plant import generate
        from neuratwin import thermal_reference, twin_observer
        rows, _, _ = generate(88001, 'healthy')
        for i in range(75, len(rows)):
            previous=rows[i-1]
            rows[i].update(load_percent=70, ambient_c=30, voltage_pu=1)
            rows[i]['oil_c']=thermal_reference.step(previous['oil_c'],30,70,
                (rows[i]['elapsed_s']-previous['elapsed_s'])/60,55,100,1000/7500)
        texts={}
        for label, shift in (('before',6),('after',0)):
            stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(twin_observer.FIELDS));writer.writeheader()
            for i,row in enumerate(rows):
                writer.writerow({**row,'oil_c':row['oil_c']+(shift if i>=75 else 0),'hotspot_c':None})
            texts[label]=stream.getvalue()
            (ROOT/'web'/f'synthetic-review-{label}.csv').write_text(texts[label],encoding='utf-8')
        provenance={'asset_id':'SYNTHETIC-REVIEW-001','source_class':'synthetic','units_verified':True,
            'calibration_reference':'Synthetic generator scale v1; no physical sensor', 'calibration_reviewed':True,
            'configuration_reference':'Synthetic reference model 55C-rise/100min v1', 'configuration_reviewed':True,
            'reviewer':'Synthetic rehearsal reviewer','note':'Generated reference demonstration only; no field measurement or physical repair.'}
        base='/api/halo/twin/challenges';headers={'Authorization':'Bearer isolated-reference-rehearsal'}
        def post(client,url,payload=None):
            response=client.post(url,headers=headers,json=payload)
            if response.status_code!=200:raise RuntimeError(f'{url}: {response.status_code}: {response.text}')
            return response.json()
        with TestClient(app) as client:
            cases={}
            for label,day in (('before','01'),('after','02')):
                p={'request_id':'synthetic-review-'+label,'temperature_mode':'oil_only','csv_text':texts[label],
                    'name':'SYNTHETIC reference review '+label,'origin_index':90,'healthy_reference_reviewed':True,
                    'provenance':{**provenance,'recording_started_at':f'2026-01-{day}T00:00:00Z'}}
                c=post(client,base+'/import',p);cases[label]=post(client,base+'/'+c['id']+'/assess')
            origin=cases['before'];url=base+'/'+origin['id']
            w=post(client,url+'/work',{'request_id':'synthetic-review-work','title':'Review recorded thermal discrepancy',
                'owner':'Reference reviewer','acceptance_note':'A later synthetic reference must meet stable comparable-input criteria. No physical repair claim.'})
            work_url=url+'/work/'+w['id']
            for kind,minute in (('inspection','31'),('action','32')):
                w=post(client,work_url+'/observations',{'request_id':'synthetic-'+kind,'revision':w['revision'],
                    'kind':kind,'observed_at':f'2026-01-01T01:{minute}:00Z',
                    'note':f'Retrospective synthetic {kind}; no control command or physical intervention.'})
            w=post(client,work_url+'/followup',{'request_id':'synthetic-followup-link','revision':w['revision'],
                'case_id':cases['after']['id'],'note':'Later explicitly synthetic recording with the same source scale and assumed configuration.'})
            if not w['verification']['eligible']:raise RuntimeError(json.dumps(w['verification']))
            w=post(client,work_url+'/close',{'request_id':'synthetic-review-close','revision':w['revision'],
                'note':'Synthetic reference acceptance met; physical repair and causal benefit are not established.'})
            for c in cases.values():post(client,base+'/'+c['id']+'/reveal')
            export=client.get(url+'/workflow/export');export.raise_for_status()
            result={'status':'passed','source':'synthetic only','database':'temporary isolated SQLite; removed after rehearsal',
                'case_id':origin['id'],'followup_case_id':cases['after']['id'],'work_status':w['status'],
                'verification':w['verification'],'export_sha256':export.json()['sha256'],
                'physical_repair_verified':False,'hardware_commands_issued':0,
                'browser_inputs':{'before_file':'web/synthetic-review-before.csv','after_file':'web/synthetic-review-after.csv',
                    'origin_index':90,'temperature_mode':'oil_only','provenance':provenance,
                    'before_started_at':'2026-01-01T00:00:00Z','after_started_at':'2026-01-02T00:00:00Z',
                    'inspection_at':'2026-01-01T01:31:00Z','action_at':'2026-01-01T01:32:00Z'}}
            (ROOT/'reports'/'observation-workflow-rehearsal.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result,indent=2))


if __name__=='__main__':main()
