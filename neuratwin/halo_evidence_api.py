"""Authenticated evidence records, advisory analytics and portable reports."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from typing import Literal
import uuid
import zipfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field, model_validator, field_validator
from .halo_api import Context, obtain, operator
from .halo_contracts import Contract
from . import halo_evidence as analysis, halo_store as store
from .storage import now
from .halo_report import report_html

router=APIRouter(prefix='/api/halo/evidence')


def snapshot(context):
    return obtain(**context.model_dump(include=set(Context.model_fields)))


def keep(kind,content,actor):
    row={**content,'id':kind.upper()+'-'+uuid.uuid4().hex[:12],'created_at':now(),'actor':actor}
    row['sha256']=analysis.digest(row)
    store.put(kind,row['id'],row)
    return row


@router.post('/overview')
def overview(context:Context):
    snap=snapshot(context)
    return {'asset_id':snap['asset_id'],'source':snap['source'],'timestamp':(snap.get('current') or {}).get('timestamp'),
            'investigation':analysis.investigation(snap),'ledger':analysis.ledger(snap,store.get('ageing_profile',snap['asset_id'])),
            'channels':snap['evidence'],'holds':snap['holds']}


class Plan(Context):
    horizon:int=Field(default=5,ge=1,le=120)
    max_delay:int=Field(default=5,ge=0,le=30)
    protected_branches:list[int]=Field(default_factory=list,max_length=3)

    @field_validator('protected_branches')
    @classmethod
    def branches(cls,values):
        if any(v not in (1,2,3) for v in values) or len(set(values))!=len(values):raise ValueError('Protect unique branches K1–K3 only.')
        return values


@router.post('/plan')
def plan(payload:Plan,actor=Depends(operator)):
    result=analysis.plan(snapshot(payload),payload.horizon,payload.max_delay,payload.protected_branches)
    if result['available']:
        return keep('plan',{**result,'context':payload.model_dump()},actor)
    return result


class Freeze(Context):
    horizon:int=Field(default=5,ge=1,le=120)


@router.post('/forecasts')
def freeze(payload:Freeze,actor=Depends(operator)):
    snap=snapshot(payload)
    try:prediction=analysis.predict(snap,payload.horizon)
    except ValueError as e:raise HTTPException(422,str(e))
    return keep('forecast',{**prediction,'horizon_min':payload.horizon,'asset_id':snap['asset_id'],'source':snap['source'],
                           'context':payload.model_dump(include=set(Context.model_fields)),
                           'evidence_ids':[e['id'] for e in snap['evidence']],
                           'assumptions':'Current/load, ambient and voltage held constant; prediction is frozen before later observations are scored.'},actor)


@router.post('/forecasts/{proof_id}/score')
def score(proof_id:str,context:Context,actor=Depends(operator)):
    proof=store.get('forecast',proof_id)
    if not proof:raise HTTPException(404,'Forecast not found.')
    if any(proof['context'][k]!=getattr(context,k) for k in ('mode','scenario','dataset_id')):
        raise HTTPException(409,'Return to the exact source/scenario used to freeze this forecast.')
    original={k:v for k,v in proof.items() if k!='sha256'}
    if analysis.digest(original)!=proof['sha256']:raise HTTPException(409,'Stored forecast checksum does not match.')
    result=analysis.score_prediction(proof,analysis.rows_for(context))
    return keep('forecast_score',{'asset_id':proof['asset_id'],'source':proof['source'],'forecast_id':proof_id,
                                 'forecast_sha256':proof['sha256'],**result},actor)


@router.post('/benchmark')
def benchmark(context:Context,actor=Depends(operator)):
    try:result=analysis.benchmark(context,analysis.rows_for(context),snapshot)
    except ValueError as e:raise HTTPException(422,str(e))
    snap=snapshot(context)
    return keep('benchmark',{**result,'asset_id':snap['asset_id'],'source':snap['source'],'context':context.model_dump()},actor)


class Check(Contract):
    name:str=Field(min_length=2,max_length=120)
    kind:Literal['measurement','threshold','communication']
    unit:Literal['V','A','°C','s']
    reference:float|None=Field(default=None,ge=-100,le=100000)
    observed:float|None=Field(default=None,ge=-100,le=100000)
    tolerance_pct:float=Field(default=1,ge=0,le=100)
    tolerance_abs:float|None=Field(default=None,ge=0,le=10000)
    event_at:datetime|None=None
    response_at:datetime|None=None
    response_kind:Literal['not_observed','software_detection','command_acknowledgment','independent_contact_observation','communication_recovery']='not_observed'
    evidence:str=Field(default='',max_length=1000)

    @model_validator(mode='after')
    def verify(self):
        if self.kind!='communication' and (self.reference is None or self.observed is None):raise ValueError('Reference and observation are required.')
        if self.kind=='communication' and self.unit!='s':raise ValueError('Communication duration uses seconds.')
        for value in (self.event_at,self.response_at):
            if value and (value.utcoffset() is None or value>datetime.now(timezone.utc)):raise ValueError('Use timezone-aware observed times, not future times.')
        if self.response_at and (not self.event_at or self.response_at<self.event_at):raise ValueError('Response must follow the event.')
        if self.response_kind!='not_observed' and (not self.event_at or not self.response_at or len(self.evidence)<5):raise ValueError('A response claim requires both timestamps and evidence.')
        return self


class Acceptance(Contract):
    asset_id:str=Field(pattern=r'^[\w-]{1,80}$')
    source:Literal['manual_bench_observations','imported_recording','demonstration_fixture']
    reviewer:str=Field(min_length=2,max_length=100)
    reference_instrument:str=Field(min_length=5,max_length=300)
    calibration_reference:str=Field(min_length=5,max_length=300)
    firmware_version:str=Field(min_length=2,max_length=100)
    note:str=Field(min_length=5,max_length=1000)
    confirmed:bool=False
    checks:list[Check]=Field(min_length=1,max_length=50)


def evaluate_check(check):
    result=check.model_dump(mode='json');result.update(status='not demonstrated',elapsed_s=None)
    if check.reference is not None and check.observed is not None:
        absolute=abs(check.observed-check.reference)
        percent=absolute/abs(check.reference)*100 if check.reference else None
        result.update(absolute_error=absolute,absolute_error_pct=percent)
        if check.kind=='measurement':
            passes=(percent<=check.tolerance_pct) if percent is not None else (absolute<=check.tolerance_abs if check.tolerance_abs is not None else None)
            result['status']='pass' if passes is True else 'fail' if passes is False else 'not demonstrated'
        else:
            result['status']='threshold observation only'
    if check.event_at and check.response_at:
        result['elapsed_s']=(check.response_at-check.event_at).total_seconds()
        result['response_claim']=check.response_kind
    result['physical_contact_opening_verified']=check.response_kind=='independent_contact_observation' and result['elapsed_s'] is not None
    return result


@router.get('/acceptance/reference')
def reference_checks():
    rows=json.loads((Path(__file__).resolve().parents[1]/'data/cpri_reference_checks.json').read_text(encoding='utf-8'))
    return {**rows,'checks':[evaluate_check(Check.model_validate(r)) for r in rows['checks']],
            'source':'CPRI supplied reference example; not measurements from this demonstrator',
            'notice':'A passing imported example is not bench acceptance or CPRI certification. No trip duration is provided in the supplied example.'}


@router.post('/acceptance')
def acceptance(payload:Acceptance,actor=Depends(operator)):
    if not payload.confirmed:raise HTTPException(422,'Confirm that the entries match the referenced observations.')
    return keep('acceptance',{**payload.model_dump(mode='json'),'checks':[evaluate_check(c) for c in payload.checks],
                              'scope':'Operator-entered evidence, not independently certified. Detection, acknowledgement and physical contact observation remain distinct.'},actor)


class Ageing(Context):
    reference_c:float=Field(default=110,ge=50,le=150)
    activation_k:float=Field(default=15000,ge=1000,le=30000)
    remaining_equivalent_hours:float|None=Field(default=None,gt=0,le=1000000)
    future_ageing_factor:float=Field(default=1,gt=0,le=1000)
    reviewer:str=Field(min_length=2,max_length=100)
    note:str=Field(min_length=10,max_length=1000)
    hypothetical_confirmed:bool=False


@router.post('/ageing')
def ageing(payload:Ageing,actor=Depends(operator)):
    if payload.mode!='transformer':raise HTTPException(422,'The surface bench has no oil-paper ageing model.')
    if not payload.hypothetical_confirmed:raise HTTPException(422,'Confirm the scenario assumptions; these are not verified insulation parameters.')
    snap=snapshot(payload)
    profile=keep('ageing_version',{**payload.model_dump(exclude=set(Context.model_fields)),'asset_id':snap['asset_id']},actor)
    store.put('ageing_profile',snap['asset_id'],profile)
    return analysis.ledger(snap,profile)


UNITS={'hydrogen':'ppm','methane':'ppm','acetylene':'ppm','ethylene':'ppm','ethane':'ppm','carbon_monoxide':'ppm',
       'carbon_dioxide':'ppm','furan_2fal':'ppb','moisture':'ppm','breakdown_voltage':'kV','acidity':'mg KOH/g'}


class LabValue(Contract):
    analyte:Literal['hydrogen','methane','acetylene','ethylene','ethane','carbon_monoxide','carbon_dioxide','furan_2fal','moisture','breakdown_voltage','acidity']
    value:float=Field(ge=0,le=100000000)
    unit:str
    laboratory_flag:Literal['not_assessed','within_lab_range','outside_lab_range']='not_assessed'

    @model_validator(mode='after')
    def unit_check(self):
        if self.unit!=UNITS[self.analyte]:raise ValueError(f'{self.analyte} requires {UNITS[self.analyte]}; verify the original report.')
        return self


class LabReport(Contract):
    asset_id:str=Field(pattern=r'^[\w-]{1,80}$')
    report_reference:str=Field(min_length=3,max_length=200)
    laboratory:str=Field(min_length=2,max_length=100)
    sample_at:datetime
    reviewer:str=Field(min_length=2,max_length=100)
    note:str=Field(min_length=5,max_length=1000)
    evidence_type:Literal['laboratory_report','demonstration_fixture']
    confirmed:bool=False
    values:list[LabValue]=Field(min_length=1,max_length=11)

    @model_validator(mode='after')
    def review(self):
        if not self.confirmed:raise ValueError('Review the original report, identity, date, units and values before confirming.')
        if self.sample_at.utcoffset() is None or self.sample_at>datetime.now(timezone.utc):raise ValueError('Sample time must be timezone-aware and not in the future.')
        if len({v.analyte for v in self.values})!=len(self.values):raise ValueError('Each analyte may appear once per report.')
        return self


@router.post('/lab-reports')
def lab_report(payload:LabReport,actor=Depends(operator)):
    return keep('lab_report',payload.model_dump(mode='json'),actor)


class Selection(Contract):
    asset_id:str=Field(pattern=r'^[\w-]{1,80}$')


@router.post('/records')
def records(payload:Selection,actor=Depends(operator)):
    kinds=['forecast','forecast_score','benchmark','plan','acceptance','lab_report']
    result={kind:[r for r in store.records(kind) if r.get('asset_id')==payload.asset_id][:100] for kind in kinds}
    reports=sorted(result['lab_report'],key=lambda r:r['sample_at'])
    trends=[]
    for analyte,unit in UNITS.items():
        for provenance in ('laboratory_report','demonstration_fixture'):
            points=[{'sample_at':r['sample_at'],'value':v['value'],'laboratory_flag':v['laboratory_flag'],'report_id':r['id']} for r in reports if r['evidence_type']==provenance for v in r['values'] if v['analyte']==analyte]
            if points:trends.append({'analyte':analyte,'unit':unit,'source':provenance,'points':points,
                                     'change':points[-1]['value']-points[-2]['value'] if len(points)>1 else None,
                                     'next_step':'Review the signed laboratory interpretation and sampling comparability. These trends do not identify a fault or remaining life.'})
    result['lab_trends']=trends
    return result


@router.post('/export')
def export_case(context:Context,actor=Depends(operator)):
    snap=snapshot(context); saved=records(Selection(asset_id=snap['asset_id']),actor)
    payload={'version':'halo-evidence-1','created_at':now(),'context':context.model_dump(),'snapshot':snap,
             'investigation':analysis.investigation(snap),'ledger':analysis.ledger(snap,store.get('ageing_profile',snap['asset_id'])),
             'records':saved,'maintenance':[r for r in store.records('incident') if r['asset_id']==snap['asset_id']],
             'limitations':'Recorded/replayed evidence is not field certification. No secrets or raw attachment files are included.'}
    raw=json.dumps(payload,indent=2,ensure_ascii=False).encode()
    summary=report_html(payload)
    files={'case.json':raw,'report.html':summary}
    manifest={'created_at':now(),'files':{name:__import__('hashlib').sha256(value).hexdigest() for name,value in files.items()},
              'note':'Checksums detect changes against a retained manifest; they are not a third-party signature or proof of measurement truth.'}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="halo-case-{snap["asset_id"]}.zip"','Cache-Control':'no-store'})
