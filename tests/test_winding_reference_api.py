"""Reviewed winding evidence is causal, optional and frozen with its case."""
from copy import deepcopy
import csv
import io
from test_submission import client, OP
from test_winding_adaptation import fixture_rows
from neuratwin import twin_challenge as challenge, twin_observer as observer, twin_core as core
from neuratwin import halo_store as store, twin_studies as studies, thermal_adaptation

BASE='/api/halo/twin/challenges'


def payload(key,reviewed=False,mode='oil_and_hotspot',rows=None):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(observer.FIELDS))
    writer.writeheader();writer.writerows(rows or fixture_rows())
    return {'request_id':key,'name':'Analytic winding-reference fixture','temperature_mode':mode,
            'csv_text':stream.getvalue(),'origin_index':80,'healthy_reference_reviewed':True,
            'winding_reference_reviewed':reviewed}


def imported(c,data):
    response=c.post(BASE+'/import',headers=OP,json=data)
    assert response.status_code==200,response.text
    return response.json()


def test_reported_hotspot_fit_needs_separate_review_and_does_not_rewrite_old_case(client):
    unreviewed=imported(client,payload('unreviewed-winding'))
    stored=store.get('twin_challenge',unreviewed['id'])
    assert not unreviewed['qualification']['winding_fit_used']
    assert stored['settings']['rated_winding_rise_c']==core.Settings().rated_winding_rise_c
    reviewed=imported(client,payload('reviewed-winding',True))
    assert reviewed['qualification']['winding_fit_used']
    fit=reviewed['qualification']['winding_reference']
    reviewed_settings=store.get('twin_challenge',reviewed['id'])['settings']
    assert reviewed_settings['rated_winding_rise_c']==core.Settings().rated_winding_rise_c
    assert reviewed_settings['winding_forecast_reference']==fit
    assert fit['fit_end_s']==69*60 and fit['training_end_s']==48*60
    assert fit['validation_samples']==21 and fit['reviewed_healthy']
    assert client.get(BASE+'/'+unreviewed['id']).json()['qualification']==unreviewed['qualification']
    assert store.get('twin_challenge',unreviewed['id'])==stored
    assert client.post(BASE+'/import',headers=OP,json=payload('unreviewed-winding',True)).status_code==409


def test_oil_only_ignores_reported_hotspot_and_never_calls_winding_fit(client,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('oil-only must not fit winding')
    monkeypatch.setattr(thermal_adaptation,'fit_winding',forbidden)
    value=imported(client,payload('oil-only-winding',True,'oil_only'))
    assert not value['qualification']['winding_fit_used']
    assert value['qualification']['winding_reference']['holds']==['oil_only_has_no_reported_hotspot_reference']
    assert all(row['hotspot_c'] is None for row in value['observations'])


def test_fit_is_frozen_from_prefix_and_assessment_binds_adapter_source(client):
    rows=fixture_rows();original=imported(client,payload('prefix-original',True,rows=rows))
    for row in rows[70:]:row.update(hotspot_c=row['hotspot_c']+40,load_percent=140)
    changed=imported(client,payload('prefix-future-changed',True,rows=rows))
    assert original['qualification']['winding_reference']==changed['qualification']['winding_reference']
    result=client.post(BASE+'/'+original['id']+'/assess',headers=OP)
    assert result.status_code==200,result.text
    assessment=result.json()['assessment']
    assert 'thermal_adaptation.py' in assessment['model_source_sha256']
    assert assessment['settings_sha256']==studies.digest(store.get('twin_challenge',original['id'])['settings'])
    assert client.post(BASE+'/'+original['id']+'/assess',headers=OP).json()['assessment']==assessment
    assert store.records('command')==[]


def test_legacy_request_id_does_not_refit_or_rewrite_settings(client,monkeypatch):
    request=payload('legacy-winding-case')
    value=imported(client,request);record=store.get('twin_challenge',value['id'])
    record.pop('winding_fit')
    record['request_digest']=studies.digest(challenge.Import(**request).model_dump(mode='json',exclude={'winding_reference_reviewed'}))
    store.put('twin_challenge',value['id'],record);frozen=deepcopy(record)
    def forbidden(*args,**kwargs):raise AssertionError('legacy retry must not refit')
    monkeypatch.setattr(challenge,'winding_reference',forbidden)
    again=imported(client,request)
    assert again['qualification']['winding_reference']['holds']==['legacy_case_not_refitted']
    assert store.get('twin_challenge',value['id'])==frozen


def test_synthetic_create_uses_phase_aware_oil_adapter_and_frozen_prefix(client,monkeypatch):
    rows=fixture_rows(count=181)
    for row in rows:row.update(phase_current_a=10,phase_current_b=20,phase_current_c=30)
    monkeypatch.setattr(challenge,'generate',lambda *args,**kwargs:(rows,[],{}))
    received=[]
    def oil_fit(data):
        received.extend(data)
        return {'identified':False,'beats_persistence':False}
    monkeypatch.setattr(challenge.thermal_reference,'fit',oil_fit)
    response=client.post(BASE,headers=OP,json={'request_id':'synthetic-phase-adapter','temperature_mode':'oil_only'})
    assert response.status_code==200,response.text
    assert received==observer.reference_rows(rows[:70]) and received[-1]['load_percent']!=rows[69]['load_percent']
    assert not response.json()['qualification']['winding_fit_used']
