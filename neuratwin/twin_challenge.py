"""Committed blind synthetic case: assess first, then reveal later observations."""
from copy import deepcopy
import csv
import io
import math
import hashlib
import secrets
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field
from .halo_contracts import Contract
from .halo_api import operator,WRITE_LOCK
from . import halo_store as store,twin_core as core,twin_studies as studies,twin_observer as observer
from .validation_plant import generate,SCENARIOS,MIXED,FAMILIES
from . import thermal_reference,thermal_adaptation
from .evidence_workflow import RecordingProvenance, immutable_binding, checked_binding
from .storage import now

router=APIRouter(prefix='/api/halo/twin/challenges')


class Create(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    temperature_mode:Literal['oil_only','oil_and_hotspot']='oil_and_hotspot'


class Import(Contract):
    request_id:str=Field(pattern=r'^[\w-]{8,80}$')
    temperature_mode:Literal['oil_only','oil_and_hotspot']='oil_only'
    csv_text:str=Field(min_length=50,max_length=1000000)
    name:str=Field(min_length=3,max_length=120)
    origin_index:int=Field(ge=70,le=4998)
    healthy_reference_reviewed:bool=False
    winding_reference_reviewed:bool=False
    provenance:RecordingProvenance|None=None


def context(c):
    index=c.get('origin_index',120)
    return index,c['rows'][index]['elapsed_s']/60,c.get('temperature_mode','oil_and_hotspot')


def get(key):
    c=store.get('twin_challenge',key)
    if not c:raise HTTPException(404,'Blind case not found.')
    return c


def public(c):
    index,minute,mode=context(c)
    observations=deepcopy([r for r in c['rows'][:index+1] if r['elapsed_s']>=(minute-30)*60])
    if mode=='oil_only':
        for row in observations:row['hotspot_c']=None
    return {'id':c['id'],'source':c.get('source','independent synthetic challenge'),'name':c.get('name','Unseen synthetic case'),
            'binding':checked_binding(c),
            'temperature_mode':mode,'commitment':c['commitment'],
            'origin_min':minute,'horizon_min':30,'observations':observations,
            'assessment':c.get('assessment'),'revealed':c.get('revealed',False),
            'qualification':{'oil_fit_used':c['fit']['identified'] and c['fit']['beats_persistence'],
                             'winding_fit_used':bool(c.get('winding_fit',{}).get('qualified')),
                             'winding_reference':deepcopy(c.get('winding_fit',{'qualified':False,'holds':['legacy_case_not_refitted']})),
                             'reference_basis':c.get('reference_basis','First 70 assumed-healthy synthetic observations')},
            'note':'Future rows stay hidden from the assessor until its result is frozen. An imported recording is known to its uploader and is a retrospective holdout, not a blind prospective trial.' if c.get('source')=='imported reference' else 'Fault label, seed and later observations remain withheld until assessment. Synthetic experiment; no field-accuracy claim.'}


def winding_reference(first,settings,mode,reviewed):
    if mode=='oil_only':return {'qualified':False,'holds':['oil_only_has_no_reported_hotspot_reference']}
    if not reviewed:return {'qualified':False,'holds':['reported_hotspot_reference_not_reviewed']}
    try:return thermal_adaptation.fit_winding(observer.winding_reference_rows(first),settings,reviewed_healthy=True)
    except ValueError as error:return {'qualified':False,'holds':['winding_reference_ineligible'],'reason':str(error)}


@router.post('')
def create(payload:Create,actor=Depends(operator)):
    with WRITE_LOCK:
        key='BLIND-'+payload.request_id;prior=store.get('twin_challenge',key)
        if prior:
            if prior.get('temperature_mode','oil_and_hotspot')!=payload.temperature_mode:raise HTTPException(409,'Request ID already used with a different channel capability.')
            return public(prior)
        seed=secrets.randbelow(2**31);kind=secrets.choice((*SCENARIOS,*MIXED))
        rows,truth,meta=generate(seed,kind,family=secrets.choice(FAMILIES),variable_event=True);nonce=secrets.token_hex(16)
        fit=thermal_reference.fit(observer.reference_rows(rows[:70]));settings=core.Settings().model_dump()
        if fit['identified'] and fit['beats_persistence']:
            settings.update(rated_oil_rise_c=fit['rated_oil_rise_c'],oil_tau_min=fit['oil_tau_min'])
        winding_fit=winding_reference(rows[:70],settings,payload.temperature_mode,True)
        settings=thermal_adaptation.apply_winding(settings,winding_fit)
        hidden={'rows':rows,'truth':truth,'meta':meta,'nonce':nonce}
        c={'id':key,**hidden,'settings':settings,'fit':fit,'winding_fit':winding_fit,
           'reference_basis':'First 70 assumed-healthy synthetic observations; reported hot-spot/oil winding fit only in two-channel mode.',
           'temperature_mode':payload.temperature_mode,'commitment':studies.digest(hidden),'created_by':actor}
        store.put('twin_challenge',key,c);return public(c)


@router.post('/import')
def import_recording(payload:Import,actor=Depends(operator)):
    """Strict observation contract; hidden state and future rows never enter assess()."""
    with WRITE_LOCK,store.transaction():
        key='RECORDING-'+payload.request_id;prior=store.get('twin_challenge',key)
        fingerprint=studies.digest(payload.model_dump(mode='json'))
        if prior:
            compatible={fingerprint}
            if not payload.winding_reference_reviewed:
                compatible.add(studies.digest(payload.model_dump(mode='json',exclude={'winding_reference_reviewed'})))
            if payload.provenance is None:
                compatible.add(studies.digest(payload.model_dump(mode='json',exclude={'provenance'})))
                if not payload.winding_reference_reviewed:
                    compatible.add(studies.digest(payload.model_dump(mode='json',exclude={'provenance','winding_reference_reviewed'})))
            if prior.get('request_digest') not in compatible:raise HTTPException(409,'Request ID already used for a different recording.')
            return public(prior)
        if not payload.healthy_reference_reviewed:raise HTTPException(422,'Review the first 70 observations as a healthy oil reference before importing; surface-probe data are not oil.')
        reader=csv.DictReader(io.StringIO(payload.csv_text));required=set(observer.FIELDS)-({'hotspot_c'} if payload.temperature_mode=='oil_only' else set())
        if not required.issubset(reader.fieldnames or []):raise HTTPException(422,'CSV needs '+', '.join(sorted(required))+'. Temperature must represent oil, not a surface probe.')
        rows=[]
        try:
            for raw in reader:
                if len(rows)>=5000:raise ValueError('CSV limit is 5,000 observations.')
                fields=(*observer.FIELDS,*(k for k in getattr(observer,'OPTIONAL_FIELDS',()) if k in (reader.fieldnames or [])))
                row={k:float(raw[k]) if (raw.get(k) or '').strip() else None for k in fields}
                if row['elapsed_s'] is None or not math.isfinite(row['elapsed_s']) or not 0<=row['elapsed_s']<=315576000:
                    raise ValueError('Every elapsed_s must be finite, nonnegative and within the supported ten-year elapsed range.')
                if any(v is not None and not math.isfinite(v) for v in row.values()):raise ValueError('NaN and infinity are not observations.')
                if rows and row['elapsed_s']<=rows[-1]['elapsed_s']:raise ValueError('elapsed_s must be strictly increasing.')
                rows.append(row)
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e))
        if payload.origin_index>=len(rows)-1:raise HTTPException(422,'Origin index needs at least one later observation for holdout scoring.')
        first=rows[:70]
        if any(not all(observer.finite(r[k]) for k in ('oil_c','ambient_c','load_percent','voltage_pu')) or not observer.in_domain(r,True) for r in first):
            raise HTTPException(422,'The healthy commissioning prefix needs finite in-domain oil, ambient, loading and voltage.')
        try:fit=thermal_reference.fit(observer.reference_rows(first))
        except ValueError as e:raise HTTPException(422,'Commissioning reference: '+str(e))
        settings=core.Settings().model_dump()
        if fit['identified'] and fit['beats_persistence']:settings.update(rated_oil_rise_c=fit['rated_oil_rise_c'],oil_tau_min=fit['oil_tau_min'])
        winding_fit=winding_reference(first,settings,payload.temperature_mode,payload.winding_reference_reviewed)
        settings=thermal_adaptation.apply_winding(settings,winding_fit)
        hidden={'rows':rows,'truth':[],'meta':{'scenario':'unlabelled_recording','name':payload.name},'nonce':secrets.token_hex(16)}
        c={'id':key,**hidden,'source':'imported reference','name':payload.name,'origin_index':payload.origin_index,
           'temperature_mode':payload.temperature_mode,'settings':settings,'fit':fit,'winding_fit':winding_fit,'created_by':actor,
           'created_at':now(),'source_file_sha256':hashlib.sha256(payload.csv_text.encode('utf-8')).hexdigest(),
           'reference_basis':'First 70 observations; uploader asserts healthy oil reference'+(' and separately reviews the reported hot-spot winding reference' if payload.winding_reference_reviewed and payload.temperature_mode!='oil_only' else '')+'; not independently certified.',
           'commitment':studies.digest(hidden),'request_digest':fingerprint}
        store.put('twin_challenge',key,c)
        if payload.provenance:immutable_binding(c,payload.provenance,actor)
        return public(c)


@router.get('/{key}')
def read(key:str):
    c=get(key)
    return reveal_result(c) if c.get('revealed') else public(c)


@router.post('/{key}/assess')
def assess(key:str,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        c=get(key)
        if not c.get('assessment'):
            index,minute,mode=context(c)
            value=observer.assess(c['rows'][:index+1],c['settings'],30,temperature_mode=mode)
            c['assessment']={'result':value,'sha256':studies.digest(value),'actor':actor,'origin_min':minute,
                             'temperature_mode':mode,'settings_sha256':studies.digest(c['settings']),
                             'recorded_at':now(),'input_sha256':studies.digest(c['rows'][:index+1]),
                             'model_source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                 for name in ('twin_observer.py','twin_core.py','twin_studies.py','thermal_reference.py','thermal_adaptation.py')},
                             'binding_sha256':checked_binding(c)['sha256'] if checked_binding(c) else None}
            store.put('twin_challenge',key,c)
        return public(c)


@router.post('/{key}/reveal')
def reveal(key:str,actor=Depends(operator)):
    with WRITE_LOCK:
        c=get(key)
        if not c.get('assessment'):raise HTTPException(409,'Freeze the observation-only assessment before revealing the case.')
        c['revealed']=True;store.put('twin_challenge',key,c)
        return reveal_result(c)


def reveal_result(c):
        index,origin,mode=context(c)
        result=c['assessment']['result'];future=[r for r in c['rows'][index+1:] if r['elapsed_s']/60<=origin+30];scored=[]
        target='oil_c' if mode=='oil_only' else 'hotspot_c';point_key='oil_c' if mode=='oil_only' else 'temperature_c'
        if result['available']:
            initial=c['rows'][index][target]
            for row in future:
                minute=row['elapsed_s']/60-origin
                if row[target] is not None:
                    left=int(math.floor(minute));right=min(30,left+1);points=result['forecast']['points']
                    prediction=points[left][point_key]+(minute-left)*(points[right][point_key]-points[left][point_key])
                    scored.append({'minute':minute,'actual_c':row[target],'predicted_c':prediction,
                        'error_c':abs(row[target]-prediction),'persistence_error_c':abs(row[target]-initial)})
        hidden={k:c[k] for k in ('rows','truth','meta','nonce')}
        return {**public(c),'reveal':hidden,'commitment_verified':studies.digest(hidden)==c['commitment'],
            'scores':{'target':target,'count':len(scored),'possible':len(future),'model_mae_c':sum(r['error_c'] for r in scored)/len(scored) if scored else None,
                      'persistence_mae_c':sum(r['persistence_error_c'] for r in scored)/len(scored) if scored else None,
                      'note':'All available future target observations are retained, including future input changes. No score is evidence of safety or diagnostic certainty.'},'observed_future':scored}
