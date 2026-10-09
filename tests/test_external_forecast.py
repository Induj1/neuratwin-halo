"""Forecast causality, partition purging, numeric artifacts and evidence bindings."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import math
import numpy as np
import pytest
from neuratwin import external_forecast as ef
from scripts import evaluate_external_forecast as evaluation


def rows(count=560):
    start=datetime(2020,1,1)
    return [{'date':(start+timedelta(hours=i)).isoformat(), 'OT':30+math.sin(i/8)+i*.002,
             **{key:10+j+math.cos(i/11) for j,key in enumerate(ef.CHANNELS[1:])}} for i in range(count)]


def test_causal_features_ignore_all_future_rows():
    data=rows();original=ef.feature_vector(data[:201]);changed=deepcopy(data)
    for row in changed[201:]:
        for key in ef.CHANNELS:row[key]=1e9
    assert ef.feature_vector(changed[:201])==original
    assert len(original)==len(ef.feature_names())==len(set(ef.feature_names()))


@pytest.mark.parametrize('failure',['short','gap','duplicate','missing','nan','boolean'])
def test_missing_or_invalid_acquisition_withholds(failure):
    data=rows(169)
    if failure=='short':data=data[1:]
    elif failure=='gap':data[80]['date']=(datetime.fromisoformat(data[80]['date'])+timedelta(minutes=1)).isoformat()
    elif failure=='duplicate':data[80]['date']=data[79]['date']
    elif failure=='missing':data[80]['HUFL']=None
    elif failure=='nan':data[80]['OT']=float('nan')
    else:data[80]['OT']=True
    with pytest.raises(ValueError):ef.feature_vector(data)


def test_target_boundary_purged_and_previous_history_permitted(monkeypatch):
    monkeypatch.setattr(ef,'SPLITS',{'train':(0,300),'validation':(300,420),'test':(420,540)})
    train,tc=evaluation.examples(rows(),'train',6);val,vc=evaluation.examples(rows(),'validation',6)
    assert train[0]['index']==168 and train[-1]['index']==293
    assert max(r['index']+6 for r in train)==299
    assert val[0]['index']==300 and val[-1]['index']==413
    assert tc['possible']==294 and tc['scored']==126 and tc['unavailable']['initial_lookback']==168
    assert vc['scored']==114 and vc['boundary_purged_origins']==6
    # Future target is used only in the label; feature at origin stays causal.
    data=rows();data[306]['OT']+=900
    modified,_=evaluation.examples(data,'validation',6)
    assert modified[0]['features']==val[0]['features'] and modified[0]['actual']!=val[0]['actual']


def test_numeric_ridge_and_tree_inference_and_cycles():
    ridge={'kind':'ridge_delta','coefficients':[2.],'mean':[1.],'scale':[2.],'intercept':3.}
    assert ef.predict_numeric(ridge,[5.],10.,8.)==17.
    tree={'kind':'hist_gradient_boosting_delta','baseline':1.,'trees':[[
        {'leaf':False,'feature':0,'threshold':2.,'left':1,'right':2},
        {'leaf':True,'value':3.},{'leaf':True,'value':-3.}]]}
    assert ef.predict_numeric(tree,[2.],10.,0.)==14.
    assert ef.predict_numeric(tree,[2.01],10.,0.)==8.
    tree['trees'][0][0]['left']=0
    with pytest.raises(ValueError,match='Cyclic'):ef.predict_numeric(tree,[1.],10.,0.)
    with pytest.raises(ValueError):ef.predict_numeric({'kind':'python'},[],0.,0.)


def test_exported_fitted_estimators_match_numeric_json(monkeypatch):
    data=rows(360)
    monkeypatch.setattr(ef,'SPLITS',{'train':(0,320),'validation':(320,340),'test':(340,360)})
    samples,_=evaluation.examples(data,'train',1)
    # fit_models itself verifies every training prediction against sklearn.
    models=evaluation.fit_models(samples)
    restored=json.loads(json.dumps(models,allow_nan=False))
    assert set(restored)==set(evaluation.CANDIDATES)
    for sample in samples[-4:]:
        for name in models:
            assert ef.predict_numeric(restored[name],sample['features'],sample['current'],sample['seasonal'])==ef.predict_numeric(models[name],sample['features'],sample['current'],sample['seasonal'])


def test_baselines_and_horizon_are_explicit():
    data=rows(200)
    artifact={'selected_models':{'1':'seasonal_24h','6':'persistence'},'sha256':'test',
              'models':{'1':{'seasonal_24h':{'kind':'seasonal_24h'}},'6':{'persistence':{'kind':'persistence'}}}}
    assert ef.predict_prefix(data,1,artifact)['predicted_oil']==data[-24]['OT']
    assert ef.predict_prefix(data,6,artifact)['predicted_oil']==data[-1]['OT']
    with pytest.raises(ValueError):ef.predict_prefix(data,24,artifact)


def test_metrics_keep_common_coverage_and_underprediction_tails():
    result=evaluation.metrics([10,20,30],[8,24,25],{'possible':4,'scored':3,'coverage_fraction':.75})
    assert result['mae']==pytest.approx(11/3)
    assert result['rmse']==pytest.approx(math.sqrt(15))
    assert result['max_underprediction']==5 and result['coverage_fraction']==.75


def test_protocol_freeze_binding_and_exclusive_creation(tmp_path,monkeypatch):
    directory=tmp_path/'ett';directory.mkdir()
    content=b'date,OT\n';(directory/'ETTh1.csv').write_bytes(content)
    (directory/'provenance.json').write_text(json.dumps({'files':{'ETTh1.csv':{'sha256':hashlib.sha256(content).hexdigest()}}}))
    monkeypatch.setattr(ef,'DATA_DIR',directory);monkeypatch.setattr(ef,'source_hashes',lambda:{'module':'abc'})
    path=tmp_path/'protocol.json';p=evaluation.freeze(path)
    assert evaluation.checked(path)['sha256']==p['sha256']
    with pytest.raises(FileExistsError):evaluation.freeze(path)
    monkeypatch.setattr(ef,'source_hashes',lambda:{'module':'changed'})
    with pytest.raises(ValueError,match='sources changed'):evaluation.checked(path)


def test_model_hash_rejects_mutation_without_deserialization(tmp_path,monkeypatch):
    monkeypatch.setattr(ef,'DATA_DIR',tmp_path);monkeypatch.setattr(ef,'source_hashes',lambda:{'module':'abc'})
    model={'version':ef.VERSION,'source_sha256':{'module':'abc'},'feature_names':ef.feature_names(),'selected_models':{},'models':{}}
    model['sha256']=ef.digest(model);path=tmp_path/'forecast-models.json';path.write_text(json.dumps(model))
    assert ef.load_models()['sha256']==model['sha256']
    model['selected_models']={'1':'arbitrary'};path.write_text(json.dumps(model))
    with pytest.raises(ValueError,match='digest mismatch'):ef.load_models()


def test_demo_rejects_non_test_origin_before_reading_artifacts():
    for value in (11519,14394,True,'11520'):
        with pytest.raises(ValueError):ef.demo(value)


@pytest.mark.parametrize('mutate',[None,'ETTh1.csv','LICENSE.txt','protocol','claim','report','model'])
def test_public_status_checks_entire_evidence_chain(tmp_path,monkeypatch,mutate):
    data=tmp_path/'data';reports=tmp_path/'reports';data.mkdir();reports.mkdir()
    monkeypatch.setattr(ef,'ROOT',tmp_path);monkeypatch.setattr(ef,'DATA_DIR',data)
    monkeypatch.setattr(ef,'REPORT_PATH',reports/'external-ett-report.json')
    monkeypatch.setattr(ef,'source_hashes',lambda:{'module':'abc'})
    provenance={'files':{}}
    for name in ('ETTh1.csv','LICENSE.txt','UPSTREAM_README.md'):
        content=name.encode();(data/name).write_bytes(content)
        provenance['files'][name]={'sha256':hashlib.sha256(content).hexdigest()}
    dataset_hash=provenance['files']['ETTh1.csv']['sha256']
    protocol={'source_sha256':ef.source_hashes(),'provenance':provenance,'dataset_sha256':dataset_hash}
    protocol['sha256']=ef.digest(protocol)
    model={'version':ef.VERSION,'feature_names':ef.feature_names(),'source_sha256':ef.source_hashes(),
           'protocol_sha256':protocol['sha256'],'run_id':'run1','dataset_sha256':dataset_hash}
    model['sha256']=ef.digest(model)
    report={'model_sha256':model['sha256'],'source_sha256':ef.source_hashes(),'protocol_sha256':protocol['sha256'],
            'run_id':'run1','provenance':provenance}
    report['sha256']=ef.digest(report)
    claim={'run_id':'run1','protocol_sha256':protocol['sha256']}
    files={'protocol':reports/'external-ett-protocol.json','claim':reports/'external-ett-claim.json',
           'report':ef.REPORT_PATH,'model':data/'forecast-models.json'}
    for key,value in [('protocol',protocol),('claim',claim),('model',model),('report',report)]:
        files[key].write_text(json.dumps(value))
    if mutate in ('ETTh1.csv','LICENSE.txt'):(data/mutate).write_text('changed')
    elif mutate:
        obj=json.loads(files[mutate].read_text());obj['run_id']='different';files[mutate].write_text(json.dumps(obj))
    if mutate:
        with pytest.raises(ValueError):ef.public_status()
    else:assert ef.public_status()['integrity'] is True
