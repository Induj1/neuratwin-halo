"""Industrial studies and complete, source-labelled PDF snapshots."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
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
from . import protection_study
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
    version:Literal['prototype-display-1','prototype-display-2']
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
    estimates:dict[str,DisplayChannel]=Field(default_factory=dict)
    estimated_loading_percent:float|None=None
    disagreement:bool=False
    rating_a:Literal[1]=1
    loading_percent:float|None=None
    demo_health:float|None=None
    demo_health_version:Literal['current-only-1','observed-current-2']
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
        if self.version=='prototype-display-2':
            if self.demo_health_version!='observed-current-2':raise ValueError('Separated readings require observed-current-2 screening.')
            for c in self.channels.values():
                if c.source not in ('measured','unavailable') or c.value is not None and (c.source!='measured' or c.value!=c.raw):
                    raise ValueError('Observed channels must preserve measured values; estimates belong in estimates.')
                if not self.live and c.value is not None:raise ValueError('Stale current values must be unavailable; retain them in raw.')
            if set(self.estimates)!={'primary_current','secondary_current'}:raise ValueError('Two separate current estimates are required.')
            for c in self.estimates.values():
                if c.source not in ('frontend_estimated','unavailable'):raise ValueError('Estimates cannot be declared measured.')
                if c.value is not None and (c.source!='frontend_estimated' or not self.live):raise ValueError('Estimates require live inputs.')
            estimate=self.estimates['secondary_current'].value
            estimated_loading=None if estimate is None else estimate*100
            if self.estimated_loading_percent!=estimated_loading:raise ValueError('Estimated loading must use the separate estimate.')
            disagreement=current is not None and estimate is not None and abs(current-estimate)>max(.05,.2*estimate)
            if self.disagreement!=disagreement:raise ValueError('Current disagreement must reflect both series.')
            if estimate is not None:
                voltage=self.channels['secondary_voltage'].value
                resistance=self.branch_ohms/self.active_branches if self.active_branches else None
                if voltage is None or resistance is None or not math.isclose(estimate,voltage/resistance,rel_tol=1e-9,abs_tol=1e-9):
                    raise ValueError('Secondary estimate must match its declared voltage and load-bank inputs.')
            primary_estimate=self.estimates['primary_current'].value
            if primary_estimate is not None:
                primary_voltage=self.channels['primary_voltage'].value
                secondary_voltage=self.channels['secondary_voltage'].value
                if estimate is None or primary_voltage is None or primary_voltage<=0 or secondary_voltage is None or not math.isclose(primary_estimate,secondary_voltage*estimate/primary_voltage,rel_tol=1e-9,abs_tol=1e-9):
                    raise ValueError('Primary estimate must match the declared ideal-transformer inputs.')
        expected=None if current is None or not self.live else current*100
        if self.loading_percent!=expected:raise ValueError('Loading must match the supplied 1 A display current.')
        health=None if expected is None or self.version=='prototype-display-2' and (not self.calibrated or self.disagreement) else 100-max(0,min(100,expected-80))
        if self.demo_health!=health:raise ValueError('Demo score must match its declared current-only calculation.')
        return self


class DemoLoadStep(Contract):
    seconds: float = Field(ge=0, le=86400)
    load_percent: float = Field(ge=0, le=180)


class PhysicsDemo(Contract):
    started_at: datetime
    elapsed_seconds: float = Field(ge=0, le=86400)
    initial_temperature_c: float = Field(35, ge=-20, le=100)
    steps: list[DemoLoadStep] = Field(min_length=1, max_length=2048)

    @model_validator(mode='after')
    def ordered(self):
        if self.started_at.utcoffset() is None:
            raise ValueError('Demo clock requires a timezone.')
        times = [s.seconds for s in self.steps]
        if times[0] != 0 or times != sorted(set(times)) or times[-1] > self.elapsed_seconds:
            raise ValueError('Demo load steps must start at zero and increase within the demo clock.')
        return self

    def rows(self):
        times = sorted({0., self.elapsed_seconds, *range(0, int(self.elapsed_seconds)+1, 10),
                        *(s.seconds for s in self.steps)})
        index = 0
        for seconds in times:
            while index+1 < len(self.steps) and self.steps[index+1].seconds <= seconds:
                index += 1
            yield dict(timestamp=(self.started_at+timedelta(seconds=seconds)).isoformat(),
                       sample_key=f'oil-demo:{seconds}', boot_id='oil-demo',
                       current_a=self.steps[index].load_percent/100, voltage_v=12.,
                       temperature_c=self.initial_temperature_c, current_source='demo simulation',
                       source='Independent virtual oil demo; not an ESP32 acquisition')


class OilAction(Contract):
    at:datetime
    operation:Literal['leak','stop','refill']
    rate_l_min:float=Field(0,ge=0,le=100)
    litres:float=Field(0,ge=0,le=5000)

    @model_validator(mode='after')
    def valid_action(self):
        if self.at.utcoffset() is None:raise ValueError('Oil action requires a timezone.')
        if self.operation=='leak' and self.rate_l_min<=0:raise ValueError('A leak requires a positive rate.')
        if self.operation=='refill' and self.litres<=0:raise ValueError('Refill must be positive.')
        return self


class ElectricalExercise(Contract):
    kind:Literal['none','overload','short','recovery']='none'
    elapsed_seconds:float=Field(0,ge=0,le=120)
    current_pu:float=Field(8,ge=2,le=10)


class PhysicsOptions(Contract):
    settings:physics.Settings=Field(default_factory=physics.Settings)
    fault:Literal['none','leak','gas','surge']='none'
    fault_at:datetime|None=None
    reset_at:datetime|None=None
    demo:PhysicsDemo|None=None
    oil_actions:list[OilAction]=Field(default_factory=list,max_length=100)
    electrical:ElectricalExercise=Field(default_factory=ElectricalExercise)

    @model_validator(mode='after')
    def timezones(self):
        times=[a.at for a in self.oil_actions]
        if times!=sorted(times):raise ValueError('Oil actions must be chronological.')
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


def physics_display_row(sample):
    """Use the gauge's chosen current without replacing the observed channel."""
    row=lifetime.from_display(sample)
    estimate=sample.get('estimates',{}).get('secondary_current',{}).get('value')
    observed=sample['channels']['secondary_current']['value']
    row['current_a']=estimate if estimate is not None else observed
    row['current_source']='frontend_estimated' if estimate is not None else sample['channels']['secondary_current']['source']
    row['observed_current_a']=observed
    row['estimated_current_a']=estimate
    row['calibrated']=sample.get('calibrated',False)
    row['measurement_disagreement']=sample.get('disagreement',False)
    row['observed_current_source']=sample['channels']['secondary_current']['source']
    return row


def physics_result(asset,payload,state=None):
    physical=asset=='BENCH-001'
    demo=physical and payload.options.demo is not None
    if physical:
        samples=[v.model_dump(mode='json') for v in payload.display_history]
        current=payload.display_current.model_dump(mode='json') if payload.display_current else None
        if current:samples.append(current)
        rows=[physics_display_row(v) for v in samples if v.get('timestamp')]
        rated=1;live=bool(current and current['live']);branches=(current or {}).get('active_branches') or 0
        if demo:
            rows=list(payload.options.demo.rows())
            live=False
            branches=0
    else:
        state=state or deepcopy(run_or_404(asset))
        if payload.revision is not None and payload.revision!=state['revision']:raise HTTPException(409,'Run changed. Refresh the physics study.')
        rows=[{**lifetime.from_industrial(v),'temperature_c':v.get('oil_temperature'),'source':'industrial modelled top-oil'} for v in [*state['history'],state['telemetry']]]
        rated=lifetime.defaults('industrial',state['settings']).rated_current_a;live=True;branches=0
    o=payload.options
    result=physics.assess(rows,o.settings,rated_current=rated,live=live,fault=o.fault,
        fault_at=o.fault_at.timestamp() if o.fault_at else None,reset_at=o.reset_at.timestamp() if o.reset_at else None,branches=branches,
        oil_actions=[dict(time=a.at.timestamp(),operation=a.operation,rate_l_min=a.rate_l_min,litres=a.litres) for a in o.oil_actions])
    if physical and not demo and current:
        result['measurement_disagreement']=bool(current.get('disagreement'))
        result['current_basis']='Displayed load-bank estimate' if current.get('estimates',{}).get('secondary_current',{}).get('value') is not None else 'Displayed measured current'
        result['input_note']='Measured current is uncalibrated or disagrees with the estimate; the oil study uses the displayed current basis, not proof of actual load current.' if current.get('disagreement') or not current.get('calibrated') else ''
    result.update(asset_id=asset,mode='prototype' if physical else 'industrial',revision=None if physical else state['revision'])
    result['simulated_inputs']=demo
    if demo:
        result['temperature_basis']='Demo seed temperature; no measured surface or oil temperature is substituted.'
        result['scope']='Independent virtual oil demo. Inputs are simulated; measured readings and physical controls are unchanged.'
    if not physical:result['temperature_basis']='Initial industrial top-oil is modelled, then independently projected with this study profile.'
    if result['available']:result['fem']=physics.fem(result['loading_pu'],o.settings.ambient_c,energized=result['energized'])
    electrical_rows=[physics_display_row(v) for v in samples if v.get('timestamp')] if physical else rows
    result['electrical']=protection_study.electrical(electrical_rows,o.settings,rated_current=rated,
        nominal_voltage=12 if physical else state['settings']['secondary_v'],live=bool(current and current['live']) if physical else live,
        scenario=o.electrical.model_dump())
    result['calculations']=protection_study.calculations(result,o.settings,result['electrical'])
    result['input_sha256']=studies.digest({'rows':rows,'electrical_rows':electrical_rows,'options':o.model_dump(mode='json'),'version':result['version']})
    return result


@router.post('/physics/{asset}')
def physics_assessment(asset:str,payload:PhysicsRequest,actor=Depends(operator)):
    return physics_result(asset,payload)


@router.get('/physics-sensor-study')
def physics_sensor_study(actor=Depends(operator)):
    return physics.sensor_study()


class ProtectionJobRequest(PhysicsRequest):
    request_id:str=Field(min_length=8,max_length=80,pattern=r'^[\w-]+$')


class ProtectionJobUpdate(PhysicsRequest):
    job_revision:int=Field(ge=0)
    operation:Literal['finding','action','verify']
    note:str=Field(min_length=3,max_length=2000)


@router.get('/protection-jobs/{asset}')
def protection_jobs(asset:str,actor=Depends(operator)):
    if asset!='BENCH-001':run_or_404(asset)
    return [v for v in store.records('protection_job') if v['asset_id']==asset]


def compact_study(study):
    frozen=deepcopy(study)
    if frozen.get('fem'):frozen['fem']={k:v for k,v in frozen['fem'].items() if k not in ('nodes','triangles','materials','temperature_c')}
    return frozen


@router.post('/protection-jobs/{asset}')
def create_protection_job(asset:str,payload:ProtectionJobRequest,actor=Depends(operator)):
    from uuid import uuid4
    with WRITE_LOCK,store.transaction():
        prior=next((j for j in store.records('protection_job') if j['asset_id']==asset and j['request_id']==payload.request_id),None)
        if prior:return prior
        study=compact_study(physics_result(asset,payload))
        e=study['electrical'];oil=study.get('oil_balance',{})
        if e['severity'] not in ('warning','critical') and study.get('stage') not in ('warning','trip') and not oil.get('missing_l') and not oil.get('loss_rate_l_min'):
            raise HTTPException(422,'Run or capture an abnormal condition before creating a protection job.')
        title=e['label'] if e['severity'] in ('warning','critical') else 'Oil loss inspection' if oil.get('missing_l') or oil.get('loss_rate_l_min') else 'Thermal and oil protection inspection'
        record=dict(id=str(uuid4()),asset_id=asset,request_id=payload.request_id,title=title,status='open',revision=0,created_at=now(),
            study=study,options=payload.options.model_dump(mode='json'),
            display_current=payload.display_current.model_dump(mode='json') if payload.display_current else None,
            display_history=[v.model_dump(mode='json') for v in payload.display_history],
            trail=[dict(at=now(),operation='created',note='Frozen source readings, limits and calculations retained.')],verification=None)
        store.create_unique('protection_job',record['id'],record)
        return record


@router.post('/protection-jobs/{asset}/{job}')
def update_protection_job(asset:str,job:str,payload:ProtectionJobUpdate,actor=Depends(operator)):
    with WRITE_LOCK,store.transaction():
        record=store.get('protection_job',job)
        if not record or record['asset_id']!=asset:raise HTTPException(404,'Protection job not found.')
        if record['revision']!=payload.job_revision:raise HTTPException(409,'Job changed; refresh before saving.')
        entry=dict(at=now(),operation=payload.operation,note=payload.note)
        if payload.operation=='action':record['status']='awaiting_verification'
        if payload.operation=='verify':
            if not any(v['operation']=='action' for v in record['trail']):raise HTTPException(422,'Record the corrective action before verification.')
            after=compact_study(physics_result(asset,payload));before=record['study']
            same=before['settings']==after['settings'] and before['simulated_inputs']==after['simulated_inputs']
            electrical_job=before['electrical']['severity'] in ('warning','critical')
            # Resetting a synthetic exercise is not evidence that an actual electrical fault was repaired.
            electrical_clear=after['electrical']['stage']=='normal' and after['electrical']['source']==before['electrical']['source']
            oil_clear=after.get('available') and after.get('stage')=='normal' and after.get('loss_rate_l_min')==0 and after.get('inventory_percent',0)>=after['settings']['oil_warning_percent']
            fresh=after.get('timestamp') and before.get('timestamp') and after['timestamp']>before['timestamp']
            passed=bool(same and fresh and (electrical_clear if electrical_job else oil_clear))
            verification=dict(outcome='model_recovered' if passed else 'not_verified',verified_at=now(),
                note='Conditional model comparison only; technician findings do not prove physical isolation or repair.',
                before_oil_l=before.get('inventory_l'),after_oil_l=after.get('inventory_l'),before_peak_c=max((v['oil_c'] for v in before.get('curves',[])),default=None),
                after_peak_c=max((v['oil_c'] for v in after.get('curves',[])),default=None),same_assumptions=same,newer_source=bool(fresh),study=after)
            record['verification']=verification;entry['outcome']=verification['outcome'];record['status']=verification['outcome']
        record['trail'].append(entry);record['revision']+=1;store.put('protection_job',job,record)
        return record


@router.get('/protection-jobs/{asset}/{job}/report.pdf')
def protection_job_report(asset:str,job:str,actor=Depends(operator)):
    from .pdf_report import render
    record=store.get('protection_job',job)
    if not record or record['asset_id']!=asset:raise HTTPException(404,'Protection job not found.')
    snap=dict(mode=record['study']['mode'],asset_id=asset,generated_at=now(),requested_interval=dict(start=None,end=None),
        coverage=dict(first=record['study'].get('timestamp'),last=record['study'].get('timestamp'),records=0),readings=[],display_history=record.get('display_history',[]),display_current=record.get('display_current'),
        configuration=record['study']['settings'],assessment={'physics_and_protection':record['study']},events=record['trail'],
        decisions=[{k:v for k,v in record.items() if k not in ('study','display_current','display_history')}],
        notes=['Frozen protection job. Oil inventory and injected electrical events are simulated; raw acquisition channels are unchanged.','Model recovery does not establish physical repair or protection performance.'])
    snap['sha256']=studies.digest(snap)
    return Response(render(snap),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="neuratwin-protection-job.pdf"'})


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
    basis='Explicit independent scenario assumptions' if assumptions else 'Default industrial ageing assumptions'
    if not physical and assumptions == lifetime.defaults(mode,settings):
        basis='Default industrial ageing assumptions'
    if physical:
        from .maintenance_model import Profile
        record=store.get('maintenance_profile',asset)
        p=Profile(**record['profile']) if record else Profile()
        thermal={'ambient_c':p.ambient_c,'rated_rise_c':p.rated_rise_c,
            'thermal_tau_min':p.tau_min,'limit_temperature_c':p.temperature_limit_c}
        if assumptions is None or all(getattr(assumptions,k)==v for k,v in thermal.items()):
            assumptions=assumptions or lifetime.defaults(mode,settings).model_copy(update=thermal)
            basis='Thermal defaults inherited from maintenance profile revision '+str(record['revision'] if record else 0)+'; ageing and lifetime parameters remain assumptions'
    result=lifetime.assess(rows,assumptions or lifetime.defaults(mode,settings),mode=mode,source_status=status)
    result['assumption_origin']=basis
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
    decisions.extend({'record_type':'protection_job',**r} for r in store.records('protection_job') if r.get('asset_id')==asset and selected(r.get('created_at'),payload))
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
