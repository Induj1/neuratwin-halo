"""Inspectable synthetic experiments. No device control or field qualification.

Challenge observations use the independent three-node plant; diagnosis receives
only observations and deliberately requested checks, never the injection schedule.
Planning uses the separate two-state thermal model and a parameter sensitivity
envelope. Network screening is balanced, steady state, constant-PQ radial flow.
"""
from functools import lru_cache
import math
from typing import Literal
import numpy as np
from pydantic import Field, model_validator
from .halo_contracts import Contract
from .domain import Asset
from .thermal import ThermalState, step
from .simulation import plant_step

NOTICE = 'Synthetic distribution study only. No equipment commands; no field-validated capacity or failure probability.'
MODEL = Asset(asset_id='ARENA-DT', name='Arena study transformer', location='Synthetic neighbourhood', rated_kva=100)


class Knot(Contract):
    minute: int = Field(ge=0, le=120)
    load_pu: float = Field(ge=0, le=2)
    ambient_c: float = Field(ge=-10, le=50)


class Study(Contract):
    profile: list[Knot] = Field(default_factory=lambda: [Knot(minute=m, load_pu=k, ambient_c=a) for m,k,a in [(0,1.05,30),(15,1.65,33),(30,1.5,35),(60,1.,31)]], min_length=2, max_length=12)
    initial_oil_c: float = Field(default=70, ge=0, le=125)
    initial_gradient_c: float = Field(default=20, ge=0, le=50)
    reduction_pct: float = Field(default=15, ge=0, le=60)
    delay_min: int = Field(default=15, ge=0, le=120)
    load_limit_pu: float = Field(default=1.5, ge=.5, le=2)
    room_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{24}$')

    @model_validator(mode='after')
    def ordered(self):
        minutes=[p.minute for p in self.profile]
        if minutes[0]!=0 or minutes[-1]<15 or any(b<=a for a,b in zip(minutes, minutes[1:])):
            raise ValueError('Profile must start at zero, end at 15–120 minutes and have strictly increasing times.')
        if self.delay_min>minutes[-1]: raise ValueError('Delay must not exceed the study horizon.')
        return self


def profile_at(study, minute):
    points=study.profile
    for a,b in zip(points,points[1:]):
        if minute<=b.minute:
            f=(minute-a.minute)/(b.minute-a.minute)
            return a.load_pu+(b.load_pu-a.load_pu)*f, a.ambient_c+(b.ambient_c-a.ambient_c)*f
    return points[-1].load_pu,points[-1].ambient_c


def trajectory(study, reduction=0, delay=0, extra=0, horizon=None):
    horizon=horizon or study.profile[-1].minute
    variants=[MODEL.model_copy(update={'rated_oil_rise_c':MODEL.rated_oil_rise_c*f,
              'rated_winding_gradient_c':MODEL.rated_winding_gradient_c*f,'oil_tau_min':MODEL.oil_tau_min/f}) for f in (.9,1.,1.1)]
    states=[ThermalState(study.initial_oil_c,study.initial_gradient_c) for _ in variants]
    rows=[]; curtailment=0.;raw_hot=[];raw_oil=[];raw_load=[]
    for minute in range(horizon+1):
        baseline,ambient=profile_at(study,minute)
        # Minute zero is the shared observation, not an already realised intervention.
        load=(baseline+extra)*(1-reduction/100 if minute>delay else 1)
        if minute:
            states=[step(asset,state,load,ambient,1) for asset,state in zip(variants,states)]
            curtailment+=(baseline+extra-load)*MODEL.rated_kva*.95/60
            raw_load.append(load)
        raw_hot.append(max(s.hotspot_c for s in states));raw_oil.append(max(s.oil_c for s in states))
        rows.append({'minute':minute,'load_pu':round(load,5),'ambient_c':round(ambient,3),
                     'oil_c':round(states[1].oil_c,3),'hotspot_c':round(states[1].hotspot_c,3),
                     'low_c':round(min(s.hotspot_c for s in states),3),'high_c':round(max(s.hotspot_c for s in states),3),
                     'oil_high_c':round(max(s.oil_c for s in states),3)})
    # Screen unrounded values to avoid boundary acceptance caused by display rounding.
    max_hot=max(raw_hot);max_oil=max(raw_oil);max_load=max(raw_load)
    violations=[]
    if max_hot>=MODEL.hotspot_limit_c:violations.append('hot-spot sensitivity bound')
    if max_oil>=MODEL.oil_limit_c:violations.append('oil-temperature sensitivity bound')
    if max_load>study.load_limit_pu:violations.append('declared load limit')
    return {'rows':rows,'reduction_pct':reduction,'delay_min':delay,'passes':not violations,'violations':violations,
            'peak_hotspot_c':max(r['hotspot_c'] for r in rows),'peak_upper_c':max_hot,'peak_load_pu':max_load,
            'first_limit_min':next((i for i in range(horizon+1) if raw_hot[i]>=MODEL.hotspot_limit_c or raw_oil[i]>=MODEL.oil_limit_c or (i>0 and raw_load[i-1]>study.load_limit_pu)),None),
            'curtailed_kwh':round(curtailment,3)}


def study_metadata(study):
    return {'notice':NOTICE,'inputs':study.model_dump(),'model':MODEL.model_dump(),
            'assumptions':['Piecewise-linear load and ambient profiles; one-minute integration.',
              'Three parameter variants: 0.9 / 1.0 / 1.1. Bounds are sensitivity, not confidence intervals.',
              '100 kVA study rating; fixed power factor 0.95 for curtailed energy.',
              'Load-limit setting is an experiment constraint, not permission to exceed a real nameplate.',
              'Initial oil and winding gradient are declared synthetic inputs.']}


def futures(study):
    baseline=trajectory(study);operator=trajectory(study,study.reduction_pct,study.delay_min)
    planner=None;searched=0
    for reduction in range(0,61,5):
        candidate=trajectory(study,reduction,0);searched+=1
        if candidate['passes']:
            planner=candidate;break
    return {**study_metadata(study),'baseline':baseline,'operator':operator,'planner':planner,'searched':searched,
            'planner_method':'Smallest immediate reduction passing all three declared constraints, in 5% steps from 0 to 60%. No feasible candidate is a valid result.'}


def capacity(study):
    result=[];horizon=study.profile[-1].minute
    for span in sorted(set([min(horizon,h) for h in (15,30,60,90,120)])):
        base=trajectory(study,horizon=span)
        if not base['passes']:
            result.append({'horizon_min':span,'extra_load_pu':0.,'extra_kva':0.,'status':'Base profile violates constraints','binding':base['violations'],'peak_upper_c':base['peak_upper_c']});continue
        lo=0.;hi=2.
        for _ in range(16):
            mid=(lo+hi)/2
            if trajectory(study,extra=mid,horizon=span)['passes']:lo=mid
            else:hi=mid
        boundary=trajectory(study,extra=hi,horizon=span)
        result.append({'horizon_min':span,'extra_load_pu':round(lo,4),'extra_kva':round(lo*100,2),'status':'Conditional model headroom',
                       'binding':boundary['violations'],'peak_upper_c':trajectory(study,extra=lo,horizon=span)['peak_upper_c']})
    return {**study_metadata(study),'rows':result,'definition':'Extra constant apparent load added to every future profile point, with no intervention. Initial temperature is unchanged. No equipment rating is changed.'}


class NetworkStudy(Contract):
    demand_scale: float = Field(default=1.3, ge=.5, le=2)
    outage: Literal['none','A','B','C'] = 'none'
    transfer_allowed: bool = True
    room_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{24}$')


def radial_bus(p_kw, rating_kva):
    """One radial transformer+line branch on a common 100 kVA / 415 V base.

    Constant PQ is delivered at the load bus. Returned source power includes
    I²Z losses. Fixed-point complex voltage iteration is checked explicitly.
    """
    q=p_kw*math.tan(math.acos(.95));s=complex(p_kw,q)/100
    z=complex(.02,.04)*(100/rating_kva)+complex(.01,.01)
    v=complex(1);converged=False
    for _ in range(80):
        if abs(v)<.2:break
        current=(s/v).conjugate();new=1-z*current
        if abs(new-v)<1e-10:v=new;converged=True;break
        v=new
    current=(s/v).conjugate() if abs(v)>.01 else complex(100)
    source=current.conjugate()*100
    return {'voltage_pu':abs(v),'source_kva':abs(source),'source_kw':source.real,'source_kvar':source.imag,'load_kw':p_kw,
            'loss_kw':abs(current)**2*z.real*100,'current_a':abs(current)*100000/(math.sqrt(3)*415),'converged':converged}


def neighbourhood(request):
    scale=request.demand_scale
    # Clinic is fixed on A; only the named 20 kW workshop block may transfer.
    demand={'A':25+55*scale,'B':45*scale,'C':35*scale};ratings={'A':100,'B':100,'C':80}
    flex={'A':55*scale,'B':45*scale,'C':35*scale}
    thermal_cache={}
    def evaluate(cuts,transfer):
        loads={k:demand[k]-flex[k]*cuts[i] for i,k in enumerate(demand)}
        moved=0.
        if transfer!='none':
            moved=min(20.,flex['A']*(1-cuts[0]));loads['A']-=moved;loads[transfer]+=moved
        unserved=sum(flex[k]*cuts[i] for i,k in enumerate(demand));clinic=25.
        if request.outage!='none':
            unserved+=loads[request.outage];loads[request.outage]=0
            if request.outage=='A':clinic=0.
        buses=[];violations=[]
        for key,kw in loads.items():
            row=radial_bus(kw,ratings[key]);load=row['source_kva']/ratings[key]
            cache_key=(key,round(load,8))
            if cache_key not in thermal_cache:
                st=Study(profile=[Knot(minute=0,load_pu=load,ambient_c=32),Knot(minute=30,load_pu=load,ambient_c=32)], initial_oil_c=70,initial_gradient_c=20,delay_min=0,load_limit_pu=2)
                # Candidates outside the contract cannot be thermally qualified.
                thermal_cache[cache_key]=trajectory(st)['peak_upper_c']
            peak=thermal_cache[cache_key]
            reasons=[]
            if not row['converged']:reasons.append('power-flow convergence')
            if request.outage!=key and not .95<=row['voltage_pu']<=1.05:reasons.append('bus voltage')
            if row['source_kva']>ratings[key]:reasons.append('transformer nameplate')
            if row['current_a']>160:reasons.append('160 A branch limit')
            if peak>=120:reasons.append('30-minute thermal bound')
            violations.extend(f'{key}: {r}' for r in reasons)
            buses.append({'id':key,'rating_kva':ratings[key],**row,'voltage_pu':row['voltage_pu'] if request.outage!=key else 0.,
                          'energized':request.outage!=key,'peak_upper_c':peak,'violations':reasons})
        source=abs(sum(complex(b['source_kw'],b['source_kvar']) for b in buses))
        if source>250:violations.append('250 kVA shared source limit')
        if clinic<25:violations.append('Clinic cannot be fully supplied on the declared topology')
        return {'buses':buses,'source_kva':source,'served_kw':sum(loads.values()),'unserved_kw':unserved,'clinic_served_kw':clinic,
                'loss_kw':sum(b['loss_kw'] for b in buses),'violations':violations,'passes':not violations,
                'cuts_pct':[int(c*100) for c in cuts],'transfer_to':transfer,'transferred_kw':moved}
    baseline=evaluate((0,0,0),'none');best=None;count=0;passing=0
    destinations=['none']+([k for k in ('B','C') if k!=request.outage] if request.transfer_allowed and request.outage!='A' else [])
    for a in (0,.25,.5,.75,1.):
        for b in (0,.5,1.):
            for c in (0,.5,1.):
                for destination in destinations:
                    result=evaluate((a,b,c),destination);count+=1
                    if result['passes']:
                        passing+=1
                        if best is None or (result['unserved_kw'],result['loss_kw'])<(best['unserved_kw'],best['loss_kw']):best=result
    return {'notice':NOTICE,'inputs':request.model_dump(),'demand_kw':demand,'baseline':baseline,'plan':best,'candidates':count,'passing':passing,
            'method':'Enumerate A curtailment 0/25/50/75/100%, B/C 0/50/100%, and a permitted workshop transfer. Minimise unserved kW, then losses. Clinic demand cannot be curtailed.',
            'assumptions':['Balanced radial AC constant-PQ load flow; power factor 0.95; fixed 1.0 pu source.',
              'Common base: 100 kVA, 415 V line-line. Transformer Z=(0.02+j0.04) pu on own rating; each line Z=(0.01+j0.01) pu on common base.',
              'A/B/C ratings 100/100/80 kVA; each branch 160 A; source 250 kVA; bus voltage 0.95–1.05 pu.',
              'Thermal screening: 30 minutes, ambient 32°C, initial oil 70°C, initial gradient 20°C; shared illustrative thermal parameters.',
              'Only workshop load may transfer A→B or A→C, maximum 20 kW, via assumed isolated break-before-make alternative supply. No parallel ties.',
              'No transient, unbalanced, protection-coordination or real switching study. Outage A cannot restore clinic on this topology.']}


class Injection(Contract):
    kind: Literal['overload','cooling','bias','dropout']
    start: int = Field(ge=1, le=119)
    duration: int = Field(ge=1, le=60)
    severity: float = Field(ge=.1, le=1)

    @model_validator(mode='after')
    def end(self):
        if self.start+self.duration>121:raise ValueError('Disturbance must end by minute 120.')
        return self


@lru_cache(maxsize=64)
def initial_plant(seed):
    scale=1+(seed%11-5)*.003
    state=np.array([72.,61.,53.])
    for _ in range(1500):state=plant_step(state,.76,29,scale=scale)
    return tuple(float(x) for x in state),scale


def challenge_rows(seed, events, cursor):
    initial,scale=initial_plant(seed);actual=np.array(initial);reference=np.array(initial);rows=[];checks={}
    rng=np.random.default_rng(seed)
    for minute in range(cursor+1):
        active=[e for e in events if e['start']<=minute<e['start']+e['duration']]
        overload=min(1.,sum(e['severity'] for e in active if e['kind']=='overload'))
        cooling=min(1.,sum(e['severity'] for e in active if e['kind']=='cooling'))
        bias=min(1.,sum(e['severity'] for e in active if e['kind']=='bias'))
        dropout=any(e['kind']=='dropout' for e in active)
        load=.76+overload*.85;ambient=29+math.sin(minute/30)*.7
        if minute:
            for _ in range(2):
                actual=plant_step(actual,load,ambient,cooling=1+cooling*1.8,scale=scale)
                reference=plant_step(reference,load,ambient,scale=scale)
        oil=float(actual[1])+float(rng.normal(0,.12))+bias*15
        rows.append({'minute':minute,'oil_c':None if dropout else round(oil,2),'load_pu':None if dropout else round(load,3),
                     'ambient_c':None if dropout else round(ambient,2),'reference_model_oil_c':round(float(reference[1]),2),
                     'source':'synthetic three-node plant','quality':'missing' if dropout else 'available'})
        checks[minute]={'probe':{'minute':minute,'value_c':round(float(actual[1])+.04,2),'channel':'Independent synthetic oil probe'},
                        'clamp':{'minute':minute,'load_pu':round(load,3),'channel':'Independent synthetic load reference'},
                        'inspection':{'minute':minute,'finding':'Cooling path obstructed' if cooling else 'No obstruction observed','channel':'Simulated visual inspection'}}
    return rows,checks


def diagnose(rows, revealed_checks):
    """Observation-only rules. No event labels, plant state or seed accepted."""
    current=rows[-1];minute=current['minute'];findings=[];hypotheses=[]
    if current['quality']=='missing':
        findings.append('Latest telemetry is missing; thermal inference is withheld.')
        hypotheses.append('Telemetry interruption')
    else:
        clamp=next((c for c in reversed(revealed_checks) if c['type']=='clamp' and c['minute']==minute),None)
        if clamp:
            agrees=abs(clamp['load_pu']-current['load_pu'])<=.08
            findings.append('Independent load reference agrees within 0.08 pu.' if agrees else 'Independent load reference disagrees; verify the electrical channel before acting.')
            if not agrees:hypotheses.append('Load-channel discrepancy')
        if current['load_pu']>1.05:
            findings.append(f"Observed load {current['load_pu']:.2f} pu exceeds the 1.05 pu diagnostic threshold.");hypotheses.append('Excess loading')
        residual=current['oil_c']-current['reference_model_oil_c']
        probe=next((c for c in reversed(revealed_checks) if c['type']=='probe' and c['minute']==minute),None)
        inspection=next((c for c in reversed(revealed_checks) if c['type']=='inspection' and c['minute']==minute),None)
        if abs(residual)>3:
            findings.append(f'Oil channel differs from the healthy-response model by {residual:+.1f}°C.')
            if probe:
                if abs(current['oil_c']-probe['value_c'])>2:
                    hypotheses.append('Temperature-channel discrepancy');findings.append('Independent probe disagrees with the primary channel by more than 2°C.')
                if probe['value_c']-current['reference_model_oil_c']>3:
                    hypotheses.append('Unexpected physical heating');findings.append('Independent probe also exceeds the model; sensor bias alone is insufficient.')
            else:hypotheses.extend(['Unexpected physical heating','Temperature-channel discrepancy'])
        if inspection and inspection['finding']=='Cooling path obstructed':
            hypotheses.append('Cooling obstruction observed');findings.append('Inspection found an obstructed cooling path; this does not quantify internal damage.')
    if not hypotheses:findings.append('No configured rule has detected an anomaly yet. This is not proof of health.')
    return {'minute':minute,'hypotheses':list(dict.fromkeys(hypotheses)),'findings':findings,'alert':bool(hypotheses),
            'next_checks':[
                {'type':'probe','title':'Independent oil probe','reason':'Separates a biased temperature channel from heat confirmed by a second channel.'},
                {'type':'clamp','title':'Independent load reference','reason':'Checks whether reported electrical loading is supported independently.'},
                {'type':'inspection','title':'Inspect cooling path','reason':'Looks for a physical explanation of heating; no obstruction does not rule out other causes.'}],
            'limitations':'Rule-based evidence, not fault probabilities. Slow heating may remain undetectable during a short observation. The healthy-response reference assumes a known synthetic baseline. Checks describe only their requested minute.'}
