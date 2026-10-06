"""Open-source local interpretation. Numerical warnings never depend on an LLM."""
import hashlib
import json
import os
import time
import math
from typing import Literal
import httpx
from pydantic import Field
from .halo_contracts import Contract
from . import halo_store as store
from .storage import now

HYPOTHESES = {
    'expected_load_response':'Observed response is consistent with loading; cause is not independently established.',
    'possible_thermal_deviation':'Thermal evidence needs investigation; cooling degradation is only one possible cause.',
    'possible_sensor_discrepancy':'A measurement issue is plausible; compare against an independent reference.',
    'insufficient_evidence':'Available evidence cannot separate the supported explanations.'}
INSPECTIONS = {
    'independent_temperature':'Compare surface temperature with an independent instrument at the same location.',
    'check_load':'Have the technician compare secondary RMS current and selected resistor branches.',
    'check_connection':'Check the USB acquisition link and channel configuration with mains disconnected.',
    'visual_inspection':'With the assembly isolated, inspect the probe mounting and unobstructed ventilation.'}
STUDY_INSPECTIONS = {
    'independent_temperature':'Compare the oil-temperature channel with an independent reference. The winding hot-spot is inferred, not directly measured.',
    'check_load':'Review the loading trajectory, configured asset rating and voltage; compare a feasible reduction in Action Lab.',
    'check_connection':'Check the recording timestamps, missing channels and measurement quality before relying on the study.',
    'visual_inspection':'Review the documented cooling conditions and temperature references; this model study is not a physical inspection.'}


class Decision(Contract):
    hypothesis: Literal['expected_load_response','possible_thermal_deviation','possible_sensor_discrepancy','insufficient_evidence']
    inspection: Literal['independent_temperature','check_load','check_connection','visual_inspection']
    evidence_ids: list[str] = Field(min_length=1,max_length=12)


def evidence_bundle(snap,observations):
    return {'asset_id':snap['asset_id'],'source':snap['source'],'quality':snap['quality'],
            'evidence':snap['evidence'],'numerical_alerts':snap['alerts'],'metrics':snap['metrics'],
            'findings':[{'finding':o['finding'],'independent_surface_c':o.get('independent_surface_c'),
                         'observed_at':o['observed_at'],'id':o['id']} for o in observations[-8:]],
            'boundaries':snap.get('notes',[])}


def baseline(bundle):
    codes={a['code'] for a in bundle['numerical_alerts']}
    if bundle['quality']['freshness'] in ('stale','disconnected') or 'telemetry' in codes:
        h,step='insufficient_evidence','check_connection'
    elif any(o.get('finding')=='sensor_disagrees' for o in bundle['findings'][-2:]):
        h,step='possible_sensor_discrepancy','independent_temperature'
    elif 'temperature_change' in codes or 'measurement' in codes:
        h,step='possible_sensor_discrepancy','independent_temperature'
    elif codes & {'surface_limit','thermal_deviation','thermal_limit'}:
        h,step='possible_thermal_deviation','visual_inspection'
    elif 'overcurrent' in codes or 'load_mismatch' in codes or 'loading' in codes:
        h,step='expected_load_response','check_load'
    else: h,step='insufficient_evidence','independent_temperature'
    refs=[e['id'] for e in bundle['evidence'] if e.get('available')][:8]
    return {'hypothesis':h,'inspection':step,'evidence_ids':refs or [bundle['evidence'][0]['id']]}


def assess(snap,observations,force=False):
    bundle=evidence_bundle(snap,observations)
    study='transformer' in snap
    inspections=STUDY_INSPECTIONS if study else INSPECTIONS
    bundle['interpretation_profile']='distribution-study-v5' if study else 'bench-v5'
    key=hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest()[:20]
    previous=store.get('assessment_latest',snap['asset_id'])
    if previous and previous['id']=='AI-'+key and not force and time.time()-previous['assessed_epoch']<60 and (previous['provider']=='laya' or os.getenv('HALO_AI_ENABLED')!='1'):
        return {**previous,'cached':True}
    selected=baseline(bundle); provider='rules'; error=None
    model='convaiinnovations/laya'; distributions=None; policy_override=False; abstained=False; raw_choices=None; usage=None
    start=time.monotonic()
    if os.getenv('HALO_AI_ENABLED')=='1':
        try:
            # The endpoint is local by design; no telemetry is sent to a cloud model.
            # Keep the English checkpoint's bounded context explicit. Free-text user
            # notes and challenge labels never enter this classification request.
            profile='Distribution transformer model study' if study else 'Transformer bench'
            compact=(f"{profile} evidence is {bundle['source']}, freshness {bundle['quality']['freshness']}, calibration {bundle['quality']['calibration']}. "
                     + 'Readings: '+ '; '.join(e['channel']+'='+('missing' if e['value'] is None else str(round(e['value'],2))+' '+e['unit']) for e in bundle['evidence'])+'. '
                     + 'Numerical warnings: '+('; '.join(a['title'] for a in bundle['numerical_alerts']) or 'none')+'. '
                     + 'Independent findings: '+(', '.join(o['finding'] for o in bundle['findings'][-2:]) or 'none')+'. '
                     + 'Do not infer a cause from a temperature reading alone.')
            response=httpx.post('http://127.0.0.1:8766/v1/systemone',timeout=30,json={
                'model':'english','state':compact,
                'max_len':512,'head_max_len':192,
                'questions':{
                    'hypothesis':{'type':'choice','instructions':'Choose the best supported explanation. Uncertain or missing data means insufficient_evidence.', 'criteria':HYPOTHESES},
                    'inspection':{'type':'choice','instructions':'Select a relevant non-energizing inspection. Never authorize switching.', 'criteria':inspections}}})
            response.raise_for_status()
            body=response.json(); answers=body['answers']; usage=body.get('usage',{}); distributions={}
            if usage.get('truncated'): raise ValueError('Evidence was truncated by the model context.')
            for name,options in [('hypothesis',HYPOTHESES),('inspection',INSPECTIONS)]:
                answer=answers[name]
                if answer['choice'] not in options: raise ValueError('Unknown model choice')
                probs=answer['probabilities']
                if not isinstance(probs,dict) or set(probs)!=set(options): raise ValueError('Invalid probability keys')
                if any(not isinstance(p,(int,float)) or not math.isfinite(p) or not 0<=p<=1 for p in probs.values()) or abs(sum(probs.values())-1)>.02: raise ValueError('Invalid distribution')
                distributions[name]=probs
            candidate=Decision(hypothesis=answers['hypothesis']['choice'],inspection=answers['inspection']['choice'],evidence_ids=selected['evidence_ids']).model_dump()
            raw_choices={name:answers[name]['choice'] for name in ('hypothesis','inspection')}
            ranked=sorted(distributions['hypothesis'].values(),reverse=True)
            if ranked[0]<.55 or ranked[0]-ranked[1]<.12:
                candidate['hypothesis']='insufficient_evidence'; candidate['inspection']=selected['inspection'];abstained=True
            codes={a['code'] for a in snap['alerts']}
            findings={o['finding'] for o in bundle['findings']}
            supported={
                'expected_load_response':bool(codes & {'overcurrent','loading','load_mismatch'}) or not codes,
                'possible_thermal_deviation':bool(codes & {'surface_limit','thermal_deviation','thermal_limit'}),
                'possible_sensor_discrepancy':bool(codes & {'temperature_change','measurement'}) or 'sensor_disagrees' in findings,
                'insufficient_evidence':True}
            if not supported[candidate['hypothesis']]:
                candidate['hypothesis']='insufficient_evidence';candidate['inspection']=selected['inspection'];policy_override=True
            # Data-quality policy cannot be overridden by model output.
            if snap['connection'] in ('stale','disconnected') or 'telemetry' in codes or any(a['code'].startswith(('missing_','quality','calibration')) for a in snap['alerts']):
                candidate={'hypothesis':'insufficient_evidence','inspection':'check_connection','evidence_ids':selected['evidence_ids']};policy_override=True
            selected=candidate; provider='laya'
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            error='Local model unavailable or response rejected; deterministic interpretation remains active.'
    result={**selected,'id':'AI-'+key,'asset_id':snap['asset_id'],'provider':provider,
            'model':model if provider=='laya' else 'halo-rules-v2','prompt_version':'halo-laya-5',
            'explanation':HYPOTHESES[selected['hypothesis']],'next_step':inspections[selected['inspection']],
            'model_confidence':None,'distributions':distributions if provider=='laya' else None,'policy_override':policy_override,
            'abstained':abstained,'raw_model_choices':raw_choices,'usage':usage,
            'confidence_note':'Laya choice distributions are not transformer failure probabilities; no domain calibration claimed.',
            'assessed_at':now(),'assessed_epoch':time.time(),'latency_ms':round((time.monotonic()-start)*1000),
            'evidence_snapshot':bundle,'fallback_reason':error}
    store.put('assessment',result['id'],result); store.put('assessment_latest',snap['asset_id'],result)
    return result


def answer(question,snap,decision):
    q=question.lower(); current=snap.get('current') or {}; tool=None
    if any(x in q for x in ('switch','turn on','activate','energize','relay on')):
        text='I cannot energize equipment through conversation. Use the commissioned load controls; K4 remains locked.'
    elif any(x in q for x in ('future','forecast','reduce','compare')):
        text='Action Lab compares the same initial state under two stated operating assumptions. It sends no physical commands.'
        tool={'name':'open_view','value':'actions'}
    elif any(x in q for x in ('temperature','hot','surface')):
        t=current.get('surface_c')
        if 'transformer' in snap:
            oil=current.get('oil_c');hot=current.get('estimated_hotspot_c')
            text=(f'The distribution study reports oil {oil:.1f} °C and an inferred winding hot-spot {hot:.1f} °C. These are separate from the physical bench surface probe. ' if oil is not None and hot is not None else 'Distribution-study temperature evidence is incomplete. ')+decision['next_step']
            tool={'name':'highlight','value':'transformer'}
        else:
            text=(f'The surface reading is {t:.1f} °C. ' if t is not None else 'No valid surface reading is available. ')+decision['next_step']
            tool={'name':'highlight','value':'surface'}
    elif any(x in q for x in ('current','load','amp')):
        a=current.get('current_a')
        if 'transformer' in snap and current.get('load_pu') is not None:
            text=f'Distribution-study loading is {current["load_pu"]*100:.1f}% of the configured asset rating. This is not a bench current measurement.'
        else:text=(f'Secondary current is {a:.3f} A. ' if a is not None else 'No secondary current reading is available. ')+ 'Relay GPIO states do not confirm electrical contact closure.'
        tool={'name':'highlight','value':'transformer' if 'transformer' in snap else 'current'}
    elif any(x in q for x in ('maintenance','inspect','repair')):
        text=decision['next_step']+' Record the finding, then collect follow-up evidence before resolution.'
        tool={'name':'open_view','value':'maintenance'}
    else:
        text=decision['explanation']+' '+decision['next_step']
    return {'text':text,'tool':tool,'evidence_ids':decision['evidence_ids'],
            'source':snap['source'],'provider':'grounded local response','assessment_id':decision['id']}
