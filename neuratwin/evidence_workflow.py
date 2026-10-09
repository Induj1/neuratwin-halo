"""Case-scoped review of immutable imported observations; never physical repair proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import statistics
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field, field_validator, model_validator
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from . import halo_store as store, twin_studies as studies, twin_observer as observer
from .storage import now

router = APIRouter(prefix='/api/halo/twin/challenges')
VERSION = 'observation-workflow-1'
LIMITATION = ('Imported recordings are retrospective references. Acceptance closes an evidence review; '
              'it does not establish a prospective forecast, causal maintenance benefit or verified physical repair.')


class RecordingProvenance(Contract):
    asset_id: str = Field(pattern=r'^[\w-]{1,80}$')
    source_class: Literal['synthetic', 'recorded_oil_reference', 'unknown'] = 'unknown'
    recording_started_at: datetime | None = None
    units_verified: bool = False
    calibration_reference: str | None = Field(default=None, min_length=3, max_length=300)
    calibration_reviewed: bool = False
    configuration_reference: str | None = Field(default=None, min_length=3, max_length=300)
    configuration_reviewed: bool = False
    reviewer: str = Field(min_length=2, max_length=100)
    note: str = Field(min_length=5, max_length=2000)

    @field_validator('recording_started_at')
    @classmethod
    def aware(cls, value):
        if value is not None:
            if value.utcoffset() is None: raise ValueError('Recording start needs an explicit timezone.')
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode='after')
    def references(self):
        if self.calibration_reviewed and not self.calibration_reference:
            raise ValueError('Calibration review requires its reference.')
        if self.configuration_reviewed and not self.configuration_reference:
            raise ValueError('Configuration review requires its reference.')
        return self


class BindingRequest(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    provenance: RecordingProvenance


class Acceptance(Contract):
    stable_minutes: int = Field(10, ge=5, le=30)
    max_gap_seconds: int = Field(120, ge=30, le=180)
    max_load_percent: float = Field(99, ge=0, lt=100)
    max_oil_c: float = Field(90, ge=20, le=120)
    min_oil_drop_c: float = Field(0, ge=0, le=30)
    max_load_difference_pct: float = Field(5, ge=0, le=10)
    max_ambient_difference_c: float = Field(3, ge=0, le=5)
    max_voltage_difference_pu: float = Field(.02, ge=0, le=.05)


class WorkRequest(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    title: str = Field(min_length=5, max_length=180)
    owner: str = Field(min_length=2, max_length=100)
    priority: Literal['routine', 'soon', 'urgent'] = 'soon'
    acceptance_note: str = Field(min_length=15, max_length=1500)
    acceptance_rules: Acceptance = Field(default_factory=Acceptance)


class Mutation(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    revision: int = Field(ge=0)
    note: str = Field(min_length=10, max_length=2000)


class Observation(Mutation):
    kind: Literal['inspection', 'action']
    observed_at: datetime

    @field_validator('observed_at')
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None: raise ValueError('Observation time needs an explicit timezone.')
        return value.astimezone(timezone.utc)


class Followup(Mutation):
    case_id: str = Field(min_length=8, max_length=160)


def case(key):
    from .twin_challenge import get
    return get(key)


def binding(c):
    return store.get('observation_binding', c['id'])


def immutable_binding(c, provenance, actor):
    """Metadata is a separate immutable record; original samples are not rewritten."""
    meta = provenance.model_dump(mode='json')
    prior = binding(c)
    if prior:
        if prior['provenance'] != meta: raise HTTPException(409, 'Case provenance is immutable. Import a new case for a corrected interpretation.')
        return prior
    value = {'case_id': c['id'], 'provenance': meta, 'recording_sha256': studies.digest(c['rows']),
             'settings_sha256': studies.digest(c['settings']), 'temperature_mode': c.get('temperature_mode', 'oil_and_hotspot'),
             'source_file_sha256': c.get('source_file_sha256'), 'bound_at': now(), 'bound_by': actor,
             'review_scope': 'Uploader-declared references; their contents and physical calibration were not independently verified.'}
    value['sha256'] = studies.digest(value)
    store.put('observation_binding', c['id'], value)
    return value


def checked_binding(c):
    b = binding(c)
    if not b: return None
    if studies.digest({k: v for k, v in b.items() if k != 'sha256'}) != b['sha256']:
        raise HTTPException(409, 'Recording binding integrity mismatch.')
    if studies.digest(c['rows']) != b['recording_sha256'] or studies.digest(c['settings']) != b['settings_sha256']:
        raise HTTPException(409, 'Bound recording or settings changed.')
    return b


def frozen_context(c):
    b = checked_binding(c)
    a = c.get('assessment')
    if not a: raise HTTPException(409, 'Freeze this case assessment before creating or linking maintenance evidence.')
    if studies.digest(a['result']) != a['sha256'] or studies.digest(c['settings']) != a['settings_sha256']:
        raise HTTPException(409, 'Frozen assessment integrity mismatch.')
    return {'case_id': c['id'], 'recording_sha256': studies.digest(c['rows']),
            'settings_sha256': a['settings_sha256'], 'assessment_sha256': a['sha256'],
            'assessment_version': a['result'].get('version', 'unknown'),
            'model_source_sha256': deepcopy(a.get('model_source_sha256', {})),
            'binding_sha256': b['sha256'] if b else None,
            'source_file_sha256': c.get('source_file_sha256')}


def scoped_work(key, identifier):
    w = store.get('observation_work', identifier)
    if not w or w['case_id'] != key: raise HTTPException(404, 'Work order does not belong to this observation case.')
    if frozen_context(case(key)) != w['origin']: raise HTTPException(409, 'Origin evidence no longer matches the work order.')
    return w


def time_at(c, elapsed):
    b = checked_binding(c)
    start = b['provenance']['recording_started_at'] if b else None
    if not start: return None
    try: return datetime.fromisoformat(start) + timedelta(seconds=elapsed)
    except (ValueError, OverflowError): raise HTTPException(422, 'Recording time exceeds the supported calendar range.')


def window(c, rules):
    index = c.get('origin_index', 120)
    end = c['rows'][index]['elapsed_s']
    return [r for r in c['rows'][:index + 1] if end - rules['stable_minutes'] * 60 <= r['elapsed_s'] <= end]


def verification(w):
    """Compare recorded evidence under predeclared criteria; do not infer causality."""
    holds = []
    original = case(w['case_id'])
    ob = checked_binding(original)
    om = ob['provenance'] if ob else {}
    if not w['followups']:
        return {'eligible': False, 'holds': ['Link a later frozen follow-up recording.'],
                'physical_repair_verified': False, 'causal_benefit_established': False, 'note': LIMITATION}
    follow = w['followups'][-1]
    current = case(follow['case_id'])
    if frozen_context(current) != follow['evidence']:
        holds.append('Follow-up evidence no longer matches its immutable link.')
    cb = checked_binding(current)
    cm = cb['provenance'] if cb else {}
    for label, meta in (('Origin', om), ('Follow-up', cm)):
        if meta.get('source_class') not in ('synthetic', 'recorded_oil_reference'):
            holds.append(label + ' source class is unknown.')
        if not meta.get('units_verified'): holds.append(label + ' units are not reviewed as seconds, Celsius, percent and per-unit voltage.')
        if not meta.get('calibration_reviewed') or not meta.get('calibration_reference'):
            holds.append(label + ' calibration/source-scale reference is not reviewed.')
        if not meta.get('configuration_reviewed') or not meta.get('configuration_reference'):
            holds.append(label + ' configuration reference is not reviewed.')
        if not meta.get('recording_started_at'): holds.append(label + ' absolute recording time is unknown.')
    for field in ('asset_id', 'source_class', 'calibration_reference', 'configuration_reference'):
        if not om.get(field) or om.get(field) != cm.get(field): holds.append('Origin and follow-up ' + field.replace('_', ' ') + ' must match.')
    if original.get('temperature_mode') != current.get('temperature_mode'):
        holds.append('Origin and follow-up temperature capabilities differ.')
    rules = w['acceptance_rules']
    before, after = window(original, rules), window(current, rules)
    actions = [e for e in w['trail'] if e['kind'] == 'action']
    if not actions: holds.append('Record an inspection and action before reviewing a follow-up.')
    metrics = {}
    numeric = ('oil_c', 'ambient_c', 'load_percent', 'voltage_pu')
    usable = True
    for label, rows in (('Origin', before), ('Follow-up', after)):
        if len(rows) < 6 or rows[-1]['elapsed_s'] - rows[0]['elapsed_s'] < rules['stable_minutes'] * 60:
            holds.append(label + ' observation window is too short.'); usable = False
        if any(b['elapsed_s'] - a['elapsed_s'] > rules['max_gap_seconds'] for a, b in zip(rows, rows[1:])):
            holds.append(label + ' observation window contains a gap.'); usable = False
        if any(any(not isinstance(r.get(k), (int, float)) or not math.isfinite(r[k]) for k in numeric) for r in rows):
            holds.append(label + ' comparison channels contain missing or invalid values.'); usable = False
        elif any(not observer.in_domain(r, True) for r in rows):
            holds.append(label + ' comparison contains out-of-domain readings.'); usable = False
    if after and actions:
        start = time_at(current, after[0]['elapsed_s'])
        if start is None or start <= datetime.fromisoformat(actions[-1]['observed_at']):
            holds.append('The entire follow-up window must occur after the recorded action.')
    if usable:
        avg = lambda rows, field: statistics.mean(r[field] for r in rows)
        metrics = {'origin_mean_oil_c': avg(before, 'oil_c'), 'followup_mean_oil_c': avg(after, 'oil_c'),
                   'oil_drop_c': avg(before, 'oil_c') - avg(after, 'oil_c'),
                   'load_difference_pct': abs(avg(before, 'load_percent') - avg(after, 'load_percent')),
                   'ambient_difference_c': abs(avg(before, 'ambient_c') - avg(after, 'ambient_c')),
                   'voltage_difference_pu': abs(avg(before, 'voltage_pu') - avg(after, 'voltage_pu')),
                   'followup_peak_load_percent': max(r['load_percent'] for r in after),
                   'followup_peak_oil_c': max(r['oil_c'] for r in after), 'samples': len(after)}
        for field in ('load_difference_pct', 'ambient_difference_c', 'voltage_difference_pu'):
            if metrics[field] > rules['max_' + field]: holds.append('Load/ambient/voltage conditions are not comparable: ' + field + '.')
        if metrics['followup_peak_load_percent'] > rules['max_load_percent']: holds.append('Follow-up load exceeds the declared acceptance limit.')
        if metrics['followup_peak_oil_c'] > rules['max_oil_c']: holds.append('Follow-up oil exceeds the declared acceptance limit.')
        if metrics['oil_drop_c'] + 1e-9 < rules['min_oil_drop_c']: holds.append('The declared oil-temperature change is not established.')
        for label, rows in (('Origin', before), ('Follow-up', after)):
            for field, span in (('load_percent', 10), ('ambient_c', 3), ('voltage_pu', .04)):
                if max(r[field] for r in rows) - min(r[field] for r in rows) > span:
                    holds.append(label + ' operating inputs vary too much for a stable comparable window: ' + field + '.')
        oil_only = current.get('temperature_mode') == 'oil_only'
        if any(observer.observed_condition(r, current['settings'], oil_only)['observed_status'] != 'NORMAL' for r in after):
            holds.append('Follow-up contains an observed warning, missing channel or breach within the review window.')
    result = current['assessment']['result']
    if result.get('observed_status') != 'NORMAL': holds.append('Follow-up observed condition is not normal on its available channels.')
    if result.get('hypotheses'): holds.append('Follow-up diagnostic or evidence holds remain: ' + ', '.join(result['hypotheses']) + '.')
    if not result.get('available'): holds.append('Follow-up model validity remains withheld.')
    return {'eligible': not holds, 'holds': list(dict.fromkeys(holds)), 'metrics': metrics,
            'classification': 'reference_acceptance_met' if not holds else 'review_required',
            'physical_repair_verified': False, 'causal_benefit_established': False,
            'criteria_basis': 'Operator-declared review criteria; not manufacturer limits or a safety certification.', 'note': LIMITATION}


def public_work(w):
    if frozen_context(case(w['case_id'])) != w['origin']:
        raise HTTPException(409, 'Origin evidence no longer matches the work order.')
    return {k: deepcopy(v) for k, v in w.items() if k != 'requests'} | {'verification': verification(w)}


def command(w, payload, route):
    fp = studies.digest({'route': route, 'payload': payload.model_dump(mode='json')})
    prior = w['requests'].get(payload.request_id)
    if prior:
        if prior['digest'] != fp: raise HTTPException(409, 'Request ID already used for different content.')
        return fp, True
    if payload.revision != w['revision']: raise HTTPException(409, 'Work order changed; refresh before recording this evidence.')
    if w['status'] == 'closed_reference_review': raise HTTPException(409, 'Closed evidence reviews are immutable. Create a new review for new evidence.')
    return fp, False


def save(w, payload, route, fp, actor):
    w['revision'] += 1
    w['requests'][payload.request_id] = {'digest': fp, 'revision': w['revision']}
    store.put('observation_work', w['id'], w)
    store.event(w['asset_id'], 'observation_work_' + route, {'case_id': w['case_id'], 'work_id': w['id'],
                'revision': w['revision'], 'actor': actor})
    return public_work(w)


@router.get('')
def list_cases():
    result = []
    for c in store.records('twin_challenge'):
        b = binding(c)
        result.append({'id': c['id'], 'name': c.get('name', 'Synthetic challenge'), 'asset_id': b['provenance']['asset_id'] if b else None,
                       'source': c.get('source', 'independent synthetic challenge'),
                       'source_class': b['provenance']['source_class'] if b else 'unknown',
                       'assessed': bool(c.get('assessment')), 'revealed': c.get('revealed', False)})
    return {'cases': result[:200]}


@router.post('/{key}/binding')
def bind(key: str, payload: BindingRequest, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        c = case(key)
        if c.get('source') != 'imported reference': raise HTTPException(422, 'Bind imported reference recordings only.')
        b = immutable_binding(c, payload.provenance, actor)
        return {'binding': b, 'note': LIMITATION}


@router.get('/{key}/workflow')
def workflow(key: str):
    c = case(key); b = checked_binding(c)
    return {'case_id': key, 'asset_id': b['provenance']['asset_id'] if b else None,
            'source_class': b['provenance']['source_class'] if b else 'unknown', 'binding': b,
            'work_orders': [public_work(w) for w in store.records('observation_work') if w['case_id'] == key],
            'limitations': [LIMITATION], 'version': VERSION}


@router.post('/{key}/work')
def create_work(key: str, payload: WorkRequest, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        c = case(key); b = checked_binding(c)
        if not b: raise HTTPException(422, 'Bind the originating asset and source before creating its maintenance review.')
        identifier = key + '-work-' + payload.request_id
        fingerprint = studies.digest(payload.model_dump(mode='json'))
        prior = store.get('observation_work', identifier)
        if prior:
            if prior['request_digest'] != fingerprint: raise HTTPException(409, 'Work request ID already has different content.')
            return public_work(prior)
        w = {**payload.model_dump(exclude={'request_id'}), 'id': identifier, 'case_id': key,
             'asset_id': b['provenance']['asset_id'], 'source_class': b['provenance']['source_class'],
             'origin': frozen_context(c), 'version': VERSION, 'created_by': actor, 'created_at': now(),
             'status': 'open', 'revision': 0, 'trail': [], 'followups': [], 'requests': {}, 'request_digest': fingerprint,
             'physical_repair_verified': False}
        store.put('observation_work', identifier, w)
        store.event(w['asset_id'], 'observation_work_created', {'case_id': key, 'work_id': identifier, 'actor': actor})
        return public_work(w)


@router.post('/{key}/work/{identifier}/observations')
def observe(key: str, identifier: str, payload: Observation, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        w = scoped_work(key, identifier); fp, repeat = command(w, payload, 'observation')
        if repeat: return public_work(w)
        if payload.kind == 'action' and not any(e['kind'] == 'inspection' for e in w['trail']):
            raise HTTPException(422, 'Record the inspection before the action.')
        c = case(key); origin = time_at(c, c['rows'][c.get('origin_index', 120)]['elapsed_s'])
        latest = datetime.fromisoformat(w['trail'][-1]['observed_at']) if w['trail'] else origin
        if latest and payload.observed_at < latest: raise HTTPException(422, 'Inspection/action time cannot precede the originating observation or previous action.')
        w['trail'].append({**payload.model_dump(mode='json', exclude={'revision'}), 'actor': actor, 'recorded_at': now()})
        w['status'] = 'inspected' if payload.kind == 'inspection' else 'action_recorded'
        return save(w, payload, 'observation', fp, actor)


@router.post('/{key}/work/{identifier}/followup')
def attach_followup(key: str, identifier: str, payload: Followup, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        w = scoped_work(key, identifier); fp, repeat = command(w, payload, 'followup')
        if repeat: return public_work(w)
        if not any(e['kind'] == 'action' for e in w['trail']): raise HTTPException(422, 'Record the action before linking follow-up evidence.')
        if payload.case_id == key: raise HTTPException(422, 'Follow-up must be a separate later recording.')
        c = case(payload.case_id); b = checked_binding(c)
        if not b or b['provenance']['asset_id'] != w['asset_id'] or b['provenance']['source_class'] != w['source_class']:
            raise HTTPException(422, 'Follow-up must belong to the same asset and declared source class.')
        if any(f['case_id'] == payload.case_id for f in w['followups']): raise HTTPException(409, 'This follow-up is already linked.')
        w['followups'].append({'case_id': payload.case_id, 'evidence': frozen_context(c), 'note': payload.note,
                              'linked_at': now(), 'actor': actor})
        w['status'] = 'verification_pending'
        return save(w, payload, 'followup', fp, actor)


@router.post('/{key}/work/{identifier}/close')
def close(key: str, identifier: str, payload: Mutation, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        w = scoped_work(key, identifier); fp, repeat = command(w, payload, 'close')
        if repeat: return public_work(w)
        verdict = verification(w)
        if not verdict['eligible']: raise HTTPException(423, {'message': 'Reference acceptance is not established.', 'verification': verdict})
        w['status'] = 'closed_reference_review'
        w['closure'] = {'verification': verdict, 'note': payload.note, 'actor': actor, 'recorded_at': now(),
                        'physical_repair_verified': False, 'evidence': deepcopy(w['followups'][-1]['evidence'])}
        return save(w, payload, 'close', fp, actor)


@router.get('/{key}/workflow/export')
def export(key: str):
    c = case(key)
    if not c.get('revealed'): raise HTTPException(409, 'Reveal the frozen case before exporting its full recording.')
    data = workflow(key)
    linked = {f['case_id'] for w in data['work_orders'] for f in w['followups']}
    if any(not case(k).get('revealed') for k in linked): raise HTTPException(409, 'Reveal every linked follow-up before exporting its full recording.')
    bundle = {'version': VERSION, 'origin_recording': c, 'workflow': data,
              'followup_recordings': [{'case': case(k), 'binding': checked_binding(case(k))} for k in sorted(linked)],
              'physical_repair_verified': False, 'note': LIMITATION}
    body = {**bundle, 'sha256': studies.digest(bundle)}
    # Download these bytes directly. A JS JSON round-trip normalizes 10.0 to 10
    # and breaks the existing canonical digest contract, including nested hashes.
    artifact = json.dumps(body, indent=2, allow_nan=False).encode('utf-8')
    return Response(artifact, media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="observation-maintenance-evidence.json"',
                             'Cache-Control': 'no-store'})
