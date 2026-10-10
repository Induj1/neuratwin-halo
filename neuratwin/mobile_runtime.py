"""Single server simulation clock and opt-in event notification delivery."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import logging
import os
import time
import httpx
from . import cloud, halo_store as store, twin_core as core
from .halo_api import WRITE_LOCK

log=logging.getLogger(__name__)


def transaction():return cloud.transaction() if cloud.enabled() else nullcontext()


def clock_tick(wall=None):
    wall=time.time() if wall is None else wall
    with WRITE_LOCK, transaction():
        for current in store.records('twin_run'):
            if not current['running'] or wall-current.get('clock_wall',wall-2)<1.5:continue
            state=deepcopy(current)
            try:core.advance(state,state['inputs']['speed'])
            except ValueError:
                state['running']=False
                core.log(state,'paused','Run capacity reached; export and create a new run.')
            state['clock_wall']=wall
            state['revision']+=1
            store.put('twin_run',state['id'],state)


def queue_notifications():
    from .twin_api import prototype_view
    with WRITE_LOCK,transaction():
        for sub in store.records('mobile_subscription'):
            if not sub['enabled']:continue
            if sub['source']=='industrial':
                s=store.get('twin_run',sub['run_id'])
                if not s:continue
                snap=s;events=s['events']
                critical=[e for e in events if e.get('severity') in ('CRITICAL','TRIP')]
                latest=str(critical[-1]['id']) if critical else None
                body=critical[-1]['detail'] if critical else ''
            else:
                snap=prototype_view()
                critical=[a for a in snap['analysis']['alerts'] if a['severity'] in ('CRITICAL','TRIP')]
                latest='|'.join(sorted(a['code'] for a in critical)) or None
                body=critical[0]['detail'] if critical else ''
            key=hashlib.sha256(sub['token'].encode()).hexdigest()
            seen=store.get('mobile_notice_cursor',key)
            # Registration establishes a baseline, rather than replaying old alarms.
            if seen is not None and seen.get('asset_id')==snap['id'] and latest and latest!=seen.get('latest'):
                identity=hashlib.sha256((key+latest+snap['id']).encode()).hexdigest()
                if not store.get('mobile_outbox',identity):
                    store.put('mobile_outbox',identity,{'id':identity,'token':sub['token'],'actor':sub['actor'],
                        'title':'Transformer needs attention','body':body[:180],
                        'data':{'source':sub['source'],'run_id':sub.get('run_id'),'asset_id':snap['id']},
                        'state':'pending','attempts':0,'retry_at':0})
            store.put('mobile_notice_cursor',key,{'latest':latest,'asset_id':snap['id']})


def deliver_notifications():
    for notice in store.records('mobile_outbox'):
        if notice['state']!='pending' or notice['retry_at']>time.time():continue
        sub=store.get('mobile_subscription',hashlib.sha256(notice['token'].encode()).hexdigest())
        active=bool(sub and sub['enabled'] and sub['actor']==notice['actor'] and sub['asset_id']==notice['data']['asset_id'])
        if cloud.enabled() and notice['actor'].startswith('user:'):
            active=active and bool(cloud.rows('halo_members',{'user_id':'eq.'+notice['actor'][5:],'active':'eq.true','select':'role'},1))
        if not active:
            notice['state']='cancelled';store.put('mobile_outbox',notice['id'],notice);continue
        notice['attempts']+=1
        try:
            response=httpx.post('https://exp.host/--/api/v2/push/send',timeout=10,
                json={k:notice[k] for k in ('title','body','data')}|{'to':notice['token'],'sound':'default','channelId':'transformer-alerts'})
            response.raise_for_status();ticket=response.json()['data']
            if ticket.get('status')!='ok':raise ValueError('Push service rejected notification')
            notice.update(state='accepted',ticket=ticket.get('id'))
        except (httpx.HTTPError,ValueError,KeyError):
            notice['state']='failed' if notice['attempts']>=5 else 'pending'
            notice['retry_at']=time.time()+min(300,2**notice['attempts']*5)
        store.put('mobile_outbox',notice['id'],notice)


async def run():
    while True:
        try:
            if os.getenv('HALO_SERVER_CLOCK')=='1':await asyncio.to_thread(clock_tick)
            if os.getenv('HALO_PUSH_ENABLED')=='1':
                await asyncio.to_thread(queue_notifications)
                await asyncio.to_thread(deliver_notifications)
        except Exception:
            log.warning('Mobile background update deferred; retrying on next tick.')
        await asyncio.sleep(1.5)
