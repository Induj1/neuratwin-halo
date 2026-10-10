"""Conditional thermal decisions and observation-based follow-up, without actuation."""
from datetime import datetime
from itertools import product
import math
from pydantic import Field, model_validator
from .halo_contracts import Contract

VERSION = 'maintenance-thermal-1'


class Profile(Contract):
    rated_current_a: float = Field(1, gt=0, le=200000)
    rated_rise_c: float = Field(45, ge=5, le=150)
    tau_min: float = Field(30, ge=1, le=600)
    loss_ratio: float = Field(5, ge=.1, le=30)
    ambient_c: float = Field(25, ge=-20, le=55)
    temperature_limit_c: float = Field(80, ge=30, le=180)
    max_loading_pu: float = Field(2, ge=.1, le=3)


class DecisionOptions(Contract):
    horizon_min: int = Field(120, ge=10, le=240)
    cooling_min: float = Field(.6, ge=.3, le=1.5)
    cooling_max: float = Field(1, ge=.3, le=1.5)
    rise_uncertainty_percent: float = Field(15, ge=0, le=40)
    max_reduction_percent: int = Field(70, ge=0, le=100)
    site_kw: float | None = Field(None, gt=0, le=100000)
    energy_cost_per_kwh: float | None = Field(None, ge=0, le=100000)
    intervention_cost: float | None = Field(None, ge=0, le=10000000)
    inspection_cost: float | None = Field(None, ge=0, le=10000000)
    sensor_purchase_cost: float | None = Field(None, ge=0, le=10000000)
    sensor_install_cost: float | None = Field(None, ge=0, le=10000000)
    sensor_service_cost: float | None = Field(None, ge=0, le=10000000)

    @model_validator(mode='after')
    def bounds(self):
        if self.cooling_min > self.cooling_max:
            raise ValueError('Cooling lower bound must not exceed upper bound.')
        return self


def seconds(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def unique_rows(rows):
    return sorted({r['sample_key']: r for r in rows if r and r.get('timestamp')}.values(), key=lambda r: seconds(r['timestamp']))


def valid(row, p):
    return all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) for k in ('current_a', 'temperature_c', 'voltage_v')) and 0 <= row['current_a']/p.rated_current_a <= p.max_loading_pu and -20 <= row['temperature_c'] <= 200 and row['voltage_v'] >= 0


def step(temperature, loading, seconds_dt, p, cooling=1, rise_scale=1, energized=True, ambient=None):
    ambient = p.ambient_c if ambient is None else ambient
    rise = p.rated_rise_c * rise_scale * ((1+p.loss_ratio*loading**2)/(1+p.loss_ratio))**.8/cooling
    target = ambient + (rise if energized else 0)
    return target + (temperature-target)*math.exp(-seconds_dt/(p.tau_min*60))


def forecast(row, p, options, reduction=0, cooling=1, rise_scale=1):
    loading = row['current_a']/p.rated_current_a*(1-reduction/100)
    return [{'minute': minute, 'temperature_c': step(row['temperature_c'], loading, minute*60, p, cooling, rise_scale, row['voltage_v']>1)} for minute in range(options.horizon_min+1)]


def decision(rows, p, options, *, live, channel):
    rows = unique_rows(rows)
    base = {'version': VERSION, 'available': False, 'channel': channel, 'profile': p.model_dump(), 'options': options.model_dump(),
            'scope': 'Conditional scenario comparison; no calibrated probabilities, no hardware action.',
            'holds': [], 'scenarios': [], 'measurements': [], 'forecast': []}
    if not rows or not valid(rows[-1], p):
        base['holds'] = ['Current, temperature or voltage is missing or outside the declared model envelope.']
        return base
    if not live:
        base['holds'] = ['Source is cached or offline. Reconnect before recording a new action forecast.']
        return base
    last = rows[-1]
    scenarios = []
    actions = list(range(0, options.max_reduction_percent+1, 10))
    if options.max_reduction_percent not in actions: actions.append(options.max_reduction_percent)
    factors = sorted(set([1-options.rise_uncertainty_percent/100, 1, 1+options.rise_uncertainty_percent/100]))
    coolings = sorted(set([options.cooling_min, (options.cooling_min+options.cooling_max)/2, options.cooling_max]))
    for cooling, rise in product(coolings, factors):
        curve = forecast(last, p, options, cooling=cooling, rise_scale=rise)
        candidates = []
        for reduction in actions:
            candidate = forecast(last, p, options, reduction, cooling, rise)
            # Include initial exposure: a hot asset cannot be declared safe by erasing t=0.
            if max(v['temperature_c'] for v in candidate) < p.temperature_limit_c:
                candidates.append(reduction)
        crossing = next((v['minute'] for v in curve if v['temperature_c'] >= p.temperature_limit_c), None)
        scenarios.append({'cooling': cooling, 'rise_scale': rise, 'peak_c': max(v['temperature_c'] for v in curve),
                          'first_crossing_min': crossing, 'minutes_at_or_above_limit': sum(v['temperature_c'] >= p.temperature_limit_c for v in curve[1:]),
                          'reduction_percent': min(candidates) if candidates else None, 'safe_candidates': candidates})
    common = set(actions)
    for s in scenarios: common &= set(s['safe_candidates'])
    robust = min(common) if common else None
    recommendations = {s['reduction_percent'] for s in scenarios}
    agree = len(recommendations) == 1
    before = forecast(last, p, options)
    after = forecast(last, p, options, robust or 0)
    costs_known = all(v is not None for v in (options.site_kw, options.energy_cost_per_kwh, options.intervention_cost))
    cost = lambda r: options.site_kw*options.horizon_min/60*r/100*options.energy_cost_per_kwh + (options.intervention_cost if r else 0)
    robust_cost = cost(robust) if costs_known and robust is not None else None
    for name, resolves, price in [('Cooling inspection', 'cooling', options.inspection_cost),
        ('Calibrated thermal measurement', 'rise_scale', None if any(v is None for v in (options.sensor_purchase_cost, options.sensor_install_cost, options.sensor_service_cost)) else options.sensor_purchase_cost+options.sensor_install_cost+options.sensor_service_cost)]:
        groups = []
        for value in sorted({s[resolves] for s in scenarios}):
            group = [s for s in scenarios if s[resolves] == value]
            choices = set(actions)
            for s in group: choices &= set(s['safe_candidates'])
            groups.append(min(choices) if choices else None)
        can_change = any(r is not None and r != robust for r in groups)
        upper = max(0, robust_cost-min(cost(r) for r in groups if r is not None)) if robust_cost is not None and any(r is not None for r in groups) else None
        base['measurements'].append({'name': name, 'resolves': resolves, 'total_cost': price,
            'can_change_action': can_change, 'maximum_avoidable_cost': upper,
            'net_benefit_upper_bound': upper-price if upper is not None and price is not None else None,
            'assessment': 'No action change in these scenarios' if not can_change else 'Enter cost assumptions' if upper is None or price is None else 'Could justify its cost; review assumptions' if upper > price else 'Cost exceeds this optimistic benefit bound',
            'basis': 'Optimistic bound: measurement perfectly resolves this scenario parameter; remaining uncertainty persists. No outcome probabilities or expected savings are claimed.'})
    base.update(available=True, origin=last, scenarios=scenarios, agreement=agree, robust_reduction_percent=robust,
        recommendation='Inspect before increasing load; no tested reduction meets all limits' if robust is None else 'Maintain present load' if robust==0 else f'Reduce load by {robust}% under these assumptions',
        uncertainty_action='Same action across all tested scenarios' if agree else 'Scenarios disagree: review the targeted measurement comparison',
        forecast=before, after_forecast=after, thermal_range_c=[min(s['peak_c'] for s in scenarios), max(s['peak_c'] for s in scenarios)],
        curtailed_kwh=options.site_kw*options.horizon_min/60*(robust/100) if options.site_kw is not None and robust is not None else None,
        robust_action_cost=robust_cost, currency='INR', interval_kind='scenario range, not probability interval')
    return base


def verification(job, rows, *, live):
    action = job.get('action')
    if not action: return {'outcome': 'insufficient_evidence', 'reason': 'Record the action and freeze its follow-up forecast first.', 'points': []}
    p = Profile(**action['profile']); origin = action['origin']; start = seconds(origin['timestamp'])
    points = []; excluded = []; gaps = False; last_time = start
    limit = job['acceptance']['temperature_limit_c']; window = job['acceptance']['stable_minutes']
    for row in unique_rows(rows):
        minute = (seconds(row['timestamp'])-start)/60
        if minute <= 0 or minute > action['horizon_min']: continue
        reason = None
        if not valid(row, p): reason = 'invalid channels'
        elif row.get('boot_id') != origin.get('boot_id'): reason = 'device restarted'
        elif row.get('current_source') != origin.get('current_source'): reason = 'current provenance changed'
        elif abs(row['current_a']-origin['current_a']) > max(.01*p.rated_current_a, .05*abs(origin['current_a'])): reason = 'loading changed'
        elif (row['voltage_v']>1) != (origin['voltage_v']>1): reason = 'energization changed'
        elif abs(row.get('ambient_c', p.ambient_c)-origin.get('ambient_c',p.ambient_c)) > 2: reason = 'ambient changed'
        if seconds(row['timestamp'])-last_time > (10 if job['mode']=='prototype' else 65): gaps=True
        last_time = seconds(row['timestamp'])
        if reason:
            excluded.append({'timestamp':row['timestamp'], 'reason':reason});continue
        prediction = step(origin['temperature_c'],origin['current_a']/p.rated_current_a,minute*60,p,ambient=origin.get('ambient_c',p.ambient_c),energized=origin['voltage_v']>1)
        points.append({'minute':minute, 'predicted_c':prediction, 'observed_c':row['temperature_c'], 'timestamp':row['timestamp']})
    coverage = points[-1]['minute'] if points else 0
    enough = live and not gaps and not excluded and len(points)>=3 and coverage>=window
    if not enough: outcome='insufficient_evidence'; reason='Need fresh, uninterrupted comparable readings through the acceptance window. Changed inputs and provenance are excluded.'
    elif any(v['observed_c']>=limit for v in points if v['minute']>=coverage-window): outcome='unresolved'; reason='Observed temperature still crosses the recorded limit.'
    elif job['findings'].get('issue_resolved') and points[-1]['observed_c']<origin['temperature_c']-1: outcome='improved'; reason='Operator reports correction; comparable observations are cooler and within the recorded limit. This does not establish internal repair.'
    else: outcome='stabilized'; reason='Comparable observations are within the recorded limit; lasting repair is not established.'
    return {'outcome':outcome,'reason':reason,'points':points,'excluded':excluded,'gap_detected':gaps,'coverage_minutes':coverage,
            'mae_c':sum(abs(v['predicted_c']-v['observed_c']) for v in points)/len(points) if points else None,
            'scope':'Observed surface verification' if job['mode']=='prototype' else 'Simulation consistency check, not field validation'}
