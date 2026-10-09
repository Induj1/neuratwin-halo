"""Recovery tests exercise the actual bridge outbox and server ingest/command APIs."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import importlib.util
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from test_halo import client,OP,DEVICE,frame,configure,calibration,post
from neuratwin.app import app
from neuratwin import halo_store as store
spec=importlib.util.spec_from_file_location('recovery_bridge',Path(__file__).parents[1]/'scripts/usb_bridge.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)


class IngestClient:
    def __init__(self,client):self.client=client;self.fail=None
    def post(self,path,json):
        if self.fail=='before':raise httpx.ConnectError('Injected network loss')
        r=self.client.post(path,json=json,headers=DEVICE)
        if self.fail=='after':raise httpx.ReadTimeout('Injected lost acknowledgment')
        return r


def test_network_loss_then_restart_replays_exact_frame_once(client,tmp_path):
    path=tmp_path/'outbox.sqlite3';queue=bridge.Outbox(path);f=frame();queue.append(f);queued=deepcopy(queue.next()[1]);transport=IngestClient(client)
    transport.fail='before'
    with pytest.raises(httpx.ConnectError):bridge.deliver_one(queue,transport)
    assert queue.next() and not store.frames('HALO-ESP32')
    transport.fail='after'
    with pytest.raises(httpx.ReadTimeout):bridge.deliver_one(queue,transport)
    assert len(store.frames('HALO-ESP32'))==1 and queue.next()
    queue.close();queue=bridge.Outbox(path)
    # A fresh application client represents a backend process restart against persisted records.
    with TestClient(app) as restarted:
        accepted=bridge.deliver_one(queue,IngestClient(restarted))
    assert accepted==queued and queue.next() is None
    assert datetime.fromisoformat(accepted['timestamp'].replace('Z','+00:00'))==datetime.fromisoformat(f['timestamp'])
    assert len(store.frames('HALO-ESP32'))==1
    queue.close()


def test_conflicting_duplicate_quarantined_without_poisoning_next(client,tmp_path):
    f=frame();client.post('/api/halo/telemetry',headers=DEVICE,json=f)
    queue=bridge.Outbox(tmp_path/'queue');queue.append({**f,'surface_c':40})
    assert bridge.deliver_one(queue,IngestClient(client)) is None
    assert queue.db.execute('SELECT state FROM outbox').fetchone()[0]=='rejected'
    assert store.frames('HALO-ESP32')[-1]['surface_c']==30
    queue.close()


def test_late_ack_cannot_become_success_or_contact_feedback(client):
    r=post(client,'/relays',{'states':[False]*4,'request_id':'late-command'}).json()
    r['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat();store.put('command',r['id'],r)
    ack=client.post('/api/halo/device/commands/'+r['id']+'/ack',headers=DEVICE,json={'accepted':True,'states':[False]*4})
    assert ack.status_code==409 and store.get('command',r['id'])['status']=='expired'


def test_delivery_revokes_a_queued_on_command_when_latch_changes(client,monkeypatch):
    configure(client);calibration(client);monkeypatch.setenv('HALO_ALLOW_CONTROL','1')
    client.post('/api/halo/telemetry',headers=DEVICE,json=frame(calibration_id='CAL-TEST'))
    cmd=post(client,'/relays',{'states':[True,False,False,False],'request_id':'queued-on-command'});assert cmd.status_code==200
    store.put('twin_prototype','BENCH-001',{'latched':True})
    assert client.get('/api/halo/device/commands',headers=DEVICE).json()['commands']==[]
    assert store.get('command','queued-on-command')['status']=='cancelled'


def test_bridge_permission_expires_and_checks_handshake(client):
    configure(client);c=client.get('/api/halo/config').json()['config']
    hello={**c,'chip':'ESP32','boot_id':'boot-test','protocol':1,'adc_verified':True,'relay_verified':True,'control_compiled':True}
    configuration={**client.get('/api/halo/config').json(),'control_enabled':True};f=frame(quality_flags=[])
    assert bridge.control_permit(hello,configuration,f,100,100,101,accepted_frame=f)
    assert not bridge.control_permit(hello,configuration,f,100,100,101)
    for key,value in [('boot_id','previous-boot'),('sequence',-1),('timestamp','2026-01-01T00:00:00Z')]:
        assert not bridge.control_permit(hello,configuration,f,100,100,101,accepted_frame={**f,key:value})
    assert not bridge.control_permit(hello,configuration,f,100,100,103,accepted_frame=f) # USB stops
    assert not bridge.control_permit(hello,configuration,f,100,80,101,accepted_frame=f) # stale config
    for change in ({'boot_id':'new-boot'},{'device_id':'OTHER'},{'protocol':2},{'chip':'ESP32-S3'}):
        assert not bridge.control_permit({**hello,**change},configuration,f,100,100,101,accepted_frame=f)
    assert not bridge.control_permit(hello,configuration,{**f,'current_a':None},100,100,101,accepted_frame=f)
    assert not bridge.control_permit(hello,configuration,{**f,'quality_flags':['current_adc_range']},100,100,101,accepted_frame=f)
    assert not bridge.control_permit(hello,configuration,{**f,'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=20)).isoformat()},100,100,101,accepted_frame=f)


def test_emulator_cannot_be_forwarded_as_physical_frame():
    with pytest.raises(ValueError,match='physical telemetry'):
        bridge.convert({'device_id':'EMULATOR','emulated':True},{},{})
