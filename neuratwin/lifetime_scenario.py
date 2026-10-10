"""Read-only thermal-ageing scenarios, not measured life or calibrated failure risk."""
from datetime import datetime
import math
from pydantic import Field, model_validator
from .halo_contracts import Contract

VERSION = 'lifetime-scenario-1'
YEAR_HOURS = 365.25 * 24


class Assumptions(Contract):
    model_config={**Contract.model_config,'validate_default':True}
    reference_life_years: float = Field(20, ge=1, le=100)
    initial_equivalent_age_years: float = Field(5, ge=0, le=200)
    weibull_shape: float = Field(3, ge=1.01, le=8)
    reference_temperature_c: float = Field(60, ge=20, le=150)
    temperature_offset_c: float = Field(20, ge=0, le=80)
    doubling_c: float = Field(10, ge=3, le=30)
    minimum_ageing_rate: float = Field(.25, ge=.01, le=1)
    ambient_c: float = Field(30, ge=-20, le=60)
    rated_rise_c: float = Field(25, gt=0, le=150)
    thermal_tau_min: float = Field(15, ge=1, le=1440)
    limit_temperature_c: float = Field(55, ge=0, le=200)
    rated_current_a: float = Field(1, gt=0, le=100000)
    nominal_voltage_v: float = Field(12, gt=0, le=100000)
    recent_window_s: float = Field(300, ge=10, le=3600)
    maximum_gap_s: float = Field(10, ge=1, le=300)
    risk_horizon_days: int = Field(365, ge=1, le=3650)

    @model_validator(mode='after')
    def thermal_limits(self):
        if self.limit_temperature_c <= self.ambient_c:
            raise ValueError('Temperature limit must exceed assumed ambient.')
        return self


def defaults(mode, settings=None):
    p=settings or {}
    if mode=='industrial':
        return Assumptions(reference_temperature_c=98,temperature_offset_c=0,
            rated_rise_c=p.get('rated_oil_rise_c',55)+p.get('rated_winding_rise_c',23),
            thermal_tau_min=p.get('oil_tau_min',120),limit_temperature_c=p.get('temperature_critical',125),
            rated_current_a=p.get('rated_kva',630)*1000/(math.sqrt(3)*p.get('secondary_v',433)),
            nominal_voltage_v=p.get('secondary_v',433),maximum_gap_s=65)
    return Assumptions()


def numeric(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)


def from_display(sample):
    if not sample:return None
    channels=sample['channels'];temperature=channels['surface_temperature']['value']
    if temperature is None and sample.get('probe_valid'):
        temperature=channels['surface_temperature']['raw']
    return {'timestamp':sample['timestamp'],'sample_key':str(sample.get('boot_id'))+':'+str(sample.get('sequence')),
        'boot_id':sample.get('boot_id'),'temperature_c':temperature,
        'current_a':channels['secondary_current']['value'],'voltage_v':channels['secondary_voltage']['value'],
        'current_source':channels['secondary_current']['source'],'quality':sample['quality'],
        'source':'client-submitted prototype display; surface temperature'}


def from_industrial(row):
    return {'timestamp':row['timestamp'],'sample_key':row['timestamp'],
        'boot_id':'industrial','temperature_c':row.get('hotspot_temperature'),
        'current_a':row.get('secondary_current'),'voltage_v':row.get('secondary_voltage'),
        'current_source':'industrial simulation','quality':row.get('quality'),'source':'industrial modelled hot-spot'}


def assess(observations, assumptions, *, mode, source_status):
    a=assumptions; unique={}
    for row in observations:
        if row and row.get('timestamp'):
            time=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')).timestamp()
            unique[row['sample_key']]={**row,'time':time}
    rows=sorted(unique.values(),key=lambda r:r['time'])
    out={'version':VERSION,'mode':mode,'source_status':source_status,'assumptions':a.model_dump(),
        'available':False,'condition_score':None,'condition_components':{},'minutes_to_limit':None,
        'limit_state':'unavailable','remaining_life_years':None,'life_state':'unavailable',
        'failure_probability':None,'risk_horizon_days':a.risk_horizon_days,'risk_curve':[],
        'temperature_curve':[],'reasons':[],
        'scope':'Assumption-driven thermal-ageing scenario; not measured RUL or calibrated all-cause failure probability.',
        'life_definition':'Conditional Weibull median, advanced by modelled equivalent ageing; reference life is the characteristic scale, not a guaranteed lifespan.',
        'coverage_note':'Only supplied intervals are integrated. Gaps and unknown prior exposure are not filled; initial equivalent age is an assumption.',
        'temperature_basis':'Surface + assumed offset; not a measured winding hot-spot' if mode=='prototype' else 'Industrial modelled hot-spot',
        'future_basis':'Recent mean-square current held constant; assumed ambient, rated rise and first-order thermal time constant.'}
    if not rows:out['reasons']=['Waiting for recorded readings.'];return out
    last=rows[-1];out['basis_timestamp']=last['timestamp']
    out['current_sources']=sorted({r['current_source'] for r in rows})
    def rate(t):return min(1024.,max(a.minimum_ageing_rate,2**max(-30,min(30,(t+a.temperature_offset_c-a.reference_temperature_c)/a.doubling_c))))
    covered=0.;age=0.;skipped=0.;overload_s=0.;sums={'current_a':0.,'voltage_v':0.,'temperature_c':0.};weights={k:0. for k in sums}
    recent=[r for r in rows if r['time']>=last['time']-a.recent_window_s]
    for before,after in zip(rows,rows[1:]):
        dt=after['time']-before['time']
        if dt<=0:continue
        if dt>a.maximum_gap_s or before['boot_id']!=after['boot_id']:
            skipped+=dt;continue
        if all(numeric(r['temperature_c']) for r in (before,after)):
            age+=dt/3600*(rate(before['temperature_c'])+rate(after['temperature_c']))/2;covered+=dt
        w=max(0.,after['time']-max(before['time'],last['time']-a.recent_window_s))
        if not w:continue
        if numeric(before['current_a']) and before['current_a']>a.rated_current_a:overload_s+=w
        for k in sums:
            if all(numeric(r[k]) for r in (before,after)):
                power=2 if k=='current_a' else 1
                sums[k]+=w*(before[k]**power+after[k]**power)/2;weights[k]+=w
    averages={k:(sums[k]/weights[k])**(.5 if k=='current_a' else 1) if weights[k] else last[k] for k in sums}
    # Missing latest channels cannot be replaced by an earlier average.
    for k in averages:
        if not numeric(last[k]):averages[k]=None
    peaks={k:max((r[k] for r in recent if numeric(r[k])),default=None) for k in sums}
    out['observations']={'samples':len(rows),'first':rows[0]['timestamp'],'last':last['timestamp'],
        'integrated_seconds':covered,'skipped_gap_seconds':skipped,'observed_equivalent_age_hours':age,
        'recent_averages':averages,'recent_peaks':peaks,'recent_overload_seconds':overload_s,
        'recent_covered_seconds':weights,'average_method':'Time-weighted endpoints; root mean square current retains heating contribution. A single sample is instantaneous.'}
    missing=[k for k,v in averages.items() if v is None]
    if missing:out['reasons']=['Missing current observation: '+', '.join(missing)];return out
    clamp=lambda v:max(0,min(100,v))
    load=averages['current_a']/a.rated_current_a
    components={'loading':clamp((peaks['current_a']/a.rated_current_a-.8)/.7*100),
        'temperature':clamp((peaks['temperature_c']-(a.limit_temperature_c-20))/20*100),
        'voltage':clamp(max(abs(r['voltage_v']/a.nominal_voltage_v-1) for r in recent if numeric(r['voltage_v']))/.2*100)}
    out['condition_components']={k:{'stress':v,'weight':w} for (k,v),w in zip(components.items(),(.35,.45,.2))}
    out['condition_score']=100-sum(v['stress']*v['weight'] for v in out['condition_components'].values())
    if peaks['current_a']/a.rated_current_a>3:
        out['reasons']=['Current exceeds the 3 pu thermal-scenario domain; electrical faults need separate diagnosis.'];return out
    t0=last['temperature_c'];equilibrium=a.ambient_c+a.rated_rise_c*load**2;tau=a.thermal_tau_min/60
    if equilibrium>250 or t0>250 or t0 < -55:
        out['reasons']=['Temperature exceeds the scenario model domain.'];return out
    temperature=lambda h:equilibrium+(t0-equilibrium)*math.exp(-h/tau)
    out['temperature_curve']=[{'minute':m,'temperature_c':temperature(m/60)} for m in range(0,241,5)]
    out['equilibrium_temperature_c']=equilibrium
    out['limit_state']='no_crossing'
    if t0>=a.limit_temperature_c:out.update(minutes_to_limit=0.,limit_state='already_reached')
    elif equilibrium>a.limit_temperature_c:
        crossing=-a.thermal_tau_min*math.log((a.limit_temperature_c-equilibrium)/(t0-equilibrium))
        out.update(minutes_to_limit=crossing if crossing<=240 else None,limit_state='crossing' if crossing<=240 else 'beyond_horizon')
    effective=a.initial_equivalent_age_years*YEAR_HOURS+age
    scale=a.reference_life_years*YEAR_HOURS;shape=a.weibull_shape
    # Resolve the initial thermal transient, then continue the steady exposure.
    dt=10*tau/240;curve=[(0.,0.)];previous_rate=rate(t0)
    for i in range(1,241):
        value=rate(temperature(i*dt));curve.append((i*dt,curve[-1][1]+dt*(previous_rate+value)/2));previous_rate=value
    steady=rate(equilibrium)
    def exposure(hours):
        if hours>=curve[-1][0]:return curve[-1][1]+(hours-curve[-1][0])*steady
        i=min(239,int(hours/dt));x,y=curve[i];return y+(hours-x)/dt*(curve[i+1][1]-y)
    def clock_for(exposure_hours):
        for (x,y),(xx,yy) in zip(curve,curve[1:]):
            if exposure_hours<=yy:return x+(exposure_hours-y)/(yy-y)*(xx-x)
        return curve[-1][0]+(exposure_hours-curve[-1][1])/steady
    def probability(days):
        delta=((effective+exposure(days*24))/scale)**shape-(effective/scale)**shape
        return -math.expm1(-max(0,delta))
    median_budget=scale*((effective/scale)**shape+math.log(2))**(1/shape)-effective
    median=clock_for(median_budget)/YEAR_HOURS
    out.update(available=True,remaining_life_years=median if median<=50 else None,life_state='estimated' if median<=50 else 'beyond_horizon',
        failure_probability=probability(a.risk_horizon_days),effective_age_years=effective/YEAR_HOURS,
        projected_steady_ageing_rate=steady,reference_budget_remaining_hours=max(0,scale-effective),
        risk_curve=[{'days':d,'probability':probability(d)} for d in sorted(set([0,30,90,180,365,730,a.risk_horizon_days]))])
    return out
