"""Restart an isolated API process and recover an actual durable USB outbox.

Uses loopback and temporary SQLite; never reads .env or opens a serial port.
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import os
import sys
import tempfile
import subprocess
import socket
import time
import json
import httpx
from usb_bridge import Outbox,deliver_one
ROOT=Path(__file__).resolve().parents[1]


def main():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='halo-recovery-') as folder:
        folder=Path(folder);env={k:v for k,v in os.environ.items() if not k.startswith(('HALO_','SUPABASE_','NEURATWIN_'))}
        env.update(HALO_STORAGE_BACKEND='sqlite',NEURATWIN_DB=str(folder/'app.sqlite3'),HALO_ALLOW_CONTROL='0',HALO_DEVICE_TOKEN='isolated-recovery-fixture')
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        server=f'http://127.0.0.1:{port}';log=(folder/'server.log').open('w');process=None
        def stop():
            nonlocal process
            if process:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                process=None
        def start():
            nonlocal process
            process=subprocess.Popen([sys.executable,'-m','uvicorn','neuratwin.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Disposable API exited before readiness.')
                try:
                    if httpx.get(server+'/api/health',timeout=.5).status_code==200:return
                except httpx.HTTPError:pass
                time.sleep(.1)
            raise RuntimeError('Disposable API did not become ready.')
        queue=Outbox(folder/'bridge.sqlite3')
        try:
            start();acquired=datetime.now(timezone.utc)-timedelta(seconds=10)
            frame={'device_id':'HALO-ESP32','boot_id':'restart-fixture','sequence':1,'uptime_ms':1000,'timestamp':acquired.isoformat(),
                   'secondary_v':12,'current_a':.3,'surface_c':30,'relay_states':[False]*4,'relay_output_configured':False}
            queue.append(frame);queued=queue.next()[1]
            with httpx.Client(base_url=server,headers={'Authorization':'Bearer isolated-recovery-fixture'},timeout=2) as client:
                r=client.post('/api/halo/telemetry',json=queued);r.raise_for_status()
                # Simulate a response lost after durable commit: leave outbox pending.
                first_pid=process.pid;stop();checks.append('Backend process terminated after accepting a frame; bridge acknowledgment deliberately lost')
                try:deliver_one(queue,client);raise AssertionError('An unavailable API must not complete the outbox.')
                except httpx.HTTPError:pass
                assert queue.next();checks.append('Network loss retained the original pending acquisition')
                queue.close();queue=Outbox(folder/'bridge.sqlite3');start();assert process.pid!=first_pid
                assert deliver_one(queue,client)==queued and queue.next() is None
                r=client.get('/api/halo/lab/commissioning');r.raise_for_status();d=r.json()['diagnostics']
                assert d['frames']==1 and d['latest']['sequence']==1
                assert datetime.fromisoformat(d['latest']['timestamp'].replace('Z','+00:00'))==acquired
                checks.append('New API process and reopened bridge spool recovered exactly one frame with original acquisition time')
                assert d['connection']=='stale';checks.append('Restarted historical frame is visibly stale, never live')
                assert client.get('/api/halo/commands').json()['commands']==[];checks.append('No physical relay command generated')
        finally:queue.close();stop();log.close()
    report={'status':'passed','scope':'Real disposable API process restart and durable outbox; no physical hardware or cloud outage injection','checks':checks}
    (ROOT/'reports/transport-recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
