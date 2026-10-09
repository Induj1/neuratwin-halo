"""Imported observations retain their own maintenance/evidence identity."""
from copy import deepcopy
import csv
import io
import json
import pytest
from test_submission import client, OP
from test_cloud import backend
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import halo_store as store, twin_observer as observer, twin_studies as studies
from neuratwin.validation_plant import generate

BASE = '/api/halo/twin/challenges'


def payload(key, *, asset='REFERENCE-TX-001', start='2026-01-01T00:00:00Z', reviewed=True, source='synthetic'):
    rows, _, _ = generate(88001, 'healthy')
    # Retain the independently excited first-70 commissioning prefix; make the
    # final comparison window an explicitly synthetic stable operating segment.
    for row in rows[75:]:
        row.update(load_percent=70, ambient_c=30, voltage_pu=1)
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=list(observer.FIELDS))
    writer.writeheader(); writer.writerows(rows)
    return {'request_id': key, 'temperature_mode': 'oil_only', 'csv_text': out.getvalue(),
            'name': 'Synthetic reference workflow fixture', 'origin_index': 90, 'healthy_reference_reviewed': True,
            'provenance': {'asset_id': asset, 'source_class': source, 'recording_started_at': start,
                'units_verified': reviewed, 'calibration_reference': 'synthetic-scale-v1' if reviewed else None,
                'calibration_reviewed': reviewed, 'configuration_reference': 'synthetic-transformer-v1' if reviewed else None,
                'configuration_reviewed': reviewed, 'reviewer': 'Fixture reviewer', 'note': 'Synthetic source and assumed configuration only.'}}


def imported(c, key='reference-origin', **options):
    r = c.post(BASE + '/import', headers=OP, json=payload(key, **options))
    assert r.status_code == 200, r.text
    value = r.json(); r = c.post(BASE + '/' + value['id'] + '/assess', headers=OP)
    assert r.status_code == 200, r.text
    return r.json()


def work(c, origin, **options):
    p = {'request_id': 'reference-work-01', 'title': 'Inspect the recorded thermal condition', 'owner': 'Reference reviewer',
         'acceptance_note': 'Review comparable later observations; this is not physical repair verification.', **options}
    r = c.post(BASE + '/' + origin['id'] + '/work', headers=OP, json=p)
    assert r.status_code == 200, r.text
    return r.json()


def observe(c, w, kind, *, request_id=None, at=None):
    p = {'request_id': request_id or 'reference-' + kind, 'revision': w['revision'], 'kind': kind,
         'observed_at': at or ('2026-01-01T01:31:00Z' if kind == 'inspection' else '2026-01-01T01:32:00Z'),
         'note': 'Reviewer recorded this retrospective ' + kind + '; no physical control issued.'}
    r = c.post(BASE + '/' + w['case_id'] + '/work/' + w['id'] + '/observations', headers=OP, json=p)
    assert r.status_code == 200, r.text
    return r.json(), p


def link(c, w, follow):
    p = {'request_id': 'reference-followup', 'revision': w['revision'], 'case_id': follow['id'],
         'note': 'Separate later reference recording from the same declared asset.'}
    return c.post(BASE + '/' + w['case_id'] + '/work/' + w['id'] + '/followup', headers=OP, json=p)


def prepared(c, *, reviewed=True):
    origin = imported(c, reviewed=reviewed)
    w = work(c, origin); w, _ = observe(c, w, 'inspection'); w, _ = observe(c, w, 'action')
    follow = imported(c, 'reference-followup-01', start='2026-01-02T00:00:00Z', reviewed=reviewed)
    r = link(c, w, follow); assert r.status_code == 200, r.text
    return origin, follow, r.json()


def test_imported_chain_is_case_scoped_persistent_and_never_physical(client):
    origin, follow, w = prepared(client)
    url = BASE + '/' + origin['id']
    assert w['asset_id'] == 'REFERENCE-TX-001' and 'run_id' not in w
    assert w['origin']['assessment_sha256'] == origin['assessment']['sha256']
    assert w['followups'][0]['evidence']['assessment_sha256'] == follow['assessment']['sha256']
    assert not w['physical_repair_verified']
    assert w['verification']['eligible'], w['verification']
    close_payload = {'request_id': 'close-reference-01', 'revision': w['revision'], 'note': 'Comparable reference criteria are met; physical repair is not established.'}
    closed = client.post(url + '/work/' + w['id'] + '/close', headers=OP, json=close_payload)
    assert closed.status_code == 200, closed.text
    w = closed.json()
    assert w['status'] == 'closed_reference_review' and not w['closure']['physical_repair_verified']
    assert client.post(url + '/work/' + w['id'] + '/close', headers=OP, json=close_payload).json() == w
    stored = client.get(url + '/workflow').json()['work_orders'][0]
    assert stored == w
    assert client.get(url + '/workflow/export').status_code == 409
    for identifier in (origin['id'], follow['id']):
        assert client.post(BASE + '/' + identifier + '/reveal', headers=OP).status_code == 200
    bundle = client.get(url + '/workflow/export').json()
    assert studies.digest({k: v for k, v in bundle.items() if k != 'sha256'}) == bundle['sha256']
    assert bundle['origin_recording']['assessment'] == store.get('twin_challenge', origin['id'])['assessment']
    assert bundle['followup_recordings'][0]['case']['id'] == follow['id']
    assert bundle['physical_repair_verified'] is False


def test_missing_review_metadata_blocks_quantitative_acceptance(client):
    origin, _, w = prepared(client, reviewed=False)
    assert not w['verification']['eligible']
    assert any('calibration' in h for h in w['verification']['holds'])
    assert any('units' in h for h in w['verification']['holds'])
    r = client.post(BASE + '/' + origin['id'] + '/work/' + w['id'] + '/close', headers=OP,
                    json={'request_id': 'close-reference-01', 'revision': w['revision'], 'note': 'Attempted reference acceptance.'})
    assert r.status_code == 423
    assert store.get('observation_work', w['id'])['status'] == 'verification_pending'


def test_downloaded_artifact_keeps_integer_valued_floats_and_nested_hashes(client, tmp_path):
    origin = imported(client, 'artifact-number-format')
    assert client.post(BASE + '/' + origin['id'] + '/reveal', headers=OP).status_code == 200
    response = client.get(BASE + '/' + origin['id'] + '/workflow/export')
    assert response.status_code == 200, response.text
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['cache-control'] == 'no-store'
    artifact = tmp_path / 'downloaded-evidence.json'
    artifact.write_bytes(response.content)
    bundle = json.loads(artifact.read_bytes())
    reading = bundle['origin_recording']['rows'][75]
    assert reading['ambient_c'] == 30.0 and isinstance(reading['ambient_c'], float)
    assert b'"ambient_c": 30.0' in artifact.read_bytes()
    assert studies.digest({k: v for k, v in bundle.items() if k != 'sha256'}) == bundle['sha256']
    assessment = bundle['origin_recording']['assessment']
    assert studies.digest(assessment['result']) == assessment['sha256']
    binding = bundle['workflow']['binding']
    assert studies.digest({k: v for k, v in binding.items() if k != 'sha256'}) == binding['sha256']
    assert studies.digest(bundle['origin_recording']['rows']) == binding['recording_sha256']


def test_cloud_cookie_member_can_download_raw_artifact(backend, monkeypatch):
    from neuratwin import auth
    key = 'cloud-artifact-fixture'
    # Minimal already-revealed legacy record isolates authentication/transport;
    # the complete assessed-record integrity path is exercised above.
    with store.transaction():
        store.put('twin_challenge', key, {'id': key, 'source': 'imported reference',
                  'revealed': True, 'rows': [{'elapsed_s': 10.0}], 'settings': {}})
    claims_seen = []
    def cookie_claims(token):
        claims_seen.append(token)
        return {'sub': '12345678-1234-1234-1234-123456789012'}
    monkeypatch.setattr(auth, 'claims', cookie_claims)
    with TestClient(app) as c:
        url = BASE + '/' + key + '/workflow/export'
        assert c.get(url).status_code == 401
        c.cookies.set(auth.ACCESS, 'test-member-cookie')
        response = c.get(url)
        assert response.status_code == 200, response.text
        bundle = json.loads(response.content)
        assert isinstance(bundle['origin_recording']['rows'][0]['elapsed_s'], float)
        assert studies.digest({k: v for k, v in bundle.items() if k != 'sha256'}) == bundle['sha256']
        assert claims_seen == ['test-member-cookie']


def test_raw_case_export_preserves_hashes_and_conceals_future_until_revealed(client, tmp_path):
    origin = imported(client, 'raw-blind-export-case')
    url = BASE + '/' + origin['id']
    before = client.get(url)
    assert before.status_code == 200
    artifact = tmp_path / 'case-before-reveal.json'
    artifact.write_bytes(before.content)
    case = json.loads(artifact.read_bytes())
    assert 'reveal' not in case and 'observed_future' not in case
    assert studies.digest(case['assessment']['result']) == case['assessment']['sha256']
    assert studies.digest({k: v for k, v in case['binding'].items() if k != 'sha256'}) == case['binding']['sha256']
    assert client.post(url + '/reveal', headers=OP).status_code == 200
    after = client.get(url)
    artifact.write_bytes(after.content)
    case = json.loads(artifact.read_bytes())
    assert isinstance(case['reveal']['rows'][75]['ambient_c'], float)
    assert studies.digest(case['reveal']) == case['commitment']
    assert studies.digest(case['assessment']['result']) == case['assessment']['sha256']


def test_work_idempotency_revision_and_inspection_order(client):
    origin = imported(client); w = work(client, origin)
    assert work(client, origin) == w
    url = BASE + '/' + origin['id'] + '/work/' + w['id'] + '/observations'
    p = {'request_id': 'reference-action', 'revision': 0, 'kind': 'action',
         'observed_at': '2026-01-01T01:32:00Z', 'note': 'Must not bypass the recorded inspection.'}
    assert client.post(url, headers=OP, json=p).status_code == 422
    w, p = observe(client, w, 'inspection')
    assert client.post(url, headers=OP, json=p).json() == w
    assert client.post(url, headers=OP, json={**p, 'note': 'Conflicting use of the same request ID.'}).status_code == 409
    assert client.post(url, headers=OP, json={**p, 'request_id': 'new-inspection-id'}).status_code == 409
    assert len(store.get('observation_work', w['id'])['trail']) == 1


@pytest.mark.parametrize('options', [{'asset': 'OTHER-ASSET'}, {'source': 'recorded_oil_reference'}])
def test_followup_cannot_cross_asset_or_source(client, options):
    origin = imported(client); w = work(client, origin)
    w, _ = observe(client, w, 'inspection'); w, _ = observe(client, w, 'action')
    follow = imported(client, 'wrong-followup-01', start='2026-01-02T00:00:00Z', **options)
    assert link(client, w, follow).status_code == 422
    assert not store.get('observation_work', w['id'])['followups']


def test_provenance_is_immutable_and_legacy_binding_does_not_change_samples(client):
    p = payload('legacy-import-01'); provenance = p.pop('provenance')
    r = client.post(BASE + '/import', headers=OP, json=p); assert r.status_code == 200, r.text
    key = r.json()['id']; original = deepcopy(store.get('twin_challenge', key))
    request = {'request_id': 'bind-legacy-01', 'provenance': provenance}
    url = BASE + '/' + key + '/binding'
    assert client.post(url, headers=OP, json=request).status_code == 200
    assert store.get('twin_challenge', key) == original
    assert client.post(url, headers=OP, json=request).status_code == 200
    assert client.post(url, headers=OP, json={**request, 'provenance': {**provenance, 'asset_id': 'DIFFERENT'}}).status_code == 409


def test_case_binding_detects_recording_and_assessment_tampering(client):
    origin = imported(client); w = work(client, origin)
    c = store.get('twin_challenge', origin['id']); c['assessment']['result']['available'] = not c['assessment']['result']['available']
    store.put('twin_challenge', origin['id'], c)
    assert client.get(BASE + '/' + origin['id'] + '/workflow').status_code == 409


def test_action_times_and_followup_chronology_are_not_inferred(client):
    origin = imported(client); w = work(client, origin)
    url = BASE + '/' + origin['id'] + '/work/' + w['id']
    invalid = {'request_id': 'too-early-action', 'revision': 0, 'kind': 'inspection',
               'observed_at': '2026-01-01T00:30:00Z', 'note': 'Timestamp predates the originating observation.'}
    assert client.post(url + '/observations', headers=OP, json=invalid).status_code == 422
    w, _ = observe(client, w, 'inspection'); w, _ = observe(client, w, 'action')
    follow = imported(client, 'old-followup-01')
    linked = link(client, w, follow); assert linked.status_code == 200, linked.text
    assert any('after the recorded action' in h for h in linked.json()['verification']['holds'])


def test_changed_operating_conditions_and_calibration_prevent_acceptance(client):
    origin = imported(client); w = work(client, origin)
    w, _ = observe(client, w, 'inspection'); w, _ = observe(client, w, 'action')
    p = payload('changed-context-01', start='2026-01-02T00:00:00Z')
    p['provenance']['calibration_reference'] = 'different-scale-v2'
    rows = list(csv.DictReader(io.StringIO(p['csv_text'])))
    for r in rows[75:]: r['ambient_c'] = 39
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=list(observer.FIELDS));writer.writeheader();writer.writerows(rows)
    p['csv_text'] = out.getvalue()
    r = client.post(BASE + '/import', headers=OP, json=p); assert r.status_code == 200, r.text
    follow = client.post(BASE + '/' + r.json()['id'] + '/assess', headers=OP).json()
    response = link(client, w, follow); assert response.status_code == 200, response.text
    holds = response.json()['verification']['holds']
    assert any('calibration reference' in h for h in holds)
    assert any('ambient_difference_c' in h for h in holds)


def test_missing_or_earlier_breached_followup_never_closes(client):
    origin = imported(client); w = work(client, origin)
    w, _ = observe(client, w, 'inspection'); w, _ = observe(client, w, 'action')
    p = payload('missing-followup-01', start='2026-01-02T00:00:00Z')
    rows = list(csv.DictReader(io.StringIO(p['csv_text'])))
    rows[83]['load_percent'] = '110'
    rows[84]['oil_c'] = ''
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=list(observer.FIELDS));writer.writeheader();writer.writerows(rows)
    p['csv_text'] = out.getvalue()
    r = client.post(BASE + '/import', headers=OP, json=p); assert r.status_code == 200, r.text
    follow = client.post(BASE + '/' + r.json()['id'] + '/assess', headers=OP).json()
    result = link(client, w, follow).json()
    assert not result['verification']['eligible']
    assert any('missing' in h for h in result['verification']['holds'])


def test_old_idempotency_digest_remains_compatible(client):
    p = payload('old-client-case'); p.pop('provenance')
    result = client.post(BASE + '/import', headers=OP, json=p); assert result.status_code == 200, result.text
    c = store.get('twin_challenge', result.json()['id']);c['request_digest'] = studies.digest(p)
    store.put('twin_challenge', c['id'], c)
    assert client.post(BASE + '/import', headers=OP, json=p).status_code == 200


def test_optional_phase_scope_is_preserved_at_import_and_assessment(client):
    p = payload('phase-aware-recording')
    rows = list(csv.DictReader(io.StringIO(p['csv_text'])))
    for r in rows:r['phase_imbalance_percent'] = 20
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=[*observer.FIELDS, 'phase_imbalance_percent'])
    writer.writeheader();writer.writerows(rows);p['csv_text'] = out.getvalue()
    response = client.post(BASE + '/import', headers=OP, json=p)
    assert response.status_code == 200, response.text
    key = response.json()['id']; stored = store.get('twin_challenge', key)
    assert all(r['phase_imbalance_percent'] == 20 for r in stored['rows'])
    result = client.post(BASE + '/' + key + '/assess', headers=OP).json()['assessment']['result']
    assert result['phase_scope']['imbalance_percent'] == 20
    assert result['observed_status'] == 'CRITICAL'
    assert 'phase_imbalance' in result['hypotheses']


def test_incomplete_declared_phase_prefix_cannot_silently_calibrate_as_balanced(client):
    p = payload('incomplete-phase-prefix')
    rows = list(csv.DictReader(io.StringIO(p['csv_text'])))
    for r in rows:r['phase_current_a'] = 10
    out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=[*observer.FIELDS, 'phase_current_a'])
    writer.writeheader();writer.writerows(rows);p['csv_text'] = out.getvalue()
    response = client.post(BASE + '/import', headers=OP, json=p)
    assert response.status_code == 422, response.text
    assert 'phase' in response.text.lower()
    assert store.get('twin_challenge', 'RECORDING-incomplete-phase-prefix') is None


def test_transaction_rolls_back_work_if_audit_write_fails(client, monkeypatch):
    origin = imported(client)
    def fail(*args, **kwargs): raise RuntimeError('forced audit failure')
    monkeypatch.setattr(store, 'event', fail)
    with pytest.raises(RuntimeError, match='forced audit failure'): work(client, origin)
    assert not store.records('observation_work')


def test_writes_require_operator_and_cloud_reads_require_membership(client, backend):
    with TestClient(app) as c:
        assert c.get(BASE).status_code == 401
        assert c.get(BASE + '/unknown/workflow').status_code == 401
        assert c.post(BASE + '/unknown/work', json={}).status_code == 401
