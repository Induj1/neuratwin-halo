"""Fleet triage and retrospective model qualification. Never controls equipment.

Original implementation: a two-parameter thermal surrogate, chronological
fit/calibration/test blocks, and explicit abstention. No vendor code or ratings.
"""
from datetime import datetime, timedelta, timezone
import math
import random
import hashlib
from pathlib import Path
from typing import Literal
import numpy as np
from scipy.optimize import least_squares
from pydantic import Field, model_validator
from .halo_contracts import Contract
from .twin_studies import digest

VERSION = 'fleet-evidence-1'
POLICY = 'fleet-screening-1'


class Sample(Contract):
    timestamp: datetime
    load_pu: float = Field(ge=0, le=3)
    ambient_c: float = Field(ge=-20, le=60)
    oil_c: float | None = Field(None, ge=-20, le=200)
    voltage_pu: float | None = Field(None, ge=0, le=2)

    @model_validator(mode='after')
    def aware(self):
        if self.timestamp.utcoffset() is None:
            raise ValueError('Every timestamp needs an explicit timezone.')
        return self


class Asset(Contract):
    asset_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,48}$')
    name: str = Field(min_length=1, max_length=100)
    rated_kva: float = Field(gt=0, le=10000)
    tie_group: str = Field('', max_length=40)
    criticality: int = Field(1, ge=1, le=5)
    construction: Literal['sealed', 'conservator'] = 'sealed'
    oil_limit_c: float = Field(95, ge=40, le=150)
    max_loading_pu: float = Field(1, gt=0, le=1.5)
    samples: list[Sample] = Field(min_length=1, max_length=2016)

    @model_validator(mode='after')
    def chronological(self):
        if any(a.timestamp >= b.timestamp for a, b in zip(self.samples, self.samples[1:])):
            raise ValueError('Samples must be strictly chronological with no duplicate timestamps.')
        return self


class Portfolio(Contract):
    name: str = Field(min_length=3, max_length=120)
    source: Literal['synthetic', 'imported']
    source_note: str = Field(min_length=5, max_length=1000)
    assets: list[Asset] = Field(min_length=1, max_length=25)

    @model_validator(mode='after')
    def identities(self):
        if len({a.asset_id for a in self.assets}) != len(self.assets):
            raise ValueError('Asset IDs must be unique within the portfolio.')
        if sum(len(a.samples) for a in self.assets) > 20000:
            raise ValueError('At most 20,000 samples per portfolio.')
        return self


def step(t, load, ambient, minutes, rise, tau):
    target = ambient + rise * ((1 + 5 * load * load) / 6) ** .8
    return target + (t - target) * math.exp(-minutes / tau)


def qualify(asset):
    rows = asset.samples
    card = {'version': VERSION, 'policy': POLICY, 'target': 'top-oil temperature',
        'status': 'withheld', 'holds': [], 'parameters': None, 'metrics': None,
        'forecast': [], 'horizon_min': 30, 'data_sha256': digest(asset.model_dump(mode='json')),
        'assumptions': ['Future loading and ambient held at forecast origin.',
            'Loss ratio 5 and thermal exponent 0.8 are assumed, not fitted.',
            'Configured oil/loading limits are study inputs, not certified equipment ratings.',
            'Empirical bands rely on calibration-block representativeness; no field coverage guarantee.'],
        'scope': 'Retrospective top-oil screening only. No hot-spot, all-cause failure probability or automatic switching.'}
    if len(rows) < 180:
        card['holds'].append('Need at least 180 chronological samples for separate fit, calibration and test blocks.')
        return card
    dt = np.diff([r.timestamp.timestamp() for r in rows]) / 60
    cadence = float(np.median(dt))
    if cadence < 1 or cadence > 10 or np.max(np.abs(dt-cadence)) > cadence*.1:
        card['holds'].append('Use regular 1–10 minute sampling; gaps must be resolved before fitting.')
    if any(r.oil_c is None for r in rows):
        card['holds'].append('Missing oil readings; missing data are never interpolated into qualification evidence.')
    if card['holds']:
        return card
    fit_end, cal_end = int(len(rows)*.6), int(len(rows)*.8)
    fit, calibration, test = rows[:fit_end], rows[fit_end:cal_end], rows[cal_end:]
    card['split'] = {name: {'count': len(part), 'start': part[0].timestamp.isoformat(), 'end': part[-1].timestamp.isoformat()}
        for name, part in [('fit', fit), ('calibration', calibration), ('test', test)]}
    card['cadence_min'] = cadence
    if max(r.load_pu for r in fit)-min(r.load_pu for r in fit) < .2:
        card['holds'].append('Fit-window loading span is below 0.20 pu; thermal parameters are not sufficiently excited.')
        return card
    def residual(parameters):
        t = fit[0].oil_c
        errors = []
        for before, after in zip(fit, fit[1:]):
            t = step(t, before.load_pu, before.ambient_c, cadence, *parameters)
            errors.append(t-after.oil_c)
        return errors
    opt = least_squares(residual, [45, 90], bounds=([5, 5], [100, 300]), loss='soft_l1', max_nfev=100)
    rise, tau = map(float, opt.x)
    card['parameters'] = {'rated_rise_c': rise, 'tau_min': tau, 'loss_ratio': 5, 'exponent': .8}
    condition = float(np.linalg.cond(opt.jac))
    card['fit_condition_number'] = condition if math.isfinite(condition) else None
    if not math.isfinite(condition) or condition > 1000:
        card['holds'].append('Thermal parameters are poorly identified; fit Jacobian condition number exceeds 1000.')
    if not opt.success or rise < 5.5 or rise > 99.5 or tau < 5.5 or tau > 299:
        card['holds'].append('Thermal fit did not converge inside its parameter bounds.')
    horizon = max(1, round(30/cadence))
    card['horizon_min'] = horizon*cadence
    def windows(part):
        output = []
        for i in range(0, len(part)-horizon, horizon+1):
            origin = part[i]
            predicted = [step(origin.oil_c, origin.load_pu, origin.ambient_c, j*cadence, rise, tau) for j in range(1, horizon+1)]
            actual = [r.oil_c for r in part[i+1:i+horizon+1]]
            output.append({'origin': origin.timestamp.isoformat(), 'predicted': predicted, 'actual': actual,
                'errors': [abs(a-p) for a, p in zip(actual, predicted)],
                'baseline': [abs(a-origin.oil_c) for a in actual]})
        return output
    cal_windows, test_windows = windows(calibration), windows(test)
    if len(cal_windows) < 9 or len(test_windows) < 8:
        card['holds'].append('Need at least 9 disjoint calibration trajectories and 8 test trajectories at this horizon.')
        return card
    # One maximum error per trajectory. Test data never selects the band or parameters.
    maxima = sorted(max(w['errors']) for w in cal_windows)
    rank = math.ceil((len(maxima)+1)*.9)
    radius = maxima[min(rank, len(maxima))-1]
    errors = [e for w in test_windows for e in w['errors']]
    baseline = [e for w in test_windows for e in w['baseline']]
    mae, base_mae = float(np.mean(errors)), float(np.mean(baseline))
    coverage = sum(max(w['errors']) <= radius for w in test_windows)/len(test_windows)
    latest = test_windows[-1]
    drift = max(latest['errors']) > radius
    card['metrics'] = {'mae_c': mae, 'persistence_mae_c': base_mae,
        'improvement_percent': 100*(base_mae-mae)/base_mae if base_mae > 1e-9 else None,
        'p95_error_c': float(np.quantile(errors, .95)), 'band_radius_c': radius,
        'nominal_trajectory_coverage': .9, 'test_trajectory_coverage': coverage,
        'calibration_windows': len(cal_windows), 'test_windows': len(test_windows),
        'latest_trajectory_outside_band': drift}
    card['test_windows'] = [{k: v for k, v in w.items() if k in ('origin', 'predicted', 'actual')} for w in test_windows]
    if base_mae <= 1e-9 or mae >= base_mae*.95:
        card['holds'].append('Held-out forecasts did not beat persistence by at least 5%.')
    if mae > 2:
        card['holds'].append('Held-out MAE exceeds the declared 2°C screening policy.')
    if coverage < .8:
        card['holds'].append('Held-out trajectory coverage is below the 80% screening floor.')
    if drift:
        card['holds'].append('Latest complete test trajectory exceeded its frozen calibration band; review possible drift.')
    last = rows[-1]
    domain = {'load_pu': [min(r.load_pu for r in fit), max(r.load_pu for r in fit)],
        'ambient_c': [min(r.ambient_c for r in fit), max(r.ambient_c for r in fit)]}
    card['domain'] = domain
    if any(not domain[k][0] <= getattr(last, k) <= domain[k][1] for k in domain):
        card['holds'].append('Current inputs fall outside the fitted operating range.')
    card['status'] = 'qualified_for_recording' if not card['holds'] else 'withheld'
    if not card['holds']:
        card['forecast'] = [{'minute': j*cadence,
            'temperature_c': step(last.oil_c, last.load_pu, last.ambient_c, j*cadence, rise, tau),
            'lower_c': step(last.oil_c, last.load_pu, last.ambient_c, j*cadence, rise, tau)-radius,
            'upper_c': step(last.oil_c, last.load_pu, last.ambient_c, j*cadence, rise, tau)+radius}
            for j in range(horizon+1)]
    return card


def triage(asset, card, reference):
    last = asset.samples[-1]
    reasons, points = [], 0
    stale = (reference-last.timestamp).total_seconds() > 1200
    if stale or last.oil_c is None or last.voltage_pu is None:
        reasons.append('Resolve stale or missing evidence before trusting the asset assessment.'); points += 35
    if last.load_pu > asset.max_loading_pu:
        reasons.append(f'Loading {last.load_pu:.2f} pu exceeds configured {asset.max_loading_pu:.2f} pu.'); points += 30
    if last.oil_c is not None and last.oil_c >= asset.oil_limit_c:
        reasons.append(f'Top-oil {last.oil_c:.1f}°C exceeds configured {asset.oil_limit_c:.1f}°C.'); points += 45
    if last.voltage_pu is not None and not .9 <= last.voltage_pu <= 1.1:
        reasons.append('Voltage outside the declared 0.90–1.10 pu study band.'); points += 20
    if card['forecast'] and max(p['upper_c'] for p in card['forecast']) >= asset.oil_limit_c:
        reasons.append('Qualified recording forecast band reaches the configured oil limit.'); points += 20
    if (card.get('metrics') or {}).get('latest_trajectory_outside_band'):
        reasons.append('Thermal response disagrees with the frozen calibration band.'); points += 15
    priority = min(100, points+(asset.criticality-1)*3) if reasons else 0
    # Quality does not erase an observed overload/overtemperature.
    status = 'urgent' if points >= 45 else 'review' if reasons else 'observe'
    return {'score': priority, 'status': status, 'reasons': reasons or ['No configured observed limit is exceeded in this snapshot.'],
        'stale': stale, 'criticality': asset.criticality,
        'basis': 'Rule-based triage, not a failure probability. Load +30, oil +45, voltage +20, forecast +20, drift +15, missing/stale +35; criticality adds 0–12, capped at 100.'}


def analyse(portfolio):
    reference = max(a.samples[-1].timestamp for a in portfolio.assets)
    assessed = []
    for asset in portfolio.assets:
        card = qualify(asset)
        if (reference-asset.samples[-1].timestamp).total_seconds() > 1200:
            card['holds'].append('Latest sample is over 20 minutes behind the portfolio reference time.')
            card['status'] = 'withheld'
            card['forecast'] = []
        assessed.append({'asset': asset.model_dump(mode='json', exclude={'samples'}),
            'current': asset.samples[-1].model_dump(mode='json'), 'sample_count': len(asset.samples),
            'card': card, 'priority': triage(asset, card, reference)})
    assessed.sort(key=lambda r: (-r['priority']['score'], r['asset']['asset_id']))
    return {'version': VERSION, 'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source': portfolio.source, 'source_note': portfolio.source_note,
        'reference_time': reference.isoformat(), 'assets': assessed,
        'summary': {'assets': len(assessed), 'urgent': sum(r['priority']['status']=='urgent' for r in assessed),
            'review': sum(r['priority']['status']=='review' for r in assessed),
            'qualified': sum(r['card']['status']=='qualified_for_recording' for r in assessed),
            'withheld': sum(r['card']['status']!='qualified_for_recording' for r in assessed)},
        'scope': 'A frozen portfolio recording, not a live fleet connection. Qualification applies only to this recording and target.'}


def demonstration(seed=20261011):
    """Independent two-store oil/radiator plant; not the fitted one-node predictor."""
    rng = random.Random(seed)
    start = datetime(2026, 10, 8, tzinfo=timezone.utc)
    assets = []
    for k in range(25):
        rise, tau = rng.uniform(35, 58), rng.uniform(60, 130)
        oil, radiator = 38., 33.
        samples = []
        for i in range(720):
            load = .68+.23*math.sin(i/19+k*.17)+.06*math.sin(i/5)
            ambient = 28+2*math.sin(i/48)
            if k in (2, 8) and i > 620: load = 1.32
            cooling = .55 if k == 5 and i > 620 else 1
            # Two separate thermal stores, integrated with one-minute Euler steps.
            for _ in range(5):
                exchange = (oil-radiator)/(tau*.35)
                rejection = cooling*(radiator-ambient)/(tau*.65)
                oil += rise*((1+5*load**2)/6)**.8/tau-exchange
                radiator += (exchange-rejection)/.7
            recorded = oil+rng.gauss(0, .12)
            if k == 11 and i > 620: recorded += 8
            samples.append(Sample(timestamp=start+timedelta(minutes=i*5), load_pu=load,
                ambient_c=ambient, oil_c=None if k==17 and i>710 else recorded,
                voltage_pu=1.14 if k==20 and i>620 else 1))
        if k==23: samples=samples[:-20]
        assets.append(Asset(asset_id=f'DT-{k+1:02}', name=f'{["Urban", "Rural", "Industrial"][k%3]} feeder {k+1:02}',
            rated_kva=[100, 160, 250, 315, 500][k%5], tie_group=f'TIE-{k//5+1}',
            criticality=k%5+1, construction='sealed' if k%2 else 'conservator', samples=samples))
    return Portfolio(name='25-asset demonstration', source='synthetic',
        source_note=f'Independent two-store thermal plant; seed {seed}. Includes overload, cooling degradation, sensor bias, missing data and voltage excursion. No physical fleet attached.', assets=assets)


class Transfer(Contract):
    donor: str
    receiver: str
    kva: float = Field(gt=0, le=10000)
    tie_capacity_kva: float = Field(gt=0, le=10000)
    topology_reviewed: bool = False


def transfer(report, request):
    lookup = {a['asset']['asset_id']: a for a in report['assets']}
    if request.donor not in lookup or request.receiver not in lookup or request.donor == request.receiver:
        raise ValueError('Select two different assets from this portfolio.')
    donor, receiver = lookup[request.donor], lookup[request.receiver]
    holds, rows = [], []
    if not request.topology_reviewed: holds.append('Review the tie topology and enter its capacity before evaluating a transfer.')
    if not donor['asset']['tie_group'] or donor['asset']['tie_group'] != receiver['asset']['tie_group']:
        holds.append('Assets do not share a declared transfer tie.')
    if request.kva > request.tie_capacity_kva: holds.append('Requested transfer exceeds the entered tie capacity.')
    if datetime.fromisoformat(donor['current']['timestamp']) != datetime.fromisoformat(receiver['current']['timestamp']):
        holds.append('Asset observations are not simultaneous.')
    for member, sign in [(donor, -1), (receiver, 1)]:
        a, c, model = member['asset'], member['current'], member['card']
        before = c['load_pu']*a['rated_kva']; after = before+sign*request.kva
        pu = after/a['rated_kva']; peak = None
        if after < 0 or pu > a['max_loading_pu']: holds.append(f'{a["asset_id"]}: resulting load exceeds configured limits or is negative.')
        if member['priority']['stale'] or model['status'] != 'qualified_for_recording':
            holds.append(f'{a["asset_id"]}: fresh, qualified thermal evidence is unavailable.')
        elif not model['domain']['load_pu'][0] <= pu <= model['domain']['load_pu'][1]:
            holds.append(f'{a["asset_id"]}: transfer is outside the fitted loading range.')
        else:
            p = model['parameters']; radius = model['metrics']['band_radius_c']
            peak = max(c['oil_c'], step(c['oil_c'], pu, c['ambient_c'], model['horizon_min'], p['rated_rise_c'], p['tau_min']))+radius
            if peak >= a['oil_limit_c']: holds.append(f'{a["asset_id"]}: upper thermal band reaches the configured limit.')
        if c['voltage_pu'] is None or not .9 <= c['voltage_pu'] <= 1.1: holds.append(f'{a["asset_id"]}: voltage evidence is unavailable or outside the study band.')
        rows.append({'asset_id': a['asset_id'], 'before_kva': before, 'after_kva': after, 'after_load_pu': pu, 'upper_peak_c': peak})
    return {'feasible_in_study': not holds, 'holds': holds, 'assets': rows,
        'balance_error_kva': sum(r['after_kva']-r['before_kva'] for r in rows),
        'scope': 'Advisory equal-kVA transfer only; assumes compatible power factor. No load-flow, phase balance, protection coordination, switching order or equipment command. Engineering review required.'}


class CostOption(Contract):
    hardware: float = Field(ge=0, le=1e8)
    installation: float = Field(ge=0, le=1e8)
    commissioning: float = Field(ge=0, le=1e8)
    annual_connectivity: float = Field(ge=0, le=1e8)
    annual_service: float = Field(ge=0, le=1e8)
    replacement_allowance: float = Field(ge=0, le=1e8)


class Costs(Contract):
    asset_count: int = Field(ge=1, le=100000)
    years: int = Field(5, ge=1, le=20)
    halo: CostOption
    comparison: CostOption
    avoided_incident_value: float | None = Field(None, gt=0, le=1e10)


def costs(c):
    def total(option):
        upfront = option.hardware+option.installation+option.commissioning
        recurring = option.annual_connectivity+option.annual_service
        return {'upfront_per_asset': upfront, 'annual_per_asset': recurring,
            'period_per_asset': upfront+recurring*c.years+option.replacement_allowance,
            'fleet_total': c.asset_count*(upfront+recurring*c.years+option.replacement_allowance)}
    ours, other = total(c.halo), total(c.comparison)
    return {'halo': ours, 'comparison': other, 'cost_difference': other['fleet_total']-ours['fleet_total'],
        'break_even_avoided_incidents': math.ceil(ours['fleet_total']/c.avoided_incident_value) if c.avoided_incident_value else None,
        'scope': 'Undiscounted INR from entered assumptions. Replacement allowance is once per study period. No predicted failures avoided, vendor quotation or demonstrated savings.'}


class LabSample(Contract):
    timestamp: datetime
    hydrogen: float = Field(ge=0, le=1e6)
    methane: float = Field(ge=0, le=1e6)
    ethane: float = Field(ge=0, le=1e6)
    ethylene: float = Field(ge=0, le=1e6)
    acetylene: float = Field(ge=0, le=1e6)
    carbon_monoxide: float = Field(ge=0, le=1e6)
    lab_reference: str = Field(min_length=3, max_length=160)

    @model_validator(mode='after')
    def aware(self):
        if self.timestamp.utcoffset() is None: raise ValueError('Lab timestamps need a timezone.')
        return self


def lab_trend(samples):
    if any(a.timestamp >= b.timestamp for a, b in zip(samples, samples[1:])):
        raise ValueError('Lab samples must be chronological and distinct.')
    gases = ['hydrogen', 'methane', 'ethane', 'ethylene', 'acetylene', 'carbon_monoxide']
    points = [{'timestamp': s.timestamp.isoformat(), 'total_combustible_ppm': sum(getattr(s, g) for g in gases), 'lab_reference': s.lab_reference} for s in samples]
    days = (samples[-1].timestamp-samples[-2].timestamp).total_seconds()/86400 if len(samples)>1 else None
    rates = {g: (getattr(samples[-1], g)-getattr(samples[-2], g))/days for g in gases} if days else {}
    return {'points': points, 'rates_ppm_per_day': rates,
        'scope': 'Entered laboratory results in ppm. Total = H2 + CH4 + C2H6 + C2H4 + C2H2 + CO; CO2 excluded. Trend arithmetic only, not a Duval/IEC diagnosis or a sensor reading. Laboratory interpretation and sampling comparability remain necessary.'}
