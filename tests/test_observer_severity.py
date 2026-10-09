"""Observed limit breaches outrank absence of a residual diagnostic hypothesis."""
from copy import deepcopy

import pytest

from neuratwin import twin_core as core, twin_observer as observer, twin_studies as studies


def observations(**changes):
    return [dict(elapsed_s=minute*60, oil_c=109., hotspot_c=131., ambient_c=45.,
                 load_percent=97., voltage_pu=1., **changes) for minute in range(31)]


def test_critical_observation_is_prominent_even_with_no_residual_hypothesis():
    rows=observations()
    original=deepcopy(rows)
    result=observer.assess(rows)
    assert result['available'] is True
    assert result['hypothesis']=='no_anomaly_established' and result['hypotheses']==[]
    assert result['analysis']['status']=='CRITICAL'
    assert result['observed_status']=='CRITICAL'
    alert=next(a for a in result['observed_alerts'] if a['code']=='transformer_temperature')
    assert alert['value']==131 and alert['threshold']==125 and alert['severity']=='CRITICAL'
    assert result['presentation_headline']=='Observed critical threshold breach'
    assert 'Do not wait for a forecast' in result['next_action']
    assert result['minutes_to_critical']==0
    state={'settings':core.Settings().model_dump(), 'inputs':core.Inputs(load_percent=97,ambient_c=45).model_dump(),
           'fault':None,'breaker':'CLOSED','elapsed_s':1800,
           'telemetry':{'oil_temperature':109.,'hotspot_temperature':131.}}
    scenario=studies.projection(state,30)
    assert result['forecast']['peak_c']==scenario['peak_c']
    assert [(p['minute'],p['oil_c'],p['temperature_c']) for p in result['forecast']['points']]==[
        (p['minute'],p['oil_c'],p['temperature_c']) for p in scenario['points']]
    assert result['forecast']['served_kwh'] is None  # Observation magnitudes do not establish real power.
    assert result['forecast']['scenario_inputs_used'] is False
    assert rows==original


@pytest.mark.parametrize(('field','value','status','code'),[
    ('hotspot_c',115,'WARNING','transformer_temperature'),
    ('hotspot_c',140,'TRIP','transformer_temperature'),
    ('load_percent',130,'CRITICAL','loading_percent'),
    ('voltage_pu',1.4,'TRIP','voltage'),
])
def test_valid_threshold_breach_survives_missing_other_channel(field,value,status,code):
    row={**observations()[-1],'hotspot_c':79.,'oil_c':None,field:value}
    result=observer.assess([row])
    assert result['available'] is False and result['hypothesis']=='missing_data'
    assert result['validity']=={'forecast_allowed':False,'holds':['missing_data']}
    assert result['minutes_to_critical'] is None and 'forecast' not in result
    assert result['observed_status']==status
    assert any(a['code']==code and a['severity']==status for a in result['observed_alerts'])
    assert 'oil_c' in result['unavailable_observed_channels']
    assert 'Forecast remains withheld' in result['next_action']


@pytest.mark.parametrize('invalid',[None,float('nan'),float('inf'),9999])
def test_invalid_temperature_is_not_manufactured_into_a_threshold_alert(invalid):
    row={**observations()[-1],'hotspot_c':invalid,'load_percent':130}
    result=observer.assess([row])
    assert result['available'] is False
    assert result['observed_status']=='CRITICAL'
    assert 'hotspot_c' in result['unavailable_observed_channels']
    assert {a['code'] for a in result['observed_alerts']}=={'loading_percent'}
    row['load_percent']=70
    result=observer.assess([row])
    assert result['observed_status']=='UNKNOWN' and result['observed_alerts']==[]
    assert result['presentation_headline'].startswith('Evidence hold:')


def test_oil_only_never_promotes_inferred_hotspot_to_an_observed_breach():
    rows=observations()
    result=observer.assess(rows,temperature_mode='oil_only')
    assert result['available'] is True
    assert result['inferred_hotspot_c']>125
    assert result['observed_status']=='NORMAL' and result['observed_alerts']==[]
    assert 'hotspot_c' not in result['observed_channels']
    assert result['minutes_to_critical'] is None
    assert 'not observed in oil-only' in result['observed_scope']
    assert result['presentation_headline']=='No threshold breach in available observed channels'
    assert 'healthy' not in result['presentation_headline'].lower()
    assert observer.assess([{**r,'hotspot_c':9999} for r in rows],temperature_mode='oil_only')==result


def test_evidence_hold_stays_visible_without_measured_threshold_breach():
    result=observer.assess([{**observations()[0],'oil_c':65,'hotspot_c':79,'ambient_c':30,'load_percent':70}])
    assert result['hypothesis']=='insufficient_evidence'
    assert result['observed_status']=='NORMAL'
    assert result['presentation_headline']=='Evidence hold: insufficient evidence'
    assert result['available'] is False and result['observed_alerts']==[]


def test_empty_observations_are_unknown_and_never_healthy():
    result=observer.assess([])
    assert result['observed_status']=='UNKNOWN'
    assert result['observed_channels']==[] and result['observed_alerts']==[]
    assert set(result['unavailable_observed_channels'])==set(observer.FIELDS)
    assert result['presentation_headline']=='Evidence hold: missing data'
