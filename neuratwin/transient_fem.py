"""Transient P1 conduction FEM for the declared illustrative cross-section."""
from functools import lru_cache
from time import perf_counter
import numpy as np
from scipy.sparse import lil_matrix, diags
from scipy.sparse.linalg import factorized
from pydantic import Field, model_validator
from .halo_contracts import Contract
from .prototype_physics import fem_basis


class Segment(Contract):
    minute:int=Field(ge=0,le=240)
    loading_pu:float=Field(ge=0,le=3)
    energized:bool=True


class Study(Contract):
    ambient_c:float=Field(25,ge=-20,le=55)
    initial_c:float=Field(25,ge=-20,le=150)
    horizon_min:int=Field(120,ge=10,le=240)
    segments:list[Segment]=Field(default_factory=lambda:[Segment(minute=0,loading_pu=.7),Segment(minute=20,loading_pu=1.4),Segment(minute=60,loading_pu=.7)],min_length=1,max_length=8)

    @model_validator(mode='after')
    def ordered(self):
        minutes=[s.minute for s in self.segments]
        if minutes[0]!=0 or minutes!=sorted(set(minutes)) or minutes[-1]>=self.horizon_min:
            raise ValueError('Load segments must start at zero, increase strictly and precede the horizon.')
        return self


@lru_cache(maxsize=4)
def matrices(n):
    nodes,triangles,materials,_,boundary,h,depth=fem_basis(n)
    matrix=lil_matrix((len(nodes),len(nodes)));mass=np.zeros(len(nodes));loads=np.zeros((len(nodes),2))
    areas=[]
    properties={'core':(15,7800,460),'winding':(2,8960,385),'oil':(.3,870,1900)}
    for tri,material in zip(triangles,materials):
        pts=nodes[list(tri)];a=abs(np.linalg.det(np.column_stack((np.ones(3),pts))))/2;areas.append(a)
        grad=np.linalg.inv(np.column_stack((np.ones(3),pts)))[1:,:]
        conductivity,rho,cp=properties[material]
        local=conductivity*depth*a*(grad.T@grad)
        for i,u in enumerate(tri):
            mass[u]+=rho*cp*a*depth/3
            for j,v in enumerate(tri):matrix[u,v]+=local[i,j]
    totals={m:sum(a for a,kind in zip(areas,materials) if kind==m) for m in ('core','winding')}
    for tri,area,material in zip(triangles,areas,materials):
        if material in totals:
            for u in tri:loads[u,0 if material=='core' else 1]+=area/totals[material]/3
    boundary_vector=np.zeros(len(nodes))
    for a,b in boundary:
        length=np.linalg.norm(nodes[a]-nodes[b]);v=h*depth*length/6
        matrix[a,a]+=2*v;matrix[b,b]+=2*v;matrix[a,b]+=v;matrix[b,a]+=v
        boundary_vector[a]+=h*depth*length/2;boundary_vector[b]+=h*depth*length/2
    return nodes,triangles,materials,matrix.tocsc(),mass,loads,boundary_vector


@lru_cache(maxsize=8)
def solver(n,dt):
    _,_,_,k,m,_,_=matrices(n)
    return factorized(k+diags(m/dt,format='csc'))


def solve(study,n=18,dt=30):
    start=perf_counter();nodes,triangles,materials,k,m,loads,boundary=matrices(n);advance=solver(n,dt)
    t=np.full(len(nodes),study.initial_c-study.ambient_c,dtype=float)
    first=study.segments[0];input_w=2+10*first.loading_pu**2 if first.energized else 0
    frames=[{'minute':0,'peak_c':study.initial_c,'temperature_c':(t+study.ambient_c).tolist(),'input_w':input_w,'stored_w':input_w-float(boundary@t),'rejected_w':float(boundary@t),'balance_error_w':None}]
    maximum_residual=0.;segment=0
    for sec in range(dt,study.horizon_min*60+1,dt):
        while segment+1<len(study.segments) and study.segments[segment+1].minute*60 <= sec-dt:segment+=1
        s=study.segments[segment];power=np.array([2.,10*s.loading_pu**2]) if s.energized else np.zeros(2)
        new=advance(m/dt*t+loads@power)
        stored=float(m@(new-t)/dt);rejected=float(boundary@new)
        residual=abs(float(sum(power))-stored-rejected);maximum_residual=max(maximum_residual,residual)
        t=new
        if sec%120==0 or sec==study.horizon_min*60:
            frames.append({'minute':sec/60,'peak_c':float(max(t)+study.ambient_c),'temperature_c':(t+study.ambient_c).tolist(),
                'input_w':float(sum(power)),'stored_w':stored,'rejected_w':rejected,'balance_error_w':residual})
    return {'version':'transient-fem-1','nodes':nodes.tolist(),'triangles':triangles,'materials':materials,'frames':frames,
        'settings':study.model_dump(),'elements':len(triangles),'max_balance_error_w':maximum_residual,'solve_ms':(perf_counter()-start)*1000,
        'peak_c':max(f['peak_c'] for f in frames),'dt_seconds':dt,
        'assumptions':{'geometry_m':[.3,.4,.2],'convection_w_m2k':8,'core_loss_w':2,'rated_copper_loss_w':10,
            'properties':{'core':{'k_w_mk':15,'rho_kg_m3':7800,'cp_j_kgk':460},'winding':{'effective_k_w_mk':2,'rho_kg_m3':8960,'cp_j_kgk':385},'oil':{'effective_k_w_mk':.3,'rho_kg_m3':870,'cp_j_kgk':1900}}},
        'scope':'Declared 2D transient conduction study, lumped heat capacity and backward Euler. 3D view extrudes the solved 2D field uniformly through depth. No fluid flow, measured internal temperatures or industrial validation.'}


@lru_cache(maxsize=1)
def checks():
    study=Study();coarse=solve(study);fine=solve(study,n=36);time=solve(study,dt=15)
    warm=[solve(study)['solve_ms'] for _ in range(3)]
    a=np.array([f['peak_c'] for f in coarse['frames']]);b=np.array([f['peak_c'] for f in fine['frames']]);c=np.array([f['peak_c'] for f in time['frames']])
    return {'reference':study.model_dump(),'coarse_elements':coarse['elements'],'fine_elements':fine['elements'],
        'mesh_peak_difference_c':float(max(abs(a-b))),'time_step_peak_difference_c':float(max(abs(a-c))),
        'max_balance_error_w':max(coarse['max_balance_error_w'],fine['max_balance_error_w'],time['max_balance_error_w']),
        'warm_solve_median_ms':float(np.median(warm)),
        'interpretation':'Numerical consistency checks on this declared case, not physical validation or a convergence proof.',
        'surrogate_decision':'Direct sparse solves reuse the matrix factorization. No learned surrogate is used; measured latency is reported so its need can be assessed.'}
