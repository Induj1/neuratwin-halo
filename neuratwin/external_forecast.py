"""Causal ETTh1 statistical forecasts, separate from the physical thermal twin.

Artifacts contain numeric JSON only. No pickle, executable model or user-supplied
path is loaded. Dataset units and asset transferability remain unverified.
"""
from datetime import datetime, timedelta
from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data' / 'external' / 'ett'
REPORT_PATH = ROOT / 'reports' / 'external-ett-report.json'
VERSION = 'ett-causal-forecast-1'
CHANNELS = ('OT', 'HUFL', 'HULL', 'MUFL', 'MULL', 'LUFL', 'LULL')
LAGS = tuple(range(25)) + (48, 72, 168)
LOOKBACK = 169
HORIZONS = (1, 6)
SPLITS = {'train': (0, 8640), 'validation': (8640, 11520), 'test': (11520, 14400)}
SCOPE = ('Retrospective forecast of public ETTh1 oil-temperature observations. '
         'Not physical-bench validation, a fault classifier, a calibrated safety deadline or an asset-life estimate.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
            ('neuratwin/external_forecast.py', 'scripts/evaluate_external_forecast.py', 'requirements.txt')}


def read_rows(path=None):
    """Keep source column meanings unchanged; missing numerics remain unavailable."""
    with Path(path or DATA_DIR / 'ETTh1.csv').open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if not set(('date', *CHANNELS)).issubset(reader.fieldnames or []):
            raise ValueError('ETTh1 requires date, OT and the six original power-load channels.')
        rows = []
        for record in reader:
            row = {'date': record['date']}
            for key in CHANNELS:
                try:
                    value = float(record[key])
                    row[key] = value if math.isfinite(value) else None
                except (TypeError, ValueError):
                    row[key] = None
            rows.append(row)
    return rows


def feature_names():
    names = [f'OT_lag_{lag}h_minus_current' for lag in LAGS if lag]
    names += ['OT_current']
    for window in (3, 6, 24, 168):
        names += [f'OT_mean_{window}h_minus_current', f'OT_std_{window}h']
    for key in CHANNELS[1:]:
        names += [f'{key}_lag_{lag}h' for lag in (0, 1, 24)] + [f'{key}_mean_24h']
    return names + ['hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos']


def feature_vector(prefix):
    """Use only a contiguous 169-hour observed prefix, inclusive of its origin."""
    if len(prefix) < LOOKBACK:
        raise ValueError('169 hourly observations are required.')
    rows = prefix[-LOOKBACK:]
    times = [datetime.fromisoformat(r['date']) for r in rows]
    if any(b-a != timedelta(hours=1) for a, b in zip(times, times[1:])):
        raise ValueError('Missing, duplicate or non-hourly timestamps withhold this forecast.')
    if any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) for r in rows for k in CHANNELS):
        raise ValueError('Missing/nonfinite required observations withhold this forecast; no zero imputation.')
    current = rows[-1]['OT']
    values = [rows[-1-lag]['OT']-current for lag in LAGS if lag] + [current]
    for window in (3, 6, 24, 168):
        history = [r['OT'] for r in rows[-window:]]
        mean = sum(history)/window
        values += [mean-current, math.sqrt(sum((x-mean)**2 for x in history)/window)]
    for key in CHANNELS[1:]:
        values += [rows[-1-lag][key] for lag in (0, 1, 24)] + [sum(r[key] for r in rows[-24:])/24]
    last = times[-1]
    values += [math.sin(2*math.pi*last.hour/24), math.cos(2*math.pi*last.hour/24),
               math.sin(2*math.pi*last.weekday()/7), math.cos(2*math.pi*last.weekday()/7)]
    return values


def predict_numeric(model, features, current, seasonal):
    """Execute an allowlisted numeric model, never arbitrary serialized code."""
    kind = model['kind']
    if kind == 'persistence': return float(current)
    if kind == 'seasonal_24h': return float(seasonal)
    if kind == 'ridge_delta':
        if not len(features) == len(model['coefficients']) == len(model['mean']) == len(model['scale']):
            raise ValueError('Feature dimensions differ from the frozen model.')
        value = model['intercept'] + sum(c*(x-m)/s for c, x, m, s in
            zip(model['coefficients'], features, model['mean'], model['scale']))
    elif kind == 'hist_gradient_boosting_delta':
        value = model['baseline']
        for tree in model['trees']:
            node_index = 0
            for _ in range(len(tree)+1):
                if not 0 <= node_index < len(tree): raise ValueError('Invalid numeric tree edge.')
                node = tree[node_index]
                if node['leaf']:
                    value += node['value']
                    break
                feature = node['feature']
                if type(feature) is not int or not 0 <= feature < len(features):
                    raise ValueError('Invalid numeric feature index.')
                node_index = node['left'] if features[feature] <= node['threshold'] else node['right']
            else: raise ValueError('Cyclic numeric tree rejected.')
    else:
        raise ValueError('Unrecognized model kind.')
    result = float(current + value)
    if not math.isfinite(result): raise ValueError('Nonfinite prediction rejected.')
    return result


def load_models():
    artifact = json.loads((DATA_DIR / 'forecast-models.json').read_text(encoding='utf-8'))
    if artifact.get('version') != VERSION or digest({k: v for k, v in artifact.items() if k != 'sha256'}) != artifact.get('sha256'):
        raise ValueError('Forecast artifact version/digest mismatch.')
    if artifact['feature_names'] != feature_names() or artifact['source_sha256'] != source_hashes():
        raise ValueError('Forecast source/feature contract changed; revalidation required.')
    return artifact


def predict_prefix(prefix, horizon_hours, artifact=None):
    if type(horizon_hours) is not int or horizon_hours not in HORIZONS:
        raise ValueError('Only frozen 1-hour and 6-hour horizons are supported.')
    artifact = artifact or load_models()
    features = feature_vector(prefix)
    selected = artifact['selected_models'][str(horizon_hours)]
    models = artifact['models'][str(horizon_hours)]
    current = prefix[-1]['OT']
    seasonal = prefix[-1-(24-horizon_hours)]['OT']
    prediction = predict_numeric(models[selected], features, current, seasonal)
    return {'horizon_hours': horizon_hours, 'model': selected, 'predicted_oil': prediction,
            'persistence_oil': current, 'seasonal_oil': seasonal, 'units': 'source units',
            'model_sha256': artifact['sha256'], 'scope': SCOPE}


def public_status():
    if not REPORT_PATH.is_file():
        return {'available': False, 'status': 'not_evaluated', 'scope': SCOPE}
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))
    artifact = load_models()
    valid = (report.get('model_sha256') == artifact['sha256'] and
             report.get('source_sha256') == source_hashes() and
             report.get('sha256') == digest({k: v for k, v in report.items() if k != 'sha256'}))
    if not valid: raise ValueError('External evaluation integrity mismatch.')
    protocol = json.loads((ROOT / 'reports' / 'external-ett-protocol.json').read_text(encoding='utf-8'))
    claim = json.loads((ROOT / 'reports' / 'external-ett-claim.json').read_text(encoding='utf-8'))
    if (protocol.get('sha256') != digest({k:v for k,v in protocol.items() if k!='sha256'}) or
        protocol['sha256'] != report['protocol_sha256'] or protocol['sha256'] != artifact['protocol_sha256'] or
        claim['protocol_sha256'] != protocol['sha256'] or claim['run_id'] != report['run_id'] or
        artifact['run_id'] != report['run_id'] or protocol['source_sha256'] != source_hashes() or
        report['provenance'] != protocol['provenance'] or artifact['dataset_sha256'] != protocol['dataset_sha256']):
        raise ValueError('External protocol/model/report/claim binding mismatch.')
    for name, entry in protocol['provenance']['files'].items():
        if name not in ('ETTh1.csv', 'LICENSE.txt', 'UPSTREAM_README.md'):
            raise ValueError('Unexpected external provenance file.')
        if hashlib.sha256((DATA_DIR / name).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Public source/license bytes changed.')
    return {'available': True, 'status': 'evaluated_public_reference', 'integrity': True, **report}


def demo(origin_index=11520, history_hours=48):
    if type(origin_index) is not int or not 11520 <= origin_index <= 14393:
        raise ValueError('Historical demo origins must lie in the frozen test segment, 11520–14393.')
    if type(history_hours) is not int or not 1 <= history_hours <= 168:
        raise ValueError('History display must be 1–168 hours.')
    report = public_status()
    if not report['available']: raise ValueError('External report is not available.')
    provenance = json.loads((DATA_DIR / 'provenance.json').read_text(encoding='utf-8'))
    if hashlib.sha256((DATA_DIR / 'ETTh1.csv').read_bytes()).hexdigest() != provenance['files']['ETTh1.csv']['sha256']:
        raise ValueError('Dataset bytes differ from their public source provenance.')
    rows = read_rows(); artifact = load_models()
    prefix = rows[max(0, origin_index-LOOKBACK+1):origin_index+1]
    forecasts = []
    for horizon in HORIZONS:
        point = predict_prefix(prefix, horizon, artifact)
        point.update(actual_oil=rows[origin_index+horizon]['OT'], target_timestamp=rows[origin_index+horizon]['date'])
        forecasts.append(point)
    return {'source': 'external_public_dataset', 'dataset': 'ETTh1', 'origin_index': origin_index,
            'origin_timestamp': rows[origin_index]['date'], 'units': 'source units', 'scope': SCOPE,
            'history': [{'timestamp': r['date'], 'oil': r['OT']} for r in rows[origin_index-history_hours+1:origin_index+1]],
            'forecasts': forecasts, 'report_sha256': report['sha256'], 'provenance': report['provenance'],
            'reveal_note': 'Later actual observations are retrospective comparison references; they never enter prefix inference.'}
