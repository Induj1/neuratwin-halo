"""Industrial studies and complete, source-labelled PDF snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field, field_validator, model_validator
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from . import halo_store as store, halo_engine as bench, twin_core as core, twin_studies as studies
from . import electrical_diagnostics as diagnostics
from . import lifetime_scenario as lifetime
from . import prototype_physics as physics
from .twin_api import run_or_404, prototype_view
from .storage import now

router=APIRouter(prefix='/api/halo/twin')


class DisplayChannel(Contract):
    value:float|None=None
    raw:float|None=None
    unit:str=Field(max_length=10)
    source:Literal['measured','firmware_calculated','frontend_estimated','simulated','unavailable']
    method:str=Field(max_length=200)
    quality:str=Field(max_length=40)


class DisplaySample(Contract):
    timestamp:datetime|None=None
    device_id:str|None=Field(None,max_length=64)
    boot_id:str|None=Field(None,max_length=64)
    sequence:int|None=Field(None,ge=0)
    version:Literal['prototype-display-1']
    quality:str=Field(max_length=40)
    age_s:float|None=Field(None,ge=0)
    active_branches:int|None=Field(None,ge=0,le=4)
    resistance_ohms:float|None=Field(None,gt=0)
    branch_ohms:float=Field(39,gt=0)
    reason:str|None=Field(None,max_length=500)
    calibrated:bool=False
    probe_valid:bool=False
    live:bool=False
    relay_states:tuple[bool,bool,bool,bool]|None=None
    loads:dict[str,bool|int]|None=None
    channels:dict[str,DisplayChannel]
    rating_a:Literal[1]=1
    loading_percent:float|None=None
    demo_health:float|None=None
    demo_health_version:Literal['current-only-1']
    scope:str=Field(max_length=200)

    @field_validator('channels')
    @classmethod
    def channel_names(cls,value):
        if set(value)!={'primary_voltage','secondary_voltage','primary_current','secondary_current','surface_temperature'}:
            raise ValueError('Exactly the five prototype display channels are required.')
        return value

    @model_validator(mode='after')
    def consistent(self):
        if self.timestamp is not None and self.timestamp.utcoffset() is None:raise ValueError('Display time needs a timezone.')
        current=self.channels['secondary_current'].value
        expected=None if current is None or not self.live else current*100
        if self.loading_percent!=expected:raise ValueError('Loading must match the supplied 1 A display current.')
        health=None if expected is None else 100-max(0,min(100,expected-80))
        if self.demo_health!=health:raise ValueError('Demo score must match its declared current-only calculation.')
        return self


class PhysicsOptions(Contract):
    settings:physics.Settings=Field(default_factory=physics.Settings)
    fault:Literal['none','leak','gas','surge']='none'
    fault_at:datetime|None=None
    reset_at:datetime|None=None

    @model_validator(mode='after')
    def timezones(self):
        if any(t and t.utcoffset() is None for t in (self.fault_at,self.reset_at)):
            raise ValueError('Scenario times require a timezone.')
        if self.fault!='none' and self.fault_at is None:raise ValueError('Fault start time is required.')
        if self.fault=='gas' and self.settings.tank!='conservator':raise ValueError('Buchholz scenario requires a conservator.')
        if self.fault=='surge' and self.settings.tank!='sealed':raise ValueError('Gas-cushion surge requires a sealed tank.')
        return self


class PDFRequest(Contract):
    start:datetime|None=None
    end:datetime|None=None
    revision:int|None=Field(None,ge=0)
    display_current:DisplaySample|None=None
    display_history:list[DisplaySample]=Field(default_factory=list,max_length=300)
    lifetime_assumptions:lifetime.Assumptions|None=None
    physics_options:PhysicsOptions|None=None

    @model_validator(mode='after')
    def interval(self):
        if any(t is not None and t.utcoffset() is None for t in (self.start,self.end)):raise ValueError('Report interval needs timezone-aware dates.')
        if self.start and self.end and self.start>self.end:raise ValueError('Start must precede end.')
        return self


def selected(timestamp,payload):
    if not timestamp:return not(payload.start or payload.end)
    value=datetime.fromisoformat(timestamp.replace('Z','+00:00'))
    return (not payload.start or value>=payload.start) and (not payload.end or value<=payload.end)


class LifetimeRequest(Contract):
    revision:int|None=Field(None,ge=0)
    assumptions:lifetime.Assumptions|None=None
    display_current:DisplaySample|None=None
    display_history:list[DisplaySample]=Field(default_factory=list,max_length=300)


class PhysicsRequest(LifetimeRequest):
    options:PhysicsOptions=Field(default_factory=PhysicsOptions)


def physics_result(asset,payload,state=None):
    physical=asset=='BENCH-001'
    if physical:
        samples=[v.model_dump(mode='json') for v in payload.display_history]
        current=payload.display_current.model_dump(mode='json') if payload.display_current else None
        if current:samples.append(current)
        rows=[lifetime.from_display(v) for v in samples if v.get('timestamp')]
        rated=1;live=bool(current and current['live']);branches=(current or {}).get('active_branches') or 0
    else:
        state=state or deepcopy(run_or_404(asset))
        if payload.revision is not None and payload.revision!=state['revision']:raise HTTPException(409,'Run changed. Refresh the physics study.')
        rows=[{**lifetime.from_industrial(v),'temperature_c':v.get('oil_temperature'),'source':'industrial modelled top-oil'} for v in [*state['history'],state['telemetry']]]
        rated=lifetime.defaults('industrial',state['settings']).rated_current_a;live=True;branches=0
    o=payload.options
    result=physics.assess(rows,o.settings,rated_current=rated,live=live,fault=o.fault,
        fault_at=o.fault_at.timestamp() if o.fault_at else None,reset_at=o.reset_at.timestamp() if o.reset_at else None,branches=branches)
    result.update(asset_id=asset,mode='prototype' if physical else 'industrial',revision=None if physical else state['revision'])
    if not physical:result['temperature_basis']='Initial industrial top-oil is modelled, then independently projected with this study profile.'
    if result['available']:result['fem']=physics.fem(result['loading_pu'],o.settings.ambient_c,energized=result['energized'])
    result['input_sha256']=studies.digest({'rows':rows,'options':o.model_dump(mode='json'),'version':result['version']})
    return result


@router.post('/physics/{asset}')
def physics_assessment(asset:str,payload:PhysicsRequest,actor=Depends(operator)):
    return physics_result(asset,payload)


@router.get('/physics-sensor-study')
def physics_sensor_study(actor=Depends(operator)):
    return physics.sensor_study()


def lifetime_result(asset, assumptions, display_current=None, display_history=None, state=None):
    physical=asset=='BENCH-001';mode='prototype' if physical else 'industrial'
    if physical:
        samples=[v.model_dump(mode='json') for v in (display_history or [])]
        current=display_current.model_dump(mode='json') if display_current else None
        if current:samples.append(current)
        rows=[lifetime.from_display(v) for v in samples if v.get('timestamp')]
        status='live' if current and current['live'] else 'cached' if rows else 'unavailable'
        settings={}
    else:
        state=state or deepcopy(run_or_404(asset));settings=state['settings']
        rows=[lifetime.from_industrial(v) for v in state['history']]
        rows.append(lifetime.from_industrial(state['telemetry']));status='industrial simulation'
    result=lifetime.assess(rows,assumptions or lifetime.defaults(mode,settings),mode=mode,source_status=status)
    result['asset_id']=asset;result['revision']=None if physical else state['revision']
    result['input_sha256']=studies.digest({'observations':rows,'assumptions':result['assumptions'],'version':result['version']})
    return result


@router.post('/lifetime/{asset}')
def lifetime_assessment(asset:str,payload:LifetimeRequest,actor=Depends(operator)):
    state=None
    if asset!='BENCH-001':
        state=deepcopy(run_or_404(asset))
        if payload.revision is not None and payload.revision!=state['revision']:
            raise HTTPException(409,'Run changed before assessment. Refresh the scenario.')
    return lifetime_result(asset,payload.assumptions,payload.display_current,payload.display_history,state)


def report_snapshot(asset,payload):
    captured=now()
    physical=asset=='BENCH-001'
    with WRITE_LOCK:
        if physical:
            cfg=bench.config();raw=store.report_frames(cfg.device_id,captured)
            selected_raw=[r for r in raw if selected(r.get('timestamp'),payload)]
            readings=[]
            for r in selected_raw:
                readings.append({'sample_id':r.get('evidence_id'),'timestamp':r.get('timestamp'),
                    'boot_id':r.get('boot_id'),'sequence':r.get('sequence'),
                    'primary_voltage':r.get('primary_v'),'secondary_voltage':r.get('secondary_v'),
                    'primary_current':r.get('primary_current_a'),'secondary_current':r.get('current_a'),
                    'transformer_temperature':r.get('surface_c'),'loading_percent':None,
                    'quality':','.join(r.get('quality_flags') or []) or 'calibration/configuration not established by export',
                    'source':'raw reported acquisition','config_id':r.get('config_id'),'calibration_id':r.get('calibration_id'),
                    'ambient_temperature':r.get('ambient_c'),'ambient_source':r.get('ambient_source'),
                    'relay_states':r.get('relay_states'),'relay_output_configured':r.get('relay_output_configured'),
                    'hardware_config_status':r.get('hardware_config_status'),'raw_channels':r.get('raw',{})})
            view=prototype_view(raw[-600:])
            configuration={'prototype_reference_a':1,'current_source':'Raw reported acquisition and browser display estimates are separate',
                'surface_probe':'DS18B20 surface; no measured oil/hot-spot/pressure',
                'load_mapping':{'M1':'load1','M2':'load2','M3':'load4','M4':'all three OFF; no hardware branch'},
                'configuration_binding':view['configuration_binding'],'calibration_id':view.get('calibration_id'),
                'browser_calculations':{'prototype-display-1':'V/R effective; ideal unity-PF primary estimate',
                    'current-only-1':'100 - clamp(loading_percent - 80, 0, 100); demo only'}}
            assessment={'at_export':view['analysis'],'note':'Current backend assessment, not a reconstruction of historical interval health.'}
            events=[r for r in store.report_events(asset,captured) if selected(r['created_at'],payload)]
            decisions=[r for r in store.records('mobile_inspection') if r.get('asset_id')==asset and selected(r.get('created_at'),payload)]
        else:
            s=deepcopy(run_or_404(asset))
            if payload.revision is not None and payload.revision!=s['revision']:raise HTTPException(409,'Run changed before export. Refresh and export again.')
            readings=[{**r,'sample_id':str(i),'source':'industrial simulation'} for i,r in enumerate(core.history_view(s['history'])) if selected(r['timestamp'],payload)]
            view=core.summary(s);configuration={'profile':view['profile'],'settings':s['settings'],'electrical_model':view['electrical_model'],
                'pressure_model':view['pressure_model'],'revision':s['revision']}
            assessment={'at_export':view['analysis'],'prediction_at_export':view['prediction']}
            events=[r for r in deepcopy(s['events']) if selected(r['timestamp'],payload)]
            decisions=[]
            for kind in ('twin_proof','twin_plan','twin_work','twin_thermal_pair','twin_electrical_review'):
                decisions.extend({'record_type':kind,**r} for r in store.records(kind) if r.get('run_id')==asset)
    decisions.extend({'record_type':'maintenance_job',**r} for r in store.records('maintenance_job') if r.get('asset_id')==asset and selected(r.get('created_at'),payload))
    profile=store.get('maintenance_profile',asset)
    if profile:configuration['maintenance_profile']=profile
    display_history=[r.model_dump(mode='json') for r in payload.display_history if physical and selected(r.timestamp.isoformat() if r.timestamp else None,payload)]
    display=payload.display_current.model_dump(mode='json') if physical and payload.display_current else None
    if display and not selected(display['timestamp'],payload):display=None
    assessment['lifetime_scenario_at_export']=lifetime_result(asset,payload.lifetime_assumptions,payload.display_current,payload.display_history,None if physical else s)
    if payload.physics_options is not None:
        study=physics_result(asset,PhysicsRequest(revision=payload.revision,options=payload.physics_options,display_current=payload.display_current,display_history=payload.display_history),None if physical else s)
        # Retain the computed study; FEM matrices are exported separately as JSON, not thousands of PDF cells.
        if study.get('fem'):study['fem']={k:v for k,v in study['fem'].items() if k not in ('nodes','triangles','materials','temperature_c')}
        assessment['physics_and_protection']=study
    snapshot={'version':'halo-pdf-snapshot-1','mode':'prototype' if physical else 'industrial','asset_id':asset,
        'generated_at':captured,'requested_interval':{'start':payload.start.isoformat() if payload.start else None,'end':payload.end.isoformat() if payload.end else None},
        'coverage':{'first':readings[0]['timestamp'] if readings else None,'last':readings[-1]['timestamp'] if readings else None,'records':len(readings)},
        'configuration':configuration,'assessment':assessment,'readings':readings,'events':events,'decisions':deepcopy(decisions),
        'display_current':display,'display_history':display_history,
        'notes':['Complete retained selected acquisitions; missing values remain unavailable. Acquisition gaps are not interpolated.',
            'Charts and appendices use this frozen snapshot. SHA-256 detects changes; it is not a signature or measurement certification.',
            'Raw readings appendix and bounded client-submitted display snapshots are separate sources. Browser estimates are not independent current measurements.' if physical else 'Industrial readings, pressure and protective actions are simulated.',
            'Historical displayed estimates outside the supplied browser buffer were not retained here; no retrospective values are invented.' if physical else 'Current assessment and linked study/work-order context are labelled separately from interval readings.',
            'No claim of reduced field failure rate, calibrated failure probability or physical isolation is established by this report.']}
    snapshot['sha256']=studies.digest(snapshot)
    return snapshot


@router.post('/reports/{asset}/pdf')
def pdf(asset:str,payload:PDFRequest,actor=Depends(operator)):
    from .pdf_report import render
    snapshot=report_snapshot(asset,payload)
    content=render(snapshot)
    # Retain the exact report source after successful generation, without raw credentials.
    store.create_unique('twin_report',snapshot['sha256'],snapshot)
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="neuratwin-'+snapshot['mode']+'-report.pdf"',
        'X-Report-SHA256':snapshot['sha256'],'Cache-Control':'no-store'})


@router.get('/reports/{digest}/snapshot')
def snapshot(digest:str):
    value=store.get('twin_report',digest)
    if not value:raise HTTPException(404,'Report snapshot not found.')
    return value


@router.get('/electrical-evaluation')
def evaluation():
    from functools import lru_cache
    return cached_evaluation()


from functools import lru_cache
@lru_cache(maxsize=1)
def cached_evaluation():return diagnostics.evaluate()


class Revision(Contract):
    revision:int=Field(ge=0)


@router.post('/runs/{key}/thermal-pair')
def thermal_pair(key:str,payload:Revision,actor=Depends(operator)):
    s=deepcopy(run_or_404(key))
    if s['revision']!=payload.revision:raise HTTPException(409,'Run changed. Refresh the study.')
    if s['fault'] or s['breaker']!='CLOSED':raise HTTPException(422,'Use an energised run without an active injected disturbance for a controlled thermal comparison.')
    results=[]
    for label,oil,winding in [('Cool',s['inputs']['ambient_c']+10,5),('Already hot',90,20)]:
        paired=deepcopy(s);paired['oil_c']=oil;paired['winding_rise_c']=winding
        core.evaluate(paired,0)
        forecast=studies.projection(paired,60)
        results.append({'label':label,'initial_oil_c':oil,'initial_winding_rise_c':winding,
                        'forecast':forecast,'time_to_limit':core.forecast(paired)})
    result={'run_id':key,'revision':s['revision'],'source':'controlled industrial simulation','created_at':now(),
        'settings':s['settings'],'inputs':s['inputs'],'cases':results,
        'note':'Identical parameters, ambient, cooling and imposed demand; only initial thermal state differs. Conditional unprotected trajectories, not operating clearance.'}
    identifier=studies.digest(result);store.create_unique('twin_thermal_pair',identifier,result)
    return result


@router.post('/runs/{key}/electrical-review')
def electrical_review(key:str,payload:Revision,actor=Depends(operator)):
    s=deepcopy(run_or_404(key))
    if s['revision']!=payload.revision:raise HTTPException(409,'Run changed. Refresh the review.')
    rated=core.terminal_fault(s['settings'])['rated_secondary_a']
    rows=[{'time_s':r['elapsed_s'],'current_pu':r.get('secondary_current')/rated if r.get('secondary_current') is not None else None,
        'voltage_pu':r.get('secondary_voltage')/s['settings']['secondary_v'] if r.get('secondary_voltage') is not None else None,
        'valid':r.get('quality')=='qualified'} for r in s['history'][-20:]]
    result={'run_id':key,'revision':s['revision'],'created_at':now(),'source':'Recorded industrial RMS observations',
        'assessment':diagnostics.assess(rows,{'sampled_waveform':False}),
        'input_sha256':studies.digest(rows),'excluded':['fault label','scenario','hidden plant state','future samples'],
        'note':'This RMS-only review withholds inrush/internal/external discrimination. Use the existing blind challenge in electrical waveform mode for that experiment.'}
    store.create_unique('twin_electrical_review',studies.digest(result),result)
    return result
