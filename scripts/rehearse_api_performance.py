"""Measured disposable loopback HTTP workload; no .env, cloud, serial or hardware.

Twelve independent industrial runs, ten state-changing actions per run and a
read-back after every action, at four concurrent clients. Reports measurements,
not an invented latency threshold, production SLA or fleet capacity.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import closing
from datetime import datetime,timezone
from importlib.metadata import version,PackageNotFoundError
from pathlib import Path
import argparse
import hashlib
import io
import json
import math
import os
import platform
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import httpx

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('neuratwin/app.py','neuratwin/halo_api.py','neuratwin/halo_store.py','neuratwin/twin_api.py',
         'neuratwin/twin_core.py','scripts/rehearse_api_performance.py')


def source_hashes():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def percentiles(values):
    ordered=sorted(values)
    def at(p):
        if not ordered:return None
        offset=(len(ordered)-1)*p;lo=math.floor(offset);hi=math.ceil(offset)
        return round(ordered[lo]+(ordered[hi]-ordered[lo])*(offset-lo),3)
    return {'count':len(ordered),'p50_ms':at(.5),'p95_ms':at(.95),'p99_ms':at(.99),
            'max_ms':round(ordered[-1],3) if ordered else None}


def machine_info():
    result={'os':platform.system(),'os_release':platform.release(),'architecture':platform.machine(),
            'processor':platform.processor() or 'unavailable','logical_cpu_count':os.cpu_count(),
            'python_version':platform.python_version(),'packages':{}}
    for name in ('fastapi','uvicorn','httpx','pydantic'):
        try:result['packages'][name]=version(name)
        except PackageNotFoundError:result['packages'][name]='unavailable'
    if os.name=='nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),
                ('available',ctypes.c_ulonglong),('total_page',ctypes.c_ulonglong),('available_page',ctypes.c_ulonglong),
                ('total_virtual',ctypes.c_ulonglong),('available_virtual',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
        memory=MemoryStatus();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result['physical_memory_gib']=round(memory.total/1024**3,2)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/local-api-performance.json')
    parser.add_argument('--contention-note',default='Other system activity was not controlled or profiled.')
    args=parser.parse_args()
    samples=[];failures=[];results=[];sample_lock=threading.Lock();run_count=12;concurrency=4
    started=datetime.now(timezone.utc).isoformat();process=None;server_stopped=False;sources_before=source_hashes()
    with tempfile.TemporaryDirectory(prefix='halo-api-performance-') as directory:
        folder=Path(directory);db_path=folder/'workload.sqlite3';token=secrets.token_urlsafe(24)
        env={k:v for k,v in os.environ.items() if not k.upper().startswith(('HALO_','SUPABASE_','NEURATWIN_'))}
        env.update(HALO_STORAGE_BACKEND='sqlite',NEURATWIN_DB=str(db_path),HALO_ALLOW_CONTROL='0',
                   HALO_OPERATOR_TOKEN=token,HALO_LOCAL_OPERATOR='0')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=f'http://127.0.0.1:{port}'
        def request(client,operation,method,path,**kwargs):
            begin=time.perf_counter();response=None
            try:
                response=client.request(method,path,**kwargs)
                response.raise_for_status()
                return response
            finally:
                entry={'operation':operation,'latency_ms':(time.perf_counter()-begin)*1000,
                       'status':response.status_code if response is not None else None}
                with sample_lock:samples.append(entry)

        def exercise(index):
            key=f'performance-run-{index:02d}';profile_name=f'Isolated HTTP workload {index:02d}'
            base_load=55+index*2;final_load=base_load+5;expected_elapsed=151+index
            with httpx.Client(base_url=server,headers={'Authorization':'Bearer '+token},timeout=30,trust_env=False) as client:
                state=request(client,'create','POST','/api/halo/twin/runs',json={'request_id':key,
                    'profile':{'name':profile_name}}).json()
                path='/api/halo/twin/runs/'+state['id']
                first_inputs={**state['inputs'],'load_percent':base_load,'ambient_c':25+index*.25}
                actions=[('inputs',{'inputs':first_inputs}),('start',{}),('step',{'seconds':60}),
                    ('step',{'seconds':61+index}),('pause',{}),
                    ('inputs',{'inputs':{**first_inputs,'load_percent':final_load}}),('start',{}),
                    ('step',{'seconds':30}),('pause',{}),
                    ('maintenance',{'maintenance':'inspection','note':f'Isolated synthetic inspection for run {index:02d}.'})]
                for number,(action,data) in enumerate(actions):
                    state=request(client,'action','POST',path+'/actions',json={'request_id':f'performance-{index:02d}-{number:02d}',
                        'revision':state['revision'],'action':action,**data}).json()
                    check=request(client,'read','GET',path).json()
                    assert check['id']==state['id'] and check['revision']==number+1
                    assert check['inputs']['load_percent']==(base_load if number<5 else final_load)
                    assert check['profile']['name']==profile_name
                    state=check
                assert state['revision']==10 and state['elapsed_s']==expected_elapsed and not state['running']
                assert state['source']=='industrial' and state['telemetry']['transformer_id']==state['id']
                response=request(client,'export','GET',path+'/report')
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    report=json.loads(archive.read('run.json'))
                    assert report['summary']['id']==state['id']
                    assert report['summary']['revision']==10
                    assert report['full_history'] and report['full_events']
                return {'run_index':index,'revision':state['revision'],'elapsed_s':state['elapsed_s'],
                        'load_percent':state['inputs']['load_percent'],'profile_matches':True,'report_matches':True}

        with (folder/'server.log').open('w',encoding='utf-8') as log:
            try:
                process=subprocess.Popen([sys.executable,'-m','uvicorn','neuratwin.app:app','--host','127.0.0.1',
                    '--port',str(port),'--workers','1','--no-access-log'],cwd=ROOT,env=env,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                deadline=time.monotonic()+30
                with httpx.Client(base_url=server,timeout=.5,trust_env=False) as readiness:
                    while time.monotonic()<deadline:
                        if process.poll() is not None:raise RuntimeError('Disposable API exited before readiness.')
                        try:
                            if readiness.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('Disposable API did not become ready.')
                start=time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    futures={executor.submit(exercise,index):index for index in range(run_count)}
                    for future in as_completed(futures):
                        try:results.append(future.result())
                        except Exception as error:failures.append({'run_index':futures[future],'error_type':type(error).__name__})
                elapsed=time.perf_counter()-start
                with httpx.Client(base_url=server,headers={'Authorization':'Bearer '+token},timeout=10,trust_env=False) as check:
                    diagnostic=check.get('/api/halo/analysis-recovery');diagnostic.raise_for_status()
                    worker=diagnostic.json()['worker']
                    commands=check.get('/api/halo/commands');commands.raise_for_status()
                    assert commands.json()['commands']==[]
            finally:
                if process:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    server_stopped=process.poll() is not None
        with closing(sqlite3.connect(db_path)) as db:
            persisted=[json.loads(row[0]) for row in db.execute("SELECT content FROM halo_records WHERE kind='twin_run'")]
            frame_count=db.execute('SELECT count(*) FROM halo_frames').fetchone()[0]
            physical_commands=db.execute("SELECT count(*) FROM halo_records WHERE kind='command'").fetchone()[0]
            persisted_verified=0
            for state in persisted:
                index=int(state['id'].rsplit('-',1)[-1])
                if (state['revision']==10 and state['elapsed_s']==151+index and
                    state['inputs']['load_percent']==60+index*2):persisted_verified+=1
        database_bytes=db_path.stat().st_size
    counts={str(code):sum(s['status']==code for s in samples) for code in sorted(set(s['status'] for s in samples),key=str)}
    sources_after=source_hashes();source_changes=[name for name in SOURCES if sources_before[name]!=sources_after[name]]
    passed=(len(results)==run_count and not failures and len(persisted)==run_count and
            persisted_verified==run_count and frame_count==0 and physical_commands==0 and server_stopped and not source_changes)
    report={'status':'passed' if passed else 'failed',
        'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Real loopback HTTP to a disposable single-process Uvicorn server and temporary SQLite; synthetic independent industrial runs.',
        'workload':{'runs':run_count,'actions_per_run':10,'readback_after_each_action':True,'export_per_run':True,
            'max_concurrent_clients':concurrency,'server_workers':1,'measured_requests':len(samples),
            'expected_requests':run_count*22,'readiness_and_final_diagnostics_excluded':True,
            'delete_operation':'Not exercised; the application exposes no run DELETE operation.'},
        'latency':{'all':percentiles([s['latency_ms'] for s in samples]),
            **{operation:percentiles([s['latency_ms'] for s in samples if s['operation']==operation]) for operation in ('create','action','read','export')}},
        'status_counts':counts,'request_error_count':sum(s['status'] is None or s['status']>=400 for s in samples),
        'run_errors':failures,'wall_seconds':round(elapsed,3),'observed_requests_per_second':round(len(samples)/elapsed,3),
        'isolation':{'passed_runs':len(results),'persisted_runs':len(persisted),'persisted_runs_verified':persisted_verified,
            'unique_profiles_and_inputs_verified':len(results)==run_count,
            'correct_revision_and_elapsed_per_run':len(results)==run_count,'report_matches_run':len(results)==run_count,
            'physical_frames':frame_count,'physical_commands':physical_commands,'server_stopped':server_stopped},
        'recovery_worker':{'running_during_workload':worker['running'],'hardware_commands_allowed':worker['hardware_commands_allowed'],
            'storage_failures':worker['storage_failures']},'database_bytes_after_workload':database_bytes,
        'machine':machine_info(),'contention_note':args.contention_note,
        'source_sha256':sources_before,'source_changed_during_run':source_changes,
        'limits':['Single local measured workload, not a capacity, security or production SLA claim.',
            'No remote Supabase, WAN latency, browser rendering or physical acquisition was measured.',
            'Four clients share one application process; this is not a multiprocess/fleet throughput test.',
            'No invented pass/fail latency threshold; only workload correctness is asserted.',
            'Percentiles use linear interpolation on this finite sample; repeat runs may differ.'],
        'runs':sorted(results,key=lambda row:row['run_index'])}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('status','workload','latency','request_error_count','run_errors','wall_seconds','isolation')},indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
