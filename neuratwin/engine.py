"""Deterministic inference over observed history only; scenario labels are absent."""
from datetime import timedelta
import math
import numpy as np
from .domain import Asset, Reading, check_sequence
from .thermal import ThermalState, equilibrium, step, forecast, forecast_metrics


def analyse(asset: Asset, readings: list[Reading], reduction_pct=20, delay_min=10):
    check_sequence(readings)
    intervals = [(b.timestamp - a.timestamp).total_seconds() / 60 for a, b in zip(readings, readings[1:])]
    typical_interval = float(np.median(intervals))
    first = readings[0]
    last_load = first.load_pu if first.load_pu is not None else .75
    last_ambient = first.ambient_c if first.ambient_c is not None else 30
    last_voltage = first.voltage_pu if first.voltage_pu is not None else 1
    eq = equilibrium(asset, last_load, last_ambient, last_voltage)
    reference = ThermalState(first.oil_c if first.oil_c is not None else eq.oil_c, eq.gradient_c)
    points, events, active, residual_window = [], [], {}, []
    current_alerts = []
    for i, row in enumerate(readings):
        flags = []
        dt = intervals[i-1] if i else 0
        if dt > max(15, typical_interval * 3):
            flags.append('time_gap')
        if row.load_pu is None or row.ambient_c is None or row.voltage_pu is None:
            flags.append('missing_operating')
        last_load = row.load_pu if row.load_pu is not None else last_load
        last_ambient = row.ambient_c if row.ambient_c is not None else last_ambient
        last_voltage = row.voltage_pu if row.voltage_pu is not None else last_voltage
        reference = step(asset, reference, last_load, last_ambient, dt, last_voltage)
        oil, second = row.oil_c, row.oil_reference_c
        measured = oil
        source = 'primary probe'
        confidence = 'High'
        if oil is None:
            flags.append('missing_primary')
            measured, source, confidence = second, 'reference probe', 'Moderate'
        if oil is not None and second is not None and abs(oil - second) > 3:
            flags.append('sensor_disagreement')
            if abs(second - reference.oil_c) < asset.residual_limit_c:
                measured, source, confidence = second, 'reference probe; primary quarantined', 'Moderate'
            elif abs(oil - reference.oil_c) < asset.residual_limit_c:
                measured, source, confidence = oil, 'primary probe; reference quarantined', 'Moderate'
            else:
                measured, source, confidence = None, 'model only; probes disagree', 'Low'
        if oil is not None and second is None:
            confidence = 'Moderate'
        if i >= 5:
            recent = readings[i-5:i+1]
            oils = [r.oil_c for r in recent]
            loads = [r.load_pu for r in recent if r.load_pu is not None]
            if all(v is not None for v in oils) and max(oils) == min(oils) and len(loads) == 6 and max(loads) - min(loads) > .12:
                flags.append('stuck_probe')
                measured, source, confidence = second, 'reference probe after primary flatline', 'Moderate' if second is not None else 'Low'
        residual = measured - reference.oil_c if measured is not None else None
        residual_window.append(residual)
        persistent = len(residual_window) >= 3 and all(r is not None and r > asset.residual_limit_c for r in residual_window[-3:])
        if persistent and second is None:
            flags.append('unverified_temperature')
            confidence = 'Low'
        if measured is None:
            flags.append('no_oil_measurement')
            confidence = 'Low'
        if 'missing_operating' in flags or 'time_gap' in flags:
            confidence = 'Low'
        estimate = ThermalState(measured if measured is not None else reference.oil_c, reference.gradient_c)
        current_alerts = []

        def alert(code, severity, title, evidence, action):
            current_alerts.append({'code': code, 'severity': severity, 'title': title, 'evidence': evidence, 'action': action})

        if 'missing_operating' in flags or 'no_oil_measurement' in flags or 'time_gap' in flags:
            alert('telemetry', 'warning', 'Telemetry needs attention',
                  'Critical inputs are missing or the sampling interval has a gap. State propagation uses previous inputs.',
                  'Restore the measurement stream and verify timestamps before relying on a new action forecast.')
        if 'sensor_disagreement' in flags or 'stuck_probe' in flags:
            detail = f'Oil probes disagree by {abs(oil-second):.1f} C.' if oil is not None and second is not None else 'The primary probe is flat while load changes.'
            alert('measurement', 'warning', 'Check temperature measurement', detail + ' ' + source.capitalize() + '.',
                  'Compare with an independent calibrated reading and inspect the indicated probe; equipment fault is not established.')
        if persistent:
            title = 'Unexplained thermal deviation' if second is not None else 'Temperature cause unresolved'
            corroboration = 'An independent probe is available.' if second is not None else 'A second temperature channel is unavailable; sensor bias cannot be excluded.'
            alert('thermal_deviation', 'warning', title,
                  f'Temperature exceeds the reference response by {residual:.1f} C for at least three readings. {corroboration}',
                  'Verify temperature, loading and model parameters; inspect heat-rejection paths if the excess temperature is confirmed.')
        if row.load_pu is not None and row.load_pu > 1.05:
            alert('loading', 'warning', 'Loading above nameplate', f'Observed loading is {row.load_pu*100:.0f}% of the configured {asset.rated_kva:g} kVA rating.',
                  'Review the load trajectory and compare a feasible reduction with the current forecast.')
        if measured is not None and confidence != 'Low' and estimate.hotspot_c >= asset.hotspot_limit_c:
            alert('thermal_limit', 'critical', 'Estimated hot-spot above configured limit',
                  f'Estimated {estimate.hotspot_c:.1f} C versus the demonstration limit of {asset.hotspot_limit_c:g} C; winding hot-spot is not directly measured.',
                  'Escalate for operator assessment and evaluate load reduction under the asset operating procedure.')
        if row.voltage_pu is not None and not .9 <= row.voltage_pu <= 1.1:
            alert('voltage', 'warning', 'Voltage outside demonstration band', f'Measured voltage is {row.voltage_pu:.3f} per unit; demo band is 0.90–1.10.',
                  'Verify the measurement and investigate supply conditions. This band is not a standards-compliance assessment.')
        if row.current_thd_pct is not None and row.current_thd_pct > 8:
            alert('harmonics', 'warning', 'Elevated measured current distortion', f'Measured current THD is {row.current_thd_pct:.1f}%; demo screening threshold is 8%.',
                  'Obtain a harmonic spectrum and equipment-specific assessment; THD alone does not determine additional losses.')
        now_codes = {a['code'] for a in current_alerts}
        for code in set(active) - now_codes:
            active[code]['resolved_at'] = row.timestamp.isoformat()
            del active[code]
        for a in current_alerts:
            if a['code'] not in active:
                event = {**a, 'id': f'{asset.asset_id}:{a["code"]}:{row.timestamp.isoformat()}',
                         'started_at': row.timestamp.isoformat(), 'resolved_at': None}
                active[a['code']] = event
                events.append(event)
            a['id'] = active[a['code']]['id']
            a['started_at'] = active[a['code']]['started_at']
        thermal_penalty = max(0, estimate.hotspot_c - 80) * .85
        loading_penalty = max(0, last_load - 1) * 65
        deviation_penalty = max(0, (residual or 0) - asset.residual_limit_c) * 2
        index = max(0, min(100, round(100 - max(thermal_penalty, loading_penalty, deviation_penalty)))) if confidence != 'Low' else None
        points.append({'timestamp': row.timestamp.isoformat(), 'load_pu': row.load_pu, 'ambient_c': row.ambient_c,
                       'oil_c': oil, 'oil_reference_c': second, 'expected_oil_c': reference.oil_c,
                       'estimated_hotspot_c': estimate.hotspot_c, 'residual_c': residual, 'condition_index': index,
                       'confidence': confidence, 'source': source, 'flags': flags, 'voltage_pu': row.voltage_pu,
                       'current_thd_pct': row.current_thd_pct})
    current = points[-1]
    forecast_available = current['confidence'] != 'Low'
    baseline = alternative = metrics = None
    if forecast_available:
        baseline = forecast(asset, estimate, last_load, last_ambient, last_voltage)
        alternative = forecast(asset, estimate, last_load, last_ambient, last_voltage, reduction_pct, delay_min)
        before = forecast_metrics(baseline, asset.hotspot_limit_c)
        after = forecast_metrics(alternative, asset.hotspot_limit_c)
        metrics = {'baseline': before, 'alternative': after,
                   'peak_reduction_c': before['peak_hotspot_c'] - after['peak_hotspot_c'],
                   'exposure_reduction_c_min': before['exposure_c_min'] - after['exposure_c_min']}
        if before['minutes_to_limit'] is not None and before['minutes_to_limit'] > 0:
            current_alerts.append({'code': 'forecast', 'severity': 'warning', 'title': 'Projected thermal limit approach',
                                  'id': f'{asset.asset_id}:forecast:{current["timestamp"]}', 'started_at': current['timestamp'],
                                  'evidence': f'The central forecast reaches the configured limit in {before["minutes_to_limit"]} minutes if the latest load and ambient stay constant.',
                                  'action': 'Compare feasible load reductions; this is a conditional model projection, not time to failure.'})
    current_alerts.sort(key=lambda a: (a['severity'] != 'critical', a['code'] not in ('telemetry', 'measurement')))
    status = 'critical' if any(a['severity'] == 'critical' for a in current_alerts) else 'attention' if current_alerts else 'normal'
    return {'asset': asset.model_dump(), 'current': current, 'status': status, 'history': points,
            'alerts': current_alerts, 'events': events, 'forecast': baseline, 'alternative': alternative, 'comparison': metrics,
            'forecast_note': 'Latest measured load, ambient and voltage are held constant. Shading spans ±10% thermal-parameter scenarios; it is not a calibrated probability interval.',
            'forecast_unavailable_reason': None if forecast_available else 'Measurement confidence is low. Resolve the data or diagnostic uncertainty before comparing actions.',
            'intervention': {'reduction_pct': reduction_pct, 'delay_min': delay_min, 'horizon_min': 120},
            'index_note': 'Heuristic thermal-condition score: 100 minus the largest thermal, loading or residual penalty. Not failure probability or remaining life.',
            'limitations': ['Hot-spot is an unvalidated inferred state.', 'No DGA, moisture or maintenance-history evidence is connected.',
                            'Cause attribution is conditional; common-mode sensor faults and model mismatch can remain indistinguishable.',
                            'No physical switching or automatic control is performed.']}
