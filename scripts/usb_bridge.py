"""Opt-in USB transport. No serial port is opened until --port is supplied.

Frames keep their acquisition time through retries. A durable SQLite outbox is
separate from the application database. This is not an electrical safety device.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuratwin.halo_contracts import Frame, BenchConfig
from neuratwin.halo_engine import holds


class Outbox:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, identity TEXT UNIQUE, content TEXT, state TEXT DEFAULT "pending", error TEXT)')
        self.db.commit()
    def append(self,frame):
        value=Frame.model_validate(frame).model_dump(mode='json')
        identity=f'{value["device_id"]}/{value["boot_id"]}/{value["sequence"]}'
        content=json.dumps(value,sort_keys=True,allow_nan=False)
        old=self.db.execute('SELECT content FROM outbox WHERE identity=?',(identity,)).fetchone()
        if old and old[0]!=content: raise ValueError('Device reused an acquisition sequence.')
        self.db.execute('INSERT OR IGNORE INTO outbox(identity,content) VALUES (?,?)',(identity,content));self.db.commit()
    def next(self):
        r=self.db.execute('SELECT id,content FROM outbox WHERE state="pending" ORDER BY id LIMIT 1').fetchone()
        return (r[0],json.loads(r[1])) if r else None
    def finish(self,key,state,error=None):
        self.db.execute('UPDATE outbox SET state=?,error=? WHERE id=?',(state,error,key));self.db.commit()
    def close(self): self.db.close()


def convert(raw,anchor,calibration,ambient=None):
    if raw.get('boot_id')!=anchor['boot_id']: raise ValueError('Handshake required after a reboot.')
    elapsed=(int(raw['uptime_ms'])-anchor['uptime_ms'])/1000
    if elapsed<0: raise ValueError('Pre-handshake buffered frame discarded.')
    timestamp=anchor['utc']+timedelta(seconds=elapsed)
    if timestamp>datetime.now(timezone.utc)+timedelta(seconds=2): raise ValueError('Device clock moved into the future.')
    flags=list(raw.get('quality_flags',[]));values={};cal=calibration or {}
    for name,unit in [('primary','v'),('secondary','v'),('current','a')]:
        rms=raw.get(name+'_rms_mv');scale=cal.get(f'{name}_{unit}_per_mv')
        invalid=any(f in flags for f in ('adc_unverified','pinmap_unverified','sampling_overrun',name+'_adc_range'))
        if rms is None or scale is None or invalid: values[f'{name}_{unit}']=None
        elif name=='current': values['current_a']=math.sqrt(max(0,rms*rms-cal.get('current_noise_mv',0)**2))*scale
        else: values[f'{name}_{unit}']=rms*scale
    surface=raw.get('surface_raw_c')
    values['surface_c']=surface+cal.get('surface_offset_c',0) if surface is not None else None
    if not calibration: flags.append('calibration_unrecorded')
    raw_values={k:v for k,v in raw.items() if k.endswith(('_mv','_us')) or k in ('sample_count','surface_raw_c')}
    ambient_time=datetime.fromisoformat(ambient['observed_at']) if ambient else None
    valid_ambient=ambient_time is not None and 0<=(timestamp-ambient_time).total_seconds()<=600
    return Frame(device_id=raw['device_id'],boot_id=raw['boot_id'],sequence=raw['sequence'],uptime_ms=raw['uptime_ms'],timestamp=timestamp,
                 **values,ambient_c=ambient['value_c'] if valid_ambient else None,ambient_source='manual' if valid_ambient else 'not_measured',
                 ambient_observed_at=ambient_time if valid_ambient else None,relay_states=raw['relay_states'],
                 relay_output_configured=raw.get('relay_output_configured',False),
                 calibration_id=cal.get('id'),quality_flags=flags,raw=raw_values).model_dump(mode='json')


def compatible(hello,config):
    c=BenchConfig.model_validate(config)
    if holds(c) or not all(hello.get(k) for k in ('pinmap_verified','adc_verified','relay_verified','control_compiled')): return False
    chip=hello.get('chip','').upper()
    if ('S3' in chip)!=(c.board=='ESP32-S3') or not chip.startswith('ESP32'): return False
    return all(hello.get(k)==getattr(c,k) for k in ('primary_adc_pin','secondary_adc_pin','current_adc_pin','temperature_pin','active_low')) and hello.get('relay_pins')==list(c.relay_pins)


def run(port,server,queue_path):
    import serial
    token=os.getenv('HALO_DEVICE_TOKEN')
    if not token: raise SystemExit('Set HALO_DEVICE_TOKEN in both the application and this bridge. No port opened.')
    if not server.startswith(('http://127.0.0.1:','http://localhost:','https://')): raise SystemExit('Use loopback HTTP or authenticated HTTPS.')
    queue=Outbox(queue_path);hello=None;anchor=None;configuration=None;next_config=0;last_frame=None;nonce=None;sent_at=None;last_accepted=0
    with httpx.Client(base_url=server,headers={'Authorization':'Bearer '+token},timeout=2) as client, serial.Serial(port,115200,timeout=.05,write_timeout=1) as usb:
        def write(value): usb.write((json.dumps(value,separators=(',',':'))+'\n').encode())
        def handshake():
            nonlocal nonce,sent_at
            nonce=secrets.token_hex(8);sent_at=(datetime.now(timezone.utc),time.monotonic());write({'type':'hello','nonce':nonce})
        handshake();buffer=b'';next_poll=0
        try:
            while True:
                if time.monotonic()>=next_config:
                    try:
                        r=client.get('/api/halo/device/config');r.raise_for_status();configuration=r.json();next_config=time.monotonic()+10
                    except httpx.HTTPError: next_config=time.monotonic()+3
                incoming=usb.read(usb.in_waiting or 1)
                if incoming: buffer+=incoming
                if len(buffer)>16384: buffer=b'';anchor=None;handshake()
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1)
                    try:
                        raw=json.loads(line)
                        if raw.get('type')=='hello':
                            if raw.get('nonce')!=nonce:
                                if anchor is None or raw.get('boot_id')!=anchor['boot_id']:anchor=None;handshake()
                                continue
                            rtt=time.monotonic()-sent_at[1]
                            if rtt>.5:handshake();continue
                            hello=raw;anchor={'boot_id':raw['boot_id'],'uptime_ms':raw['uptime_ms'],'utc':sent_at[0]+timedelta(seconds=rtt/2)}
                            print('USB handshake established. Host UTC anchor; sensor channels remain subject to calibration.',flush=True)
                        elif raw.get('type')=='telemetry_raw':
                            if not anchor or raw.get('boot_id')!=anchor['boot_id']:anchor=None;handshake();continue
                            frame=convert(raw,anchor,(configuration or {}).get('calibration'),(configuration or {}).get('ambient'));queue.append(frame);last_frame=frame
                        elif raw.get('type')=='ack':
                            r=client.post('/api/halo/device/commands/'+raw['id']+'/ack',json={k:raw[k] for k in ('accepted','states','reason')});r.raise_for_status()
                    except (ValueError,KeyError,TypeError,httpx.HTTPError):
                        print('Rejected malformed, unanchored or refused USB message; no control permission granted.',flush=True)
                if time.monotonic()<next_poll: continue
                next_poll=time.monotonic()+.4
                try:
                    pending=queue.next()
                    fresh_accepted=False
                    if pending:
                        key,frame=pending;r=client.post('/api/halo/telemetry',json=frame)
                        if r.status_code in (409,422):queue.finish(key,'rejected',str(r.status_code));print('Historical or invalid queued frame quarantined.',flush=True)
                        else:
                            r.raise_for_status();queue.finish(key,'delivered')
                            fresh_accepted=(datetime.now(timezone.utc)-datetime.fromisoformat(frame['timestamp'].replace('Z','+00:00'))).total_seconds()<2
                            if fresh_accepted: last_accepted=time.monotonic()
                    c=(configuration or {}).get('config',{});cal=(configuration or {}).get('calibration') or {}
                    permit=bool(time.monotonic()-last_accepted<2 and hello and c and compatible(hello,c) and configuration.get('control_enabled') and not (last_frame or {}).get('quality_flags'))
                    write({'type':'heartbeat','permit':permit,**{k:cal.get(k) or 0 for k in ('current_a_per_mv','secondary_v_per_mv','current_noise_mv','surface_offset_c')},**{k:c.get(k) or 0 for k in ('current_limit_a','surface_limit_c','nominal_secondary_v')}})
                    r=client.get('/api/halo/device/commands');r.raise_for_status()
                    for cmd in r.json()['commands']:
                        enabling=any(cmd['states']);remaining=(datetime.fromisoformat(cmd['expires_at'])-datetime.now(timezone.utc)).total_seconds()
                        if remaining<=0: continue
                        if enabling and not permit: continue
                        device_now=anchor['uptime_ms']+(datetime.now(timezone.utc)-anchor['utc']).total_seconds()*1000 if anchor else 0
                        write({'type':'command','id':cmd['id'],'states':cmd['states'],'resistor_ohms':c.get('resistor_ohms',[39]*4),'deadline_uptime_ms':int(device_now+min(remaining,2)*1000)})
                except (httpx.HTTPError,ValueError,KeyError):
                    write({'type':'heartbeat','permit':False});next_poll=time.monotonic()+1
        finally:
            try:write({'type':'heartbeat','permit':False})
            finally:queue.close()


if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True,help='Explicit serial port, e.g. COM6. May reset the attached board.')
    parser.add_argument('--server',default='http://127.0.0.1:8765')
    parser.add_argument('--queue',default=str(Path(__file__).resolve().parents[1]/'runtime/usb-outbox.sqlite3'))
    args=parser.parse_args();run(args.port,args.server,args.queue)
