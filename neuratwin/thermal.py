"""Reduced-order thermal model with explicit limits on its interpretation.

Independent implementation of a lumped loading-guide-style approximation.
This is not the complete IEC model, nor a certification of compliance.
Top-oil follows an absolute-temperature energy-response approximation;
winding gradient has its own time constant. Parameters are asset specific.
"""
from dataclasses import dataclass
from math import exp, isfinite
import numpy as np
from .domain import Asset


@dataclass(frozen=True)
class ThermalState:
    oil_c: float
    gradient_c: float

    @property
    def hotspot_c(self):
        return self.oil_c + self.gradient_c


def equilibrium(asset: Asset, load_pu: float, ambient_c: float, voltage_pu=1.0):
    losses = (voltage_pu**2 + asset.loss_ratio * load_pu**2) / (1 + asset.loss_ratio)
    oil = ambient_c + asset.rated_oil_rise_c * losses ** asset.oil_exponent
    gradient = asset.rated_winding_gradient_c * load_pu ** asset.winding_exponent
    return ThermalState(oil, gradient)


def step(asset: Asset, state: ThermalState, load_pu: float, ambient_c: float, dt_min: float, voltage_pu=1.0):
    if not all(isfinite(x) for x in [load_pu, ambient_c, dt_min, voltage_pu, state.oil_c, state.gradient_c]):
        raise ValueError('Thermal inputs must be finite.')
    if dt_min < 0 or load_pu < 0 or ambient_c <= -273.15 or voltage_pu <= 0:
        raise ValueError('Invalid physical input or elapsed time.')
    target = equilibrium(asset, load_pu, ambient_c, voltage_pu)
    return ThermalState(
        target.oil_c + (state.oil_c - target.oil_c) * exp(-dt_min / asset.oil_tau_min),
        target.gradient_c + (state.gradient_c - target.gradient_c) * exp(-dt_min / asset.winding_tau_min),
    )


def forecast(asset, initial, load_pu, ambient_c, voltage_pu=1, reduction_pct=0, delay_min=0, horizon_min=120):
    """Hold latest known inputs; never consult actual future telemetry.

    Bands are parameter-sensitivity envelopes, not calibrated probabilities.
    Every intervention branch starts from exactly the same state.
    """
    if not 0 <= reduction_pct <= 50 or not 0 <= delay_min <= 120:
        raise ValueError('Reduction must be 0–50% and delay 0–120 minutes.')
    states = [initial for _ in range(9)]
    factors = np.linspace(.9, 1.1, len(states))
    models = [asset.model_copy(update={
        'rated_oil_rise_c': asset.rated_oil_rise_c * f,
        'rated_winding_gradient_c': asset.rated_winding_gradient_c * f,
        'oil_tau_min': asset.oil_tau_min / f,
    }) for f in factors]
    rows = [{'minute': 0, 'oil_c': initial.oil_c, 'hotspot_c': initial.hotspot_c,
             'low_c': initial.hotspot_c, 'high_c': initial.hotspot_c, 'load_pu': load_pu}]
    for minute in range(1, horizon_min + 1):
        future_load = load_pu * (1 - reduction_pct / 100) if minute > delay_min else load_pu
        states = [step(model, state, future_load, ambient_c, 1, voltage_pu) for model, state in zip(models, states)]
        values = [state.hotspot_c for state in states]
        rows.append({'minute': minute, 'oil_c': states[4].oil_c, 'hotspot_c': states[4].hotspot_c,
                     'low_c': min(values), 'high_c': max(values), 'load_pu': future_load})
    return rows


def forecast_metrics(rows, limit):
    crossing = next((r['minute'] for r in rows if r['hotspot_c'] >= limit), None)
    exposure = sum(max(0, r['hotspot_c'] - limit) for r in rows[1:])
    return {'peak_hotspot_c': float(max(r['hotspot_c'] for r in rows)),
            'minutes_to_limit': crossing,
            'minutes_above_limit': int(sum(r['hotspot_c'] >= limit for r in rows[1:])),
            'exposure_c_min': float(exposure)}
