"""Public-data forecast routes preserve evidence and never control the twin/rig."""
from datetime import datetime, timedelta
import json
import math

import pytest

from neuratwin import external_forecast as ef, halo_store as store
from test_submission import client, OP, BASE, create, act


REPORT = '/api/halo/twin/external-forecast'
DEMO = REPORT + '/demo'


def test_public_report_preserves_evidence_units_and_negative_result(client):
    response = client.get(REPORT, headers=OP)
    assert response.status_code == 200, response.text
    result = response.json()
    retained = json.loads(ef.REPORT_PATH.read_text(encoding='utf-8'))
    assert result == {'available': True, 'status': 'evaluated_public_reference',
                      'integrity': True, **retained}
    assert result['dataset'] == 'ETTh1' and result['units'] == 'source units'
    assert result['source_sha256'] == ef.source_hashes()
    assert result['sha256'] == ef.digest({k:v for k,v in retained.items() if k != 'sha256'})
    assert result['provenance']['license'] == 'CC BY-ND 4.0'
    assert 'not specified' in result['provenance']['physical_units']
    assert 'Not physical-bench validation' in result['scope']
    for horizon in ('1', '6'):
        selected = result['selected_models'][horizon]
        assert selected == min(result['validation'][horizon],
                               key=lambda name: result['validation'][horizon][name]['mae'])
        selected_error = result['test'][horizon][selected]['mae']
        baseline_error = result['test'][horizon]['persistence']['mae']
        reduction = result['paired_test_comparisons'][horizon]['persistence']['mae_reduction_percent']
        assert reduction == pytest.approx((baseline_error-selected_error)/baseline_error*100)
        # The retained trial lost to persistence on both horizons; never hide that result.
        assert reduction < 0


@pytest.mark.parametrize('origin', [11520, 14393])
def test_public_demo_valid_boundaries_and_explicit_later_reference(client, origin):
    response = client.get(DEMO, params={'origin_index': origin}, headers=OP)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['source'] == 'external_public_dataset' and result['dataset'] == 'ETTh1'
    assert result['origin_index'] == origin and result['units'] == 'source units'
    assert len(result['history']) == 48
    assert result['history'][-1]['timestamp'] == result['origin_timestamp']
    assert 'never enter prefix inference' in result['reveal_note']
    assert [p['horizon_hours'] for p in result['forecasts']] == [1, 6]
    current = result['history'][-1]['oil']
    for point in result['forecasts']:
        assert point['units'] == 'source units'
        assert point['persistence_oil'] == current
        assert all(math.isfinite(point[name]) for name in ('predicted_oil', 'actual_oil', 'seasonal_oil'))
        assert datetime.fromisoformat(point['target_timestamp']) == (
            datetime.fromisoformat(result['origin_timestamp']) + timedelta(hours=point['horizon_hours']))
    json.dumps(result, allow_nan=False)  # API contract must remain strict JSON.


def test_demo_passes_only_the_observed_prefix_to_inference(client, monkeypatch):
    observed = []
    original = ef.predict_prefix

    def spy(prefix, horizon_hours, artifact=None):
        observed.append((len(prefix), prefix[0]['date'], prefix[-1]['date'], horizon_hours))
        return original(prefix, horizon_hours, artifact)

    monkeypatch.setattr(ef, 'predict_prefix', spy)
    result = client.get(DEMO, headers=OP)
    assert result.status_code == 200, result.text
    origin = datetime.fromisoformat(result.json()['origin_timestamp'])
    assert len(observed) == 2
    for count, first, last, horizon in observed:
        assert count == 169 and horizon in (1, 6)
        assert datetime.fromisoformat(last) == origin
        assert datetime.fromisoformat(first) == origin - timedelta(hours=168)


def test_public_demo_does_not_mutate_either_industrial_run_or_hardware(client):
    run = create(client, 'external-public-independence')
    other = create(client, 'external-public-other-run')
    run = act(client, run, 'inputs', inputs={**run['inputs'], 'load_percent': 121})
    run = act(client, run, 'start')
    run = act(client, run, 'step', seconds=300)
    before = {s['id']: client.get(BASE+s['id'], headers=OP).json() for s in (run, other)}
    audit = {s['id']: store.events(s['id']) for s in (run, other)}
    with store.connection() as db:
        record_counts = tuple(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                              for table in ('halo_records', 'halo_frames', 'halo_events'))
    for path in (REPORT, DEMO, DEMO+'?origin_index=14393'):
        response = client.get(path, headers=OP)
        assert response.status_code == 200, response.text
    assert {key: client.get(BASE+key, headers=OP).json() for key in before} == before
    assert {key: store.events(key) for key in audit} == audit
    assert store.records('command') == []
    with store.connection() as db:
        assert tuple(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                     for table in ('halo_records', 'halo_frames', 'halo_events')) == record_counts


@pytest.mark.parametrize('origin', ['11519', '14394', 'true', 'not-a-number', '11520.5'])
def test_demo_query_rejects_invalid_origins_before_inference(client, monkeypatch, origin):
    def must_not_run(**kwargs):
        raise AssertionError('Invalid query reached model inference.')
    monkeypatch.setattr(ef, 'demo', must_not_run)
    response = client.get(DEMO, params={'origin_index': origin}, headers=OP)
    assert response.status_code == 422


@pytest.mark.parametrize('error', [ValueError('integrity mismatch'), FileNotFoundError('missing artifact')])
def test_report_failure_is_a_non_sensitive_conflict(client, monkeypatch, error):
    def unavailable():
        raise error
    monkeypatch.setattr(ef, 'public_status', unavailable)
    response = client.get(REPORT, headers=OP)
    assert response.status_code == 409
    assert response.json() == {'detail': 'Public evaluation artifacts are missing or differ from the recorded source. Revalidation required.'}


@pytest.mark.parametrize('error', [ValueError('unverified public evidence'), FileNotFoundError('missing artifact')])
def test_demo_refuses_unavailable_evidence(client, monkeypatch, error):
    def unavailable(**kwargs):
        raise error
    monkeypatch.setattr(ef, 'demo', unavailable)
    response = client.get(DEMO, headers=OP)
    assert response.status_code == 422
    if isinstance(error,FileNotFoundError):
        assert str(error) not in response.text
        assert 'artifacts are unavailable' in response.json()['detail']
    else:
        assert response.json()['detail'] == str(error)


def test_absent_report_is_explicitly_unavailable_and_demo_is_withheld(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ef, 'REPORT_PATH', tmp_path/'absent-report.json')
    report = client.get(REPORT, headers=OP)
    assert report.status_code == 200
    assert report.json() == {'available': False, 'status': 'not_evaluated', 'scope': ef.SCOPE}
    assert client.get(DEMO, headers=OP).status_code == 422


def test_real_missing_model_with_retained_report_fails_closed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ef, 'DATA_DIR', tmp_path)
    assert client.get(REPORT, headers=OP).status_code == 409
    response=client.get(DEMO, headers=OP)
    assert response.status_code == 422
    assert str(tmp_path) not in response.text
    assert 'forecast-models.json' not in response.text


def test_real_modified_report_is_not_served_or_used_for_demo(client, tmp_path, monkeypatch):
    report = json.loads(ef.REPORT_PATH.read_text(encoding='utf-8'))
    report['units'] = 'fabricated degrees C'
    altered = tmp_path/'altered-report.json'
    altered.write_text(json.dumps(report), encoding='utf-8')
    monkeypatch.setattr(ef, 'REPORT_PATH', altered)
    assert client.get(REPORT, headers=OP).status_code == 409
    assert client.get(DEMO, headers=OP).status_code == 422


def test_current_source_mismatch_blocks_report_and_demo(client, monkeypatch):
    expected = ef.source_hashes()
    monkeypatch.setattr(ef, 'source_hashes', lambda: {**expected, 'requirements.txt': 'unvalidated-changes'})
    assert client.get(REPORT, headers=OP).status_code == 409
    assert client.get(DEMO, headers=OP).status_code == 422
