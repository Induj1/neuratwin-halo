"""Wi-Fi ESP32 integration against a mocked board. No network, port or hardware."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from neuratwin import halo_esp32 as esp32
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN

OP = {'Authorization': 'Bearer ' + LOCAL_TOKEN}


class FakeBoard:
    """Minimal stand-in for esp32_integration.ino's JSON routes."""

    def __init__(self):
        self.sequence = 7
        self.loads = {'load1': True, 'load2': True, 'load4': False}
        self.requests = []
        self.offline = False
        self.surface = 31.5

    def reading(self):
        states = [self.loads['load1'], self.loads['load2'], False, self.loads['load4']]
        return {'ok': True, 'device_id': 'HALO-ESP32', 'boot_id': 'abc123', 'sequence': self.sequence, 'uptime_ms': 1000 * self.sequence,
                'mains_present': True, 'primary_v': 229.4, 'primary_current_a': 0.018, 'primary_current_method': 'calculated',
                'primary_current_measured_a': 0.0, 'secondary_v': 12.1, 'current_a': 0.61, 'expected_current_a': 0.62,
                'surface_c': self.surface, 'temperature_probe_ok': self.surface is not None, 'current_calibrated': True,
                'calibration_status': 'OK', 'relay_output_configured': True, 'relay_states': states,
                'loads': {**self.loads, 'loads_on': sum(states), 'relay_states': states},
                'quality_flags': [] if self.surface is not None else ['surface_invalid'],
                'raw': {'primary_fund_mv': 395.5, 'secondary_fund_mv': 21.8, 'current_raw_mv': 63.0, 'current_corr_mv': 61.2, 'samples': 1300}}

    def handler(self, request: httpx.Request):
        self.requests.append((request.method, request.url.path, request.headers.get('authorization')))
        if self.offline:
            raise httpx.ConnectError('no route to host')
        if request.headers.get('authorization') != 'Bearer test-device-only' and request.url.path != '/healthz':
            return httpx.Response(401, json={'ok': False, 'error': 'Invalid token.'})
        path, method = request.url.path, request.method
        if path == '/healthz':
            return httpx.Response(200, json={'ok': True, 'firmware': 'esp32_integration', 'device_id': 'HALO-ESP32', 'boot_id': 'abc123', 'uptime_ms': 5000,
                                             'wifi': {'connected': True, 'rssi_dbm': -58}})
        if path == '/api/readings':
            return httpx.Response(200, json=self.reading())
        if path == '/api/loads' and method == 'GET':
            return httpx.Response(200, json={'ok': True, 'loads': self.reading()['loads']})
        if path == '/api/loads' and method == 'POST':
            body = json.loads(request.content)
            if 'load' in body:
                self.loads[f'load{body["load"]}'] = body['state']
            for k in ('load1', 'load2', 'load4'):
                if k in body:
                    self.loads[k] = body[k]
            return httpx.Response(200, json={'ok': True, 'loads': self.reading()['loads']})
        if path == '/api/calibration' and method == 'GET':
            return httpx.Response(200, json={'ok': True, 'calibration': {'current_method': 'ohm', 'status': 'OK'}})
        if path == '/api/calibration' and method == 'POST':
            body = json.loads(request.content)
            if body['action'] == 'mains_voltage':
                return httpx.Response(200, json={'ok': True, 'action': 'mains_voltage', 'log': 'Mains calibrated to %.2f V. Saved.\n' % body['value'],
                                                 'calibration': {'mains_v_factor': 0.58}})
            return httpx.Response(422, json={'ok': False, 'action': body['action'], 'log': 'Aborted: mains is OFF. Switch mains ON first.\n',
                                             'calibration': {'mains_v_factor': 0.58}})
        return httpx.Response(404, json={'ok': False, 'error': 'Unknown route.'})


@pytest.fixture()
def board(monkeypatch):
    fake = FakeBoard()
    monkeypatch.setattr(esp32, 'TRANSPORT', httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture()
def client(tmp_path, monkeypatch, board):
    monkeypatch.setenv('NEURATWIN_DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('HALO_DEVICE_TOKEN', 'test-device-only')
    monkeypatch.setenv('HALO_ESP32_URL', 'http://board.test')
    monkeypatch.setenv('HALO_ESP32_POLL_SECONDS', '30')  # background loop stays out of the way; tests poll explicitly
    monkeypatch.delenv('HALO_OPERATOR_TOKEN', raising=False)
    monkeypatch.delenv('HALO_ALLOW_CONTROL', raising=False)
    monkeypatch.delenv('HALO_AI_ENABLED', raising=False)
    with TestClient(app) as c:
        yield c


def test_frame_mapping_keeps_calculated_primary_current_out_of_measurements(board):
    f = esp32.to_frame(board.reading())
    assert f.device_id == 'HALO-ESP32' and f.sequence == 7 and f.secondary_v == 12.1 and f.current_a == 0.61 and f.surface_c == 31.5
    assert f.primary_v == 229.4 and f.primary_current_a is None
    assert f.raw['primary_current_calculated_a'] == 0.018 and f.raw['expected_current_a'] == 0.62
    assert f.relay_states == (True, True, False, False) and f.relay_output_configured
    assert 'primary_current_calculated' in f.quality_flags and 'calibration_unrecorded' in f.quality_flags
    assert f.timestamp.utcoffset() is not None


def test_frame_mapping_drops_invalid_probe_and_out_of_range(board):
    board.surface = None
    r = board.reading()
    r['secondary_v'] = 400
    f = esp32.to_frame(r)
    assert f.surface_c is None and f.secondary_v is None
    assert 'surface_invalid' in f.quality_flags and 'secondary_v_out_of_range' in f.quality_flags


def test_poll_forwards_reading_into_telemetry_once_per_sequence(client, board):
    s = client.post('/api/halo/esp32/poll', headers=OP).json()
    assert s['status'] == 'connected' and s['reachable'] and s['forwarded'] == 1 and s['last_sequence'] == 7
    snap = client.get('/api/halo/snapshot').json()
    assert snap['connection'] == 'live' and snap['current']['secondary_v'] == 12.1 and snap['current']['surface_c'] == 31.5
    assert snap['current']['relay_states'] == [True, True, False, False]
    # Same board sequence again: cached, not re-ingested.
    s = client.post('/api/halo/esp32/poll', headers=OP).json()
    assert s['forwarded'] == 1 and s['forward_failures'] == 0
    board.sequence += 1
    s = client.post('/api/halo/esp32/poll', headers=OP).json()
    assert s['forwarded'] == 2 and s['last_sequence'] == 8
    assert all(auth == (None if path == '/healthz' else 'Bearer test-device-only') for _, path, auth in board.requests)


def test_status_and_readings_degrade_when_board_disappears(client, board):
    client.post('/api/halo/esp32/poll', headers=OP)
    live = client.get('/api/halo/esp32/readings').json()
    assert live['live'] and not live['stale'] and live['reading']['sequence'] == 7
    board.offline = True
    s = client.post('/api/halo/esp32/poll', headers=OP).json()
    assert s['status'] == 'unreachable' and not s['reachable'] and s['consecutive_failures'] == 1 and 'unreachable' in s['last_error']
    assert client.get('/api/halo/esp32/healthz').status_code == 503
    cached = client.get('/api/halo/esp32/readings').json()
    assert cached['stale'] and cached['reading']['sequence'] == 7 and cached['readings_at']
    status = client.get('/api/halo/esp32/status').json()
    assert status['configured'] and status['poller']['status'] == 'unreachable' and 'readings' not in status['poller']


def test_loads_are_proxied_only_when_control_is_enabled(client, board, monkeypatch):
    r = client.post('/api/halo/esp32/loads', json={'load': 4, 'state': True}, headers=OP)
    assert r.status_code == 423 and board.loads['load4'] is False
    monkeypatch.setenv('HALO_ALLOW_CONTROL', '1')
    assert client.post('/api/halo/esp32/loads', json={'load': 4, 'state': True}).status_code == 401
    r = client.post('/api/halo/esp32/loads', json={'load': 4, 'state': True}, headers=OP)
    assert r.status_code == 200 and r.json()['loads']['load4'] is True and board.loads['load4'] is True
    r = client.post('/api/halo/esp32/loads', json={'load1': False, 'load2': False}, headers=OP)
    assert r.status_code == 200 and r.json()['loads']['relay_states'] == [False, False, False, True]
    assert client.post('/api/halo/esp32/loads', json={'load': 3, 'state': True}, headers=OP).status_code == 422
    assert client.post('/api/halo/esp32/loads', json={'load': 1}, headers=OP).status_code == 422
    assert client.get('/api/halo/esp32/loads').json()['loads']['load4'] is True
    events = client.get('/api/halo/snapshot').json()['events']
    assert sum(e['kind'] == 'esp32_load_set' for e in events) == 2


def test_calibration_proxy_returns_board_log_and_records_event(client, board):
    r = client.post('/api/halo/esp32/calibration', json={'action': 'mains_voltage', 'value': 228.5}, headers=OP)
    assert r.status_code == 200 and r.json()['ok'] and 'Mains calibrated to 228.50 V' in r.json()['log']
    r = client.post('/api/halo/esp32/calibration', json={'action': 'auto'}, headers=OP)
    assert r.status_code == 422 and 'mains is OFF' in r.json()['detail']
    assert client.post('/api/halo/esp32/calibration', json={'action': 'mains_voltage'}, headers=OP).status_code == 422
    assert client.post('/api/halo/esp32/calibration', json={'action': 'bogus'}, headers=OP).status_code == 422
    assert client.post('/api/halo/esp32/calibration', json={'action': 'zero'}).status_code == 401
    assert client.get('/api/halo/esp32/calibration').json()['calibration']['current_method'] == 'ohm'
    kinds = [e for e in client.get('/api/halo/snapshot').json()['events'] if e['kind'] == 'esp32_calibration']
    assert len(kinds) == 2 and {e['content']['ok'] for e in kinds} == {True, False}


def test_unconfigured_integration_is_explicit(tmp_path, monkeypatch, board):
    monkeypatch.setenv('NEURATWIN_DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.delenv('HALO_ESP32_URL', raising=False)
    with TestClient(app) as c:
        assert c.get('/api/halo/esp32/readings').status_code == 503
        s = c.get('/api/halo/esp32/status').json()
        assert not s['configured'] and s['url'] is None
        assert c.get('/api/halo/status').json()['esp32_configured'] is False
        assert c.post('/api/halo/esp32/poll', headers=OP).json()['status'] == 'not_configured'
