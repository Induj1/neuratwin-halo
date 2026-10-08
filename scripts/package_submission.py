"""Build an allowlisted source/evidence kit. Never includes the private environment."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'submission'/'Neura-Rangers-NeuraTwin-Halo-Submission.zip'
FIXED=('README.md','.env.example','requirements.txt','requirements-dev.txt','requirements-laya.txt','start-halo.ps1')
TREES={'neuratwin':{'.py'},'tests':{'.py'},'scripts':{'.py','.ps1'},'firmware':{'.ino','.h'},
       'supabase/migrations':{'.sql'},'web':{'.html','.js','.css','.svg','.png','.jpg','.webp','.mp4','.webmanifest','.txt','.csv'},
       'docs':{'.md'}}
EXCLUDE={'hardware-guide.js','hardware-guide.css','hardware-schematic-atri.png'}
EVIDENCE=('halo-submission-tests.xml','submission-benchmark.json','submission-forecast-scores.csv','submission-anomaly-decisions.csv',
          'halo-submission-browser.json','halo-submission-desktop.jpg','halo-submission-mobile.jpg',
          'firmware-esp32.txt','firmware-esp32s3.txt','halo-laya-evaluation.json','synthetic-rehearsal-case.zip',
          'submission-package-smoke.json')


def files():
    result={name:(ROOT/name).read_bytes() for name in FIXED}
    for folder,extensions in TREES.items():
        for p in sorted((ROOT/folder).rglob('*')):
            if not p.is_file() or p.suffix not in extensions or p.name in EXCLUDE:continue
            relative=p.relative_to(ROOT)
            if any(part in ('archive','__pycache__','node_modules','.venv','.git','runtime') or part.startswith('.') for part in relative.parts):continue
            result[relative.as_posix()]=p.read_bytes()
    for name in EVIDENCE:
        p=ROOT/'reports'/name
        if not p.exists():raise SystemExit(f'Missing submission evidence: {name}')
        result['reports/'+name]=p.read_bytes()
    for name in ('synthetic-oil-reference.csv','cpri_reference_checks.json','demo_calibration.json'):
        p=ROOT/'data'/name;result[p.relative_to(ROOT).as_posix()]=p.read_bytes()
    # Embedded relative links keep the dossier and current handoff easy to find offline.
    result['START-HERE.html']=b'''<!doctype html><html lang="en"><meta charset="utf-8"><title>NeuraTwin submission kit</title><style>body{font:20px/1.7 system-ui;max-width:850px;margin:8vh auto;padding:24px;color:#243d36}a{color:#276549}</style><h1>NeuraTwin Halo</h1><p>Neura Rangers / CPRI Track 2</p><ol><li><a href="web/submission-guide.html">Read the submission dossier and five-minute demo</a></li><li><a href="web/hardware-guide.html">Read the current hardware handoff</a></li><li>Install requirements.txt, then run <code>python scripts/run_local_demo.py</code>.</li><li>Open <a href="http://127.0.0.1:8765/app#demo">the local application</a>.</li><li><a href="web/halo-fallback.html">Static synthetic walkthrough</a> for a presentation fallback.</li></ol><p>README.md describes tests, model limits and hardware holds. The hash manifest detects file changes, not authorship. No credentials, physical recordings or runtime database are included.</p></html>'''
    return result


def main():
    payload=files()
    # Scan actual value-shaped secrets, not variable names or deliberately short test fixtures.
    secret=re.compile(rb'(sb_secret_[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b)')
    for name,content in payload.items():
        if secret.search(content):raise SystemExit(f'Potential secret in {name}; packaging stopped without printing its value.')
    manifest={'format':'neuratwin-submission-1','scope':'Source and synthetic software evidence; hardware validation outstanding',
              'files':{name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in sorted(payload.items())}}
    payload['MANIFEST.json']=json.dumps(manifest,indent=2).encode()
    TARGET.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(TARGET,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(payload.items()):
            entry=zipfile.ZipInfo(name,date_time=(2026,10,8,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(entry,data)
    with zipfile.ZipFile(TARGET) as z:
        assert z.testzip() is None
        for name,expected in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==expected['sha256']
        assert not any('/runtime/' in '/'+n or Path(n).name=='.env' for n in z.namelist())
    print(json.dumps({'archive':str(TARGET),'files':len(payload),'bytes':TARGET.stat().st_size,
                      'sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
