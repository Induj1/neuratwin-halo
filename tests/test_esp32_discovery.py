"""DHCP recovery, identity checks and bounded discovery without LAN traffic."""
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from neuratwin import esp32_discovery as discovery
from neuratwin import halo_esp32 as esp


@pytest.fixture
def network(tmp_path, monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('HALO_ESP32_URL', 'http://192.168.4.10')
    monkeypatch.setenv('HALO_DEVICE_TOKEN', 'test-device-only')
    monkeypatch.delenv('HALO_ESP32_DISCOVERY', raising=False)
    monkeypatch.delenv('HALO_ESP32_DEVICE_ID', raising=False)
    monkeypatch.setattr(esp, 'DISCOVERY', discovery.Discovery())
    monkeypatch.setattr(esp, 'tcp_reachable', lambda _: True)
    state = {'host': '192.168.4.20', 'boot': 'boot-a', 'online': True, 'requests': [], 'mdns': 0}

    def mdns(_):
        state['mdns'] += 1
        return ['http://' + state['host']]

    monkeypatch.setattr(discovery, 'mdns_candidates', mdns)
    monkeypatch.setattr(discovery, 'lan_candidates', lambda _: [])

    def handler(request):
        state['requests'].append((request.url.host, request.method, request.url.path, request.headers.get('authorization')))
        if not state['online'] or request.url.host != state['host']:
            raise httpx.ConnectError('Offline', request=request)
        if request.url.path == '/healthz':
            return httpx.Response(200, json={'ok': True, 'device_id': 'HALO-ESP32', 'boot_id': state['boot'],
                                           'firmware': 'esp32_integration'})
        if request.headers.get('authorization') != 'Bearer test-device-only':
            return httpx.Response(401, json={'error': 'Invalid token'})
        return httpx.Response(200, json={'ok': True, 'device_id': 'HALO-ESP32', 'boot_id': state['boot'],
                                       'sequence': 1, 'uptime_ms': 1000, 'primary_v': 230.1,
                                       'secondary_v': 12.2, 'current_a': .312, 'surface_c': 34.1,
                                       'relay_states': [False] * 4, 'primary_current_method': 'measured',
                                       'primary_current_a': .016, 'loads': {'load1': False, 'load2': False, 'load4': False}})
    monkeypatch.setattr(esp, 'TRANSPORT', httpx.MockTransport(handler))
    worker = esp.Esp32Poller()
    frames = []
    monkeypatch.setattr(worker, 'forward', frames.append)
    return state, worker, frames


def test_reconnects_after_dhcp_change_and_reboot_without_changing_measurements(network):
    state, worker, frames = network
    first = worker.poll_once()
    assert first['reachable'] and first['url'] == 'http://192.168.4.20'
    assert first['discovery']['method'] == 'mDNS'
    assert frames[-1]['primary_v'] == 230.1 and frames[-1]['current_a'] == .312
    state['online'] = False
    lost = worker.poll_once()
    assert not lost['reachable'] and lost['readings'] == first['readings']
    assert lost['readings_at'] == first['readings_at']
    # Later, the same board boots with a different DHCP lease.
    state.update(online=True, host='192.168.4.37', boot='boot-b')
    esp.DISCOVERY.next_search = 0
    recovered = worker.poll_once()
    assert recovered['reachable'] and recovered['url'] == 'http://192.168.4.37'
    assert frames[-1]['boot_id'] == 'boot-b' and frames[-1]['secondary_v'] == 12.2
    with esp.Esp32Client() as client:
        assert client.url == recovered['url']
        client.loads()
    assert all(method == 'GET' for _, method, _, _ in state['requests'])
    assert all(auth is None for _, _, path, auth in state['requests'] if path == '/healthz')
    # Only a subsequent explicit operator action sends a POST, to the new IP.
    with esp.Esp32Client() as client:
        client.set_loads({'load': 1, 'state': True})
    posts = [r for r in state['requests'] if r[1] == 'POST']
    assert len(posts) == 1 and posts[0][0] == '192.168.4.37' and posts[0][2] == '/api/loads'


def test_lost_command_reply_is_not_retried_or_replayed(network, monkeypatch):
    state, worker, _ = network
    worker.poll_once()
    original = esp.TRANSPORT
    posts = []

    def handler(request):
        if request.method == 'POST':
            posts.append(request)
            raise httpx.ReadTimeout('Reply lost after write', request=request)
        return original.handle_request(request)

    monkeypatch.setattr(esp, 'TRANSPORT', httpx.MockTransport(handler))
    with esp.Esp32Client() as client:
        with pytest.raises(esp.Esp32Unreachable):
            client.set_loads({'load': 1, 'state': True})
    state.update(host='192.168.4.38', boot='boot-c')
    esp.DISCOVERY.next_search = 0
    assert worker.poll_once()['reachable']
    assert len(posts) == 1


def test_old_ip_reassigned_to_another_device_never_receives_token(network, monkeypatch):
    state, worker, _ = network
    original = esp.TRANSPORT
    rejected = []

    def handler(request):
        if request.url.host == '192.168.4.10':
            rejected.append(request)
            return httpx.Response(200, json={'ok': True, 'device_id': 'OTHER-BOARD', 'firmware': 'router'})
        return original.handle_request(request)

    monkeypatch.setattr(esp, 'TRANSPORT', httpx.MockTransport(handler))
    assert worker.poll_once()['reachable']
    assert all(r.url.path == '/healthz' and 'authorization' not in r.headers for r in rejected)


def test_no_token_sent_to_unrelated_lan_servers(network, monkeypatch):
    state, worker, _ = network
    monkeypatch.setattr(discovery, 'mdns_candidates', lambda _: [])
    monkeypatch.setattr(discovery, 'lan_candidates', lambda _: ['http://192.168.4.2', 'http://192.168.4.20'])
    original = esp.TRANSPORT
    strangers = []

    def handler(request):
        if request.url.host == '192.168.4.2':
            strangers.append(request)
            return httpx.Response(200, json={'ok': True, 'device_id': 'HALO-ESP32', 'boot_id': 'x', 'firmware': 'other'})
        return original.handle_request(request)

    monkeypatch.setattr(esp, 'TRANSPORT', httpx.MockTransport(handler))
    assert worker.poll_once()['discovery']['method'] == 'local network'
    assert strangers and all('authorization' not in r.headers and r.url.path == '/healthz' for r in strangers)


def test_rejects_board_with_wrong_token(network, monkeypatch):
    state, worker, _ = network
    monkeypatch.setenv('HALO_DEVICE_TOKEN', 'incorrect')
    result = worker.poll_once()
    assert not result['reachable'] and result['readings'] is None
    assert esp.DISCOVERY.address(esp.base_url()) == esp.base_url()


def test_remembers_candidate_but_revalidates_it_after_server_restart(network, monkeypatch):
    state, worker, _ = network
    worker.poll_once()
    saved = json.loads(discovery.cache_path().read_text())
    assert saved['url'] == 'http://192.168.4.20'
    assert 'test-device-only' not in discovery.cache_path().read_text()
    monkeypatch.setattr(esp, 'DISCOVERY', discovery.Discovery())
    assert esp.DISCOVERY.address(esp.base_url()) == esp.base_url()  # cache not trusted yet
    result = worker.poll_once()
    assert result['reachable'] and result['discovery']['method'] == 'last known address'
    assert state['mdns'] == 1


def test_retries_are_throttled_and_can_be_disabled(network, monkeypatch):
    state, worker, _ = network
    state['online'] = False
    worker.poll_once()
    worker.poll_once()
    assert state['mdns'] == 1
    monkeypatch.setenv('HALO_ESP32_DISCOVERY', '0')
    esp.DISCOVERY.next_search = 0
    worker.poll_once()
    assert state['mdns'] == 1
    monkeypatch.delenv('HALO_ESP32_URL')
    assert worker.poll_once()['status'] == 'not_configured'
    assert state['mdns'] == 1


def test_shutdown_and_public_urls_do_not_scan(network):
    event = threading.Event()
    event.set()
    assert discovery.Discovery().discover(esp.base_url(), lambda _: pytest.fail('No probe'), event) is None
    assert not discovery.enabled('https://example.org')
    assert not discovery.enabled('http://127.0.0.1')


def test_missing_optional_dependencies_preserve_url_polling(network, monkeypatch):
    state, worker, _ = network
    monkeypatch.setattr(discovery, 'Zeroconf', None)
    result = worker.poll_once()
    assert not result['reachable']
    assert result['discovery']['status'] == 'dependencies unavailable'
    assert 'requirements-esp32.txt' in result['discovery']['last_error']
    # The configured address still works without installing the discovery extras.
    state['host'] = '192.168.4.10'
    assert worker.poll_once()['reachable']


def test_lan_scan_is_bounded_and_excludes_virtual_and_external_networks(monkeypatch):
    adapters = [SimpleNamespace(nice_name='Wi-Fi', name='wifi', ips=[SimpleNamespace(ip='10.12.164.131', network_prefix=16)]),
                SimpleNamespace(nice_name='VMware VMnet8', name='vmnet', ips=[SimpleNamespace(ip='192.168.232.1', network_prefix=24)]),
                SimpleNamespace(nice_name='Loopback', name='lo', ips=[SimpleNamespace(ip='127.0.0.1', network_prefix=8)])]
    monkeypatch.setattr(discovery.ifaddr, 'get_adapters', lambda: adapters)
    monkeypatch.setattr(discovery.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='10.12.10.25 8.8.8.8 10.12.164.131'))
    urls = discovery.lan_candidates('http://halo-esp32.local')
    assert urls[0] == 'http://10.12.10.25'
    assert len(urls) <= discovery.MAX_HOSTS
    assert all(discovery.private_ipv4(url.split('//')[1]) for url in urls)
    assert not any('192.168.232.' in u or '10.12.164.131' in u or '8.8.8.8' in u for u in urls)


def test_mdns_queries_firmware_service_directly_and_closes_sockets(monkeypatch):
    closed = []

    class FakeZeroconf:
        def __init__(self, **kwargs):
            pass

        def get_service_info(self, type_, name, timeout):
            assert type_ == '_http._tcp.local.' and name == 'halo-esp32._http._tcp.local.'
            return SimpleNamespace(server='halo-esp32.local.', port=80, parsed_addresses=lambda _: ['192.168.4.50', '8.8.8.8'])

        def close(self):
            closed.append(True)

    monkeypatch.setattr(discovery, 'Zeroconf', FakeZeroconf)
    assert discovery.mdns_candidates('http://192.168.4.10') == ['http://192.168.4.50']
    assert closed == [True]
