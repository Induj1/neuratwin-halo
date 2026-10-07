"""Explicitly started Telegram worker; only allowlisted chats may read or write."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuratwin.halo_telegram import allowed_chats, field_message
from neuratwin import halo_store as store, halo_workflow as workflow, cloud
from neuratwin.halo_contracts import Observation
from neuratwin.storage import now
from neuratwin.halo_api import obtain


def notify_subscribers(client,base):
    subscriptions=[s for s in store.records('telegram_subscription') if s['enabled'] and s['chat_id'] in allowed_chats()]
    if not subscriptions:return
    snap=obtain();codes=sorted(a['code'] for a in snap['alerts'])
    signature=hashlib.sha256(json.dumps(codes).encode()).hexdigest()
    for subscription in subscriptions:
        chat=subscription['chat_id'];previous=store.get('telegram_alert',chat)
        if previous and previous['signature']==signature:continue
        text='BENCH-001 · measured · '+snap['connection']+'\n'+('\n'.join(a['title'] for a in snap['alerts']) or 'Numerical warnings cleared in current evidence. Maintenance resolution still requires verification.')
        result=client.post(base+'sendMessage',json={'chat_id':chat,'text':text[:4000]});result.raise_for_status()
        if not result.json().get('ok'):raise ValueError('Alert refused')
        store.put('telegram_alert',chat,{'signature':signature,'at':now(),'codes':codes})


def run():
    token=os.getenv('HALO_TELEGRAM_BOT_TOKEN')
    if not token or not allowed_chats():
        raise SystemExit('Set HALO_TELEGRAM_BOT_TOKEN and HALO_TELEGRAM_ALLOWED_CHAT_IDS in your local environment. No messages sent.')
    base='https://api.telegram.org/bot'+token+'/'
    offset=store.get('integration','telegram_offset',{'offset':0})['offset']
    with httpx.Client(timeout=35) as client:
        while True:
            try:
                store.put('integration','telegram',{'status':'polling','at':now()})
                notify_subscribers(client,base)
                response=client.post(base+'getUpdates',json={'offset':offset,'timeout':5,'allowed_updates':['message']})
                response.raise_for_status(); body=response.json()
                if not body.get('ok'): raise ValueError('Telegram refused request')
                for update in body['result']:
                    uid=str(update['update_id']);message=update.get('message',{});chat=str(message.get('chat',{}).get('id',''))
                    with cloud.transaction():
                        prior=store.get('telegram_update',uid)
                        if chat in allowed_chats() and not prior:
                            actor=f'telegram:{chat}:{uid}'
                            reply=field_message(message.get('text') or message.get('caption') or '/help',actor)
                            if message.get('photo'):
                                try:
                                    words=(message.get('caption') or '').split(maxsplit=2)
                                    incident=store.get('incident',words[1]) if len(words)>1 and words[0]=='/photo' else None
                                    if not incident: reply='Photo not stored. Caption it /photo INC-ID inspection note.'
                                    elif incident['state']=='resolved': reply='Incident is resolved; open a new investigation.'
                                    else:
                                        file=client.post(base+'getFile',json={'file_id':message['photo'][-1]['file_id']}).json()
                                        path=file.get('result',{}).get('file_path','')
                                        if not file.get('ok') or '..' in path or not path.startswith('photos/'):
                                            raise ValueError('Unsupported photo path')
                                        photo=client.get('https://api.telegram.org/file/bot'+token+'/'+path)
                                        photo.raise_for_status();data=photo.content
                                        if len(data)>4_000_000: raise ValueError('Photo exceeds limit')
                                        from PIL import Image
                                        image=Image.open(io.BytesIO(data))
                                        if image.width*image.height>20_000_000: raise ValueError('Photo dimensions exceed limit')
                                        image.verify()
                                        if image.format not in ('JPEG','PNG'): raise ValueError('Unsupported image')
                                        key='PHOTO-TG-'+uid
                                        store.photo({'id':key,'incident_id':incident['id'],'filename':Path(path).name,
                                            'data':base64.b64encode(data).decode(),'mime':'image/jpeg' if image.format=='JPEG' else 'image/png',
                                            'sha256':hashlib.sha256(data).hexdigest(),'actor':actor,'created_at':now(),
                                            'interpretation':'Photo stored; no vision diagnosis performed.'},data)
                                        workflow.observe(incident,Observation(request_id='tg-photo-'+uid,kind='inspection',
                                            note=words[2] if len(words)>2 and len(words[2])>=5 else 'Telegram inspection photo received.',
                                            observed_at=now(),attachment_ids=[key]),actor)
                                        reply=f'{incident["id"]}: inspection photo stored. No automated image diagnosis.'
                                except (ValueError,KeyError,TypeError,OSError):
                                    reply="Photo could not be accepted. Use a valid incident ID and a JPEG/PNG below 4 MB and 20 megapixels."
                            # Persist before sending; retries cannot repeat a maintenance action.
                            store.put('telegram_update',uid,{'chat_id':chat,'reply':reply,'processed_at':now(),'delivery':'pending'})
                            prior=store.get('telegram_update',uid)
                    if prior and prior['delivery']=='pending':
                        sent=client.post(base+'sendMessage',json={'chat_id':chat,'text':prior['reply'][:4000]})
                        sent.raise_for_status()
                        if not sent.json().get('ok'): raise ValueError('Reply refused')
                        prior['delivery']='sent';store.put('telegram_update',uid,prior)
                    offset=update['update_id']+1
                    store.put('integration','telegram_offset',{'offset':offset})
            except KeyboardInterrupt:
                store.put('integration','telegram',{'status':'stopped','at':now()});return
            except Exception:
                # Never log exception URLs: Telegram embeds the bot token in URLs.
                store.put('integration','telegram',{'status':'retrying','at':now(),'error':'Network, configuration or message validation error'})
                time.sleep(3)


if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    run()
