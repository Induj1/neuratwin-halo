"""Synthetic three-node plant, deliberately distinct from the two-state twin.

Energy balances couple winding, oil and tank temperatures. Nonlinear heat
rejection and resistance-temperature effects create model mismatch. Synthetic
truth is kept separate from the Reading contract and never sent to inference.
This is a test plant, not field validation or a high-fidelity FEM model.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import numpy as np
from .domain import Reading

SCENARIOS = {
    'overload': {'name': 'Evening overload', 'description': 'A sustained load increase tests early warning and action comparison.'},
    'cooling': {'name': 'Cooling deviation', 'description': 'Reduced heat rejection creates a persistent temperature deviation.'},
    'sensor': {'name': 'Sensor disagreement', 'description': 'One oil probe drifts; an independent reference remains available.'},
    'ambiguous': {'name': 'Uncertain temperature', 'description': 'Temperature drift without a second probe; cause must remain unresolved.'},
    'dropout': {'name': 'Telemetry interruption', 'description': 'Missing measurements lower confidence and suppress action forecasts.'},
    'normal': {'name': 'Normal operation', 'description': 'Changing load and ambient temperature without an injected fault.'},
}


def plant_step(temperatures, load, ambient, cooling=1.0, scale=1.0, voltage=1.0, dt=.5):
    winding, oil, tank = temperatures
    copper = 4.5 * load**2 * np.clip(1 + .0039 * (winding - 75), .65, 1.5)
    core = .6 * voltage**2
    flow_wo = (winding - oil) / (4.2 * scale)
    flow_ot = (oil - tank) / (2.5 * scale)
    delta = tank - ambient
    flow_ta = delta / (7.0 * scale * cooling) * (1 + .0025 * abs(delta))
    return np.asarray([
        winding + dt * (copper - flow_wo) / 1.6,
        oil + dt * (core + flow_wo - flow_ot) / 12,
        tank + dt * (flow_ot - flow_ta) / 3,
    ])


@lru_cache(maxsize=128)
def scenario(name='overload', seed=104, count=288):
    if name not in SCENARIOS:
        raise ValueError('Unknown scenario.')
    rng = np.random.default_rng(seed)
    start = datetime(2026, 9, 22, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    scale = 1 + rng.uniform(-.04, .04)
    temperatures = np.array([72., 61., 53.])
    # Warm the independent plant before starting the recorded episode.
    for _ in range(1500):
        temperatures = plant_step(temperatures, .76, 29, scale=scale)
    rows, truth = [], []
    for index in range(count):
        minute = index * 5
        ambient = 31 + 4 * np.sin(2 * np.pi * (minute - 300) / 1440)
        load = .78 + .08 * np.sin(minute / 110) + .025 * np.sin(minute / 19)
        voltage = 1 + .012 * np.sin(minute / 49)
        fault = index >= 144
        cooling = 1.0
        if name == 'overload' and fault:
            load = 1.42 + .05 * np.sin(minute / 63)
        if name == 'cooling' and fault:
            load = .94 + .025 * np.sin(minute / 45)
            cooling = 1.85
        for _ in range(10):
            temperatures = plant_step(temperatures, load, ambient, cooling, scale, voltage)
        oil = float(temperatures[1] + rng.normal(0, .22))
        reference = float(temperatures[1] + rng.normal(0, .18))
        if name in ('sensor', 'ambiguous') and fault:
            oil += min(15, (index - 144) * .7)
        if name == 'ambiguous':
            reference = None
        data = dict(timestamp=start + timedelta(minutes=minute), load_pu=float(load), ambient_c=float(ambient),
                    oil_c=oil, oil_reference_c=reference, voltage_pu=float(voltage), current_thd_pct=3.2 + .5 * np.sin(minute / 40))
        if name == 'dropout' and 144 <= index < 169:
            data.update(oil_c=None, oil_reference_c=None, load_pu=None, ambient_c=None)
        rows.append(Reading(**data))
        truth.append({'oil_c': float(temperatures[1]), 'hotspot_c': float(temperatures[0]), 'fault_active': bool(fault and name != 'normal')})
    return tuple(rows), tuple(truth)
