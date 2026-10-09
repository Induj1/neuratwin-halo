"""Optional phase observations and genuinely independent baseline semantics."""
from copy import deepcopy
import math

import pytest

from neuratwin import twin_core as core, twin_observer as observer
from scripts import benchmark_pipeline as benchmark


def run_with_phase(imbalance):
    state=core.create_state('phase-observer-test')
    state['inputs'].update(load_percent=70,phase_imbalance_percent=imbalance,protection_enabled=False)
    state['running']=True
    core.evaluate(state,0)
    core.advance(state,1800)
    return state


@pytest.mark.parametrize('imbalance',[20,60])
def test_phase_observations_preserve_severity_and_do_not_invent_channel_fault(imbalance):
    state=run_with_phase(imbalance)
    rows=observer.from_history(state)
    immutable=deepcopy(rows)
    result=observer.assess(rows,state['settings'],5)
    assert result['available'] is True
    assert result['observed_status']=='CRITICAL'
    assert 'phase_imbalance' in result['hypotheses']
    assert not {'channel_disagreement','thermal_deviation'} & set(result['hypotheses'])
    assert result['analysis']['status']=='CRITICAL'
    assert result['phase_scope']['imbalance_percent']==imbalance
    assert result['phase_scope']['max_load_percent']==pytest.approx(70*(1+imbalance/100))
    core.advance(state,300)
    assert result['forecast']['points'][-1]['temperature_c']==pytest.approx(state['telemetry']['hotspot_temperature'],abs=1e-10)
    assert rows==immutable


def test_phase_oil_only_uses_heating_without_asserting_measured_hotspot():
    state=run_with_phase(60)
    rows=observer.from_history(state)
    result=observer.assess(rows,state['settings'],5,temperature_mode='oil_only')
    assert result['available'] and result['observed_status']=='CRITICAL'
    assert result['minutes_to_critical'] is None
    assert result['capability']['hotspot_deadline_supported'] is False
    assert result['inferred_hotspot_c'] is not None
    assert not any(a['code']=='transformer_temperature' for a in result['observed_alerts'])
    core.advance(state,300)
    assert result['forecast']['points'][-1]['oil_c']==pytest.approx(state['telemetry']['oil_temperature'],abs=1e-10)
    assert observer.assess([{**r,'hotspot_c':9999} for r in rows],state['settings'],5,temperature_mode='oil_only')==result


def test_absent_phase_scope_remains_a_labelled_legacy_assumption():
    state=run_with_phase(0)
    rows=observer.from_history(state)
    legacy=[{k:r[k] for k in observer.FIELDS} for r in rows]
    old=observer.assess(legacy,state['settings'])
    measured=observer.assess(rows,state['settings'])
    assert old['available'] and measured['available']
    assert old['forecast']==measured['forecast']
    assert old['phase_scope']['basis']=='aggregate_only_assumed_balanced'
    assert old['phase_scope']['imbalance_percent'] is None
    assert 'assumed, not established' in old['assumptions']


@pytest.mark.parametrize('change',[
    {'phase_current_c':None},
    {'phase_imbalance_percent':float('nan')},
    {'phase_imbalance_percent':61},
    {'thermal_loading_percent':999},
    {'neutral_current':9999},
])
def test_declared_missing_or_inconsistent_phase_scope_withholds_without_balanced_fallback(change):
    state=run_with_phase(20)
    rows=observer.from_history(state)
    rows[-1].update(change)
    result=observer.assess(rows,state['settings'])
    assert result['available'] is False
    assert result['hypothesis'] in ('missing_phase_data','unsupported_phase_model')
    assert result['minutes_to_critical'] is None and 'forecast' not in result


def test_disappearing_phase_columns_do_not_silently_revert_to_aggregate_mode():
    state=run_with_phase(20)
    rows=observer.from_history(state)
    rows[-1]={k:rows[-1][k] for k in observer.FIELDS}
    result=observer.assess(rows,state['settings'])
    assert result['hypothesis']=='missing_phase_data' and not result['available']


@pytest.mark.parametrize('imbalance',[20,60])
def test_imbalance_only_and_complete_currents_support_same_amplitude_model(imbalance):
    state=run_with_phase(imbalance)
    rows=observer.from_history(state)
    scalar=[{k:r[k] for k in (*observer.FIELDS,'phase_imbalance_percent')} for r in rows]
    currents=[{k:r[k] for k in (*observer.FIELDS,'phase_current_a','phase_current_b','phase_current_c')} for r in rows]
    a=observer.assess(scalar,state['settings'])
    b=observer.assess(currents,state['settings'])
    assert a['available'] and b['available']
    assert a['observed_status']==b['observed_status']=='CRITICAL'
    assert a['forecast']['peak_c']==pytest.approx(b['forecast']['peak_c'])
    reference=observer.reference_rows(scalar)
    assert reference[-1]['load_percent']==pytest.approx(70*math.sqrt(1+2*(imbalance/100)**2/3))


@pytest.mark.parametrize('load',[1,70,97,250])
@pytest.mark.parametrize('imbalance',[10,20,60])
def test_inferred_phase_boundaries_are_not_changed_by_floating_point_roundoff(load,imbalance):
    state=core.create_state('ratio-boundary')
    state['inputs'].update(load_percent=load,phase_imbalance_percent=imbalance)
    electrical=core.electrical(state)
    row={'load_percent':load,**{k:electrical[k] for k in ('phase_current_a','phase_current_b','phase_current_c')}}
    phase=observer.phase_state(row)
    assert phase['valid'] and phase['imbalance_percent']==imbalance


def test_threshold_baseline_never_runs_residual_cusum_or_forecasting(monkeypatch):
    rows=observer.from_history(run_with_phase(20))
    def forbidden(*args,**kwargs):raise AssertionError('Threshold comparator called a numerical diagnostic/forecast')
    monkeypatch.setattr(observer,'residual_details',forbidden)
    monkeypatch.setattr(observer,'thermal_drift',forbidden)
    monkeypatch.setattr(observer.studies,'projection',forbidden)
    monkeypatch.setattr(observer.studies,'observation_projection',forbidden)
    result=observer.threshold_assess(rows)
    assert result['hypotheses']==['phase_imbalance']
    assert result['observed_status']=='CRITICAL' and result['any_warning']
    assert not {'thermal_deviation','channel_disagreement'} & set(result['hypotheses'])
    assert 'forecast' not in result


def test_threshold_alert_is_not_a_cooling_or_sensor_root_cause_diagnosis():
    row={'elapsed_s':0,'oil_c':109,'hotspot_c':131,'ambient_c':45,'load_percent':97,'voltage_pu':1}
    result=observer.threshold_assess([row])
    assert result['hypotheses']==['observed_overtemperature']
    assert result['any_warning'] and result['input_eligible']
    assert 'thermal_deviation' not in result['hypotheses']


def test_threshold_and_full_pipeline_share_missing_channel_gate_but_keep_valid_breach():
    row={'elapsed_s':0,'oil_c':None,'hotspot_c':79,'ambient_c':30,'load_percent':130,'voltage_pu':1}
    threshold=observer.threshold_assess([row])
    full=observer.assess([row])
    assert threshold['validity']['holds']==full['validity']['holds']==['missing_data']
    assert threshold['hypotheses']==['missing_data','overload']
    assert threshold['observed_status']==full['observed_status']=='CRITICAL'
    assert threshold['any_warning'] and not threshold['input_eligible']


def test_benchmark_separates_early_warning_from_late_complete_diagnosis():
    trace=[
        {'minute':8,'active':False,'signals':[],'warnings':['observed_threshold']},
        {'minute':9,'active':False,'signals':[],'warnings':['conditional_limit_forecast']},
        {'minute':10,'active':False,'signals':[],'warnings':[]},
        {'minute':11,'active':True,'signals':['overload'],'warnings':['observed_threshold']},
        {'minute':12,'active':True,'signals':['overload'],'warnings':['observed_threshold']},
        {'minute':13,'active':True,'signals':['overload','thermal_deviation'],'warnings':['model_disagreement']},
    ]
    result=benchmark.comparison_case(trace,10,12,['overload','thermal_deviation'])
    assert result['expected_signal_set_complete'] and not result['complete_before_critical']
    assert result['completion_delay_min']==3
    assert result['any_warning_before_critical'] and result['warning_lead_to_critical_min']==1
    assert result['first_warning_kinds']==['observed_threshold']
    assert result['false_alarm_minutes']==2 and result['false_alarm_episodes']==1
    assert result['normal_minutes']==3


def test_threshold_warning_never_counts_as_complete_cooling_diagnosis():
    assessment=observer.threshold_assess([{'elapsed_s':600,'oil_c':109,'hotspot_c':131,
        'ambient_c':45,'load_percent':97,'voltage_pu':1}])
    trace=[{'minute':10,'active':True,'signals':assessment['hypotheses'],'warnings':benchmark.warning_kinds(assessment)}]
    result=benchmark.comparison_case(trace,10,15,['thermal_deviation'])
    assert result['any_warning_before_critical']
    assert not result['expected_signal_set_complete']
    assert result['first_warning_kinds']==['observed_threshold']


def test_forecast_warning_requires_qualified_forecast_and_warmup_is_not_alarm():
    assert benchmark.warning_kinds({'available':False,'minutes_to_critical':5,
        'hypotheses':['insufficient_evidence'],'observed_alerts':[]})==[]
    assert benchmark.warning_kinds({'available':True,'minutes_to_critical':5,
        'hypotheses':[],'observed_alerts':[]})==['conditional_limit_forecast']
    assert list(benchmark.EVALUATION_SEEDS)==list(range(91001,91025))
