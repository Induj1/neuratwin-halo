"""Explicit, held-out surface-response calibration; notes never change parameters."""
import numpy as np
from scipy.optimize import least_squares
from .maintenance_model import Profile, seconds, step, unique_rows, valid


def propose(rows, profile):
    rows = unique_rows(rows)
    result = {'available': False, 'scope': 'Surface-response fit, not winding or oil calibration.'}
    def hold(message): return {**result, 'reason': message}
    if len(rows) < 120 or seconds(rows[-1]['timestamp'])-seconds(rows[0]['timestamp']) < 1200:
        return hold('Collect at least 20 minutes and 120 independent samples.')
    if any(not valid(r, profile) or r.get('current_source') != 'measured' or not r.get('calibrated') or r.get('temperature_source') != 'measured' for r in rows):
        return hold('Calibration requires calibrated, independently measured current and surface temperature throughout.')
    if len({r.get('boot_id') for r in rows}) != 1 or any(not 0 < seconds(b['timestamp'])-seconds(a['timestamp']) <= 10 for a,b in zip(rows,rows[1:])):
        return hold('Use one uninterrupted acquisition without a device restart.')
    ambient = [r.get('ambient_c', profile.ambient_c) for r in rows]
    if max(ambient)-min(ambient) > 2:
        return hold('Ambient conditions changed; collect a comparable interval.')
    split = int(len(rows)*.7)
    train = rows[:split]
    if np.ptp([r['current_a']/profile.rated_current_a for r in train]) < .2 or np.ptp([r['temperature_c'] for r in train]) < 2:
        return hold('The training interval needs a meaningful load change and at least 2 C of temperature response.')
    def predict(data, parameters):
        p = profile.model_copy(update={'rated_rise_c': float(parameters[0]), 'tau_min': float(parameters[1])})
        value=data[0]['temperature_c']; out=[]
        for before, after in zip(data,data[1:]):
            value=step(value,before['current_a']/p.rated_current_a,seconds(after['timestamp'])-seconds(before['timestamp']),p,energized=before['voltage_v']>1,ambient=before.get('ambient_c',p.ambient_c))
            out.append(value)
        return np.array(out)
    observed=np.array([r['temperature_c'] for r in train[1:]])
    fit=least_squares(lambda x:predict(train,x)-observed,[profile.rated_rise_c,profile.tau_min],bounds=([5,1],[150,600]),max_nfev=100)
    singular=np.linalg.svd(fit.jac,compute_uv=False)
    if not fit.success or singular[-1] < 1e-5 or singular[0]/singular[-1] > 1000 or np.any(fit.active_mask):
        return hold('Parameters are poorly identified or reach the declared bounds.')
    validation=rows[split-1:]; truth=np.array([r['temperature_c'] for r in validation[1:]])
    prediction=predict(validation,fit.x)
    error=float(np.sqrt(np.mean((prediction-truth)**2)))
    baseline=float(np.sqrt(np.mean((validation[0]['temperature_c']-truth)**2)))
    if error > 2 or baseline < .2 or error >= .8*baseline:
        return hold('Held-out error must be below 2 C and improve persistence by at least 20%.')
    return {**result,'available':True,'proposed_profile':{**profile.model_dump(),'rated_rise_c':float(fit.x[0]),'tau_min':float(fit.x[1])},
        'train_samples':split,'held_out_samples':len(truth),'held_out_rmse_c':error,'persistence_rmse_c':baseline,
        'condition_number':float(singular[0]/singular[-1]),'ambient_basis':'Recorded ambient where available; otherwise explicit profile assumption.',
        'reason':'Review and explicitly accept the proposed parameters. Held-out agreement is not field-wide validation.'}
