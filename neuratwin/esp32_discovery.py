"""Read-only LAN discovery for the configured Halo board after DHCP/Wi-Fi changes.

No device tokens are sent by the network search itself. The caller verifies a
health response before authenticating a readings request. Nothing here switches
loads, calibrates sensors, edits the configured URL or replays pending commands.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_address, ip_interface, ip_network
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit

try:
    import ifaddr
    from zeroconf import IPVersion, Zeroconf
except ImportError:
    # Hosted/simulation-only installations do not need LAN discovery packages.
    ifaddr = IPVersion = Zeroconf = None

PRIVATE = tuple(ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
SEARCH_INTERVAL = 15.0
SCAN_BUDGET = 8.0
MAX_HOSTS = 512


def private_ipv4(value):
    try:
        address = ip_address(value)
        return address.version == 4 and any(address in network for network in PRIVATE)
    except ValueError:
        return False


def device_id():
    return os.getenv('HALO_ESP32_DEVICE_ID', 'HALO-ESP32').strip()


def enabled(configured_url):
    host = urlsplit(configured_url).hostname or ''
    return bool(configured_url and os.getenv('HALO_ESP32_DISCOVERY', '1') != '0'
                and (host.endswith('.local') or private_ipv4(host)))


def identity_matches(health):
    return (isinstance(health, dict) and health.get('ok') is True
            and health.get('device_id') == device_id()
            and health.get('firmware') == 'esp32_integration'
            and isinstance(health.get('boot_id'), str) and bool(health['boot_id']))


def tcp_reachable(url):
    """Cheap bounded check before constructing an HTTP client for a LAN host."""
    parsed = urlsplit(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.3):
            return True
    except OSError:
        return False


def cache_path():
    db = Path(os.getenv('NEURATWIN_DB', str(Path(__file__).resolve().parents[1] / 'runtime/neuratwin.sqlite3')))
    return db.parent / 'esp32-discovery.json'


def local_interfaces():
    """Re-enumerate adapters each search, including after a laptop Wi-Fi change."""
    rows = []
    for adapter in ifaddr.get_adapters():
        name = (str(adapter.nice_name) + ' ' + str(adapter.name)).lower()
        if any(word in name for word in ('vmware', 'virtualbox', 'vethernet', 'tailscale', 'docker', 'loopback', 'bluetooth')):
            continue
        for item in adapter.ips:
            if isinstance(item.ip, str) and private_ipv4(item.ip):
                rows.append(ip_interface(f'{item.ip}/{item.network_prefix}'))
    return rows


def lan_candidates(configured_url):
    """ARP neighbours first, then at most two local /24-sized ranges.

    A campus /16 is deliberately not swept. Its known neighbours are eligible,
    while multicast discovery can find a board elsewhere on the same LAN.
    """
    interfaces = local_interfaces()
    own = {str(i.ip) for i in interfaces}
    port = urlsplit(configured_url).port or 80
    hosts = []
    try:
        reply = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=2,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for host in re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', reply.stdout):
            if private_ipv4(host) and any(ip_address(host) in i.network for i in interfaces):
                hosts.append(host)
    except (OSError, subprocess.TimeoutExpired):
        pass
    configured_host = urlsplit(configured_url).hostname or ''
    # Prefer the adapter containing the old IP when it is still on this LAN.
    interfaces.sort(key=lambda i: not (private_ipv4(configured_host) and ip_address(configured_host) in i.network))
    for interface in interfaces:
        network = ip_network(f'{interface.ip}/{max(24, interface.network.prefixlen)}', strict=False)
        hosts.extend(str(host) for host in network.hosts())
    seen = set(own)
    result = []
    for host in hosts:
        if host in seen or any(ip_address(host) in (i.network.network_address, i.network.broadcast_address) for i in interfaces):
            continue
        seen.add(host)
        result.append(f'http://{host}' + (f':{port}' if port != 80 else ''))
        if len(result) >= MAX_HOSTS:
            break
    return result


def mdns_candidates(configured_url):
    host = os.getenv('HALO_ESP32_HOSTNAME') or urlsplit(configured_url).hostname or ''
    if not host.endswith('.local'):
        host = 'halo-esp32.local'
    name = host.removesuffix('.local')
    zc = Zeroconf(ip_version=IPVersion.V4Only)
    try:
        info = zc.get_service_info('_http._tcp.local.', name + '._http._tcp.local.', timeout=1800)
        if not info or (info.server or '').rstrip('.').lower() != host.lower():
            return []
        return [f'http://{address}' + (f':{info.port}' if info.port != 80 else '')
                for address in info.parsed_addresses(IPVersion.V4Only) if private_ipv4(address)]
    finally:
        zc.close()


class Discovery:
    def __init__(self):
        self.lock = threading.RLock()
        self.search_lock = threading.Lock()
        self.key = None
        self.active = None
        self.cached = None
        self.next_search = 0.0
        self.cursor = 0
        self.state = {}

    def _configure(self, configured_url):
        key = (configured_url, device_id(), str(cache_path()), os.getenv('HALO_DEVICE_TOKEN', ''))
        if self.key == key:
            return
        self.key, self.active, self.cached, self.next_search = key, None, None, 0.0
        self.cursor = 0
        self.state = {'enabled': enabled(configured_url), 'status': 'idle', 'method': None,
                      'attempts': 0, 'candidates_checked': 0, 'last_found_at': None, 'last_error': None}
        try:
            saved = json.loads(cache_path().read_text(encoding='utf-8'))
            candidate = saved.get('url', '')
            parsed = urlsplit(candidate)
            if (saved.get('configured_url') == configured_url and saved.get('device_id') == device_id()
                    and parsed.scheme == 'http' and private_ipv4(parsed.hostname or '')
                    and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                    and parsed.path in ('', '/')):
                self.cached = candidate
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def address(self, configured_url):
        with self.lock:
            self._configure(configured_url)
            return self.active or configured_url

    def snapshot(self, configured_url):
        with self.lock:
            self._configure(configured_url)
            return dict(self.state, enabled=enabled(configured_url), available=Zeroconf is not None)

    def remember(self, configured_url, url, method=None):
        from .storage import now
        with self.lock:
            self._configure(configured_url)
            changed = self.active != url
            self.active = url
            self.state.update(status='connected', last_error=None)
            if method:
                self.state.update(method=method, last_found_at=now())
            if not changed or not enabled(configured_url) or not private_ipv4(urlsplit(url).hostname or ''):
                return
            self.cached = url
            try:
                file = cache_path()
                file.parent.mkdir(parents=True, exist_ok=True)
                temporary = file.with_suffix('.tmp')
                temporary.write_text(json.dumps({'configured_url': configured_url, 'url': url, 'device_id': device_id()}), encoding='utf-8')
                temporary.replace(file)
            except OSError:
                pass  # Discovery must still work with read-only local storage.

    def discover(self, configured_url, probe, stop_event):
        """Return (url, health, reading) only after the caller's read-only checks."""
        if not enabled(configured_url) or stop_event.is_set() or not self.search_lock.acquire(blocking=False):
            return None
        try:
            with self.lock:
                self._configure(configured_url)
                if Zeroconf is None:
                    self.state.update(status='dependencies unavailable',
                                      last_error='Install requirements-esp32.txt and restart the backend to enable automatic discovery.')
                    return None
                if time.monotonic() < self.next_search:
                    return None
                self.next_search = time.monotonic() + SEARCH_INTERVAL
                self.state.update(status='searching', attempts=self.state['attempts'] + 1, candidates_checked=0, last_error=None)
                cached = self.cached
            checked = set()

            def check(url):
                if stop_event.is_set():
                    return None
                with self.lock:
                    if url in checked:
                        return None
                    checked.add(url)
                    self.state['candidates_checked'] += 1
                try:
                    result = probe(url)
                    return (url, *result) if result else None
                except Exception:
                    return None  # An unrelated/malformed HTTP server is not our board.

            if cached:
                result = check(cached)
                if result:
                    self.remember(configured_url, cached, 'last known address')
                    return result
            try:
                candidates = mdns_candidates(configured_url)
            except Exception as error:
                candidates = []
                with self.lock:
                    self.state['last_error'] = 'mDNS discovery unavailable: ' + type(error).__name__
            for url in candidates:
                result = check(url)
                if result:
                    self.remember(configured_url, url, 'mDNS')
                    return result
            try:
                candidates = lan_candidates(configured_url)
            except Exception as error:
                candidates = []
                with self.lock:
                    self.state['last_error'] = 'LAN discovery unavailable: ' + type(error).__name__
            deadline = time.monotonic() + SCAN_BUDGET
            # Resume after the last tested host if a busy network exhausts the
            # time budget; hosts late in the list must not starve forever.
            with self.lock:
                cursor = self.cursor % max(1, len(candidates))
            candidates = candidates[cursor:] + candidates[:cursor]
            checked_before = len(checked)

            def bounded(url):
                return check(url) if time.monotonic() < deadline else None

            pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix='esp32-discovery')
            futures = [pool.submit(bounded, url) for url in candidates]
            try:
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        self.remember(configured_url, result[0], 'local network')
                        return result
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
                with self.lock:
                    self.cursor = (cursor + len(checked) - checked_before) % max(1, len(candidates))
            with self.lock:
                self.state['status'] = 'waiting for board'
            return None
        finally:
            self.search_lock.release()
