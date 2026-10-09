"""Freeze and evaluate public ETTh1 forecasting without test-driven selection."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
import uuid
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from neuratwin import external_forecast as ef

PROTOCOL = ef.ROOT / 'reports' / 'external-ett-protocol.json'
CANDIDATES = ('persistence', 'seasonal_24h', 'ridge', 'hist_gradient_boosting')
PARAMETERS = {'ridge': {'alpha': 100.0}, 'hist_gradient_boosting': {
    'loss': 'absolute_error', 'learning_rate': .05, 'max_iter': 180, 'max_leaf_nodes': 15,
    'min_samples_leaf': 40, 'l2_regularization': 10., 'early_stopping': False, 'random_state': 17}}


def now(): return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def freeze(path=PROTOCOL):
    provenance = json.loads((ef.DATA_DIR / 'provenance.json').read_text(encoding='utf-8'))
    for name, entry in provenance['files'].items():
        if hashlib.sha256((ef.DATA_DIR / name).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Upstream data/license bytes changed.')
    value = {'version': ef.VERSION, 'created_at': now(), 'source_sha256': ef.source_hashes(),
             'dataset_sha256': provenance['files']['ETTh1.csv']['sha256'], 'provenance': provenance,
             'split_rows_half_open': ef.SPLITS, 'horizons_hours': ef.HORIZONS, 'lookback_hours': ef.LOOKBACK,
             'features': ef.feature_names(), 'models': CANDIDATES, 'parameters': PARAMETERS,
             'selection': 'Per horizon choose lowest validation MAE; ties use declared candidate order. Fit training only; no refit on validation. Freeze model and validation metrics before test evaluation.',
             'purging': 'Every target must remain strictly inside its partition. Origins can use preceding observed history only. First168 rows are warm-up; final horizon rows of each split are purged.',
             'test_access': 'Test outputs are evaluated once after model selection is frozen; no tuning, retries for preferred results, or split changes. Future observations never enter features.',
             'scope': ef.SCOPE, 'units': 'source units', 'no_fault_claim': True,
             'omitted_tail': 'Rows at index14400 and later are excluded, not alternative validation or optimization data.',
             'dependencies': {'python': platform.python_version(), 'numpy': np.__version__, 'scikit_learn': sklearn.__version__}}
    value['sha256'] = ef.digest(value); write_new(path, value); return value


def checked(path=PROTOCOL):
    protocol = json.loads(Path(path).read_text(encoding='utf-8'))
    if protocol['sha256'] != ef.digest({k:v for k,v in protocol.items() if k!='sha256'}):
        raise ValueError('Protocol digest mismatch.')
    if protocol['source_sha256'] != ef.source_hashes(): raise ValueError('Frozen evaluation sources changed.')
    if hashlib.sha256((ef.DATA_DIR/'ETTh1.csv').read_bytes()).hexdigest()!=protocol['dataset_sha256']:
        raise ValueError('Frozen dataset bytes changed.')
    return protocol


def examples(rows, partition, horizon):
    start, end = ef.SPLITS[partition]
    samples=[]; unavailable={}
    possible = max(0, min(len(rows), end)-start-horizon)
    for index in range(start, min(len(rows), end)-horizon):
        if index < ef.LOOKBACK-1:
            unavailable['initial_lookback'] = unavailable.get('initial_lookback',0)+1; continue
        try:
            features=ef.feature_vector(rows[index-ef.LOOKBACK+1:index+1])
            target=rows[index+horizon]['OT']
            if target is None or not np.isfinite(target): raise ValueError('Missing later observation.')
            # Horizon is elapsed hours, never just positional rows over a gap.
            if (datetime.fromisoformat(rows[index+horizon]['date'])-datetime.fromisoformat(rows[index]['date'])).total_seconds()!=3600*horizon:
                raise ValueError('Future target timestamp gap.')
        except (ValueError, KeyError):
            unavailable['unavailable_channels_or_timebase']=unavailable.get('unavailable_channels_or_timebase',0)+1; continue
        samples.append({'index':index, 'features':features,'actual':target,'current':rows[index]['OT'],
                        'seasonal':rows[index-(24-horizon)]['OT']})
    return samples, {'possible':possible,'scored':len(samples),'coverage_fraction':len(samples)/possible if possible else None,
                     'unavailable':unavailable,'boundary_purged_origins':horizon}


def metrics(actual, predicted, coverage):
    error=np.asarray(predicted)-np.asarray(actual);absolute=np.abs(error)
    if not len(error): return {**coverage,'mae':None,'rmse':None,'p95_absolute_error':None,'max_absolute_error':None}
    return {**coverage, 'mae':float(np.mean(absolute)), 'rmse':float(np.sqrt(np.mean(error**2))),
            'median_absolute_error':float(np.median(absolute)), 'p95_absolute_error':float(np.quantile(absolute,.95)),
            'max_absolute_error':float(np.max(absolute)), 'mean_signed_error':float(np.mean(error)),
            'p95_underprediction':float(np.quantile(np.maximum(0,-error),.95)),
            'max_underprediction':float(np.max(np.maximum(0,-error)))}


def fit_models(training):
    x=np.asarray([r['features'] for r in training]);current=np.asarray([r['current'] for r in training])
    delta=np.asarray([r['actual'] for r in training])-current
    scaler=StandardScaler().fit(x);ridge=Ridge(**PARAMETERS['ridge']).fit(scaler.transform(x),delta)
    gradient=HistGradientBoostingRegressor(**PARAMETERS['hist_gradient_boosting']).fit(x,delta)
    trees=[]
    for predictors in gradient._predictors:
        nodes=predictors[0].nodes
        trees.append([{'leaf':bool(n['is_leaf']),'value':float(n['value']),'feature':int(n['feature_idx']),
                       'threshold':float(n['num_threshold']),'left':int(n['left']),'right':int(n['right'])} for n in nodes])
    models={'persistence':{'kind':'persistence'},'seasonal_24h':{'kind':'seasonal_24h'},
            'ridge':{'kind':'ridge_delta','coefficients':ridge.coef_.tolist(),'intercept':float(ridge.intercept_),
                     'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist()},
            'hist_gradient_boosting':{'kind':'hist_gradient_boosting_delta','baseline':float(gradient._baseline_prediction[0,0]),'trees':trees}}
    # Serialized numeric inference must match its fitted estimator before any test scoring.
    for name, expected in [('ridge',current+ridge.predict(scaler.transform(x))),
                           ('hist_gradient_boosting',current+gradient.predict(x))]:
        actual=np.array([ef.predict_numeric(models[name],r['features'],r['current'],r['seasonal']) for r in training])
        if not np.allclose(actual,expected,rtol=0,atol=1e-10): raise ValueError('JSON inference differs from fitted estimator.')
    return models


def score_models(models,samples,coverage):
    actual=[r['actual'] for r in samples]
    predictions={name:[ef.predict_numeric(model,r['features'],r['current'],r['seasonal']) for r in samples]
                 for name,model in models.items()}
    return {name:metrics(actual,values,coverage) for name,values in predictions.items()},predictions


def run(path=PROTOCOL):
    protocol=checked(path); run_id='ETT-'+uuid.uuid4().hex
    claim={'run_id':run_id,'started_at':now(),'protocol_sha256':protocol['sha256'],'scope':ef.SCOPE}
    write_new(ef.ROOT/'reports'/'external-ett-claim.json',claim)
    try:
        rows=ef.read_rows()
        if len(rows)<14400: raise ValueError('Frozen split requires at least14400 hourly rows.')
        models={};validation={};chosen={};training_coverage={}
        for h in ef.HORIZONS:
            train,train_cov=examples(rows,'train',h); val,val_cov=examples(rows,'validation',h)
            models[str(h)]=fit_models(train)
            validation[str(h)],_=score_models(models[str(h)],val,val_cov)
            chosen[str(h)]=min(CANDIDATES,key=lambda name:validation[str(h)][name]['mae'])
            training_coverage[str(h)]=train_cov
        artifact={'version':ef.VERSION,'run_id':run_id,'created_at':now(),'protocol_sha256':protocol['sha256'],
                  'dataset_sha256':protocol['dataset_sha256'],'source_sha256':ef.source_hashes(),
                  'feature_names':ef.feature_names(),'selected_models':chosen,'models':models,'validation':validation,
                  'note':'Models and validation selection frozen before any test scoring; numeric JSON, no executable deserialization.'}
        artifact['sha256']=ef.digest(artifact);write_new(ef.DATA_DIR/'forecast-models.json',artifact)
        test={};paired={};partitions={}
        for h in ef.HORIZONS:
            samples,coverage=examples(rows,'test',h)
            test[str(h)],predictions=score_models(models[str(h)],samples,coverage)
            selected=chosen[str(h)]; actual=np.array([r['actual'] for r in samples]); err=np.abs(np.array(predictions[selected])-actual)
            paired[str(h)]={}
            for base in CANDIDATES:
                baseerr=np.abs(np.array(predictions[base])-actual);difference=baseerr-err
                paired[str(h)][base]={'selected':selected,'same_targets':len(samples),'selected_wins':int(sum(difference>1e-9)),
                    'ties':int(sum(np.abs(difference)<=1e-9)),'selected_losses':int(sum(difference< -1e-9)),
                    'mae_reduction_percent':float(100*(np.mean(baseerr)-np.mean(err))/np.mean(baseerr)) if np.mean(baseerr)>0 else None}
            # Calendar-month reporting exposes time-local shifts; it does not choose the deployed model.
            month={}; possible_month={}
            for index in range(ef.SPLITS['test'][0], ef.SPLITS['test'][1]-h):
                label=rows[index]['date'][:7]; possible_month[label]=possible_month.get(label,0)+1; month.setdefault(label,[])
            for i,sample in enumerate(samples):month[rows[sample['index']]['date'][:7]].append(i)
            partitions[str(h)]={m:{name:metrics([samples[i]['actual'] for i in ids],[predictions[name][i] for i in ids],
                                     {'possible':possible_month[m],'scored':len(ids),'coverage_fraction':len(ids)/possible_month[m]}) for name in CANDIDATES} for m,ids in month.items()}
        checked(path)
        result={'version':ef.VERSION,'run_id':run_id,'completed_at':now(),'scope':ef.SCOPE,'units':'source units',
                'dataset':'ETTh1','protocol_sha256':protocol['sha256'],'model_sha256':artifact['sha256'],
                'source_sha256':ef.source_hashes(),'provenance':protocol['provenance'],
                'row_count':len(rows),'split_rows_half_open':ef.SPLITS,'horizons_hours':ef.HORIZONS,
                'supported_demo_origin':{'min':11520,'max':14393,'default':11520},
                'date_ranges':{k:{'first_origin':rows[a]['date'],'last_target':rows[b-1]['date']} for k,(a,b) in ef.SPLITS.items()},
                'selected_models':chosen,'training_coverage':training_coverage,'validation':validation,'test':test,
                'paired_test_comparisons':paired,'test_month_subgroups':partitions,
                'limitations':['One externally supplied public transformer series; no independent physical commissioning.',
                    'Temperature and load physical units are not specified in the upstream README.',
                    'Regular hourly historical observations; no demonstrated missing-sensor robustness beyond withholding.',
                    'Overlapping targets and repeated origins are dependent; no significance or field uncertainty claim.',
                    'No fault labels, failure probability, RUL, current/voltage/ambient inference, or causal maintenance claim.',
                    'Test results are retained for all frozen candidates, including losses. No post-test selection or tuning.']}
        result['sha256']=ef.digest(result);write_new(ef.REPORT_PATH,result)
        return {'run_id':run_id,'report':str(ef.REPORT_PATH),'report_sha256':result['sha256'],
                'selected_models':chosen,'test':test,'paired_test_comparisons':paired}
    except BaseException as exc:
        write_new(ef.ROOT/'reports'/'external-ett-failed.json',{**claim,'error_type':type(exc).__name__,'failed_at':now()})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('freeze','run'))
    args=parser.parse_args();result=freeze() if args.action=='freeze' else run()
    print(json.dumps(result,indent=2,allow_nan=False))
