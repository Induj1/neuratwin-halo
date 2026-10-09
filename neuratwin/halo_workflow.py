"""Maintenance is a traceable sequence, not an acknowledgement-to-resolved toggle."""
import statistics
import math
import uuid
from datetime import datetime, timezone
from . import halo_store as store
from .halo_engine import timestamp, recorded_config, holds
from .halo_contracts import Calibration
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
    reason=None; result='insufficient_evidence'; delta=None; comparability=None
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
            comparability=compare_acquisition_provenance(before,after)
            avg=lambda rows,key:statistics.mean(r[key] for r in rows)
            if not comparability['comparable']:reason=comparability['reason']
            elif abs(avg(before,'current_a')-avg(after,'current_a'))>.05 or abs(avg(before,'ambient_c')-avg(after,'ambient_c'))>1:
                reason='Loading or ambient differs; a temperature drop cannot establish maintenance improvement.'
            elif snap['alerts']: reason='Active warnings remain; verified resolution is withheld.'
            else:
                delta=avg(before,'surface_c')-avg(after,'surface_c')
                result='improvement' if delta>=2 else 'no_clear_change'
                reason='Same reviewed calibration/configuration and consistent raw evidence: ≥2 °C surface decrease, current within 0.05 A and ambient within 1 °C. A comparable bench response, not proof of restored insulation or asset life.'
    incident['verification']={'result':result,'reason':reason,'surface_decrease_c':delta,'actor':actor,'at':now(),
                              'evidence_ids':[e['id'] for e in snap['evidence']],'comparability':comparability}
    store.put('incident',incident['id'],incident)
    store.event(incident['asset_id'],'verification',incident['verification'])
    return incident


def compare_acquisition_provenance(before,after):
    """Changing a conversion/limit is never credited as a physical repair."""
    rows=before+after
    evidence={'comparable':False,'calibration_id':None,'config_id':None,
              'before_evidence_ids':[r.get('evidence_id') for r in before],
              'after_evidence_ids':[r.get('evidence_id') for r in after],
              'before_samples':len(before),'after_samples':len(after)}
    def failed(reason):return {**evidence,'reason':reason}
    ids={r.get('calibration_id') for r in rows}
    if len(ids)!=1 or None in ids or '' in ids:
        return failed('Calibration identity changed or is absent across the comparison windows. Recalibration cannot verify a physical repair; acquire comparable before/after evidence under one reviewed calibration.')
    key=next(iter(ids));evidence['calibration_id']=key
    record=store.get('calibration',key)
    try:
        cal=Calibration.model_validate({k:v for k,v in (record or {}).items() if k in Calibration.model_fields})
    except ValueError:return failed('Referenced calibration review is unavailable or invalid.')
    if not all((cal.secondary_v_per_mv,cal.current_a_per_mv,cal.surface_reference,cal.ambient_reference)):
        return failed('Reviewed reference checks for voltage, current, surface and ambient are required.')
    configs={r.get('config_id') for r in rows}
    if len(configs)!=1 or None in configs or '' in configs:
        return failed('Configuration identity changed or is absent. Legacy/unbound or differently configured windows cannot verify a physical intervention.')
    evidence['config_id']=next(iter(configs))
    bound=[recorded_config(r)[0] for r in rows]
    if any(c is None for c in bound):
        return failed('Referenced immutable configuration is missing, modified or bound to another device.')
    if holds(bound[0]):return failed('The bound configuration has incomplete commissioning review; physical repair credit is withheld.')
    if any(r.get('hardware_config_status')!='reported_match' for r in rows):return failed('Firmware configuration is mismatched or unverified in the comparison window.')
    if any(not r.get('evidence_id') for r in rows):return failed('Acquisition evidence identities are missing from the comparison window.')
    for r in rows:
        raw=r.get('raw') or {}
        fields=('surface_raw_c','current_rms_mv','secondary_rms_mv')
        if any(not isinstance(raw.get(k),(int,float)) or isinstance(raw.get(k),bool) or not math.isfinite(raw[k]) for k in fields):
            return failed('Raw surface, secondary-voltage and current evidence is missing or invalid; physical repair credit is withheld.')
        reconstructed={'surface_c':raw['surface_raw_c']+cal.surface_offset_c,
                       'secondary_v':raw['secondary_rms_mv']*cal.secondary_v_per_mv,
                       'current_a':math.sqrt(max(0,raw['current_rms_mv']**2-cal.current_noise_mv**2))*cal.current_a_per_mv}
        if any(r.get(k) is None or not math.isclose(r[k],value,rel_tol=1e-6,abs_tol=1e-6) for k,value in reconstructed.items()):
            return failed('Converted measurements do not match the retained raw evidence and reviewed calibration.')
    evidence.update(comparable=True,reason='One immutable configuration and reviewed calibration; every retained raw conversion is consistent.',
        raw_surface_decrease_c=statistics.mean(r['raw']['surface_raw_c'] for r in before)-statistics.mean(r['raw']['surface_raw_c'] for r in after))
    return evidence
