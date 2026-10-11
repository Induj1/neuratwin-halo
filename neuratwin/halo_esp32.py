"""Wi-Fi ESP32 integration for the esp32_integration firmware.

The board is the HTTP server; this module is its only client. A lifecycle-owned
poller fetches /healthz and /api/readings, forwards each new acquisition into the
ordinary telemetry path and caches the last board reply so the UI can still see
the board when durable ingestion is unavailable. Load and calibration requests
are proxied one-to-one to the board. No serial port is opened. The firmware's
own interlocks, not this module, are the only automatic protection.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import os
import threading
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError, model_validator
from .halo_contracts import Contract, Frame
from . import halo_store as store
from .storage import now
from .esp32_discovery import Discovery, identity_matches, tcp_reachable

router = APIRouter(prefix='/api/halo/esp32')
ACTOR = 'esp32 poller'
READ_TIMEOUT = 3.0
LOAD_TIMEOUT = 5.0
CALIBRATION_TIMEOUT = 45.0  # relays click for up to ~15 s during auto/step actions
TRANSPORT = None  # tests inject an httpx.MockTransport here
DISCOVERY = Discovery()


class Esp32Unreachable(Exception):
    pass


class Esp32Rejected(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def base_url():
    return (os.getenv('HALO_ESP32_URL') or '').strip().rstrip('/')


def configured():
    return bool(base_url())


def poll_seconds():
    try:
        return max(0.5, float(os.getenv('HALO_ESP32_POLL_SECONDS', '2')))
    except ValueError:
        return 2.0


class Esp32Client:
    """Thin HTTP client; raises Esp32Unreachable / Esp32Rejected instead of httpx errors."""

    def __init__(self, url=None, token=None, read_timeout=READ_TIMEOUT):
        self.url = url or DISCOVERY.address(base_url())
        if not self.url:
            raise Esp32Unreachable('HALO_ESP32_URL is not configured.')
        token = token if token is not None else os.getenv('HALO_DEVICE_TOKEN', '')
        self.headers = {'Authorization': 'Bearer ' + token} if token else {}
        self.read_timeout = read_timeout
        self.verified_health = None
        self.http = httpx.Client(base_url=self.url, transport=TRANSPORT, trust_env=False)

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def call(self, method, path, body=None, timeout=None):
        if path != '/healthz' and self.verified_health is None:
            self.healthz()  # Never send the device token to an unidentified LAN host.
        try:
            r = self.http.request(method, path, json=body, timeout=timeout or self.read_timeout,
                                  headers={} if path == '/healthz' else self.headers)
        except httpx.HTTPError as error:
            raise Esp32Unreachable(f'ESP32 unreachable at {self.url}: {type(error).__name__}') from error
        try:
            data = r.json()
        except ValueError:
            raise Esp32Rejected(502, f'ESP32 returned non-JSON ({r.status_code}).')
        # A failed calibration is a 422 carrying the board's log; that is a result, not a transport fault.
        if r.status_code >= 400 and not (r.status_code == 422 and isinstance(data, dict) and 'log' in data):
            detail = data.get('error') if isinstance(data, dict) else None
            raise Esp32Rejected(r.status_code, detail or f'ESP32 error {r.status_code}')
        return data

    def healthz(self):
        data = self.call('GET', '/healthz')
        if not identity_matches(data):
            raise Esp32Rejected(409, 'The host is not the configured Halo ESP32.')
        self.verified_health = data
        return data

    def readings(self):
        data = self.call('GET', '/api/readings')
        if (not isinstance(data, dict) or data.get('device_id') != self.verified_health['device_id']
                or data.get('boot_id') != self.verified_health['boot_id']):
            raise Esp32Rejected(409, 'ESP32 identity or boot changed; waiting for a fresh acquisition.')
        return data
    def loads(self): return self.call('GET', '/api/loads')
    def set_loads(self, body): return self.call('POST', '/api/loads', body, LOAD_TIMEOUT)
    def calibration(self): return self.call('GET', '/api/calibration')
    def calibrate(self, body): return self.call('POST', '/api/calibration', body, CALIBRATION_TIMEOUT)


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _bounded(value, low, high, flags, flag):
    v = _number(value)
    if v is None:
        return None
    if not low <= v <= high:
        flags.append(flag)
        return None
    return v


def to_frame(reading, timestamp=None):
    """Map a board /api/readings reply to the backend Frame contract.

    Only directly measured channels enter the named fields. The board's primary
    current is derived from secondary power unless the firmware says 'measured',
    so a calculated value is kept in raw and never presented as a measurement.
    """
    flags = [str(f) for f in reading.get('quality_flags', [])][:12]
    frame = {
        'device_id': reading['device_id'], 'boot_id': reading['boot_id'],
        'sequence': int(reading['sequence']), 'uptime_ms': int(reading['uptime_ms']),
        'timestamp': (timestamp or datetime.now(timezone.utc)).isoformat(),
        'primary_v': _bounded(reading.get('primary_v'), 0, 300, flags, 'primary_v_out_of_range'),
        'secondary_v': _bounded(reading.get('secondary_v'), 0, 60, flags, 'secondary_v_out_of_range'),
        'current_a': _bounded(reading.get('current_a'), 0, 30, flags, 'current_a_out_of_range'),
        'surface_c': _bounded(reading.get('surface_c'), -55, 125, flags, 'surface_out_of_range'),
        'primary_current_a': None,
        'relay_states': tuple(bool(s) for s in reading.get('relay_states', [False] * 4)[:4]) if len(reading.get('relay_states', [])) == 4 else (False,) * 4,
        'relay_output_configured': bool(reading.get('relay_output_configured', False)),
        'ambient_source': 'not_measured',
    }
    raw = {k: _number(v) for k, v in (reading.get('raw') or {}).items() if _number(v) is not None}
    if reading.get('primary_current_method') == 'measured':
        frame['primary_current_a'] = _bounded(reading.get('primary_current_a'), 0, 30, flags, 'primary_current_out_of_range')
    else:
        raw['primary_current_calculated_a'] = _number(reading.get('primary_current_a'))
        flags.append('primary_current_calculated')
    if _number(reading.get('expected_current_a')) is not None:
        raw['expected_current_a'] = _number(reading.get('expected_current_a'))
    # Scaling happens on the board; no reviewed backend calibration record applies.
    flags.append('calibration_unrecorded')
    frame['quality_flags'] = list(dict.fromkeys(flags))[:16]
    frame['raw'] = dict(list(raw.items())[:20])
    return Frame.model_validate(frame)


class Esp32Poller:
    """Lifecycle-owned background poll. Idle when HALO_ESP32_URL is unset."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.wake = None
        self.task = None
        self.lock = threading.Lock()
        self.poll_lock = threading.Lock()  # background loop and /poll must not forward the same sequence twice
        self.state = {'configured': configured(), 'url': base_url() or None, 'status': 'starting', 'reachable': False,
                      'polls': 0, 'forwarded': 0, 'forward_failures': 0, 'consecutive_failures': 0,
                      'last_seen_at': None, 'last_error': None, 'last_forward_error': None, 'last_poll_at': None,
                      'last_sequence': None, 'last_boot_id': None, 'healthz': None, 'readings': None, 'readings_at': None}

    def snapshot(self):
        with self.lock:
            state = deepcopy(self.state)
        state['discovery'] = DISCOVERY.snapshot(base_url())
        return state

    def acquisition_time(self, reading):
        key=(reading.get('device_id'),reading.get('boot_id'),reading.get('sequence'))
        with self.lock:
            if not hasattr(self, 'acquisition_stamps'):
                self.acquisition_stamps={}
            stamp=self.acquisition_stamps.setdefault(key,now())
            if len(self.acquisition_stamps)>256:
                self.acquisition_stamps.pop(next(iter(self.acquisition_stamps)))
            return stamp

    def observe(self, reading):
        stamp=self.acquisition_time(reading)
        with self.lock:
            if not self.state.get('readings_at') or stamp>=self.state['readings_at']:
                self.state.update(readings=reading,readings_at=stamp)
        return stamp

    @staticmethod
    def discovery_probe(url):
        if not tcp_reachable(url):
            return None
        with Esp32Client(url=url, read_timeout=0.7) as board:
            health = board.healthz()
            reading = board.readings()
            # A JSON lookalike with the right name is not an acquisition.
            to_frame(reading)
            return health, reading

    def poll_once(self):
        """One health + readings round trip, then forward any new acquisition."""
        with self.poll_lock:
            return self._poll()

    def _poll(self):
        with self.lock:
            self.state.update(configured=configured(), url=DISCOVERY.address(base_url()) or None,
                              polls=self.state['polls'] + 1, last_poll_at=now())
        if not configured():
            with self.lock:
                self.state.update(status='not_configured', reachable=False)
            return self.snapshot()
        try:
            with Esp32Client() as board:
                health = board.healthz()
                reading = board.readings()
                connected_url = board.url
        except (Esp32Unreachable, Esp32Rejected) as error:
            with self.lock:
                self.state.update(status='unreachable', reachable=False, last_error=str(error),
                                  consecutive_failures=self.state['consecutive_failures'] + 1)
            found = DISCOVERY.discover(base_url(), self.discovery_probe, self.stop_event)
            if not found:
                return self.snapshot()
            connected_url, health, reading = found
        DISCOVERY.remember(base_url(), connected_url)
        stamp = now()
        self.observe(reading)
        with self.lock:
            self.state.update(status='connected', url=connected_url, reachable=True, last_error=None, consecutive_failures=0,
                              last_seen_at=stamp, healthz=health)
            unchanged = (self.state['last_boot_id'], self.state['last_sequence']) == (reading.get('boot_id'), reading.get('sequence'))
        if unchanged:
            return self.snapshot()
        self.forward(reading)
        return self.snapshot()

    def forward(self, reading):
        from .halo_api import ingest
        try:
            result = ingest(to_frame(reading,datetime.fromisoformat(self.acquisition_time(reading).replace('Z','+00:00'))), ACTOR)
            with self.lock:
                self.state.update(forwarded=self.state['forwarded'] + 1, last_forward_error=None,
                                  last_boot_id=reading.get('boot_id'), last_sequence=reading.get('sequence'),
                                  last_forward=result)
        except (HTTPException, ValidationError, KeyError, ValueError, TypeError) as error:
            detail = getattr(error, 'detail', None) or str(error)
            with self.lock:
                # Remember the sequence so a permanently rejected frame is not retried every poll.
                self.state.update(forward_failures=self.state['forward_failures'] + 1, last_forward_error=str(detail)[:300],
                                  last_boot_id=reading.get('boot_id'), last_sequence=reading.get('sequence'))

    async def run(self):
        from starlette.concurrency import run_in_threadpool
        self.wake = asyncio.Event()
        try:
            while not self.stop_event.is_set():
                try:
                    await run_in_threadpool(self.poll_once)
                except Exception as error:  # keep polling; never take the app down
                    with self.lock:
                        self.state.update(status='error', last_error=f'{type(error).__name__}: {error}'[:300])
                delay = poll_seconds() if configured() else 5.0
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                self.wake.clear()
        finally:
            with self.lock:
                self.state.update(status='stopped')

    async def start(self):
        self.task = asyncio.create_task(self.run(), name='halo-esp32-poller')
        return self

    async def stop(self):
        self.stop_event.set()
        if self.wake is not None:
            self.wake.set()
        if self.task is not None:
            await self.task


def poller(request: Request):
    return getattr(request.app.state, 'esp32_poller', None)


def board_call(fn):
    """Run one proxied board call, translating errors to HTTP responses."""
    if not configured():
        raise HTTPException(503, 'HALO_ESP32_URL is not configured; the Wi-Fi board integration is off.')
    try:
        with Esp32Client() as board:
            return fn(board)
    except Esp32Unreachable as error:
        raise HTTPException(503, str(error))
    except Esp32Rejected as error:
        raise HTTPException(error.status if 400 <= error.status < 600 else 502, error.detail)


@router.get('/status')
def status(request: Request):
    worker = poller(request)
    state = worker.snapshot() if worker else {'status': 'not_started'}
    state.pop('readings', None)
    return {'configured': configured(), 'url': DISCOVERY.address(base_url()) or None,
            'configured_url': base_url() or None, 'poll_seconds': poll_seconds(),
            'control_enabled': os.getenv('HALO_ALLOW_CONTROL') == '1', 'token_configured': bool(os.getenv('HALO_DEVICE_TOKEN')),
            'poller': state, 'meaning': 'Backend-side reachability of the Wi-Fi board. Not contact feedback, calibration review or electrical verification.'}


@router.get('/healthz')
def healthz():
    return board_call(lambda b: b.healthz())


@router.get('/readings')
def readings(request: Request):
    """Live board reading; falls back to the poller's last reply when unreachable."""
    worker = poller(request)
    try:
        reading=board_call(lambda b: b.readings())
        stamp=worker.observe(reading) if worker else now()
        age=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(stamp.replace('Z','+00:00'))).total_seconds())
        stale=age>max(5,3*poll_seconds())
        return {'live':not stale,'stale':stale,'reading':reading,'readings_at':stamp,
                'age_s':age,'error':'ESP32 acquisition has not advanced.' if stale else None}
    except HTTPException as error:
        cached = worker.snapshot() if worker else {}
        if error.status_code == 503 and cached.get('readings'):
            return {'live': False, 'stale': True, 'error': error.detail, 'reading': cached['readings'], 'readings_at': cached['readings_at']}
        raise


@router.get('/loads')
def loads():
    return board_call(lambda b: b.loads())


class LoadRequest(Contract):
    load1: bool | None = None
    load2: bool | None = None
    load4: bool | None = None
    load: Literal[1, 2, 4] | None = None
    state: bool | None = None

    @model_validator(mode='after')
    def one_form(self):
        single = self.load is not None
        if single != (self.state is not None):
            raise ValueError('Provide both load and state, or load1/load2/load4 booleans.')
        if not single and all(v is None for v in (self.load1, self.load2, self.load4)):
            raise ValueError('Nothing to change.')
        return self

    def body(self):
        if self.load is not None:
            return {'load': self.load, 'state': self.state}
        return {k: v for k, v in (('load1', self.load1), ('load2', self.load2), ('load4', self.load4)) if v is not None}


def operator_dependency(request: Request):
    from .halo_api import operator
    return operator(request)


@router.post('/loads')
def set_loads(payload: LoadRequest, actor=Depends(operator_dependency)):
    if os.getenv('HALO_ALLOW_CONTROL') != '1':
        raise HTTPException(423, 'Physical load switching is locked. Set HALO_ALLOW_CONTROL=1 on this server to enable it.')
    body = payload.body()
    result = board_call(lambda b: b.set_loads(body))
    store.event('BENCH-001', 'esp32_load_set', {'actor': actor, 'request': body, 'loads': result.get('loads'), 'at': now(),
                                                'meaning': 'Board acknowledged a relay drive state; not contact feedback.'})
    return result


@router.get('/calibration')
def calibration():
    return board_call(lambda b: b.calibration())


class CalibrationRequest(Contract):
    action: Literal['mains_voltage', 'secondary_voltage', 'current_meter', 'sensor_model', 'auto', 'zero', 'reset', 'step_test']
    value: float | None = Field(default=None, ge=0, le=300)

    @model_validator(mode='after')
    def value_required(self):
        if self.action in ('mains_voltage', 'secondary_voltage', 'current_meter', 'sensor_model') and self.value is None:
            raise ValueError(f'{self.action} needs a value.')
        return self


@router.post('/calibration')
def calibrate(payload: CalibrationRequest, actor=Depends(operator_dependency)):
    body = {'action': payload.action}
    if payload.value is not None:
        body['value'] = payload.value
    try:
        result = board_call(lambda b: b.calibrate(body))
    except HTTPException as error:
        store.event('BENCH-001', 'esp32_calibration', {'actor': actor, 'request': body, 'ok': False, 'detail': error.detail, 'at': now()})
        raise
    store.event('BENCH-001', 'esp32_calibration', {'actor': actor, 'request': body, 'ok': bool(result.get('ok')), 'log': result.get('log'),
                                                   'calibration': result.get('calibration'), 'at': now(),
                                                   'meaning': 'On-board scaling stored in device flash; not a reviewed backend calibration record.'})
    if not result.get('ok'):
        raise HTTPException(422, result.get('log') or 'Board rejected the calibration action.')
    return result


@router.post('/poll')
def poll_now(request: Request, actor=Depends(operator_dependency)):
    worker = poller(request)
    if worker is None:
        raise HTTPException(503, 'ESP32 poller is not running.')
    state = worker.poll_once()
    state.pop('readings', None)
    return state
