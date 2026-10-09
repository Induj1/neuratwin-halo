"""The in-run observer cannot read hidden scenario state or cross revisions."""
from copy import deepcopy

from neuratwin import twin_study_api
from test_submission import client, OP, create, act


def test_observation_review_rejects_stale_revision_and_never_mutates(client):
    run = create(client, 'observation-review-test')
    path = f"/api/halo/twin/runs/{run['id']}"
    response = client.get(path+'/observation-review', params={'revision': run['revision']}, headers=OP)
    assert response.status_code == 200
    review = response.json()
    assert review['source'] == 'industrial_simulation_observations'
    assert review['scenario_labels_supplied'] is False and review['hardware_action'] is False
    assert review['assessment']['available'] is False  # An initial sample is not a reference.
    assert client.get(path, headers=OP).json() == run
    updated = act(client, run, 'start')
    stale = client.get(path+'/observation-review', params={'revision': run['revision']}, headers=OP)
    assert stale.status_code == 409
    assert client.get(path, headers=OP).json() == updated


def test_hidden_scenario_edits_do_not_change_observation_assessment(client, monkeypatch):
    run = create(client, 'observation-hidden-state')
    original = deepcopy(run)
    monkeypatch.setattr(twin_study_api, 'run_or_404', lambda _: run)
    before = twin_study_api.observation_review(run['id'], run['revision'])
    run['scenario'] = 'arbitrary hidden label'
    run['inputs']['cooling'] = 'failed'
    run['fault'] = {'kind': 'sensor_bias', 'until_s': 999999}
    run['thermal'] = {'oil_c': -999, 'hotspot_c': 999}
    after = twin_study_api.observation_review(run['id'], run['revision'])
    assert before == after
    assert original['telemetry'] == run['telemetry']
