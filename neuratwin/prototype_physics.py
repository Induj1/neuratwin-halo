"""Inspectable virtual oil system driven by a source matrix, never a relay controller."""
from functools import lru_cache
import math
from typing import Literal
import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve
from pydantic import Field, model_validator
from .halo_contracts import Contract


class Settings(Contract):
    tank: Literal['sealed','conservator']='sealed'
    ambient_c: float=Field(25,ge=-20,le=55)
    rated_rise_c: float=Field(55,ge=10,le=90)
    loss_ratio: float=Field(5,ge=.5,le=15)
    oil_tau_min: float=Field(90,ge=10,le=300)
    clock_scale: Literal[1,60]=60
    oil_litres: float=Field(200,ge=5,le=5000)
    gas_litres: float=Field(30,ge=1,le=1000)
    conservator_litres: float=Field(40,ge=1,le=1000)
    expansion_per_c: float=Field(.0007,ge=.0003,le=.0012)
    oil_limit_c: float=Field(95,ge=60,le=130)
    pressure_limit_kpa: float=Field(50,ge=10,le=150)
    cooling: float=Field(1,ge=.4,le=1.5)
    oil_warning_percent: float=Field(95,ge=1,le=100)
    oil_critical_percent: float=Field(90,ge=1,le=100)
    leak_rate_l_min: float=Field(.12,gt=0,le=100)
    oil_density_kg_l: float=Field(.87,ge=.5,le=1.5)
    oil_cp_kj_kg_k: float=Field(1.9,ge=.5,le=5)
    solid_capacity_kj_k: float=Field(80,gt=0,le=100000)
    impedance_percent: float|None=Field(None,ge=.1,le=100)
    winding_resistance_ohm: float|None=Field(None,gt=0,le=10000)
    overload_pickup_pu: float=Field(1.1,gt=1,le=3)
    overload_delay_s: float=Field(5,ge=0,le=300)
    fault_pickup_pu: float=Field(5,ge=2,le=20)
    voltage_dip_pu: float=Field(.7,gt=0,lt=1)
    fault_delay_s: float=Field(.1,gt=0,le=10)
    startup_guard_s: float=Field(3,ge=0,le=30)

    @model_validator(mode='after')
    def limits(self):
        if self.oil_critical_percent>=self.oil_warning_percent:
            raise ValueError('Oil critical inventory must be below the warning inventory.')
        if self.fault_pickup_pu<=self.overload_pickup_pu:
            raise ValueError('Fault pickup must exceed overload pickup.')
        return self


def oil_target(k,p):
    return p.ambient_c+p.rated_rise_c*((1+p.loss_ratio*k*k)/(1+p.loss_ratio))**.8/p.cooling


def capacity(p,inventory=None):
    return p.solid_capacity_kj_k+p.oil_density_kg_l*(p.oil_litres if inventory is None else max(0,inventory))*p.oil_cp_kj_kg_k


def oil_step(t,k,seconds,p,energized=True,inventory=None):
    target=oil_target(k,p) if energized else p.ambient_c
    tau=60*p.oil_tau_min*capacity(p,inventory)/capacity(p)
    return target+(t-target)*math.exp(-seconds/tau)


def fluid(oil_c,p,leaked_l=0):
    # Bulk rise is an explicit 0.8 * top-oil rise approximation, not a measurement.
    bulk=p.ambient_c+.8*(oil_c-p.ambient_c)
    inventory=max(0,p.oil_litres-leaked_l)
    expansion=p.expansion_per_c*inventory*(bulk-25)
    level=100*(.4*p.conservator_litres+expansion-leaked_l)/p.conservator_litres
    gas=p.gas_litres-expansion+leaked_l
    pressure=None if gas<=.05*p.gas_litres else 101.325*(bulk+273.15)/298.15*p.gas_litres/gas-101.325
    return dict(bulk_oil_c=bulk,expansion_l=expansion,gas_volume_l=gas,
        inventory_l=inventory,inventory_percent=100*inventory/p.oil_litres,
        missing_l=p.oil_litres-inventory,expanded_volume_l=inventory+expansion,
        pressure_kpa=pressure if p.tank=='sealed' else None,
        level_percent=level if p.tank=='conservator' else 100*inventory/p.oil_litres,
        level_basis='Conservator fill' if p.tank=='conservator' else 'Oil inventory',
        valid=gas>.05*p.gas_litres if p.tank=='sealed' else 0<=level<=100)


def trajectory(start,k,p,energized=True,leaked_l=0,rate_l_min=0):
    points=[];temperature=start;missing=leaked_l
    for minute in range(121):
        if minute:
            temperature=oil_step(temperature,k,60,p,energized,max(0,p.oil_litres-missing))
            missing=min(p.oil_litres,missing+rate_l_min)
        if minute%2==0:points.append(dict(minute=minute,oil_c=temperature,**fluid(temperature,p,missing)))
    return points


def oil_ledger(at,p,actions):
    """Reference-temperature mass balance; actions persist beyond the source buffer."""
    missing=0.;rate=0.;lost=0.;refilled=0.;previous=None;trail=[]
    for action in [*actions,dict(time=at,operation='sample')]:
        when=action['time']
        if when>at:break
        if previous is not None:
            loss=min(p.oil_litres-missing,rate*max(0,when-previous)*p.clock_scale/60)
            missing+=loss;lost+=loss
        operation=action['operation']
        amount=0.
        if operation=='leak':rate=action['rate_l_min']
        elif operation=='stop':rate=0.
        elif operation=='refill':
            amount=min(missing,action['litres']);missing-=amount;refilled+=amount
        if operation!='sample':trail.append(dict(**action,applied_litres=amount,remaining_l=p.oil_litres-missing))
        previous=when
    return dict(missing_l=missing,loss_rate_l_min=rate,lost_total_l=lost,refilled_total_l=refilled,actions=trail)


def assess(rows,p,*,rated_current=1,live=False,fault='none',fault_at=None,reset_at=None,branches=0,oil_actions=None):
    # The matrix contains timestamp, displayed current and temperature, with provenance.
    unique={}
    for r in rows:
        if r and r.get('timestamp'):
            from datetime import datetime
            time=datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')).timestamp()
            if reset_at is None or time>=reset_at:
                unique[r['sample_key']]={**r,'time':time}
    data=sorted(unique.values(),key=lambda r:r['time'])
    out=dict(version='physics-2',settings=p.model_dump(),available=False,live=live,
        scope='Virtual oil-filled transformer driven by source loading. Oil, gas and pressure are modelled; no hardware action is automatic.',
        geometry_basis='Declared illustrative profile, not a dimensional miniature of the dry bench.',
        pressure_basis='Rigid sealed gas cushion; fixed gas mass; no tank compliance, gas solubility or relief flow. Not an arc-pressure model.',
        temperature_basis='Initial source temperature is a proxy seed, not a measured oil temperature.',
        coverage='Replay of supplied source window only; gaps > 10 seconds (prototype) or 65 seconds (industrial) are excluded.',
        curves=[],history=[],events=[],reason='Waiting for current and temperature.',fault=fault)
    valid=lambda r:all(isinstance(r.get(k),(float,int)) and math.isfinite(r[k]) for k in ('current_a','temperature_c','voltage_v')) and 0<=r['current_a']/rated_current<=3 and -55<=r['temperature_c']<=200 and r['voltage_v']>=0
    if not data or not valid(data[-1]):return out
    first=next((r for r in data if valid(r)),None)
    actions=sorted(oil_actions or [],key=lambda a:a['time'])
    if not actions and fault=='leak' and fault_at is not None:
        actions=[dict(time=fault_at,operation='leak',rate_l_min=p.leak_rate_l_min)]
    oil=first['temperature_c'];elapsed=0.;gap=0.;history=[];stage='normal';events=[];gas_ml=0.;leaked=0.
    for i,r in enumerate(data):
        if r['time']<first['time']:continue
        dt=0 if i==0 else r['time']-data[i-1]['time']
        previous=data[max(0,i-1)]
        max_gap=65 if r.get('current_source')=='industrial simulation' else 10
        if dt>max_gap or previous['boot_id']!=r['boot_id'] or not valid(previous) or not valid(r):
            gap+=max(0,dt);dt=0
        model_dt=dt*p.clock_scale;elapsed+=model_dt
        ledger=oil_ledger(r['time'],p,actions)
        if dt:oil=oil_step(oil,previous['current_a']/rated_current,model_dt,p,previous['voltage_v']>1,p.oil_litres-leaked)
        injection=bool(fault!='none' and fault_at is not None and r['time']>=fault_at)
        fault_dt=max(0,r['time']-max(previous['time'],fault_at))*p.clock_scale if injection and dt else 0
        leaked=ledger['missing_l']
        if any(a['operation'] in ('stop','refill') and previous['time']<a['time']<=r['time'] for a in actions):
            stage='normal'  # Reassess after recorded corrective action; retain thermal history.
        if injection and fault=='gas' and p.tank=='conservator':gas_ml+=.1*fault_dt
        f=fluid(oil,p,leaked)
        if injection and fault=='surge' and p.tank=='sealed' and f['pressure_kpa'] is not None:f['pressure_kpa']+=p.pressure_limit_kpa
        low=f['inventory_percent']<=p.oil_critical_percent or p.tank=='conservator' and f['level_percent']<=15
        critical=oil>=p.oil_limit_c or (f['pressure_kpa'] is not None and f['pressure_kpa']>=p.pressure_limit_kpa) or gas_ml>=200 or low or not f['valid']
        warning=oil>=p.oil_limit_c-10 or (f['pressure_kpa'] is not None and f['pressure_kpa']>=.8*p.pressure_limit_kpa) or gas_ml>=100 or f['inventory_percent']<=p.oil_warning_percent or p.tank=='conservator' and f['level_percent']<=25
        new='trip' if critical or stage=='trip' else 'warning' if warning else 'normal'
        if new!=stage:events.append(dict(timestamp=r['timestamp'],state=new,origin='injected scenario' if injection else 'virtual model'));stage=new
        history.append(dict(timestamp=r['timestamp'],minute=elapsed/60,oil_c=oil,gas_ml=gas_ml,**f))
    last=data[-1];k=last['current_a']/rated_current;energized=last['voltage_v']>1
    rate=ledger['loss_rate_l_min']
    curves=trajectory(oil,k,p,energized,leaked,rate)
    def acceptable(points):return all(v['valid'] and v['inventory_percent']>p.oil_critical_percent and v['oil_c']<p.oil_limit_c-2 and (v['pressure_kpa'] is None or v['pressure_kpa']<p.pressure_limit_kpa-2) for v in points[1:])
    # Exhaust the actual discrete bench load combinations, otherwise 5% demand steps.
    choices=[k*(branches-off)/branches for off in range(1,branches+1)] if branches else [k*v/100 for v in range(95,-1,-5)]
    recommended=k if acceptable(curves) else next((v for v in choices if acceptable(trajectory(oil,v,p,energized,leaked,rate))),0.)
    mitigated=trajectory(oil,recommended,p,energized,leaked,rate)
    crossing=next((v['minute'] for v in curves if v['inventory_percent']<=p.oil_critical_percent or v['oil_c']>=p.oil_limit_c or (v['pressure_kpa'] is not None and v['pressure_kpa']>=p.pressure_limit_kpa)),None)
    resolved=acceptable(mitigated) and stage!='trip'
    out.update(available=True,reason='',timestamp=last['timestamp'],current_source=last['current_source'],
        input_current_a=last['current_a'],surface_c=last['temperature_c'],loading_pu=k,energized=energized,
        integrated_seconds=elapsed/p.clock_scale,skipped_seconds=gap,history=history,events=events,
        oil_c=oil,**fluid(oil,p,leaked),gas_ml=gas_ml,stage=stage,oil_balance=ledger,
        loss_rate_l_min=rate,oil_limit_l=p.oil_litres*p.oil_critical_percent/100,
        oil_time_to_limit_min=0. if p.oil_litres-leaked<=p.oil_litres*p.oil_critical_percent/100 else (p.oil_litres-leaked-p.oil_litres*p.oil_critical_percent/100)/rate if rate>0 else None,
        effective_capacity_kj_k=capacity(p,p.oil_litres-leaked),effective_tau_min=p.oil_tau_min*capacity(p,p.oil_litres-leaked)/capacity(p),
        curves=curves,mitigated=mitigated,time_to_limit_min=crossing,
        recommendation=dict(current_pu=recommended,load_reduction_percent=0 if k==0 else (1-recommended/k)*100,
            branches_to_shed=round(branches*(1-recommended/k)) if branches and k else 0,
            sufficient=resolved and rate==0 and leaked==0,
            action='Stop leak and inspect oil inventory' if rate>0 else 'Inspect and replenish missing oil' if leaked>0 else 'Investigate and isolate under the site procedure' if stage=='trip' else 'Maintain present load' if recommended==k else 'Reduce load',
            peak_before_c=max(v['oil_c'] for v in curves),peak_after_c=max(v['oil_c'] for v in mitigated)),
        matrix_columns=['timestamp','current_a','temperature_c','current_source'],
        matrix=[[r['timestamp'],r.get('current_a'),r.get('temperature_c'),r.get('current_source')] for r in data])
    # Retain the injected instantaneous state for display, separate from the healthy projection.
    if history:out['pressure_kpa']=history[-1]['pressure_kpa']
    out['projection_note']='Forecast retains missing oil and continues the declared leak rate. Gas/surge are not extrapolated. Fixed heat transfer: reduced inventory changes thermal capacity, not steady-state target. Scenario estimates, not oil measurements.'
    return out


@lru_cache(maxsize=4)
def fem_basis(n=18):
    """P1 triangular FEM: -div(k grad T)=q with Robin boundary heat transfer."""
    width=.3;height=.4;depth=.2;h=8.;nx=n;ny=n
    nodes=np.array([(x*width/nx,y*height/ny) for y in range(ny+1) for x in range(nx+1)])
    triangles=[]
    for y in range(ny):
        for x in range(nx):
            a=y*(nx+1)+x;b=a+1;c=a+nx+1;d=c+1
            triangles.extend([(a,b,d),(a,d,c)])
    matrix=lil_matrix((len(nodes),len(nodes)));loads=np.zeros((len(nodes),2));materials=[];areas=[]
    for tri in triangles:
        pts=nodes[list(tri)];cx,cy=pts.mean(axis=0)
        material='winding' if (.055<cx<.105 or .195<cx<.245) and .08<cy<.32 else 'core' if .125<cx<.175 or cy<.065 or cy>.335 else 'oil'
        conductivity={'core':15.,'winding':2.,'oil':.3}[material]
        area=abs(np.linalg.det(np.column_stack((np.ones(3),pts))))/2
        grad=np.linalg.inv(np.column_stack((np.ones(3),pts)))[1:,:]
        local=conductivity*depth*area*(grad.T@grad)
        for i,a in enumerate(tri):
            for j,b in enumerate(tri):matrix[a,b]+=local[i,j]
        materials.append(material);areas.append(area)
    totals={m:sum(a for a,kind in zip(areas,materials) if kind==m) for m in ('core','winding')}
    for tri,area,material in zip(triangles,areas,materials):
        if material in totals:
            for a in tri:loads[a,0 if material=='core' else 1]+=area/totals[material]/3
    boundary=[]
    for x in range(nx):boundary.extend([(x,x+1),(ny*(nx+1)+x,ny*(nx+1)+x+1)])
    for y in range(ny):boundary.extend([(y*(nx+1),(y+1)*(nx+1)),(y*(nx+1)+nx,(y+1)*(nx+1)+nx)])
    for a,b in boundary:
        length=np.linalg.norm(nodes[a]-nodes[b]);v=h*depth*length/6
        matrix[a,a]+=2*v;matrix[b,b]+=2*v;matrix[a,b]+=v;matrix[b,a]+=v
    basis=spsolve(matrix.tocsr(),loads)
    return nodes,triangles,materials,basis,boundary,h,depth


def fem(k,ambient=25,n=18,energized=True):
    nodes,triangles,materials,basis,boundary,h,depth=fem_basis(n)
    # Declared illustrative losses, never inferred from dependent primary/secondary currents.
    losses=np.array([2.,10.*k*k]) if energized else np.zeros(2);temperatures=ambient+basis@losses
    rejected=sum(h*depth*np.linalg.norm(nodes[a]-nodes[b])*((temperatures[a]+temperatures[b])/2-ambient) for a,b in boundary)
    return dict(nodes=nodes.tolist(),triangles=triangles,materials=materials,temperature_c=temperatures.tolist(),
        peak_c=float(max(temperatures)),heat_input_w=float(sum(losses)),heat_rejected_w=float(rejected),
        balance_error_w=float(abs(sum(losses)-rejected)),elements=len(triangles),
        scope='Illustrative steady 2D conduction FEM; effective oil conductivity, no CFD or measured hot-spot claim.',
        assumptions=dict(width_m=.3,height_m=.4,depth_m=.2,convection_w_m2k=8,core_loss_w=2,rated_copper_loss_w=10,
                         conductivity_w_mk=dict(core=15,winding_effective=2,oil_effective=.3)))


def sensor_study():
    nodes,_,_,basis,_,_,_=fem_basis(18)
    boundary=np.array([i for i,(x,y) in enumerate(nodes) if x==0 or x==.3 or y==0 or y==.4])
    rng=np.random.default_rng(27);train=rng.uniform([1,1],[4,20],(60,2));test=rng.uniform([1,1],[4,20],(30,2))
    fields=train@basis.T;truth=test@basis.T;chosen=[];result=[]
    noise=rng.normal(0,.25,truth.shape)
    for count in range(1,4):
        candidates=[]
        for i in boundary:
            if int(i) in chosen:continue
            subset=chosen+[int(i)];x=fields[:,subset]
            weights=np.linalg.solve(x.T@x+len(train)*.25**2*np.eye(len(subset)),x.T@fields)
            score=float(np.mean((x@weights-fields)**2)+.25**2*np.sum(weights**2)/len(nodes));candidates.append((score,int(i),weights))
        _,pick,weights=min(candidates,key=lambda v:v[0]);chosen.append(pick)
        observed=truth[:,chosen]+noise[:,chosen]
        result.append(dict(sensors=count,node_ids=chosen.copy(),rmse_c=float(np.sqrt(np.mean((observed@weights-truth)**2)))))
    return dict(results=result,scope='Synthetic FEM field reconstruction; accessible boundary locations; held-out loss cases, assumed 0.25 C Gaussian sensor noise. Not field accuracy.',candidate_nodes=boundary.tolist())
