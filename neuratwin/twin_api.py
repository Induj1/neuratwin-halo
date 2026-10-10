"""Persistent industrial runs and the same twin view over measured bench data."""
from copy import deepcopy
from datetime import datetime, timezone
import csv
import hashlib
import html
import io
import json
import os
import uuid
import zipfile
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field, model_validator
from . import twin_core as core, halo_store as store, halo_engine as bench, cloud, auth
from .halo_contracts import Contract, Frame, RelayRequest
from .halo_api import operator, device, WRITE_LOCK, ingest, relay_command
from .storage import now

router=APIRouter(prefix='/api/halo')
PHYSICAL_ANALYZER_VERSION='halo-prototype-analysis-2'
PHYSICAL_RULE_VERSION='bench-limits-1'


class AssetProfile(Contract):
    name: str = Field('Illustrative distribution transformer',min_length=3,max_length=120)
    basis: Literal['illustrative','manufacturer_document','lab_reference','synthetic_reference'] = 'illustrative'
    reference: str = Field('No manufacturer test sheet supplied',min_length=5,max_length=1000)
    reviewer: str = Field('Unreviewed',min_length=3,max_length=120)
    impedance_basis: Literal['illustrative','nameplate','test_report','reviewed_configuration']='illustrative'
    impedance_reference: str = Field('No impedance reference supplied',min_length=5,max_length=1000)
    impedance_reviewer: str = Field('Unreviewed',min_length=3,max_length=120)

    @model_validator(mode='after')
    def reviewed(self):
        if self.impedance_basis!='illustrative' and (self.impedance_reviewer=='Unreviewed' or self.impedance_reference=='No impedance reference supplied'):
            raise ValueError('Documented impedance needs a reference and reviewer.')
        if self.basis!='illustrative' and (self.reviewer.lower()=='unreviewed' or self.reference=='No manufacturer test sheet supplied'):
            raise ValueError('Documented profiles require a reference identifier and reviewer. This records provenance, not automatic verification.')
        return self


class NewRun(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    settings: core.Settings = Field(default_factory=core.Settings)
    profile: AssetProfile = Field(default_factory=AssetProfile)


class Action(Contract):
    request_id: str = Field(pattern=r'^[\w-]{8,80}$')
    revision: int = Field(ge=0)
    action: Literal['start','pause','step','advance_paused','inputs','scenario','inject','clear_fault','trip','reconnect','maintenance','settings','profile']
    inputs: core.Inputs | None = None
    settings: core.Settings | None = None
    seconds: int = Field(60, ge=1, le=3600)
    scenario: str = Field('normal', max_length=40)
    fault: str = Field('surge', max_length=40)
    severity: int = Field(2, ge=1, le=3)
    duration_s: int = Field(120, ge=5, le=3600)
    maintenance: str = Field('inspection', max_length=60)
    note: str = Field('', max_length=2000)
    profile: AssetProfile | None = None


def run_or_404(key):
    s=store.get('twin_run',key)
    if not s:raise HTTPException(404,'Simulation run not found.')
    return s


@router.get('/twin/catalog')
def catalog():
    return {'server_clock':os.getenv('HALO_SERVER_CLOCK')=='1','scenarios':core.SCENARIOS,'faults':sorted(core.FAULTS),'maintenance':sorted(core.MAINTENANCE),
            'settings':core.Settings().model_dump(),'inputs':core.Inputs().model_dump(),
            'runs':[{k:s[k] for k in ('id','started_at','scenario','elapsed_s','breaker')} for s in store.records('twin_run')][:30]}


@router.post('/twin/runs')
def new_run(payload:NewRun,actor=Depends(operator)):
    key='IND-'+payload.request_id
    with WRITE_LOCK:
        prior=store.get('twin_run',key)
        if prior:
            if prior['initial_settings']!=payload.settings.model_dump():raise HTTPException(409,'Run request reused with different settings.')
            if prior.get('initial_profile',AssetProfile().model_dump())!=payload.profile.model_dump():raise HTTPException(409,'Run request reused with different asset provenance.')
            return core.summary(prior)
        s=core.create_state(key,payload.settings);s['initial_settings']=payload.settings.model_dump()
        s['profile']=payload.profile.model_dump();s['initial_profile']=payload.profile.model_dump()
        s['history'][0]['input_context']['profile']=deepcopy(s['profile'])
        s['events'][0]['actor']=actor
        store.put('twin_run',key,s);store.event(key,'twin_created',{'source':'industrial','actor':actor})
        return core.summary(s)


@router.get('/twin/runs/{key}')
def read_run(key:str):return core.summary(run_or_404(key))


@router.post('/twin/runs/{key}/actions')
def apply_action(key:str,payload:Action,actor=Depends(operator)):
    with WRITE_LOCK:
        s=deepcopy(run_or_404(key));body=payload.model_dump(mode='json')
        digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        prior=s['commands'].get(payload.request_id)
        if prior:
            if prior!=digest:raise HTTPException(409,'Action ID reused with different content.')
            return core.summary(s)
        if payload.revision!=s['revision']:raise HTTPException(409,'This run changed in another tab. Refresh and retry.')
        if len(s['commands'])>=5000:raise HTTPException(422,'Export this run and create a new session.')
        first_event=len(s['events']);action=payload.action
        # All observations made by this atomic command carry its resulting revision.
        s['revision']+=1
        try:
            if action in ('start','pause'):
                s['running']=action=='start';core.log(s,action,'Simulation '+('started.' if s['running'] else 'paused.'))
            elif action=='step':core.advance(s,payload.seconds)
            elif action=='advance_paused':
                s['running']=True
                core.advance(s,payload.seconds)
                s['running']=False
                core.log(s,'paused','Manual step completed; simulation paused.')
            elif action=='inputs':
                if payload.inputs is None:raise ValueError('Provide the complete input settings.')
                before=s['inputs'];s['inputs']=payload.inputs.model_dump()
                core.log(s,'inputs_changed','Operator changed simulation inputs.',before=before,after=s['inputs'])
                core.evaluate(s,0);core.remember(s)
            elif action=='settings':
                if payload.settings is None:raise ValueError('Provide complete model and protection settings.')
                if s['running'] or s['elapsed_s']>0:raise ValueError('Model settings can only change before the run starts; create a new run to change them.')
                s['settings']=payload.settings.model_dump();core.log(s,'settings_changed','Demonstration model settings recorded.',settings=s['settings'])
                core.evaluate(s,0)
            elif action=='profile':
                if payload.profile is None:raise ValueError('Provide the asset profile and parameter provenance.')
                s['profile']=payload.profile.model_dump()
                core.log(s,'profile_recorded','Parameter provenance recorded by operator; source document has not been independently verified.',profile=s['profile'])
            elif action=='scenario':
                if payload.scenario not in core.SCENARIOS:raise ValueError('Unknown scenario.')
                if s['breaker']=='OPEN':raise ValueError('Investigate and recover this trip or create a new run. A scenario cannot clear a latch.')
                case=core.SCENARIOS[payload.scenario];s['scenario']=payload.scenario
                s['inputs']=core.Inputs(**case['inputs']).model_dump();s['fault']=None
                if case.get('history_fixture'):
                    s['equivalent_age_hours']=max(s['equivalent_age_hours'],s['settings']['reference_life_hours']*.48)
                    s['historical_damage']=max(s['historical_damage'],30)
                core.log(s,'scenario_selected',case['name'],history_fixture=case.get('history_fixture',False),inputs=s['inputs'])
                if case.get('fault'):core.inject(s,case['fault'],2,120)
                core.evaluate(s,0);core.remember(s)
            elif action=='inject':core.inject(s,payload.fault,payload.severity,payload.duration_s)
            elif action=='clear_fault':
                s['fault']=None;core.log(s,'fault_cleared','Disturbance cleared by operator; breaker latch retained.');core.evaluate(s,0)
            elif action=='trip':
                core.trip(s,'Manual simulated trip');core.evaluate(s,0);core.remember(s)
            elif action=='maintenance':
                if len(payload.note.strip())<5:raise ValueError('Record an inspection or maintenance note of at least 5 characters.')
                core.maintain(s,payload.maintenance,payload.note.strip())
            elif action=='reconnect':
                holds=core.recovery_holds(s)
                if holds:raise ValueError(' '.join(holds))
                s['breaker']='CLOSED';s['critical_s']=0;s['recovery_s']=0
                core.log(s,'reconnected','Operator reclosed the simulated breaker after investigation and recovery checks.')
                core.evaluate(s,0);core.remember(s)
        except ValueError as error:raise HTTPException(422,str(error))
        if action in ('start','pause','settings','profile','clear_fault'):core.remember(s)
        s['commands'][payload.request_id]=digest
        for event in s['events'][first_event:]:event['actor']=actor
        store.put('twin_run',key,s)
        store.event(key,'twin_action',{'request_id':payload.request_id,'action':action,'revision':s['revision'],
                                     'elapsed_s':s['elapsed_s'],'actor':actor,'source':'industrial'})
        return core.summary(s)


def prototype_view(rows=None):
    cfg=bench.config();rows=store.frames(cfg.device_id) if rows is None else rows
    snap=bench.snapshot(rows,c=cfg);r=snap['current'] or {}
    complete=all(r.get(k) is not None for k in ('secondary_v','current_a','surface_c'))
    bound=snap.get('configuration_binding',{}).get('state')=='bound'
    current_binding=bound and r.get('config_id')==bench.config_identity(cfg)
    quality='qualified' if snap['connection']=='live' and bound and r.get('hardware_config_status')=='reported_match' and complete and snap['quality']['calibration']=='reference recorded' and not r.get('quality_flags') else 'unverified' if snap['connection']=='live' else snap['connection']
    t=core.Telemetry(timestamp=r.get('timestamp',now()),source='prototype',transformer_id='BENCH-001',
        primary_voltage=r.get('primary_v'),primary_current=r.get('primary_current_a'),secondary_voltage=r.get('secondary_v'),
        secondary_current=r.get('current_a'),loading_percent=snap['metrics']['load_pct'],
        transformer_temperature=r.get('surface_c'),temperature_kind='surface',ambient_temperature=r.get('ambient_c'),quality=quality).model_dump(mode='json')
    limits={'load_warning':90,'load_critical':100,'load_trip':100,
            'temperature_warning':snap['limits']['surface_c']-5 if snap['limits']['surface_c'] else None,
            'temperature_critical':snap['limits']['surface_c'],'temperature_trip':snap['limits']['surface_c'],
            'nominal_voltage':snap['limits']['nominal_secondary_v'],'voltage_warning_pu':.1,'voltage_critical_pu':.2,'voltage_trip_pu':.25}
    configs={}
    def row_load(row):
        key=row.get('config_id')
        if key not in configs:configs[key]=bench.recorded_config(row)[0]
        c=configs[key]
        return 100*row['current_a']/c.current_limit_a if c and c.current_limit_a and row.get('current_a') is not None else None
    previous=None
    if len(rows)>1:previous={'timestamp':rows[-2]['timestamp'],'transformer_temperature':rows[-2].get('surface_c'),
                              'secondary_voltage':rows[-2].get('secondary_v'),'secondary_current':rows[-2].get('current_a'),
                              'loading_percent':row_load(rows[-2])}
    if len(rows)>1 and any(rows[-2].get(k)!=r.get(k) for k in ('config_id','calibration_id')):previous=None
    state=store.get('twin_prototype','BENCH-001',{})
    a=core.analyse(t,limits,previous,state.get('historical_damage',0))
    # Keep the channel-specific bench checks: K4, acquisition integrity, resistor mismatch.
    for alert in snap['alerts']:
        if alert['severity']=='critical' and quality=='qualified':
            a['status']='TRIP'
            if alert['code']=='k4':a['alerts'].append({'code':'k4','severity':'TRIP','parameter':'relay_K4','value':True,'threshold':False,
                'timestamp':t['timestamp'],'detail':alert['evidence'],'category':'hardware_constraint','action':'Request all loads OFF'})
    configured=bool(current_binding and quality=='qualified' and cfg.automatic_cutoff_enabled and os.getenv('HALO_ALLOW_CONTROL')=='1' and not bench.holds(cfg) and not snap['holds'])
    command=store.get('command',state.get('command_id','')) or {}
    if command.get('status')=='pending' and bench.timestamp(command['expires_at'])<=datetime.now(timezone.utc):
        command={**command,'status':'expired'}
    status='ARMED' if configured else 'MONITORING ONLY'
    if state.get('latched'):
        status='OFF REQUESTED' if command.get('status')=='pending' else 'TRIP DECISION · no cutoff command'
        a['maintenance'].insert(0,'Investigate the latched trip and independently verify the physical rig before resetting the decision. No automatic reconnection.')
    if command.get('status')=='acknowledged':status='OFF ACKNOWLEDGED · contacts unverified'
    elif state.get('latched') and command.get('status') in ('rejected','expired','cancelled'):status='CUTOFF UNCONFIRMED'
    a['operating_stress_index']=a.get('operating_stress_index',a['health_index'])
    if a['status']!='NORMAL' or a['alerts'] or state.get('latched'):
        a['health_index']=None
        a['health_evidence']={'state':'review_required',
            'holds':[alert['code'] for alert in a['alerts']]+(['trip_latch'] if state.get('latched') else []),
            'calibrated_failure_probability':False,
            'note':'Condition index withheld while signal, evidence or trip holds remain. The operating stress score does not establish physical asset health.'}
    history=[{'timestamp':row['timestamp'],'transformer_temperature':row.get('surface_c'),
              'secondary_voltage':row.get('secondary_v'),'secondary_current':row.get('current_a'),
              'loading_percent':row_load(row),'config_id':row.get('config_id'),'calibration_id':row.get('calibration_id'),
              'health_index':None,'oil_temperature':None,'source':'prototype',
              'component_data_available':False,'analysis':None,
              'component_data_note':'Historical component analysis was not retained for this measured prototype observation.',
              **{k:None for k in core.PHASE_FIELDS}} for row in rows[-240:]]
    return {'id':'BENCH-001','source':'prototype','telemetry':t,'analysis':a,'history':history,'history_count':len(rows),
            'events':list(reversed(store.events('BENCH-001',100))),'protection_state':status,
            'breaker':'UNKNOWN · no contact feedback','trip':state.get('trip'),'connection':snap['connection'],
            'holds':snap['holds'],'relay_states':r.get('relay_states'),'command':command,
            'control_enabled':configured,'latched':bool(state.get('latched')),
            'load_control_available':bool(current_binding and os.getenv('HALO_ALLOW_CONTROL')=='1' and not bench.holds(cfg) and not snap['holds'] and quality=='qualified' and not state.get('latched') and r.get('relay_output_configured')),
            'condition':{'conditional_life_years':None,'life_note':'Oil, insulation ageing and remaining life are unavailable on this surface-sensing prototype.'},
            'assumptions':snap['notes']+['Primary current is optional and requires its own sensor, reviewed ADC pin and calibration. Missing measurements stay unavailable.'],
            'evidence':snap['evidence'],'configuration_binding':snap['configuration_binding'],'hardware_configuration':snap['hardware_configuration'],'calibration_id':r.get('calibration_id'),
            'settings':limits,'inputs':None,'running':False,
            'analyzer_version':PHYSICAL_ANALYZER_VERSION,'rule_version':PHYSICAL_RULE_VERSION}


def process_prototype(frame,*,allow_control=True):
    """Called by authenticated ingestion, independent of the dashboard being open.

    Latches once per incident. Only requests ALL OFF; it never automatically recloses.
    The physical source remains live; relay acknowledgments do not establish isolation.
    """
    with WRITE_LOCK, store.transaction():
        cfg=bench.config();rows=store.frames(cfg.device_id)
        if not rows:return {'status':'unavailable','reason':'No stored acquisition'}
        latest=rows[-1]
        if (latest['device_id'],latest['boot_id'],latest['sequence'])!=(frame.device_id,frame.boot_id,frame.sequence):
            return {'status':'superseded','reason':'A newer acquisition or different active device is available; live state was not rewound.'}
        state=store.get('twin_prototype','BENCH-001',{})
        identity=f'{frame.device_id}:{frame.boot_id}:{frame.sequence}'
        if state.get('last_frame')==identity:return {'status':'complete','duplicate':True}
        v=prototype_view(rows);a=v['analysis'];state['last_frame']=identity
        provenance={'config_id':frame.config_id,'calibration_id':frame.calibration_id,'frame':identity,
                    'configuration_binding':v['configuration_binding'],'hardware_configuration':v['hardware_configuration'],
                    'analyzer_version':PHYSICAL_ANALYZER_VERSION,'rule_version':PHYSICAL_RULE_VERSION}
        state['provenance']=provenance
        if a['status']=='TRIP' and not state.get('latched'):
            state.update(latched=True,historical_damage=min(100,state.get('historical_damage',0)+2),
                         trip={'timestamp':frame.timestamp.isoformat(),'reason':'Configured physical limit exceeded',
                               'telemetry':v['telemetry'],'alerts':a['alerts'],'provenance':provenance})
            store.event('BENCH-001','twin_trip_decision',state['trip'])
            if allow_control and v['control_enabled'] and frame.relay_output_configured:
                key='cutoff-'+uuid.uuid4().hex
                command=relay_command(RelayRequest(states=(False,False,False,False),request_id=key),actor='automatic cutoff · authenticated telemetry')
                state['command_id']=command['id']
            else:store.event('BENCH-001','twin_cutoff_withheld',{'reason':'Recovery is analysis-only, or commissioning/output/automatic-cutoff permission is incomplete. No physical command issued.'})
        elif a['status']!=state.get('last_status'):
            store.event('BENCH-001','twin_condition',{'status':a['status'],'telemetry':v['telemetry'],'health_index':a['health_index'],'provenance':provenance})
        state['last_status']=a['status'];store.put('twin_prototype','BENCH-001',state)
        return {'status':'complete','provenance':provenance,'condition':a['status'],'recovery':not allow_control}


@router.get('/twin/prototype')
def prototype():return prototype_view()


class Recovery(Contract):
    note: str = Field(min_length=10,max_length=2000)


@router.post('/twin/prototype/reset-latch')
def reset_prototype(payload:Recovery,actor=Depends(operator)):
    with WRITE_LOCK:
        v=prototype_view();t=v['telemetry'];cfg=bench.config()
        if t['quality']!='qualified' or cfg.current_limit_a is None or cfg.surface_limit_c is None:
            raise HTTPException(423,'Fresh, calibrated telemetry and commissioned limits are required.')
        if t['secondary_current'] is None or t['secondary_current']>=.9*cfg.current_limit_a or t['transformer_temperature'] is None or t['transformer_temperature']>=cfg.surface_limit_c-5:
            raise HTTPException(423,'Current and surface temperature have not recovered below the reset limits.')
        if any(v['relay_states'] or []) or v['analysis']['status'] in ('CRITICAL','TRIP'):
            raise HTTPException(423,'All relay GPIO states must report OFF and critical conditions must clear.')
        state=store.get('twin_prototype','BENCH-001',{});state['latched']=False;state.pop('command_id',None)
        store.put('twin_prototype','BENCH-001',state);store.event('BENCH-001','twin_latch_reset',{'note':payload.note,'actor':actor,'action':'Latch cleared; no ON command'})
        return prototype_view()


class PrototypeTelemetry(Contract):
    source: Literal['prototype']
    transformer_id: Literal['BENCH-001']
    device_id: str
    boot_id: str
    sequence: int
    uptime_ms: int
    timestamp: datetime
    primary_voltage: float | None = None
    primary_current: float | None = None
    secondary_voltage: float | None = None
    secondary_current: float | None = None
    transformer_temperature: float | None = None
    ambient_temperature: float | None = None
    ambient_source: Literal['not_measured','probe','manual'] = 'not_measured'
    ambient_observed_at: datetime | None = None
    calibration_id: str | None = None
    config_id: str | None = Field(default=None,pattern=r'^CFG-[a-f0-9]{64}$')
    hardware_config_status: Literal['reported_match','mismatch','unverified'] = 'unverified'
    raw: dict[str,float|None] = Field(default_factory=dict,max_length=20)
    relay_states: tuple[bool,bool,bool,bool] = (False,False,False,False)
    relay_output_configured: bool = False
    quality_flags: list[str] = Field(default_factory=list)


@router.post('/device/twin-telemetry')
def normalized_ingest(payload:PrototypeTelemetry,actor=Depends(device)):
    try:
        frame=Frame(**payload.model_dump(include={'device_id','boot_id','sequence','uptime_ms','timestamp','ambient_source',
                         'ambient_observed_at','calibration_id','config_id','hardware_config_status','raw','relay_states','relay_output_configured','quality_flags'}),
                    primary_v=payload.primary_voltage,primary_current_a=payload.primary_current,secondary_v=payload.secondary_voltage,
                    current_a=payload.secondary_current,surface_c=payload.transformer_temperature,ambient_c=payload.ambient_temperature)
    except ValueError as error:raise HTTPException(422,str(error))
    return ingest(frame,actor)


@router.get('/twin/runs/{key}/report')
def report(key:str):
    s=run_or_404(key);v=core.summary(s);buf=io.BytesIO()
    rows=core.history_view(s['history']);metrics={
        'duration_hours':s['elapsed_s']/3600,'mean_sampled_load_percent':sum(r['loading_percent'] for r in rows)/len(rows),
        'peak_load_percent':max(r['loading_percent'] for r in rows),
        'peak_hotspot_c':max(r['hotspot_temperature'] for r in rows),
        'peak_oil_c':max(r['oil_temperature'] for r in rows),'fault_count':s['fault_count'],'trip_count':s['trip_count'],
        'electrical_events':s['electrical_events'],
        'health_change':rows[-1]['health_index']-rows[0]['health_index']
            if rows[-1]['health_index'] is not None and rows[0]['health_index'] is not None else None}
    from . import twin_studies as studies
    proofs=[p for p in store.records('twin_proof') if p['run_id']==key]
    plans=[p for p in store.records('twin_plan') if p['run_id']==key]
    work=[{**p,'current_verification':studies.closure_check(s,p)} for p in store.records('twin_work') if p['run_id']==key]
    inspections=[p for p in store.records('mobile_inspection') if p['asset_id']==key]
    report={'summary':v,'metrics':metrics,'full_history':rows,'full_events':s['events'],'initial_settings':s['initial_settings'],
            'forecasts':[{'proof':p,'score':studies.score(p,s)} for p in proofs],'interventions':plans,'work_orders':work,'inspections':inspections}
    text=json.dumps(report,indent=2,allow_nan=False)
    csvbuf=io.StringIO();writer=csv.DictWriter(csvbuf,fieldnames=list(dict.fromkeys(k for row in rows for k in row)));writer.writeheader();writer.writerows(rows)
    esc=html.escape
    body='<h1>NeuraTwin · Transformer run report</h1><p>INDUSTRIAL SIMULATION · '+esc(key)+'</p>'
    body+='<p>All values are model outputs. This report does not establish field accuracy or electrical safety.</p><h2>Operating summary</h2><dl>'
    for k,value in metrics.items():
        display=f'{value:.3f}' if value is not None else 'Unavailable while condition evidence is withheld'
        body+=f'<dt>{esc(k.replace("_"," "))}</dt><dd>{esc(display)}</dd>'
    body+='</dl><h2>Maintenance recommendations</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in v['analysis']['maintenance'])+'</ul>'
    if inspections:
        body+='<h2>Mobile inspections</h2>'+''.join('<p><b>'+esc(p['component'])+'</b> '+esc(p['captured_at'])+'</p><p>'+esc(p['note'])+'</p>' for p in inspections)
    body+='<h2>Linked evidence</h2><p>'+str(len(proofs))+' frozen forecasts; '+str(len(plans))+' intervention studies; '+str(len(work))+' maintenance work orders. Complete records and scores are in run.json.</p>'
    for p in proofs:
        scored=studies.score(p,s);m=scored['unchanged_inputs']
        body+='<p>'+esc(p['id'])+': '+esc(scored['verdict'])+'. Comparable samples: '+str(m['count'])+'; model MAE '+esc(str(m['mae_c']))+' °C; persistence MAE '+esc(str(m['persistence_mae_c']))+' °C.</p>'
    body+='<h2>Maintenance acceptance</h2>'
    for w in work:
        check=w['current_verification']
        body+='<p><strong>'+esc(w['title'])+'</strong> — recorded status: '+esc(w['status'])+'. Current assessment: '+esc('eligible under recorded rules' if check['eligible'] else '; '.join(check['holds']))+'</p>'
    body+='<p>Historical closure is retained. Current acceptance is assessed separately; no record proves a physical repair.</p>'
    body+='<h2>Assumptions</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in v['assumptions'])+'</ul><h2>Event timeline</h2><table><tr><th>Time</th><th>Event</th><th>Finding</th></tr>'
    body+=''.join('<tr><td>'+esc(e['timestamp'])+'</td><td>'+esc(e['kind'])+'</td><td>'+esc(e['detail'])+'</td></tr>' for e in s['events'])+'</table>'
    document='<!doctype html><html lang="en"><meta charset="utf-8"><title>Transformer run report</title><style>body{font:16px/1.6 system-ui;max-width:1050px;margin:40px auto;padding:24px;color:#182c32}h1,h2{line-height:1.2}dt{font-weight:600}dd{margin-bottom:12px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}@media print{body{margin:0}}</style>'+body+'</html>'
    files={'report.html':document,'run.json':text,'telemetry.csv':csvbuf.getvalue()}
    manifest={name:hashlib.sha256(value.encode()).hexdigest() for name,value in files.items()}
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,value in files.items():archive.writestr(name,value)
        archive.writestr('manifest.json',json.dumps(manifest,indent=2))
    return Response(buf.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{key}-report.zip"'})
