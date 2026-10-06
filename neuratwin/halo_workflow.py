"""Maintenance is a traceable sequence, not an acknowledgement-to-resolved toggle."""
import statistics
import uuid
from datetime import datetime, timezone
from . import halo_store as store
from .halo_engine import timestamp
from .storage import now

STATES=['open','acknowledged','inspected','action_recorded','verification_pending','resolved']


def open_incident(snap,actor):
    if not snap['alerts']: raise ValueError('No active warning to open an incident from.')
    for row in store.records('incident'):
        if row['asset_id']==snap['asset_id'] and row['state']!='resolved': return row
    row={'id':'INC-'+uuid.uuid4().hex[:8].upper(),'asset_id':snap['asset_id'],'source':snap['source'],
         'state':'open','title':snap['alerts'][0]['title'],'created_at':now(),'observations':[],
         'baseline':snap,'transitions':[{'state':'open','actor':actor,'at':now()}],'verification':None}
    store.put('incident',row['id'],row); store.event(row['asset_id'],'incident_opened',{'id':row['id'],'actor':actor})
    return row


def observe(incident,payload,actor):
    if incident['state']=='resolved': raise ValueError('Resolved incident is immutable; open a new investigation.')
    for existing in incident['observations']:
        if existing['request_id']==payload.request_id:
            if any(existing.get(k)!=v for k,v in payload.model_dump(mode='json').items()):
                raise ValueError('Request ID reused for different evidence.')
            return incident
    if payload.observed_at>datetime.now(timezone.utc): raise ValueError('Observation cannot be in the future.')
    for attachment in payload.attachment_ids:
        info=store.get('attachment',attachment)
        if not info or info['incident_id']!=incident['id']: raise ValueError('Attachment does not belong to this incident.')
    if payload.kind=='action' and incident['state'] not in ('inspected','action_recorded'):
        raise ValueError('Record an inspection before a maintenance action.')
    if payload.kind=='followup' and incident['state'] not in ('action_recorded','verification_pending'):
        raise ValueError('Record the intervention before follow-up evidence.')
    if incident['observations'] and payload.observed_at<timestamp(incident['observations'][-1]['observed_at']):
        raise ValueError('Workflow evidence must be recorded in observation order.')
    row={**payload.model_dump(mode='json'),'id':'OBS-'+uuid.uuid4().hex[:10],'actor':actor,'recorded_at':now()}
    incident['observations'].append(row)
    next_state={'inspection':'inspected','action':'action_recorded','followup':'verification_pending'}[payload.kind]
    if STATES.index(next_state)>STATES.index(incident['state']): incident['state']=next_state
    incident['verification']=None
    incident['transitions'].append({'state':incident['state'],'actor':actor,'at':now()})
    store.put('incident',incident['id'],incident)
    store.event(incident['asset_id'],'observation',row)
    return incident


def verify(incident,snap,actor):
    reason=None; result='insufficient_evidence'; delta=None
    if incident['state'] not in ('verification_pending','resolved'):
        raise ValueError('Record an action and follow-up observation before verification.')
    if snap['asset_id']!=incident['asset_id'] or snap['source']!=incident['source']:
        raise ValueError('Verification must use the same asset and provenance.')
    if snap['source']!='measured':
        reason='Replay illustrates the workflow; it cannot verify a physical maintenance action.'
    elif snap['connection']!='live': reason='Fresh live telemetry is required.'
    elif snap['quality']['calibration']!='reference recorded': reason='Calibrated physical channels are required.'
    else:
        actions=[o for o in incident['observations'] if o['kind']=='action']
        action=actions[-1] if actions else None
        before=[r for r in incident['baseline']['history'][-30:] if action and timestamp(r['timestamp'])<timestamp(action['observed_at'])]
        after=[r for r in snap['history'] if action and timestamp(r['timestamp'])>timestamp(action['observed_at'])]
        keys=('surface_c','ambient_c','current_a')
        before=[r for r in before if all(r.get(k) is not None for k in keys) and not r.get('quality_flags')]
        after=[r for r in after if all(r.get(k) is not None for k in keys) and not r.get('quality_flags')]
        if len(before)<20 or len(after)<20: reason='Need at least 20 complete samples before and after the intervention.'
        elif (timestamp(after[-1]['timestamp'])-timestamp(after[0]['timestamp'])).total_seconds()<60:
            reason='Post-action window must span at least 60 seconds.'
        else:
            avg=lambda rows,key:statistics.mean(r[key] for r in rows)
            if abs(avg(before,'current_a')-avg(after,'current_a'))>.05 or abs(avg(before,'ambient_c')-avg(after,'ambient_c'))>1:
                reason='Loading or ambient differs; a temperature drop cannot establish maintenance improvement.'
            elif snap['alerts']: reason='Active warnings remain; verified resolution is withheld.'
            else:
                delta=avg(before,'surface_c')-avg(after,'surface_c')
                result='improvement' if delta>=2 else 'no_clear_change'
                reason='Prototype comparison: ≥2 °C surface decrease, current within 0.05 A and ambient within 1 °C. Not proof of restored insulation or asset life.'
    incident['verification']={'result':result,'reason':reason,'surface_decrease_c':delta,'actor':actor,'at':now(),
                              'evidence_ids':[e['id'] for e in snap['evidence']]}
    store.put('incident',incident['id'],incident)
    store.event(incident['asset_id'],'verification',incident['verification'])
    return incident
