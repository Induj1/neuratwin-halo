"""Demonstration readiness and physical recording export. Never sends commands."""
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from .halo_api import Context, obtain, operator, status
from .halo_qualification import qualify
from . import halo_engine as engine, halo_store as store
from .storage import database, now

router=APIRouter(prefix='/api/halo/demo')
ROOT=Path(__file__).resolve().parents[1]


def readiness(context):
    snap=obtain(**context.model_dump()); checks=[]; services=status()
    def check(name,passed,detail,required=True):
        checks.append({'name':name,'status':'pass' if passed else 'fail' if required else 'attention','detail':detail,'required':required})
    check('Application response',True,'The application handled this authenticated request.')
    with database() as db:db.execute('SELECT 1').fetchone()
    check('Evidence database',True,'Local database is readable. This does not test every future disk write.')
    files=['halo.js','halo-evidence.js','halo-demo.js','halo-demo.html','halo-fallback.html','halo-arena.js','halo-arena.css','halo-arena-guide.html','vendor/three-0.149.0.min.js']
    missing=[f for f in files if not (ROOT/'web'/f).is_file()]
    check('Demonstration assets',not missing,'Missing: '+', '.join(missing) if missing else 'Workspace, 3D code and offline rehearsal are present.')
    check('Selected source',bool(snap['current']),f"{snap['asset_id']} / {snap['source']} / {snap['connection']}")
    physical=context.mode=='bench'
    if physical:
        check('Sensor freshness',snap['connection']=='live','Fresh physical telemetry is required; replay cannot satisfy this check.')
        required=('secondary_v','current_a','surface_c'); current=snap.get('current') or {}
        check('Required sensor channels',all(current.get(k) is not None for k in required) and not current.get('quality_flags'), 'Secondary voltage, current and surface temperature; no acquisition flags.')
        check('Per-channel calibration',snap['quality']['calibration']=='reference recorded','Electrical and surface references must be recorded independently.')
        check('Commissioning review',not snap['holds'],'; '.join(snap['holds']) or 'Configured review is recorded; software does not certify electrical safety.')
    else:
        check('Replay identity',snap['source'] in ('simulated','replayed'),'Every demonstration reading remains labelled with its source.')
    qualification=qualify(snap,15 if context.mode=='transformer' else 3)
    check('Forecast qualification',qualification['status']=='qualified',qualification['reason'],False)
    # Perform an in-memory round trip, with no record creation or external transmission.
    raw=json.dumps({'asset':snap['asset_id'],'source':snap['source'],'current':snap.get('current')},allow_nan=False).encode()
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('check.json',raw)
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as z:valid=z.read('check.json')==raw
    check('Export serializer',valid,'JSON and ZIP round-trip passed. Browser download capability is checked by downloading a case.')
    check('Local language model',False,'Enabled; service health is not asserted by this check.' if services['local_model_enabled'] else 'Optional service disabled; deterministic explanations remain available.',False)
    return {'checked_at':now(),'asset_id':snap['asset_id'],'source':snap['source'],'ready':all(c['status']=='pass' for c in checks if c['required']),
            'checks':checks,'qualification':qualification,'hardware_switching_enabled':services['hardware_control_enabled'],
            'k4_locked':True,'note':'Read-only demonstration checks. Readiness does not permit energising equipment or remove commissioning holds.'}


@router.post('/readiness')
def preflight(context:Context,actor=Depends(operator)):
    return readiness(context)


@router.post('/recording')
def recording(actor=Depends(operator)):
    rows=store.frames(engine.config().device_id,20000)
    if not rows:raise HTTPException(409,'No physical samples recorded. A simulated file cannot replace a real hardware session.')
    fields=['timestamp','primary_v','secondary_v','current_a','surface_c','ambient_c','ambient_source','ambient_observed_at','calibration_id','device_id','boot_id','sequence']
    output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader()
    for row in rows:writer.writerow({k:row.get(k) for k in fields})
    calibrations={r.get('calibration_id') for r in rows if r.get('calibration_id')}
    metadata={'exported_at':now(),'source':'recorded physical telemetry','device_id':engine.config().device_id,'count':len(rows),
              'first':rows[0]['timestamp'],'last':rows[-1]['timestamp'],'calibrations':[store.get('calibration',k) for k in sorted(calibrations)],
              'notice':'Raw frame JSON retains quality flags and relay GPIO reports. CSV is a review extract, not proof of calibration or contact operation.'}
    files={'physical-telemetry.csv':output.getvalue().encode(),'frames.json':json.dumps(rows,indent=2).encode(),'provenance.json':json.dumps(metadata,indent=2).encode()}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
        z.writestr('manifest.json',json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in files.items()},indent=2))
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="halo-physical-recording.zip"','Cache-Control':'no-store'})


@router.post('/kit')
def kit(actor=Depends(operator)):
    files=['halo-fallback.html','halo-architecture.svg','halo-bench-checklist.html','halo-demo-script.html','halo-rehearsal.mp4','halo-arena-guide.html']
    missing=[name for name in files if not (ROOT/'web'/name).is_file()]
    if missing:raise HTTPException(409,'Demo kit incomplete: '+', '.join(missing))
    stream=io.BytesIO();manifest={}
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name in files:
            path=ROOT/'web'/name
            content=path.read_bytes();z.writestr(name,content);manifest[name]=hashlib.sha256(content).hexdigest()
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
        z.writestr('START-HERE.txt','Open halo-fallback.html in a browser without a server. All included telemetry is explicitly simulated. Use halo-demo-script.html for the live app walkthrough and halo-bench-checklist.html for uncompleted physical checks. The architecture SVG is not a wiring diagram. No real recording is invented; export one separately after actual acquisition.')
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="halo-demo-kit.zip"','Cache-Control':'no-store'})
