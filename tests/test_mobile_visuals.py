from copy import deepcopy
import math
import pytest
from neuratwin import twin_core as core, twin_studies as studies


def test_phase_balance_conservation_and_neutral():
    state=core.create_state('phases')
    balanced=core.electrical(state)
    assert len(set([balanced['phase_current_'+p] for p in 'abc']))==1
    assert balanced['neutral_current']==pytest.approx(0,abs=1e-9)
    state['inputs']['phase_imbalance_percent']=35
    core.evaluate(state,0)
    unbalanced=core.electrical(state)
    assert sum([unbalanced['phase_current_'+p] for p in 'abc'])/3==pytest.approx(balanced['secondary_current'])
    assert unbalanced['neutral_current']==pytest.approx(math.sqrt(3)*.35*balanced['secondary_current'])
    assert unbalanced['losses_w']>balanced['losses_w']
    assert math.sqrt(3)*unbalanced['primary_voltage']*unbalanced['primary_current']==pytest.approx(math.sqrt(3)*unbalanced['secondary_voltage']*unbalanced['secondary_current']+unbalanced['losses_w'])
    assert state['analysis']['stress']['electrical']==70
    assert any(a['code']=='phase_imbalance' for a in state['analysis']['alerts'])
    plan=studies.plan(state,60,0)
    assert plan['recommendation'] is None or plan['recommendation']['post_phase_imbalance_percent'] < core.PHASE_CRITICAL


def test_phase_heating_projection_and_recorded_health():
    state=core.create_state('history')
    state['inputs'].update(phase_imbalance_percent=15,protection_enabled=False)
    core.evaluate(state,0);core.remember(state)
    frame=deepcopy(state['history'][-1])
    projected=studies.projection(state,20)
    state['running']=True;core.advance(state,1200)
    assert state['telemetry']['transformer_temperature']==pytest.approx(projected['points'][-1]['temperature_c'],abs=.05)
    assert state['history'][1]==frame
    assert frame['analysis']['stress']['electrical']==30
    assert frame['phase_current_a']>frame['phase_current_b']
    core.trip(state,'test');core.evaluate(state,0)
    assert [state['telemetry']['phase_current_'+p] for p in 'abc']==[0,0,0]
    assert state['telemetry']['neutral_current']==0


def test_prototype_does_not_claim_three_phase_measurements():
    state=core.create_state('prototype-contract')
    payload={**state['telemetry'],'source':'prototype','temperature_kind':'surface'}
    for key in ('oil_temperature','hotspot_temperature','oil_level_percent','oil_condition','gas_indicator'):
        payload[key]=None
    with pytest.raises(ValueError):core.Telemetry(**payload)
    with pytest.raises(ValueError):core.Inputs(phase_imbalance_percent=70)
