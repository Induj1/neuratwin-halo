"""Fit demo oil-response parameters on separate synthetic healthy episodes."""
import json
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import least_squares
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuratwin.domain import ASSETS
from neuratwin.simulation import plant_step
from neuratwin.thermal import ThermalState, equilibrium, step


def episode(seed, count=576):
    rng = np.random.default_rng(seed)
    temperature = np.array([68., 58., 48.])
    scale = 1 + rng.uniform(-.03, .03)
    rows = []
    load = .8
    for i in range(count):
        if i % 36 == 0:
            load = float(rng.uniform(.45, 1.25))
        ambient = float(31 + 6 * np.sin(i / 46))
        for _ in range(10):
            temperature = plant_step(temperature, load, ambient, scale=scale)
        rows.append((load, ambient, float(temperature[1] + rng.normal(0, .18))))
    return np.asarray(rows)


def simulate(config, rows):
    state = ThermalState(rows[0, 2], equilibrium(config, rows[0, 0], rows[0, 1]).gradient_c)
    prediction = [state.oil_c]
    for load, ambient, observed in rows[1:]:
        state = step(config, state, load, ambient, 5)
        prediction.append(state.oil_c)
    return np.asarray(prediction)


def main():
    base = ASSETS['NR-104']
    training = [episode(seed) for seed in [11, 23, 37]]
    names = ['rated_oil_rise_c', 'oil_tau_min', 'oil_exponent']
    def errors(values):
        config = base.model_copy(update=dict(zip(names, values)))
        return np.concatenate([(simulate(config, rows) - rows[:, 2])[36:] for rows in training])
    fitted = least_squares(errors, [48, 155, .9], bounds=([20, 30, .4], [90, 500, 1.6]), loss='soft_l1')
    params = dict(zip(names, map(float, fitted.x)))
    report = {'parameters': params, 'training_seeds': [11, 23, 37],
              'origin': 'Fitted on separate healthy episodes from the independently implemented three-node synthetic plant.',
              'limits': 'Synthetic calibration only. Winding-gradient parameters are assumed and not fitted from oil measurements.',
              'train_oil_rmse_c': float(np.sqrt(np.mean(errors(fitted.x)**2)))}
    path = ROOT/'data/demo_calibration.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
