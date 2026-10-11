"""Build an allowlisted source/evidence kit. Never includes the private environment."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'submission'/'Neura-Rangers-NeuraTwin-Halo-Submission.zip'
FIXED=('README.md','.env.example','requirements.txt','requirements-dev.txt','requirements-laya.txt','requirements-esp32.txt','start-halo.ps1')
TREES={'neuratwin':{'.py'},'tests':{'.py','.mjs'},'scripts':{'.py','.ps1'},'firmware':{'.ino','.h'},
       'supabase/migrations':{'.sql'},'web':{'.html','.js','.css','.svg','.png','.jpg','.webp','.mp4','.webmanifest','.txt','.csv'},
       'docs':{'.md'}}
EXCLUDE={'hardware-guide.js','hardware-guide.css','hardware-schematic-atri.png','COMPETITOR_AUDIT_AND_EXECUTION_PLAN_2026-10-08.md'}
EVIDENCE=('halo-v6-tests.xml','halo-v6-js-tests.txt','halo-v6-browser.json','model-v6-upgrade.json',
          'halo-v6-tests-before-timeout-fix.xml','halo-v6-queue-recheck.xml',
          'external-ett-protocol.json','external-ett-claim.json','external-ett-report.json',
          'pipeline-v6-fresh-protocol.json','pipeline-v6-fresh-protocol-claim.json','pipeline-v6-seed-history-note.json',
          'pipeline-v6-fresh-protocol-run/benchmark.json','pipeline-v6-fresh-protocol-run/manifest.json',
          'pipeline-v6-fresh-protocol-run/forecasts.csv','pipeline-v6-fresh-protocol-run/decisions.csv',
          'pipeline-v5-before-v6-benchmark.json','pipeline-v5-before-v6-forecasts.csv','pipeline-v5-before-v6-decisions.csv',
          'winding-development-candidate/benchmark.json','winding-development-candidate/forecasts.csv','winding-development-candidate/decisions.csv',
          'winding-development-projection-only/benchmark.json','winding-development-projection-only/forecasts.csv','winding-development-projection-only/decisions.csv',
          'halo-release-tests.xml','halo-release-js-tests.txt','halo-release-browser.json','halo-release-desktop.jpg','halo-release-mobile.jpg',
          'analysis-recovery-rehearsal.json','local-api-performance.json',
          'pipeline-v5-fresh-protocol.json','pipeline-v5-fresh-protocol-claim.json',
          'pipeline-v5-fresh-protocol-run/benchmark.json','pipeline-v5-fresh-protocol-run/manifest.json',
          'pipeline-v5-fresh-protocol-run/forecasts.csv','pipeline-v5-fresh-protocol-run/decisions.csv',
          'pipeline-v4-before-v5-benchmark.json','pipeline-v4-before-v5-decisions.csv','pipeline-v4-before-v5-forecasts.csv',
          'halo-hardening-tests.xml','halo-hardening-browser.json','halo-hardening-desktop.jpg','halo-hardening-mobile.jpg','halo-hardening-js-tests.txt',
          'observation-workflow-rehearsal.json','hardware-provenance-rehearsal.json','hardware-cloud-migration.json','pipeline-v4-protocol.json',
          'pipeline-v3-before-v4-benchmark.json','pipeline-v3-before-v4-decisions.csv','pipeline-v3-before-v4-forecasts.csv',
          'halo-synchronized-tests.xml','halo-synchronized-browser.json','halo-synchronized-desktop.jpg','halo-synchronized-mobile.jpg','halo-synchronized-js-tests.txt',
          'halo-submission-tests.xml','halo-judge-fixes-tests.xml','submission-benchmark.json','submission-forecast-scores.csv','submission-anomaly-decisions.csv',
          'halo-decision-v3-tests.xml','pipeline-v3-protocol.json','pipeline-v2-historical-benchmark.json',
          'halo-decision-v3-browser.json','halo-decision-v3-desktop.jpg','halo-decision-v3-mobile.jpg',
          'halo-software-upgrades-tests.xml','pipeline-v1-historical.json','pipeline-v2-protocol.json','pipeline-development-benchmark.json',
          'bench-experiment-rehearsal.zip','bench-workflow-rehearsal.json','transport-recovery.json',
          'halo-bench-lab-browser.json','halo-bench-lab-desktop.jpg','halo-bench-lab-mobile.jpg',
          'pipeline-benchmark.json','pipeline-benchmark-baseline.json','pipeline-forecasts.csv','pipeline-decisions.csv',
          'workflow-rehearsal.json','synthetic-blind-case.json','halo-judge-fixes-browser.json','halo-judge-fixes-desktop.jpg','halo-judge-fixes-mobile.jpg',
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
    for name in ('ETTh1.csv','LICENSE.txt','UPSTREAM_README.md','provenance.json','forecast-models.json'):
        p=ROOT/'data/external/ett'/name;result[p.relative_to(ROOT).as_posix()]=p.read_bytes()
    # Embedded relative links keep the dossier and current handoff easy to find offline.
    result['START-HERE.html']=b'''<!doctype html><html lang="en"><meta charset="utf-8"><title>NeuraTwin submission kit</title><style>body{font:20px/1.7 system-ui;max-width:850px;margin:8vh auto;padding:24px;color:#243d36}a{color:#276549}</style><h1>NeuraTwin Halo</h1><p>Neura Rangers / CPRI Track 2</p><ol><li><a href="web/submission-guide.html">Read the submission dossier and five-minute demo</a></li><li><a href="web/hardware-guide.html">Read the current hardware handoff</a></li><li>Install requirements.txt, then run <code>python scripts/run_local_demo.py</code>.</li><li>Open <a href="http://127.0.0.1:8765/app#demo">the local application</a>.</li><li><a href="web/halo-fallback.html">Static synthetic walkthrough</a> for a presentation fallback.</li></ol><p>README.md describes tests, model limits and hardware holds. The hash manifest detects file changes, not authorship. No credentials, physical recordings or runtime database are included.</p></html>'''
    return result


def main():
    payload=files()
    # Scan actual value-shaped secrets, not variable names or deliberately short test fixtures.
    secret=re.compile(rb'(sb_secret_[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b)')
    for name,content in payload.items():
        if secret.search(content):raise SystemExit(f'Potential secret in {name}; packaging stopped without printing its value.')
    manifest={'format':'neuratwin-submission-1','scope':'Source, synthetic software evidence and a separately labelled public historical dataset; hardware validation outstanding',
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
