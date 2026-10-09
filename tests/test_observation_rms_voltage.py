"""Physical identities and evidence gates, independently specified examples."""
from copy import deepcopy
import math
import csv
import io

import pytest

from neuratwin import thermal_reference as reference, twin_core as core, twin_observer as observer, twin_studies as studies
from test_submission import client, OP


def varying_voltage_recording():
    rows=[];oil=31.;rise=49.;tau=72.;fraction=.28
    for minute in range(150):
        load=(45,110,65)[min(2,minute//45)]
        voltage=(.8,1.22,.94,1.13)[min(3,minute//35)]
        rows.append({'elapsed_s':60*minute,'oil_c':oil,'ambient_c':29.,'load_percent':load,'voltage_pu':voltage})
        target=29+rise*(fraction*voltage**2+(1-fraction)*(load/100)**2)**.8
        oil=target+(oil-target)*math.exp(-1/tau)
    return rows,rise,tau,fraction


def test_voltage_variation_is_not_absorbed_into_oil_parameters():
    rows,rise,tau,fraction=varying_voltage_recording();original=deepcopy(rows)
    fit=reference.fit(rows,fraction)
    assert fit['identified'] and fit['beats_persistence']
    assert fit['rated_oil_rise_c']==pytest.approx(rise,abs=1e-5)
    assert fit['oil_tau_min']==pytest.approx(tau,abs=1e-5)
    assert fit['validation_rmse_c']<1e-6
    assert fit['voltage_basis']=='recorded_per_unit_voltage'
    assert rows==original
    legacy=reference.fit([{k:v for k,v in r.items() if k!='voltage_pu'} for r in rows],fraction)
    assert legacy['voltage_basis']=='nominal_voltage_assumed'
    assert legacy['validation_rmse_c']>fit['validation_rmse_c']+.05


@pytest.mark.parametrize('value',[None,True,float('nan'),float('inf'),.39,1.61])
def test_declared_invalid_voltage_never_becomes_nominal(value):
    rows,_,_,fraction=varying_voltage_recording();rows[7]['voltage_pu']=value
    with pytest.raises(ValueError,match='Declared voltage'):reference.fit(rows,fraction)


def test_partial_voltage_column_is_a_fit_hold():
    rows,_,_,fraction=varying_voltage_recording();del rows[7]['voltage_pu']
    with pytest.raises(ValueError,match='Declared voltage'):reference.fit(rows,fraction)


def rms_rows():
    p=core.Settings().model_dump();load=70.;currents=(65.,105.,130.)
    thermal=load*math.sqrt(sum(x*x for x in currents)/3)/100
    maximum=load*max(currents)/100
    oil=30+p['rated_oil_rise_c']*((p['core_loss_w']*1.12**2+p['copper_loss_w']*(thermal/100)**2)/(p['core_loss_w']+p['copper_loss_w']))**.8
    hotspot=oil+p['rated_winding_rise_c']*(maximum/100)**1.6
    rows=[{'elapsed_s':n*60,'oil_c':oil,'hotspot_c':hotspot,'ambient_c':30.,'load_percent':load,
           'voltage_pu':1.12,'phase_current_a':65.,'phase_current_b':105.,'phase_current_c':130.,
           'neutral_current':90.} for n in range(45)]
    return rows,p,thermal,maximum


def test_arbitrary_rms_currents_keep_copper_and_worst_phase_distinct():
    rows,p,thermal,maximum=rms_rows();original=deepcopy(rows)
    phase=observer.phase_state(rows[-1])
    assert phase['valid'] and phase['imbalance_percent']==35
    assert phase['max_load_percent']==pytest.approx(maximum)
    assert phase['thermal_load_percent']==pytest.approx(thermal)
    assert phase['neutral_basis']=='reported_rms_only' and not phase['phase_angles_available']
    result=observer.assess(rows,p,30)
    assert result['available']
    assert 'channel_disagreement' not in result['hypotheses']
    assert result['forecast']['points'][-1]['temperature_c']==pytest.approx(rows[-1]['hotspot_c'],abs=1e-9)
    assert result['forecast']['served_kwh'] is None  # No measured PF, no invented real energy.
    assert not result['decision_scope']['scenario_inputs_used']
    assert rows==original


def test_neutral_is_not_inferred_from_magnitude_imbalance():
    rows,p,_,_=rms_rows();a=observer.assess(rows,p)
    for row in rows:row['neutral_current']=30.
    b=observer.assess(rows,p)
    assert b['available'] and a['forecast']==b['forecast']
    rows[-1]['neutral_current']=301.
    assert observer.assess(rows,p)['hypothesis']=='unsupported_phase_model'


def test_observation_projection_cannot_read_injected_scenario_metadata():
    rows,p,_,_=rms_rows();a=observer.assess(rows,p)
    for r in rows:r.update(cooling='failed',fault='thermal',future_hotspot_c=999)
    assert observer.assess(rows,p)==a
    with pytest.raises(ValueError,match='1–30'):
        studies.observation_projection(p,rows[-1],observer.phase_state(rows[-1]),rows[-1]['hotspot_c'],240)


def test_reference_api_preserves_voltage_and_rejects_blank_entries(client):
    rows,_,_,fraction=varying_voltage_recording()
    def csv_text(values):
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
        return out.getvalue()
    payload={'request_id':'voltage-fit-contract','name':'Varying voltage reference','reviewer':'Test engineer',
             'source':'synthetic','healthy_reviewed':True,'temperature_kind':'oil','core_fraction':fraction,
             'csv_text':csv_text(rows)}
    r=client.post('/api/halo/twin/references',headers=OP,json=payload)
    assert r.status_code==200,r.text
    assert r.json()['fit']['voltage_basis']=='recorded_per_unit_voltage'
    assert r.json()['fit']['validation_rmse_c']<1e-6
    original=r.json()
    assert client.post('/api/halo/twin/references',headers=OP,json=payload).json()==original
    run=client.post('/api/halo/twin/references/'+original['id']+'/run',headers=OP,
                    json={'request_id':'voltage-reference-run'}).json()
    assert run['settings']['rated_oil_rise_c']==pytest.approx(original['fit']['rated_oil_rise_c'])
    rows[5]['voltage_pu']=1.1
    assert client.post('/api/halo/twin/references',headers=OP,json={**payload,'csv_text':csv_text(rows)}).status_code==409
    rows[5]['voltage_pu']=None
    r=client.post('/api/halo/twin/references',headers=OP,json={**payload,'request_id':'blank-voltage-ref','csv_text':csv_text(rows)})
    assert r.status_code==422


@pytest.mark.parametrize('replacement',['NaN','inf','0.39','1.61'])
def test_reference_api_invalid_voltage_is_a_client_error(client,replacement):
    rows,_,_,fraction=varying_voltage_recording()
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=out.getvalue().splitlines();cells=lines[5].split(',');cells[-1]=replacement;lines[5]=','.join(cells)
    response=client.post('/api/halo/twin/references',headers=OP,json={
        'request_id':'invalid-voltage-case','name':'Invalid voltage fixture','reviewer':'Test engineer',
        'source':'synthetic','healthy_reviewed':True,'temperature_kind':'oil','core_fraction':fraction,
        'csv_text':'\n'.join(lines)})
    assert response.status_code==422
