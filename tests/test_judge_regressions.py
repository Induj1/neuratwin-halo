from copy import deepcopy
import json
from test_submission import client,create,act,post,OP,BASE
from neuratwin import twin_core as core,twin_studies as studies,twin_observer as observer
from neuratwin.validation_plant import generate


def test_planned_and_applied_overcurrent_action_match(client):
    s=create(client,'overcurrent-regression')
    s=act(client,s,'inputs',inputs={**s['inputs'],'load_percent':90})
    s=act(client,s,'inject',fault='overcurrent',severity=2,duration_s=3600)
    plan=post(client,s,'/plans',horizon_min=30).json();r=plan['recommendation']
    assert r and r['post_load_percent']<100
    applied=client.post(BASE+s['id']+'/apply-plan',headers=OP,json={'plan_id':plan['id'],'revision':s['revision']})
    assert applied.status_code==200,applied.text
    s=applied.json();assert abs(s['telemetry']['loading_percent']-r['post_load_percent'])<1e-8
    s=act(client,s,'start');s=act(client,s,'step',seconds=120)
    assert s['breaker']=='CLOSED'


def test_independent_adverse_parameter_corner_is_covered():
    s=core.create_state('corner');s['inputs'].update(load_percent=105,cooling='degraded',ambient_c=35);core.evaluate(s,0)
    plan=studies.plan(s,60,0)
    zero=next(c for c in plan['candidates'] if c['reduction_pct']==0)
    assert not zero['passes'] and zero['sensitivity_peak_c']>125
    proof=studies.freeze(s,60)
    adverse=studies.projection(s,60,scales=(1.15,1.15,.85,.85))
    assert all(bound['upper_c']>=actual['temperature_c'] for bound,actual in zip(proof['points'],adverse['points']))


def test_forward_risk_overrides_reassuring_advice_even_on_old_run():
    s=core.create_state('risk');s['inputs'].update(load_percent=99,cooling='degraded',ambient_c=35);core.evaluate(s,0)
    assert core.summary(s)['analysis']['status']=='WARNING'
    assert 'Act before' in core.summary(s)['analysis']['maintenance'][0]
    assert not any('no immediate action' in m for m in studies.investigation(s)['next_check'].splitlines())
    assert not any('no immediate action' in m for m in core.summary(s)['analysis']['maintenance'])
    assert 'Healthy' not in core.summary(s)['health_band']
    assert len([a for a in core.summary(s)['analysis']['alerts'] if a['code']=='forecast_thermal'])==1


def test_closure_requires_restored_cooling_and_structured_window():
    s=core.create_state('closed');s['inputs'].update(load_percent=40,cooling='degraded');core.evaluate(s,0)
    s['running']=True;core.advance(s,600)
    w={'acceptance_rules':{'stable_minutes':5,'max_load_percent':99,'max_temperature_c':110,'forecast_horizon_min':240,'require_cooling_restored':True},
       'trail':[{'status':'verification_pending','elapsed_s':0}]}
    assert 'Cooling has not' in ' '.join(studies.closure_check(s,w)['holds'])
    s['inputs']['cooling']='normal';core.evaluate(s,0)
    assert not studies.closure_check(s,w)['eligible']
    core.advance(s,360)
    assert studies.closure_check(s,w)['eligible']
    w['acceptance_rules']['max_load_percent']=30
    assert not studies.closure_check(s,w)['eligible']


def test_observer_cannot_read_hidden_fault_or_future():
    rows,truth,meta=generate(8301,'cooling');before=deepcopy(rows[:121])
    expected=observer.assess(before)
    for r in before:r.update(fault='overload',cooling='failed',true_hotspot=999,scenario='sensor_bias')
    assert observer.assess(before)==expected
    assert observer.assess([{**rows[-1],'hotspot_c':None}])['available'] is False


def test_blind_case_withholds_then_reveals_and_verifies(client):
    c=client.post('/api/halo/twin/challenges',headers=OP,json={'request_id':'blind-case-regression'}).json()
    assert 'reveal' not in c and 'seed' not in c and 'meta' not in c
    url='/api/halo/twin/challenges/'+c['id']
    assert client.post(url+'/reveal',headers=OP).status_code==409
    frozen=client.post(url+'/assess',headers=OP).json()
    assert frozen['assessment'] and 'reveal' not in frozen
    revealed=client.post(url+'/reveal',headers=OP).json()
    assert revealed['commitment_verified'] and revealed['assessment']==frozen['assessment']
    assert studies.digest(revealed['reveal'])==c['commitment']
    assert client.post(url+'/assess',headers=OP).json()['assessment']==frozen['assessment']


def test_legacy_plan_cannot_be_applied_after_model_change(client):
    from neuratwin import halo_store as store
    s=create(client,'legacy-plan');plan=post(client,s,'/plans').json();plan.pop('version')
    store.put('twin_plan',plan['id'],plan)
    assert client.post(BASE+s['id']+'/apply-plan',headers=OP,json={'plan_id':plan['id'],'revision':s['revision']}).status_code==409


def test_observer_rejects_out_of_domain_and_invalid_history():
    rows,_,_=generate(8301,'healthy')
    assert observer.assess(rows+[dict(rows[-1])])['hypothesis']=='invalid_timebase'
    rows[-1]['voltage_pu']=1.7
    assert observer.assess(rows)['hypothesis']=='outside_model_domain'
    rows[-1]['voltage_pu']=1
    rows[-2]['oil_c']=float('nan')
    assert not observer.assess(rows)['available']
