import csv
import io
from copy import deepcopy
from test_submission import client, OP
from neuratwin import twin_core as core, twin_observer as observer, thermal_reference as reference
from neuratwin.validation_plant import generate


def fitted(seed=88013, scenario='cooling_overload'):
    rows, truth, _ = generate(seed, scenario)
    fit = reference.fit(rows[:70]); settings = core.Settings().model_dump()
    if fit['identified'] and fit['beats_persistence']:
        settings.update(rated_oil_rise_c=fit['rated_oil_rise_c'],oil_tau_min=fit['oil_tau_min'])
    return rows, truth, settings


def test_audited_optimistic_countdown_is_withheld():
    rows, truth, p = fitted()
    assert truth[108]['hotspot_c'] >= p['temperature_critical']
    for mode in ('oil_and_hotspot','oil_only'):
        result = observer.assess(rows[:106],p,temperature_mode=mode)
        assert 'thermal_deviation' in result['hypotheses']
        assert not result['available'] and result['minutes_to_critical'] is None
        assert 'forecast' not in result
        assert 'overload' in result['hypotheses']


def test_oil_capability_is_explicit_not_a_dropout_fallback():
    rows, _, p = fitted(88001,'healthy')
    rows = [{**r,'hotspot_c':None} for r in rows[:91]]
    assert observer.assess(rows,p)['hypothesis']=='missing_data'
    oil = observer.assess(rows,p,temperature_mode='oil_only')
    assert oil['available'] and oil['forecast']['points'][0]['oil_c']==rows[-1]['oil_c']
    assert oil['inferred_hotspot_c']>rows[-1]['oil_c']
    assert oil['analysis']['health_index'] is None
    assert oil['minutes_to_critical'] is None
    assert not oil['capability']['channel_agreement_tested']
    assert oil['capability']['forecast_target']=='oil_c'
    # A bogus unavailable channel cannot influence an oil-only result.
    assert observer.assess([{**r,'hotspot_c':9999} for r in rows],p,temperature_mode='oil_only')==oil


def test_two_minute_cadence_and_gap_do_not_fabricate_a_healthy_reference():
    rows,_,p=fitted(88003,'cooling')
    for cadence in (1,2):
        result=observer.assess(rows[::cadence],p,temperature_mode='oil_only')
        assert result['residual']['drift']['available']
    rows[80]['oil_c']=None
    result=observer.assess(rows,p,temperature_mode='oil_only')
    assert not result['residual']['drift']['available']
    assert 'continuity lost' in result['residual']['drift']['reason']


def test_fault_holds_override_condition_score_and_preserve_arithmetic():
    s = core.create_state('health-audit');s['inputs'].update(load_percent=77,cooling='degraded',ambient_c=35)
    core.evaluate(s,0);a=core.summary(s)['analysis']
    assert a['status']=='WARNING' and a['health_index'] is None
    assert a['operating_stress_index']==100
    assert 'cooling_condition' in a['health_evidence']['holds']
    # Reading an old run is deterministic; it doesn't replace historical evidence.
    before=deepcopy(s);assert core.summary(s)['analysis']==a;assert s==before


def recording():
    rows,_,_=fitted(88001,'healthy')
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(observer.FIELDS));writer.writeheader();writer.writerows(rows)
    return {'request_id':'oil-import-regression','temperature_mode':'oil_only','csv_text':out.getvalue(),
            'name':'Synthetic oil recording for test','origin_index':90,'healthy_reference_reviewed':True}


def test_oil_import_freeze_reveal_and_reload(client):
    payload=recording();r=client.post('/api/halo/twin/challenges/import',headers=OP,json=payload)
    assert r.status_code==200,r.text
    c=r.json();url='/api/halo/twin/challenges/'+c['id']
    assert all(r['hotspot_c'] is None for r in c['observations'])
    assert 'reveal' not in c and c['source']=='imported reference'
    frozen=client.post(url+'/assess',headers=OP).json()
    assert frozen['assessment']['result']['available']
    revealed=client.post(url+'/reveal',headers=OP).json()
    assert revealed['commitment_verified'] and revealed['scores']['target']=='oil_c'
    assert revealed['scores']['count']==30 and revealed['assessment']==frozen['assessment']
    assert client.get(url).json()==revealed
    assert client.post('/api/halo/twin/challenges/import',headers=OP,json={**payload,'name':'Changed recording'}).status_code==409


def test_import_rejects_unreviewed_bad_time_and_unexcited_reference(client):
    p=recording();url='/api/halo/twin/challenges/import'
    assert client.post(url,headers=OP,json={**p,'healthy_reference_reviewed':False}).status_code==422
    lines=p['csv_text'].splitlines();lines[2]=lines[1]
    assert client.post(url,headers=OP,json={**p,'csv_text':'\n'.join(lines)}).status_code==422
    rows=list(csv.DictReader(io.StringIO(p['csv_text'])))
    for r in rows:r['load_percent']='70'
    out=io.StringIO();w=csv.DictWriter(out,fieldnames=list(observer.FIELDS));w.writeheader();w.writerows(rows)
    assert client.post(url,headers=OP,json={**p,'csv_text':out.getvalue()}).status_code==422
