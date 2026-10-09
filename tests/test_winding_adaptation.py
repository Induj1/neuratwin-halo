from copy import deepcopy
import math
import pytest
from neuratwin import thermal_adaptation as adaptation,twin_observer as observer,twin_core as core


def fixture_rows(rise=35.,tau=12.,count=100,irregular=False):
    rows=[];winding=9.;elapsed=0.
    for i in range(count):
        load=72+25*math.sin(i/8)+8*math.sin(i/3)
        oil=43+4*math.sin(i/21)
        if rows:
            dt=(30,60,90)[i%3] if irregular else 60
            prior=rows[-1];target=rise*(prior['load_percent']/100)**1.6
            winding=target+(winding-target)*math.exp(-dt/60/tau);elapsed+=dt
        rows.append({'elapsed_s':elapsed,'oil_c':oil,'hotspot_c':oil+winding,
                     'ambient_c':27.,'load_percent':load,'voltage_pu':1.})
    return rows


@pytest.mark.parametrize('rise,tau',[(35.,12.),(17.,3.5),(42.,22.)])
@pytest.mark.parametrize('irregular',[False,True])
def test_identifies_distinct_physical_coefficients_and_validates_chronologically(rise,tau,irregular):
    rows=fixture_rows(rise,tau,irregular=irregular);before=deepcopy(rows)
    fit=adaptation.fit_winding(observer.winding_reference_rows(rows),reviewed_healthy=True)
    assert fit['qualified'] and fit['identified']
    assert fit['rated_winding_rise_c']==pytest.approx(rise,rel=1e-4)
    assert fit['winding_tau_min']==pytest.approx(tau,rel=1e-4)
    assert fit['training_samples']==70 and fit['validation_samples']==30
    assert fit['training_end_s']==rows[69]['elapsed_s'] and fit['fit_end_s']==rows[-1]['elapsed_s']
    assert fit['validation_rmse_c']<1e-4 and rows==before


def test_robust_training_outliers_are_reported_without_rewriting_measurements():
    rows=fixture_rows();rows[20]['hotspot_c']+=12;rows[43]['hotspot_c']-=10
    before=deepcopy(rows);fit=adaptation.fit_winding(observer.winding_reference_rows(rows),reviewed_healthy=True)
    assert fit['qualified'] and fit['training_large_residual_count']==2
    assert abs(fit['rated_winding_rise_c']-35)<.5 and abs(fit['winding_tau_min']-12)<.5
    assert rows==before


def test_validation_outlier_prevents_unreliable_reference_promotion():
    rows=fixture_rows()
    for i in range(73,100):rows[i]['hotspot_c']+=12
    fit=adaptation.fit_winding(observer.winding_reference_rows(rows),reviewed_healthy=True)
    assert not fit['qualified'] and 'validation_error_exceeds_3_c' in fit['holds']


@pytest.mark.parametrize('change', ['missing_hotspot','missing_oil','gap','no_excitation','duplicate','bool'])
def test_missing_weak_or_noncausal_reference_is_rejected(change):
    rows=fixture_rows()
    if change=='missing_hotspot':rows[10]['hotspot_c']=None
    elif change=='missing_oil':rows[10]['oil_c']=None
    elif change=='gap':
        for row in rows[20:]:row['elapsed_s']+=180
    elif change=='no_excitation':
        for row in rows:row['load_percent']=70
    elif change=='duplicate':rows[20]['elapsed_s']=rows[19]['elapsed_s']
    else:rows[10]['hotspot_c']=True
    with pytest.raises(ValueError):adaptation.fit_winding(observer.winding_reference_rows(rows),reviewed_healthy=True)


def test_requires_review_and_never_uses_oil_or_surface_alone():
    rows=observer.winding_reference_rows(fixture_rows())
    with pytest.raises(ValueError,match='reviewed'):adaptation.fit_winding(rows)
    for row in rows:row['surface_c']=row.pop('hotspot_c')
    with pytest.raises(ValueError,match='hotspot'):adaptation.fit_winding(rows,reviewed_healthy=True)


def test_validation_is_not_refitted_and_future_rows_cannot_enter_frozen_prefix():
    rows=fixture_rows();prefix=deepcopy(rows[:70])
    before=adaptation.fit_winding(observer.winding_reference_rows(prefix),reviewed_healthy=True)
    for row in rows[70:]:row['hotspot_c']+=70;row['load_percent']=140
    after=adaptation.fit_winding(observer.winding_reference_rows(rows[:70]),reviewed_healthy=True)
    assert before==after
    changed=deepcopy(prefix)
    for row in changed[50:]:row['hotspot_c']+=7
    validation_changed=adaptation.fit_winding(observer.winding_reference_rows(changed),reviewed_healthy=True)
    assert validation_changed['rated_winding_rise_c']==before['rated_winding_rise_c']
    assert validation_changed['winding_tau_min']==before['winding_tau_min']
    assert validation_changed['validation_rmse_c']>before['validation_rmse_c']


def test_phase_adapter_uses_maximum_current_instead_of_thermal_rms_loading():
    rows=fixture_rows()
    for row in rows:row.update(phase_current_a=10,phase_current_b=20,phase_current_c=30)
    winding=observer.winding_reference_rows(rows);oil=observer.reference_rows(rows)
    assert winding[-1]['winding_load_percent']==pytest.approx(rows[-1]['load_percent']*1.5)
    assert winding[-1]['winding_load_percent']!=oil[-1]['load_percent']
    rows[-1]['phase_current_b']=None
    with pytest.raises(ValueError):observer.winding_reference_rows(rows)


def test_qualified_reference_changes_projection_only_and_preserves_diagnostic_settings():
    settings=core.Settings().model_dump();unchanged=deepcopy(settings)
    denied={'qualified':False,'rated_winding_rise_c':50,'winding_tau_min':35}
    assert adaptation.apply_winding(settings,denied)==settings
    fitted=adaptation.fit_winding(observer.winding_reference_rows(fixture_rows()),settings,reviewed_healthy=True)
    changed=adaptation.apply_winding(settings,fitted)
    assert settings==unchanged
    assert all(changed[k]==settings[k] for k in settings)
    assert changed['winding_forecast_reference']==fitted
    projected,evidence=adaptation.forecast_settings(changed)
    assert {k for k in settings if settings[k]!=projected[k]}=={'rated_winding_rise_c','winding_tau_min'}
    assert evidence['used'] and evidence['screening_reference_unchanged']
    ignored,oil_evidence=adaptation.forecast_settings(changed,oil_only=True)
    assert ignored==changed and not oil_evidence['used']
    fitted['rated_winding_rise_c']=59
    assert changed['winding_forecast_reference']['rated_winding_rise_c']!=59


def test_fit_at_engineering_boundary_is_not_promoted():
    fit=adaptation.fit_winding(observer.winding_reference_rows(fixture_rows(60.,12.)),reviewed_healthy=True)
    assert fit['at_parameter_boundary'] and not fit['identified'] and not fit['qualified']


def test_projection_reference_cannot_clear_sensor_bias_holds_from_rejected_development_case():
    from neuratwin import validation_plant,thermal_reference
    rows,_,_=validation_plant.generate(3105,'sensor_bias',family='nonlinear',variable_event=True)
    base=core.Settings().model_dump();oil=thermal_reference.fit(observer.reference_rows(rows[:70]))
    if oil['identified'] and oil['beats_persistence']:
        base.update(rated_oil_rise_c=oil['rated_oil_rise_c'],oil_tau_min=oil['oil_tau_min'])
    fit=adaptation.fit_winding(observer.winding_reference_rows(rows[:70]),base,reviewed_healthy=True)
    assert fit['qualified']
    candidate=adaptation.apply_winding(base,fit);screened=0;changed_projection=0
    for minute in range(70,181):
        before=observer.assess(rows[:minute+1],base)
        after=observer.assess(rows[:minute+1],candidate)
        assert before['available']==after['available']
        assert before['hypotheses']==after['hypotheses'] and before['residual']==after['residual']
        assert before['validity']==after['validity']
        screened+='channel_disagreement' in before['hypotheses']
        if after['available']:
            assert after['winding_forecast_reference']['used']
            assert before['forecast']['points'][0]==after['forecast']['points'][0]
            changed_projection+=before['forecast']['points'][-1]['temperature_c']!=after['forecast']['points'][-1]['temperature_c']
    assert screened>0
    assert changed_projection>0


@pytest.mark.parametrize('change',['unreviewed','unqualified','version','digest','nan','bounds'])
def test_invalid_projection_reference_is_not_silently_used(change):
    base=core.Settings().model_dump()
    fit=adaptation.fit_winding(observer.winding_reference_rows(fixture_rows()),base,reviewed_healthy=True)
    altered=deepcopy(fit)
    if change=='unreviewed':altered['reviewed_healthy']=False
    elif change=='unqualified':altered['qualified']=False
    elif change=='version':altered['version']='unknown'
    elif change=='digest':altered['fit_input_sha256']='not-a-digest'
    elif change=='nan':altered['rated_winding_rise_c']=float('nan')
    else:altered['winding_tau_min']=61
    with pytest.raises(ValueError):adaptation.forecast_settings({**base,'winding_forecast_reference':altered})


def test_malformed_projection_is_explicit_hold_but_oil_only_ignores_it():
    rows=fixture_rows(23.,7.);base=core.Settings().model_dump()
    baseline=observer.assess(rows,base)
    assert baseline['available']
    malformed={**base,'winding_forecast_reference':{'qualified':True}}
    held=observer.assess(rows,malformed)
    assert not held['available'] and held['validity']['holds']==['invalid_winding_reference']
    assert observer.assess(rows,malformed,temperature_mode='oil_only')==observer.assess(rows,base,temperature_mode='oil_only')
