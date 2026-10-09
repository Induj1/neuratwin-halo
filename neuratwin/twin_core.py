"""One normalized twin contract; source-specific physical meaning and limits.

Industrial parameters are illustrative assumptions, not IEC/IEEE compliance.
The bench adapter never manufactures oil, winding, ambient or lifetime readings.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Literal
from pydantic import Field, model_validator
from .halo_contracts import Contract


class Telemetry(Contract):
    timestamp: datetime
    source: Literal['industrial', 'prototype']
    transformer_id: str
    primary_voltage: float | None = Field(None, ge=0)
    primary_current: float | None = Field(None, ge=0)
    secondary_voltage: float | None = Field(None, ge=0)
    secondary_current: float | None = Field(None, ge=0)
    loading_percent: float | None = Field(None, ge=0)
    phase_current_a: float | None = Field(None, ge=0)
    phase_current_b: float | None = Field(None, ge=0)
    phase_current_c: float | None = Field(None, ge=0)
    neutral_current: float | None = Field(None, ge=0)
    phase_imbalance_percent: float | None = Field(None, ge=0, le=60)
    max_phase_loading_percent: float | None = Field(None, ge=0)
    thermal_loading_percent: float | None = Field(None, ge=0)
    transformer_temperature: float | None = None
    ambient_temperature: float | None = None
    oil_temperature: float | None = None
    hotspot_temperature: float | None = None
    oil_level_percent: float | None = Field(None, ge=0, le=100)
    oil_condition: float | None = Field(None, ge=0, le=100)
    gas_indicator: bool | None = None
    temperature_kind: Literal['surface', 'modelled_hotspot']
    quality: Literal['qualified', 'unverified', 'stale', 'disconnected'] = 'qualified'
    event: str | None = None

    @model_validator(mode='after')
    def origin(self):
        if self.timestamp.utcoffset() is None:
            raise ValueError('Acquisition time needs a timezone.')
        if self.source == 'prototype' and (self.temperature_kind != 'surface' or any(
                getattr(self, k) is not None for k in ('oil_temperature', 'hotspot_temperature',
                                                       'oil_level_percent', 'oil_condition', 'gas_indicator'))):
            raise ValueError('Prototype surface telemetry cannot assert oil or winding condition.')
        if self.source == 'prototype' and any(getattr(self, k) is not None for k in PHASE_FIELDS):
            raise ValueError('The single-phase prototype does not measure industrial phase or neutral channels.')
        return self


class Settings(Contract):
    rated_kva: float = Field(630, ge=1, le=100000)
    primary_v: float = Field(11000, ge=100, le=400000)
    secondary_v: float = Field(433, ge=50, le=33000)
    core_loss_w: float = Field(1000, ge=0, le=50000)
    copper_loss_w: float = Field(6500, gt=0, le=1000000)
    rated_oil_rise_c: float = Field(55, ge=10, le=100)
    rated_winding_rise_c: float = Field(23, ge=5, le=60)
    oil_tau_min: float = Field(120, ge=10, le=600)
    winding_tau_min: float = Field(7, ge=1, le=60)
    reference_life_hours: float = Field(180000, ge=10000, le=500000)
    load_warning: float = Field(100, ge=10, le=300)
    load_critical: float = Field(125, ge=10, le=400)
    load_trip: float = Field(160, ge=10, le=500)
    temperature_warning: float = Field(110, ge=40, le=180)
    temperature_critical: float = Field(125, ge=50, le=200)
    temperature_trip: float = Field(140, ge=60, le=250)
    recovery_temperature: float = Field(95, ge=10, le=170)
    voltage_warning_pu: float = Field(.1, gt=.01, le=.3)
    voltage_critical_pu: float = Field(.2, gt=.01, le=.5)
    voltage_trip_pu: float = Field(.3, gt=.01, le=.9)
    critical_delay_s: float = Field(120, ge=5, le=1800)
    recovery_hold_s: float = Field(60, ge=5, le=600)
    health_watch: float = Field(75, ge=1, le=99)
    health_degraded: float = Field(50, ge=1, le=98)
    health_high_risk: float = Field(25, ge=1, le=97)

    @model_validator(mode='after')
    def ordered(self):
        if not self.load_warning < self.load_critical < self.load_trip:
            raise ValueError('Load limits must increase from warning to critical to trip.')
        if not self.recovery_temperature < self.temperature_warning < self.temperature_critical < self.temperature_trip:
            raise ValueError('Thermal recovery must be below warning, critical and trip thresholds.')
        if not self.voltage_warning_pu < self.voltage_critical_pu < self.voltage_trip_pu:
            raise ValueError('Voltage deviation thresholds must be increasing.')
        if not self.health_high_risk < self.health_degraded < self.health_watch:
            raise ValueError('Health bands must be ordered.')
        return self


class Inputs(Contract):
    load_percent: float = Field(70, ge=0, le=250)
    phase_imbalance_percent: float = Field(0, ge=0, le=60)
    voltage_pu: float = Field(1, ge=.4, le=1.6)
    ambient_c: float = Field(30, ge=-20, le=60)
    cooling: Literal['normal', 'degraded', 'failed'] = 'normal'
    oil_level_percent: float = Field(100, ge=0, le=100)
    oil_condition: float = Field(100, ge=0, le=100)
    protection_enabled: bool = True
    speed: Literal[1, 10, 60, 300, 1800] = 60


SCENARIOS = {
    'normal': {'name': 'Normal operation', 'inputs': {}},
    'overload': {'name': 'Sustained overload', 'inputs': {'load_percent': 140}},
    'cooling': {'name': 'Cooling failure', 'inputs': {'load_percent': 100, 'cooling': 'failed'}},
    'surge': {'name': 'Voltage surge', 'inputs': {}, 'fault': 'surge'},
    'storm': {'name': 'Thunderstorm', 'inputs': {}, 'fault': 'storm'},
    'degradation': {'name': 'Historical degradation', 'inputs': {'load_percent': 110, 'oil_condition': 55}, 'history_fixture': True},
    'recovery': {'name': 'Fault → investigation → recovery', 'inputs': {}, 'fault': 'short_circuit'},
}
FAULTS = {'surge', 'storm', 'short_circuit', 'overcurrent', 'overvoltage', 'undervoltage',
          'thermal', 'cooling', 'low_oil', 'gas', 'combined', 'sensor'}
MAINTENANCE = {'inspection', 'fault_investigation', 'cooling_service', 'oil_service',
               'electrical_inspection', 'load_review', 'protection_inspection', 'condition_assessment'}
PHASE_FIELDS = ('phase_current_a', 'phase_current_b', 'phase_current_c', 'neutral_current',
                'phase_imbalance_percent', 'max_phase_loading_percent', 'thermal_loading_percent')
PHASE_WARNING = 10.
PHASE_CRITICAL = 20.
PHASE_MODEL = {
    'version': 'illustrative-fundamental-1', 'current_unit': 'A RMS',
    'voltage_basis': 'Balanced line-to-line RMS voltage', 'power_factor': 1.,
    'phase_angles_deg': [0, -120, 120],
    'imbalance_definition': '100 × maximum absolute phase-current deviation from the mean / mean; zero with no current.',
    'current_model': 'Mean secondary current × [1+u, 1, 1-u], where u is requested imbalance / 100.',
    'neutral_model': 'Magnitude of the fundamental 120-degree phase-current vector sum; illustrative neutral-capable secondary.',
    'thermal_model': 'Mean squared phase loading drives copper loss; maximum phase loading drives the winding hot-spot estimate.',
    'warning_percent': PHASE_WARNING, 'critical_percent': PHASE_CRITICAL,
    'limitations': 'Illustrative load imbalance only; balanced voltage and unity power factor assumed. No harmonics, phase-angle imbalance, sequence-network or winding-connection model. No prototype phase measurements.',
}


def stamp(state):
    return (datetime.fromisoformat(state['started_at']) + timedelta(seconds=state['elapsed_s'])).isoformat()


def log(state, kind, detail, severity='INFO', **values):
    state['events'].append({'id': len(state['events']) + 1, 'timestamp': stamp(state),
                            'elapsed_s': state['elapsed_s'], 'kind': kind, 'severity': severity,
                            'detail': detail, **values})


def create_state(identifier, settings=None):
    cfg = (settings or Settings()).model_dump()
    s = {'id': identifier, 'source': 'industrial', 'revision': 0, 'started_at': datetime.now(timezone.utc).isoformat(),
         'elapsed_s': 0., 'running': False, 'scenario': 'normal', 'settings': cfg,
         'inputs': Inputs().model_dump(), 'fault': None, 'breaker': 'CLOSED', 'trip': None,
         'critical_s': 0., 'recovery_s': 0., 'investigated': False, 'oil_c': 65., 'winding_rise_c': 14.,
         'equivalent_age_hours': 0., 'historical_damage': 0., 'overload_hours': 0., 'trip_count': 0,
         'fault_count': 0, 'electrical_events': 0, 'prior_codes': [], 'history': [], 'events': [],
         'commands': {}, 'previous_telemetry': None, 'analysis': None}
    log(s, 'created', 'Industrial simulation created. All ratings and protection settings are demonstration assumptions.')
    evaluate(s, 0)
    remember(s)
    return s


def electrical(s):
    i, p = s['inputs'], s['settings']
    pu, load = i['voltage_pu'], i['load_percent'] / 100
    fault = s['fault'] if s['fault'] and s['elapsed_s'] < s['fault']['until_s'] else None
    event = fault['kind'] if fault else None
    level = fault['severity'] if fault else 0
    if event in ('surge', 'overvoltage', 'combined'): pu += .12 * level
    if event == 'undervoltage': pu -= .12 * level
    # Deterministic disturbances; storm alone is not an unconditional trip.
    if event == 'storm': pu += .03 * level * math.sin(s['elapsed_s'] * .35)
    if event == 'storm' and int(s['elapsed_s']) % 60 < 5: pu += .06 * level
    if event == 'short_circuit': pu *= .35; load = 4. + level
    if event == 'overcurrent': load += .3 * level
    if s['breaker'] == 'OPEN':
        return dict(primary_voltage=0., secondary_voltage=0., primary_current=0., secondary_current=0.,
                    loading_percent=0., losses_w=0., voltage_pu=pu, event=event, load_pu=0.,
                    max_phase_load_pu=0., thermal_load_pu=0., **{k:0. for k in PHASE_FIELDS})
    vp = p['primary_v'] * pu
    vs = max(0, p['secondary_v'] * pu * (1 - .035 * load))
    # Constant-current demand: load is mean per-unit rated secondary current.
    si = load * p['rated_kva'] * 1000 / (math.sqrt(3) * p['secondary_v'])
    u = i.get('phase_imbalance_percent', 0.) / 100
    phase_currents = (si*(1+u), si, si*(1-u))
    # Mean square of [1+u, 1, 1-u]; default u=0 preserves the balanced plant exactly.
    thermal_load = load * math.sqrt(1 + 2*u*u/3)
    maximum_load = load * (1+u)
    neutral = math.hypot(sum(current*math.cos(angle) for current,angle in zip(phase_currents,(0,-2*math.pi/3,2*math.pi/3))),
                         sum(current*math.sin(angle) for current,angle in zip(phase_currents,(0,-2*math.pi/3,2*math.pi/3)))) if u else 0.
    losses = p['core_loss_w'] * pu**2 + p['copper_loss_w'] * load**2 * (1 + 2*u*u/3)
    apparent = math.sqrt(3) * vs * si
    # Unity power factor is an explicit industrial model assumption, never a prototype inference.
    pi = (apparent + losses) / (math.sqrt(3) * max(1, vp))
    return dict(primary_voltage=vp, secondary_voltage=vs, primary_current=pi, secondary_current=si,
                loading_percent=load*100, losses_w=losses, voltage_pu=pu, event=event, load_pu=load,
                phase_current_a=phase_currents[0], phase_current_b=phase_currents[1], phase_current_c=phase_currents[2],
                neutral_current=neutral, phase_imbalance_percent=u*100 if si else 0.,
                max_phase_loading_percent=maximum_load*100, thermal_loading_percent=thermal_load*100,
                max_phase_load_pu=maximum_load, thermal_load_pu=thermal_load)


def reduce_demand(s, reduction_pct):
    """Shared intervention semantics: reduce requested demand, not fault current."""
    if not math.isfinite(reduction_pct) or not 0 <= reduction_pct <= 100:
        raise ValueError('Demand reduction must be between 0 and 100 percent.')
    s['inputs']['load_percent'] *= 1 - reduction_pct / 100
    return electrical(s)


def telemetry(s):
    e = electrical(s)
    return Telemetry(timestamp=stamp(s), source='industrial', transformer_id=s['id'],
                     **{k: e[k] for k in ('primary_voltage', 'secondary_voltage', 'primary_current', 'secondary_current', 'loading_percent', *PHASE_FIELDS)},
                     transformer_temperature=s['oil_c']+s['winding_rise_c']+(25 if e['event']=='sensor' else 0), temperature_kind='modelled_hotspot',
                     oil_temperature=s['oil_c'], hotspot_temperature=s['oil_c']+s['winding_rise_c'],
                     ambient_temperature=s['inputs']['ambient_c'], oil_level_percent=s['inputs']['oil_level_percent'],
                     oil_condition=s['inputs']['oil_condition'], gas_indicator=e['event']=='gas', event=e['event']).model_dump(mode='json')


def analyse(t, limits, previous=None, history_damage=0., oil_condition=None):
    """Shared threshold, temporal anomaly and health pipeline for both sources."""
    alerts = []
    def add(code, severity, parameter, value, threshold, text, anomaly=False):
        alerts.append(dict(code=code, severity=severity, parameter=parameter, value=value,
                           threshold=threshold, timestamp=t['timestamp'], detail=text,
                           category='trend_anomaly' if anomaly else 'threshold', action='Monitor / investigate'))
    if t['quality'] != 'qualified':
        add('data_quality', 'WARNING', 'quality', t['quality'], 'qualified', 'Fresh, calibrated measurements are required.')
        return dict(status='UNKNOWN', health_index=None, stress={}, alerts=alerts, maintenance=['Restore telemetry and verify channel calibration.'], trend_c_min=None)
    load, temp = t['loading_percent'], t['transformer_temperature']
    maximum_load = t.get('max_phase_loading_percent')
    imbalance = t.get('phase_imbalance_percent') or 0.
    load_parameter = 'max_phase_loading_percent' if imbalance else 'loading_percent'
    protective_load = maximum_load if imbalance and maximum_load is not None else load
    for name, value, levels in [(load_parameter, protective_load, ('load_warning','load_critical','load_trip')),
                                 ('transformer_temperature', temp, ('temperature_warning','temperature_critical','temperature_trip'))]:
        if value is None: continue
        for severity, key in reversed(list(zip(('WARNING','CRITICAL','TRIP'), levels))):
            if limits.get(key) is not None and value >= limits[key]:
                add(name, severity, name, value, limits[key], 'Maximum phase loading exceeds the configured level.' if name=='max_phase_loading_percent' else 'Loading exceeds the configured level.' if name=='loading_percent' else 'Thermal threshold exceeded.')
                break
    if imbalance >= PHASE_WARNING:
        severity = 'CRITICAL' if imbalance >= PHASE_CRITICAL else 'WARNING'
        add('phase_imbalance', severity, 'phase_imbalance_percent', imbalance,
            PHASE_CRITICAL if severity == 'CRITICAL' else PHASE_WARNING,
            'Illustrative fundamental current imbalance exceeds the review level; inspect phase allocation. Thresholds are demonstration assumptions.')
    nominal = limits.get('nominal_voltage')
    voltage = t['primary_voltage'] if t['source']=='industrial' else t['secondary_voltage']
    deviation = abs(voltage/nominal-1) if nominal and voltage is not None and not limits.get('isolated') else 0
    for severity, key in reversed(list(zip(('WARNING','CRITICAL','TRIP'),('voltage_warning_pu','voltage_critical_pu','voltage_trip_pu')))):
        if limits.get(key) is not None and deviation >= limits[key]:
            add('voltage', severity, 'voltage_deviation_pu', deviation, limits[key], 'Voltage outside the configured operating band.')
            break
    if t.get('oil_level_percent') is not None and t['oil_level_percent'] < 70:
        add('oil_level','TRIP' if t['oil_level_percent'] < 40 else 'WARNING','oil_level_percent',t['oil_level_percent'],70,'Simulated oil-level indication.')
    if t.get('gas_indicator'):
        add('gas','TRIP','gas_indicator',True,False,'Injected gas-relay indication; no measured gas concentration or DGA diagnosis.')
    if t.get('hotspot_temperature') is not None and temp is not None and abs(temp-t['hotspot_temperature'])>5:
        add('sensor_residual','WARNING','sensor_model_difference_c',temp-t['hotspot_temperature'],5,
            'Synthetic sensor channel disagrees with the independent simulated thermal state.',True)
    if t.get('ambient_temperature') is not None and t['ambient_temperature'] > 45:
        add('ambient','WARNING','ambient_temperature',t['ambient_temperature'],45,'High ambient temperature; review cooling capability.')
    slope = None
    if previous and previous.get('transformer_temperature') is not None and temp is not None:
        dt=(datetime.fromisoformat(t['timestamp'])-datetime.fromisoformat(previous['timestamp'])).total_seconds()/60
        if 0 < dt <= 10:
            slope=(temp-previous['transformer_temperature'])/dt
            same_load=load is not None and previous.get('loading_percent') is not None and abs(load-previous['loading_percent'])<3
            if same_load and slope>1:
                add('thermal_trend','WARNING','rise_c_min',slope,1,'Temperature is rising rapidly at nearly constant load; inspect cooling and verify the probe.',True)
            if voltage is not None and previous.get('primary_voltage' if t['source']=='industrial' else 'secondary_voltage'):
                before=previous['primary_voltage' if t['source']=='industrial' else 'secondary_voltage']
                if abs(voltage-before)/before>.08 and not limits.get('isolated'):
                    add('voltage_step','WARNING','voltage_step_pu',abs(voltage-before)/before,.08,'Abrupt voltage change compared with the preceding observation.',True)
            current=t['secondary_current']; old=previous.get('secondary_current')
            if same_load and current is not None and old and abs(current-old)/old>.25:
                add('current_residual','WARNING','current_step_pu',abs(current-old)/old,.25,'Current changed without a corresponding loading change.',True)
    # Imbalance contribution is a declared screening heuristic, not a standard or probability.
    stress={'electrical':min(100,max(deviation*200,imbalance*2)), 'loading':min(100,max(0,(protective_load or 0)-80)),
            'thermal':min(100,max(0,(temp or 0)-(limits.get('temperature_warning') or 110)+20)*2),
            'environmental':min(100,max(0,(t['ambient_temperature'] or 30)-35)*3),
            'historical':min(100,history_damage), 'oil':100-oil_condition if oil_condition is not None else 0}
    # Screening score, not failure probability. Historical stress persists after recovery.
    health=round(max(0,100-(.18*stress['electrical']+.2*stress['loading']+.22*stress['thermal']+
                           .05*stress['environmental']+.25*stress['historical']+.1*stress['oil'])),1)
    if load is None or temp is None: health=None
    severity=max(({'WARNING':1,'CRITICAL':2,'TRIP':3}[a['severity']] for a in alerts),default=0)
    maintenance=[]
    codes={a['code'] for a in alerts}
    if codes & {'sensor_residual','current_residual'}:
        maintenance.append('Verify the discrepant channel against an independent reference before relying on its forecast; inspect sensor wiring and calibration.')
    if codes & {'loading_percent','max_phase_loading_percent'}: maintenance.append('Review loading and compare a load-reduction study against the current thermal trajectory.')
    if 'phase_imbalance' in codes: maintenance.append('Review and rebalance phase allocation; reducing demand lowers current and heating but does not correct the phase-current ratio.')
    if codes & {'transformer_temperature','thermal_trend'}: maintenance.append('Inspect cooling and compare temperature against an independent reference.')
    if codes & {'voltage','voltage_step'}: maintenance.append('Inspect supply conditions and upstream surge protection.')
    if codes & {'oil_level','gas'} or (oil_condition is not None and oil_condition<70): maintenance.append('Arrange oil-system inspection and laboratory sampling; a model is not a lab result.')
    if history_damage>30: maintenance.append('Accumulated stress remains elevated: schedule a condition assessment even if current readings recover.')
    if 'ambient' in codes: maintenance.append('Confirm ambient conditions and review available cooling and loading margin.')
    if alerts and not maintenance: maintenance.append('Investigate the active signal and record an independent check before clearing it.')
    if not maintenance: maintenance=['Continue monitoring; no immediate action indicated by the available evidence.']
    return dict(status=('NORMAL','WARNING','CRITICAL','TRIP')[severity],health_index=health,operating_stress_index=health,stress=stress,
                alerts=alerts,maintenance=maintenance,trend_c_min=slope)


def evaluate(s, dt):
    t=telemetry(s);p=s['settings'];limits={**p,'nominal_voltage':p['primary_v'],'isolated':s['breaker']=='OPEN'}
    damage=min(100,s['equivalent_age_hours']/p['reference_life_hours']*100+s['historical_damage'])
    a=analyse(t,limits,s['previous_telemetry'],damage,s['inputs']['oil_condition'])
    codes={x['code'] for x in a['alerts']}
    for alert in a['alerts']:
        if alert['code'] not in s['prior_codes']:
            log(s,'alert',alert['detail'],alert['severity'],parameter=alert['parameter'],value=alert['value'],threshold=alert['threshold'])
            if alert['code'] in ('voltage','voltage_step'): s['electrical_events']+=1
    s['prior_codes']=sorted(codes)
    if s['breaker']=='CLOSED':
        s['critical_s']=s['critical_s']+dt if a['status'] in ('CRITICAL','TRIP') else 0
        if s['inputs']['protection_enabled'] and (a['status']=='TRIP' or s['critical_s']>=p['critical_delay_s']):
            causes=[x for x in a['alerts'] if x['severity'] in ('CRITICAL','TRIP')]
            trip(s,'; '.join(x['detail'] for x in causes),t,causes)
            t=telemetry(s)
    else:
        requested_max=s['inputs']['load_percent']*(1+s['inputs'].get('phase_imbalance_percent',0)/100)
        safe=(t['hotspot_temperature']<p['recovery_temperature'] and requested_max<p['load_warning']
              and (s['inputs']['load_percent']==0 or s['inputs'].get('phase_imbalance_percent',0)<PHASE_WARNING)
              and abs(electrical(s)['voltage_pu']-1)<p['voltage_warning_pu'] and not s['fault']
              and s['inputs']['cooling']=='normal' and s['inputs']['oil_level_percent']>=70)
        s['recovery_s']=s['recovery_s']+dt if safe else 0
    if s['electrical_events']>=3:
        a['maintenance'].append('Repeated electrical events: schedule an upstream protection review.')
    if s['overload_hours']>.25:
        a['maintenance'].append('Sustained or repeated overload exposure: review the operating schedule.')
    if s['breaker']=='OPEN':
        a['maintenance'].insert(0,'Investigate the latched trip and satisfy recovery checks before manual reconnection.'
                                  if not s['investigated'] else 'Review recovery holds before manually reconnecting the simulated transformer.')
    s['analysis']=a;s['telemetry']=t;s['previous_telemetry']=t
    add_forward_risk(s)
    if any(x['code']=='forecast_thermal' for x in a['alerts']):
        if 'forecast_thermal' not in codes and 'forecast_thermal' not in s.get('previous_advisories',[]):
            log(s,'forecast_warning',next(x['detail'] for x in a['alerts'] if x['code']=='forecast_thermal'),'WARNING')
        s['previous_advisories']=['forecast_thermal']
    else:s['previous_advisories']=[]


def add_forward_risk(s):
    """Advisory risk affects advice and closure, never protective trip timing."""
    a=s['analysis']
    a['alerts']=[x for x in a['alerts'] if x['code'] not in ('forecast_thermal','cooling_condition')]
    a['maintenance']=[x for x in a['maintenance'] if not x.startswith(('Act before the projected thermal limit','Cooling remains declared'))]
    prediction=forecast(s)
    minutes=prediction.get('minutes_to_critical')
    a['forward_risk']={'available':prediction.get('available',True),
                       'minutes_to_critical':minutes,'horizon_min':240,
                       'requires_action':minutes is not None}
    if minutes is not None:
        a['alerts'].append(dict(code='forecast_thermal',severity='WARNING',parameter='minutes_to_critical',
            value=minutes,threshold=240,timestamp=s['telemetry']['timestamp'],category='conditional_forecast',
            detail=f'Critical thermal limit projected in {minutes} min under unchanged inputs; review an intervention now.',
            action='Compare demand reduction and inspect cooling'))
        if a['status']=='NORMAL':a['status']='WARNING'
        a['maintenance'].insert(0,f'Act before the projected thermal limit in {minutes} min: compare demand reduction and arrange a cooling check. Reassess when inputs change.')
    if s['inputs']['cooling']!='normal':
        a['alerts'].append(dict(code='cooling_condition',severity='WARNING',parameter='declared_cooling',
            value=s['inputs']['cooling'],threshold='normal',timestamp=s['telemetry']['timestamp'],
            category='declared_scenario',detail='Cooling is declared impaired in this simulation; reduced loading is mitigation, not repair.',
            action='Retain a maintenance hold until cooling is restored'))
        if a['status']=='NORMAL':a['status']='WARNING'
        note='Cooling remains declared impaired: maintain reduced loading and arrange cooling service. This scenario setting is not an observation-only diagnosis.'
        if minutes is None:a['maintenance'].insert(0,note)
        else:a['maintenance'].append(note)
    if s['inputs']['oil_condition']<70 and a['status']=='NORMAL':
        a['status']='WARNING'
        a['alerts'].append(dict(code='oil_condition',severity='WARNING',parameter='oil_condition',
            value=s['inputs']['oil_condition'],threshold=70,timestamp=s['telemetry']['timestamp'],
            category='scenario_condition',detail='Oil-condition scenario needs assessment; this is not a measured oil test.',action='Arrange a condition assessment'))
        a['maintenance'].insert(0,'Arrange a condition assessment for the degraded oil-condition scenario; a real oil test is required to establish physical condition.')
    if a['status']!='NORMAL':
        a['maintenance']=[x for x in a['maintenance'] if not x.startswith('Continue monitoring; no immediate action')]
    # Keep the transparent stress arithmetic, but do not present it as confirmed
    # asset health when a known condition contradicts that interpretation.
    raw=a.get('operating_stress_index',a['health_index'])
    a['operating_stress_index']=raw
    holds=[x['code'] for x in a['alerts']]
    a['health_index']=None if holds or s['breaker']=='OPEN' else raw
    a['health_evidence']={'state':'review_required' if holds or s['breaker']=='OPEN' else 'screening_only',
        'holds':holds,'calibrated_failure_probability':False,
        'note':'Condition index withheld while operational or evidence holds remain. The separate stress score describes current readings and recorded history; it does not establish asset health.' if holds or s['breaker']=='OPEN' else 'Illustrative condition screening, not a calibrated failure probability or certification of health.'}


def trip(s, reason, before=None, rules=None):
    if s['breaker']=='OPEN': return
    before=before or telemetry(s)
    s['breaker']='OPEN';s['trip_count']+=1;s['investigated']=False;s['recovery_s']=0
    s['historical_damage']=min(100,s['historical_damage']+2)
    s['trip']={'timestamp':stamp(s),'reason':reason,'rules':rules or [],'before':before,'after':telemetry(s)}
    log(s,'trip',reason,'TRIP',before=before,after=s['trip']['after'],rules=rules or [],action='Simulated breaker opened; no physical command')


def remember(s):
    t=s['telemetry'];s['history'].append(deepcopy({**t,'health_index':s['analysis']['health_index'],
                                        'breaker':s['breaker'],'elapsed_s':s['elapsed_s'],
                                        'status':s['analysis']['status'],'equivalent_age_hours':s['equivalent_age_hours'],
                                        'input_signature':input_signature(s),
                                        'channel_qualified':not any(a['code']=='sensor_residual' for a in s['analysis']['alerts']),
                                        'history_version':'synchronized-twin-1','component_data_available':True,
                                        'event_cursor':len(s['events']),
                                        'analysis':s['analysis'],'inputs':s['inputs'],'settings':s['settings'],
                                        'prediction':forecast(s),
                                        'input_context':{k:s.get(k) for k in ('id','revision','inputs','settings','breaker','fault','scenario','running','trip','profile')},
                                        'phase_model':PHASE_MODEL}))


def history_view(rows):
    """Return recorded evidence only; never infer old component scores from today's inputs."""
    result=deepcopy(rows)
    for row in result:
        if row.get('history_version')!='synchronized-twin-1' or not isinstance(row.get('analysis'),dict):
            row.update(component_data_available=False, analysis=None,
                       component_data_note='Component analysis and input context were not retained for this legacy observation.')
    return result


def input_signature(s):
    """Operating assumptions, excluding clock speed and accumulated oil ageing."""
    values={k:s['inputs'][k] for k in ('load_percent','voltage_pu','ambient_c','cooling','oil_level_percent')}
    # Keep signatures of existing balanced proofs compatible with the zero default.
    if s['inputs'].get('phase_imbalance_percent',0):values['phase_imbalance_percent']=s['inputs']['phase_imbalance_percent']
    effective=electrical(s)
    values.update(breaker=s['breaker'],event=effective['event'],model_settings=s['settings'],
                  effective_load_pu=effective['load_pu'],effective_voltage_pu=effective['voltage_pu'])
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def advance(s, seconds):
    if not s['running']: raise ValueError('Start the simulation before advancing time.')
    if len(s['history'])+math.ceil(seconds/60)+1>5000: raise ValueError('Session history is full. Export it and create a new run.')
    target=s['elapsed_s']+seconds;next_record=s['elapsed_s']+60
    while s['elapsed_s']<target:
        dt=min(5,target-s['elapsed_s']);p=s['settings'];i=s['inputs'];e=electrical(s)
        cooling={'normal':1.,'degraded':.6,'failed':.3}[i['cooling']]
        if s['fault'] and s['fault']['kind'] in ('cooling','combined'):cooling=.3
        load=e['max_phase_load_pu'];ratio=e['losses_w']/(p['core_loss_w']+p['copper_loss_w'])
        oil_target=i['ambient_c']+p['rated_oil_rise_c']*ratio**.8/cooling
        winding_target=p['rated_winding_rise_c']*load**1.6
        if e['event'] in ('thermal','combined') and s['breaker']=='CLOSED': oil_target+=70
        s['oil_c']+=(oil_target-s['oil_c'])*(1-math.exp(-dt/(60*p['oil_tau_min'])))
        s['winding_rise_c']+=(winding_target-s['winding_rise_c'])*(1-math.exp(-dt/(60*p['winding_tau_min'])))
        hotspot=s['oil_c']+s['winding_rise_c']
        acceleration=math.exp(min(20,15000/383.15-15000/(hotspot+273.15)))
        s['equivalent_age_hours']+=acceleration*dt/3600
        s['overload_hours']+=(dt/3600 if load>1 else 0)
        i['oil_condition']=max(0,i['oil_condition']-max(0,hotspot-100)*dt/3600*.001)
        s['elapsed_s']+=dt
        if s['fault'] and s['elapsed_s']>=s['fault']['until_s']:
            log(s,'fault_cleared','Injected disturbance duration ended. Trip latch is retained.');s['fault']=None
        evaluate(s,dt)
        if s['elapsed_s']>=next_record or s['elapsed_s']==target:remember(s);next_record=s['elapsed_s']+60


def inject(s, kind, severity=2, duration_s=120):
    if kind not in FAULTS:raise ValueError('Unknown fault.')
    s['fault']={'kind':kind,'severity':severity,'until_s':s['elapsed_s']+duration_s}
    s['fault_count']+=1
    if kind=='low_oil':s['inputs']['oil_level_percent']=30
    s['historical_damage']=min(100,s['historical_damage']+.5*severity)
    log(s,'fault_injected',f'{kind.replace("_"," ")} · severity {severity} · {duration_s:g} simulated seconds',fault=deepcopy(s['fault']))
    evaluate(s,0);remember(s)


def recovery_holds(s):
    if s['breaker']!='OPEN':return ['The simulated breaker is already closed.']
    holds=[]
    if not s['investigated']:holds.append('Record a fault investigation after the latest trip.')
    if s['fault']:holds.append('Clear the active disturbance.')
    if s['inputs']['cooling']!='normal':holds.append('Restore cooling.')
    if s['inputs']['load_percent']*(1+s['inputs'].get('phase_imbalance_percent',0)/100)>=s['settings']['load_warning']:holds.append('Reduce requested maximum phase loading below the warning threshold.')
    if s['inputs']['load_percent'] and s['inputs'].get('phase_imbalance_percent',0)>=PHASE_WARNING:holds.append('Rebalance requested phase currents below the illustrative warning threshold.')
    if s['recovery_s']<s['settings']['recovery_hold_s']:holds.append('Hold voltage, temperature, oil level and loading inside recovery limits.')
    return holds


def maintain(s, action, note):
    if action not in MAINTENANCE:raise ValueError('Unknown maintenance action.')
    if action in ('oil_service','cooling_service') and s['breaker']!='OPEN':raise ValueError('Isolate the simulated transformer before servicing it.')
    before={'oil_condition':s['inputs']['oil_condition'],'cooling':s['inputs']['cooling']}
    if action=='fault_investigation':s['investigated']=s['breaker']=='OPEN'
    if action=='cooling_service':s['inputs']['cooling']='normal'
    if action=='oil_service':s['inputs']['oil_condition']=95;s['inputs']['oil_level_percent']=100
    log(s,'maintenance',note,maintenance_action=action,before=before,
        after={'oil_condition':s['inputs']['oil_condition'],'cooling':s['inputs']['cooling']})
    # No maintenance action erases insulation ageing or prior event history.
    evaluate(s,0);remember(s)


def summary(s):
    # Rebuild advice on reads of historical runs without rewriting their evidence.
    s=deepcopy(s)
    s['analysis']['alerts']=[a for a in s['analysis']['alerts'] if a['code']!='forecast_thermal']
    add_forward_risk(s)
    a=s['analysis'];p=s['settings'];t=s['telemetry']
    acceleration=math.exp(min(20,15000/383.15-15000/(t['hotspot_temperature']+273.15)))
    remaining=max(0,p['reference_life_hours']-s['equivalent_age_hours'])
    band='Unavailable' if a['health_index'] is None else 'Watch' if a['health_index']>=p['health_watch'] else 'Degraded' if a['health_index']>=p['health_degraded'] else 'High risk' if a['health_index']>=p['health_high_risk'] else 'Critical'
    if a['health_index'] is not None and a['health_index']>=90:band='Healthy'
    # A screening number must never override an active operational warning.
    if a['status'] in ('WARNING','CRITICAL','TRIP'):band=a['status'].title()+' · review signals'
    if s['breaker']=='OPEN':band='Trip review required'
    return {**{k:deepcopy(s[k]) for k in ('id','source','revision','started_at','elapsed_s','running','scenario','settings','inputs','fault','breaker','trip','trip_count','fault_count','telemetry','analysis')},
            'history':history_view(s['history'][-240:]),'events':s['events'][-100:],'history_count':len(s['history']),
            'protection_state':'ISOLATED' if s['breaker']=='OPEN' else 'ARMED' if s['inputs']['protection_enabled'] else 'DISABLED · simulation only',
            'health_band':band,'recovery_holds':recovery_holds(s),
            'profile':deepcopy(s.get('profile',{'name':'Illustrative distribution transformer','basis':'illustrative','reference':'No manufacturer test sheet supplied','reviewer':'Unreviewed'})),
            'prediction':forecast(s),'phase_model':deepcopy(PHASE_MODEL),
            'condition':{'equivalent_age_hours':s['equivalent_age_hours'],'overload_hours':s['overload_hours'],
                         'insulation_consumed_percent':100*s['equivalent_age_hours']/p['reference_life_hours'],
                         'ageing_acceleration':acceleration,'conditional_life_years':remaining/max(1e-9,acceleration)/8760,
                         'life_note':'Hypothetical thermal budget at constant modelled hot-spot; not actual remaining useful life.'},
            'assumptions':['Balanced three-phase voltage, fundamental RMS constant-current demand, unity power factor; illustrative phase amplitudes [1+u, 1, 1-u], no harmonics. All ratings are illustrative.',
                           'First-order oil and winding thermal states; gas and oil condition are scenario variables, not chemistry or DGA.',
                           'No electromagnetic transient model: surge and short circuit are supervisory RMS scenarios.',
                           'Health is a transparent screening score. Simulated isolation is not a declaration of electrical safety.']}


def forecast(s):
    """Conditional unprotected trajectory; no historical data or state is modified."""
    p=s['settings'];i=s['inputs'];e=electrical(s)
    if any(a['code']=='sensor_residual' for a in s['analysis']['alerts']):
        return {'minutes_to_critical':None,'available':False,'note':'Forecast withheld: verify the discrepant temperature channel against an independent reference.'}
    if s['breaker']=='OPEN':return {'minutes_to_critical':None,'note':'Breaker open; recovery is assessed from the cooling state.'}
    cooling={'normal':1.,'degraded':.6,'failed':.3}[i['cooling']]
    if e['event'] in ('cooling','combined'):cooling=.3
    target=i['ambient_c']+p['rated_oil_rise_c']*(e['losses_w']/(p['core_loss_w']+p['copper_loss_w']))**.8/cooling
    if e['event'] in ('thermal','combined'):target+=70
    winding=p['rated_winding_rise_c']*e['max_phase_load_pu']**1.6
    crossing=None
    for minute in range(241):
        temp=target+(s['oil_c']-target)*math.exp(-minute/p['oil_tau_min'])+winding+(s['winding_rise_c']-winding)*math.exp(-minute/p['winding_tau_min'])
        if temp>=p['temperature_critical']:crossing=minute;break
    return {'minutes_to_critical':crossing,'horizon_min':240,
            'note':'Conditional hot-spot projection: present load, ambient, cooling and fault held constant; protection ignored. Not a failure forecast.'}
