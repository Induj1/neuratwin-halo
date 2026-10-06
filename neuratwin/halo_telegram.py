"""Telegram field workflow. Bot polling is opt-in; no messages are sent on startup."""
import os
import re
from fastapi import Depends, HTTPException
from pydantic import Field
from .halo_api import router, operator, Context, obtain, incident_or_404, WRITE_LOCK
from .halo_contracts import Contract, Observation
from . import halo_store as store, halo_workflow as workflow, halo_ai as ai
from .storage import now


def allowed_chats():
    return {v.strip() for v in os.getenv('HALO_TELEGRAM_ALLOWED_CHAT_IDS','').split(',') if v.strip()}


def field_message(text,actor,apply=True):
    tokens=text.strip().split(maxsplit=2)
    if not tokens: return 'Use /status BENCH-001 or /help.'
    cmd=tokens[0].split('@')[0].lower()
    help_text=('/status BENCH-001 | /status BENCH-SIM | /incidents\n'
               '/ack INC-ID\n/inspect INC-ID your observation\n'
               '/action INC-ID action performed\n/followup INC-ID follow-up observation\n'
               '/ask BENCH-001 your question\n/subscribe BENCH-001 | /unsubscribe\nPhotos: caption /photo INC-ID your note. '
               'No relay commands or resolution through chat.')
    if cmd in ('/help','/start'): return help_text
    if cmd in ('/subscribe','/unsubscribe'):
        if not apply: return 'Preview only: subscription preferences would be changed. No message sent.'
        pieces=actor.split(':')
        if len(pieces)!=3 or pieces[0]!='telegram' or pieces[1] not in allowed_chats(): return 'Subscription requires an allowed Telegram chat.'
        if cmd=='/subscribe' and (len(tokens)<2 or tokens[1]!='BENCH-001'): return 'Use /subscribe BENCH-001 for physical-bench alerts.'
        store.put('telegram_subscription',pieces[1],{'chat_id':pieces[1],'enabled':cmd=='/subscribe','asset_id':'BENCH-001','at':now()})
        return 'Physical-bench alert subscription '+('enabled. Use /unsubscribe to stop.' if cmd=='/subscribe' else 'disabled.')
    if cmd=='/incidents':
        return '\n'.join(f'{i["id"]} · {i["asset_id"]} · {i["state"]} · {i["title"]}' for i in store.records('incident')[:10]) or 'No incidents.'
    if cmd in ('/status','/ask'):
        if len(tokens)<2 or tokens[1] not in ('BENCH-001','BENCH-SIM','DT-SIM'): return 'Specify BENCH-001, BENCH-SIM or DT-SIM. Asset identity cannot be inferred.'
        mode={'BENCH-001':'bench','BENCH-SIM':'replay','DT-SIM':'transformer'}[tokens[1]]
        snap=obtain(mode,'overload' if mode=='transformer' else 'normal');row=snap.get('current') or {}
        if cmd=='/ask':
            if len(tokens)<3: return 'Add your question after the asset ID.'
            decision=ai.assess(snap,[])
            return ai.answer(tokens[2],snap,decision)['text']+'\nSource: '+snap['source']
        current=f'{row["current_a"]:.3f} A' if row.get('current_a') is not None else 'unavailable'
        temp=f'{row["surface_c"]:.1f} °C surface' if row.get('surface_c') is not None else 'unavailable'
        return f'{snap["asset_id"]} · {snap["source"]} · {snap["connection"]}\nCurrent: {current}\nTemperature: {temp}\nWarnings: '+('; '.join(a['title'] for a in snap['alerts']) or 'none in supplied evidence')
    if cmd not in ('/ack','/inspect','/action','/followup'): return help_text
    if len(tokens)<2 or not re.fullmatch(r'INC-[A-F0-9]{8}',tokens[1]): return 'Use the exact incident ID from /incidents.'
    row=store.get('incident',tokens[1])
    if not row: return 'Incident not found.'
    if not apply: return f'Preview only: {cmd} would address {row["id"]} on {row["asset_id"]}. No record changed.'
    with WRITE_LOCK:
        if cmd=='/ack':
            if row['state']!='open': return f'Incident is already {row["state"]}; no transition performed.'
            row['state']='acknowledged';row['transitions'].append({'state':'acknowledged','actor':actor,'at':now()})
            store.put('incident',row['id'],row)
        else:
            if len(tokens)<3 or len(tokens[2])<5: return 'Include a specific observation (at least five characters).'
            # actor includes Telegram update ID, providing an idempotent observation key.
            payload=Observation(request_id='tg-'+actor.replace(':','-'),kind={'/inspect':'inspection','/action':'action','/followup':'followup'}[cmd],note=tokens[2][:3000],observed_at=now())
            try: row=workflow.observe(row,payload,actor)
            except ValueError as e: return str(e)
    return f'{row["id"]} · {row["asset_id"]}: {row["state"]}. Recorded; acknowledgement is not verified resolution.'


class Preview(Contract):
    text:str=Field(min_length=1,max_length=3000)


@router.post('/telegram/preview')
def preview(payload:Preview,actor=Depends(operator)):
    return {'reply':field_message(payload.text,'preview',False),'sent':False}


@router.get('/telegram/status')
def telegram_status():
    return {'configured':bool(os.getenv('HALO_TELEGRAM_BOT_TOKEN') and allowed_chats()),
            'worker':store.get('integration','telegram'),
            'note':'Run the opt-in polling worker after setting the bot token and allowed chat IDs. No external messages are sent by the web preview.'}
