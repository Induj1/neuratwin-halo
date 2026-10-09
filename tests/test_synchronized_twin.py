"""Phase-model, planner and replay contracts share one industrial state."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from neuratwin.app import app
from neuratwin import halo_store as store, twin_core as core, twin_studies as studies
from neuratwin.halo_api import LOCAL_TOKEN

OP = {'Authorization': 'Bearer ' + LOCAL_TOKEN}
BASE = '/api/halo/twin/runs'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB', str(tmp_path / 'synchronized.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND', 'sqlite')
    for name in ('HALO_OPERATOR_TOKEN', 'HALO_ALLOW_CONTROL'):
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as value:
        yield value


def create(client, key='synchronized-twin'):
    result = client.post(BASE, headers=OP, json={'request_id': key})
    assert result.status_code == 200, result.text
    return result.json()


def action(client, state, name, **extra):
    result = client.post(BASE + '/' + state['id'] + '/actions', headers=OP, json={
        'request_id': f"sync-command-{state['revision']:05d}",
        'revision': state['revision'], 'action': name, **extra})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize('imbalance', [0, 10, 20, 60])
def test_fundamental_phasors_mean_square_heating_and_power_balance(imbalance):
    state = core.create_state('phase-algebra')
    state['inputs'].update(load_percent=80, phase_imbalance_percent=imbalance)
    measured = core.electrical(state)
    mean = measured['secondary_current']
    u = imbalance / 100
    currents = [measured['phase_current_' + phase] for phase in 'abc']
    assert currents == pytest.approx([mean * (1 + u), mean, mean * (1 - u)])
    assert sum(currents) / 3 == pytest.approx(mean)
    assert measured['neutral_current'] == pytest.approx(math.sqrt(3) * mean * u, abs=1e-10)
    assert measured['loading_percent'] == 80
    assert measured['max_phase_loading_percent'] == pytest.approx(80 * (1 + u))
    assert measured['thermal_loading_percent'] == pytest.approx(80 * math.sqrt(1 + 2 * u*u / 3))
    rated_current = state['settings']['rated_kva'] * 1000 / (math.sqrt(3) * state['settings']['secondary_v'])
    copper = state['settings']['copper_loss_w'] * sum((value / rated_current)**2 for value in currents) / 3
    assert measured['losses_w'] == pytest.approx(state['settings']['core_loss_w'] + copper)
    input_w = math.sqrt(3) * measured['primary_voltage'] * measured['primary_current']
    output_w = measured['secondary_voltage'] / math.sqrt(3) * sum(currents)
    assert input_w == pytest.approx(output_w + measured['losses_w'])


def test_zero_default_preserves_legacy_balanced_model_and_signature():
    current = core.create_state('balanced')
    legacy = deepcopy(current)
    del legacy['inputs']['phase_imbalance_percent']
    assert core.electrical(legacy) == core.electrical(current)
    assert core.input_signature(legacy) == core.input_signature(current)
    p = current['settings']
    e = core.electrical(current)
    assert e['losses_w'] == p['core_loss_w'] + p['copper_loss_w'] * .7**2
    assert e['neutral_current'] == 0
    for state in (current, legacy):
        state['running'] = True
        core.advance(state, 300)
    assert current['oil_c'] == legacy['oil_c']
    assert current['winding_rise_c'] == legacy['winding_rise_c']


def test_imbalance_increases_electrical_stress_before_temperature_moves():
    state = core.create_state('imbalance-screening')
    before = deepcopy(core.summary(state))
    state['inputs']['phase_imbalance_percent'] = 15
    core.evaluate(state, 0)
    core.remember(state)
    after = core.summary(state)
    assert after['analysis']['stress']['electrical'] > before['analysis']['stress']['electrical']
    assert after['analysis']['operating_stress_index'] < before['analysis']['operating_stress_index']
    assert after['telemetry']['transformer_temperature'] == before['telemetry']['transformer_temperature']
    assert after['telemetry']['neutral_current'] > 0
    assert after['history'][-1]['event_cursor'] == len(state['events'])


def test_current_changes_immediately_thermal_lags_and_projection_matches_plant():
    state = core.create_state('thermal-lag')
    old = deepcopy(state['telemetry'])
    state['inputs'].update(load_percent=90, phase_imbalance_percent=15, protection_enabled=False)
    core.evaluate(state, 0)
    assert state['telemetry']['phase_current_a'] > old['phase_current_a']
    assert state['telemetry']['hotspot_temperature'] == old['hotspot_temperature']
    projection = studies.projection(state, 5)
    immutable = deepcopy(state)
    studies.sensitivity(state, 5)
    assert state == immutable
    state['running'] = True
    core.advance(state, 300)
    assert state['telemetry']['hotspot_temperature'] > old['hotspot_temperature']
    assert state['telemetry']['hotspot_temperature'] == pytest.approx(projection['points'][-1]['temperature_c'], abs=1e-10)
    assert state['telemetry']['oil_temperature'] == pytest.approx(projection['points'][-1]['oil_c'], abs=1e-10)
    assert projection['points'][-1]['max_phase_loading_percent'] == pytest.approx(103.5)


def test_phase_imbalance_and_maximum_phase_have_separate_protection_channels():
    state = core.create_state('phase-protection')
    state['inputs'].update(load_percent=90, phase_imbalance_percent=15)
    core.evaluate(state, 0)
    codes = {alert['code']: alert for alert in state['analysis']['alerts']}
    assert codes['phase_imbalance']['severity'] == 'WARNING'
    assert codes['max_phase_loading_percent']['value'] == pytest.approx(103.5)
    assert state['analysis']['health_index'] is None
    assert 'Healthy' not in core.summary(state)['health_band']
    state['inputs'].update(load_percent=60, phase_imbalance_percent=20)
    core.evaluate(state, 0)
    assert state['analysis']['status'] == 'CRITICAL'
    state['running'] = True
    core.advance(state, 115)
    assert state['breaker'] == 'CLOSED'
    core.advance(state, 5)
    assert state['breaker'] == 'OPEN'
    assert any(rule['code'] == 'phase_imbalance' for rule in state['trip']['rules'])
    assert state['trip']['before']['neutral_current'] > 0
    assert all(state['telemetry'][key] == 0 for key in core.PHASE_FIELDS)
    assert state['inputs']['phase_imbalance_percent'] == 20
    assert 'Rebalance' in ' '.join(core.recovery_holds(state))


def test_critical_phase_plan_does_not_claim_partial_shedding_corrects_imbalance():
    state = core.create_state('critical-phase-plan')
    state['inputs'].update(load_percent=60, phase_imbalance_percent=20)
    core.evaluate(state, 0)
    result = studies.plan(state, 5, 0)
    assert all(not candidate['passes'] for candidate in result['candidates'] if candidate['reduction_pct'] < 100)
    assert result['recommendation']['reduction_pct'] == 100
    assert result['recommendation']['post_phase_imbalance_percent'] == 0


def test_replay_retains_exact_components_and_marks_legacy_unavailable():
    state = core.create_state('replay')
    first = deepcopy(state['history'][0])
    state['inputs'].update(load_percent=90, phase_imbalance_percent=15)
    core.evaluate(state, 0)
    core.remember(state)
    second = deepcopy(state['history'][-1])
    assert second['analysis'] == state['analysis']
    assert second['input_context']['inputs']['phase_imbalance_percent'] == 15
    state['inputs']['load_percent'] = 10
    state['settings']['rated_kva'] = 500
    state['analysis']['stress']['loading'] = 99
    state['analysis']['alerts'].clear()
    assert state['history'][0] == first
    assert state['history'][-1] == second
    legacy = {'elapsed_s': -60, 'transformer_temperature': 40, 'health_index': 95}
    state['history'].insert(0, deepcopy(legacy))
    persisted = deepcopy(state['history'])
    result = core.summary(state)['history']
    assert result[0]['component_data_available'] is False
    assert result[0]['analysis'] is None
    assert result[1]['analysis'] == first['analysis']
    assert state['history'] == persisted
    result[-1]['analysis']['stress']['loading'] = -1
    assert state['history'][-1] == second


def test_preview_is_revision_bound_read_only_and_apply_matches_phase_plan(client):
    state = create(client)
    state = action(client, state, 'inputs', inputs={**state['inputs'], 'load_percent': 95, 'phase_imbalance_percent': 15})
    assert state['history'][-1]['input_context']['revision'] == state['revision']
    path = BASE + '/' + state['id']
    before = deepcopy(store.get('twin_run', state['id']))
    events = deepcopy(store.events(state['id'], 100))
    preview = client.get(path + '/intervention-preview', params={'revision': state['revision'], 'horizon_min': 5})
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result['preview'] is True and result['origin_revision'] == state['revision']
    assert result['run_id'] == state['id'] and result['inputs'] == state['inputs']
    assert store.get('twin_run', state['id']) == before
    assert store.events(state['id'], 100) == events
    assert store.records('twin_plan') == [] and store.records('command') == []
    assert client.get(path + '/intervention-preview').status_code == 422
    assert client.get(path + '/intervention-preview', params={'revision': state['revision'] - 1}).status_code == 409
    plan = client.post(path + '/plans', headers=OP, json={'request_id': 'synchronized-plan', 'revision': state['revision'], 'horizon_min': 5})
    assert plan.status_code == 200, plan.text
    assert plan.json()['recommendation'] == result['recommendation']
    chosen = result['recommendation']
    assert chosen['post_max_phase_loading_percent'] < state['settings']['load_warning']
    applied = client.post(path + '/apply-plan', headers=OP, json={'plan_id': plan.json()['id'], 'revision': state['revision']})
    assert applied.status_code == 200, applied.text
    updated = applied.json()
    for field in ('loading_percent', 'max_phase_loading_percent', 'thermal_loading_percent', 'phase_imbalance_percent', 'neutral_current'):
        expected = chosen['post_load_percent'] if field == 'loading_percent' else chosen['post_' + field]
        assert updated['telemetry'][field] == pytest.approx(expected)
    assert updated['telemetry']['hotspot_temperature'] == state['telemetry']['hotspot_temperature']
    assert updated['history'][-1]['analysis'] == updated['analysis']
    assert updated['inputs']['phase_imbalance_percent'] == 15
    assert any(alert['code'] == 'phase_imbalance' for alert in updated['analysis']['alerts'])
    assert store.records('command') == []
    assert client.get(path + '/intervention-preview', params={'revision': state['revision']}).status_code == 409


def test_prototype_has_no_synthetic_phase_channels_or_controls(client):
    telemetry = core.Telemetry(timestamp=datetime.now(timezone.utc), source='prototype', transformer_id='BENCH-001', temperature_kind='surface')
    assert all(telemetry.model_dump()[key] is None for key in core.PHASE_FIELDS)
    for field in core.PHASE_FIELDS:
        with pytest.raises(ValueError, match='single-phase'):
            core.Telemetry(**{**telemetry.model_dump(), field: 0})
    assert client.get(BASE + '/BENCH-001/intervention-preview', params={'revision': 0}).status_code == 404
    assert store.records('command') == []


def test_prototype_alarm_withholds_condition_score_without_new_controls(client, monkeypatch):
    from test_halo import configure, calibration, frame
    monkeypatch.setenv('HALO_DEVICE_TOKEN', 'synchronized-device-fixture')
    configure(client)
    calibration(client)
    response = client.post('/api/halo/telemetry', headers={'Authorization': 'Bearer synchronized-device-fixture'},
                           json=frame(current_a=1.2, calibration_id='CAL-TEST'))
    assert response.status_code == 200, response.text
    result = client.get('/api/halo/twin/prototype').json()
    assert result['analysis']['status'] == 'TRIP'
    assert result['analysis']['health_index'] is None
    assert result['analysis']['operating_stress_index'] is not None
    assert result['analysis']['health_evidence']['state'] == 'review_required'
    assert all(result['telemetry'][key] is None for key in core.PHASE_FIELDS)
    assert store.records('command') == []


def test_warning_report_preserves_components_and_unknown_condition_change(client):
    state = create(client)
    state = action(client, state, 'inputs', inputs={**state['inputs'], 'phase_imbalance_percent': 15})
    result = client.get(BASE + '/' + state['id'] + '/report')
    assert result.status_code == 200, result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        report = json.loads(archive.read('run.json'))
        assert report['metrics']['health_change'] is None
        assert report['full_history'][-1]['analysis'] == state['analysis']
        assert report['full_history'][-1]['component_data_available'] is True
        assert b'Unavailable while condition evidence is withheld' in archive.read('report.html')


@pytest.mark.parametrize('imbalance', [-1, 61, float('nan'), float('inf')])
def test_phase_input_validation(imbalance):
    with pytest.raises(ValueError):
        core.Inputs(phase_imbalance_percent=imbalance)
