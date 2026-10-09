"""Evaluation status checks raw scoring rows and the one-run claim as well as JSON."""
import json
from pathlib import Path
from shutil import copyfile

from neuratwin import twin_study_api


def test_modified_score_rows_or_claim_withhold_artifact_integrity(tmp_path,monkeypatch):
    original=Path(twin_study_api.__file__).resolve().parents[1]
    reports=tmp_path/'reports';reports.mkdir()
    name='pipeline-v5-fresh-protocol'
    run=reports/(name+'-run');run.mkdir()
    for relative in ('submission-benchmark.json',name+'.json',name+'-claim.json',
                     name+'-run/benchmark.json',name+'-run/manifest.json',
                     name+'-run/forecasts.csv',name+'-run/decisions.csv'):
        copyfile(original/'reports'/relative,reports/relative)
    monkeypatch.setattr(twin_study_api,'__file__',str(tmp_path/'neuratwin'/'twin_study_api.py'))
    assert twin_study_api.validation()['fresh_evaluation']['artifact_integrity']
    scores=run/'forecasts.csv';old=scores.read_bytes();scores.write_bytes(old+b'\n')
    assert not twin_study_api.validation()['fresh_evaluation']['artifact_integrity']
    scores.write_bytes(old)
    claim=reports/(name+'-claim.json');data=json.loads(claim.read_text(encoding='utf-8'));data['run_id']='different-run'
    claim.write_text(json.dumps(data),encoding='utf-8')
    assert not twin_study_api.validation()['fresh_evaluation']['artifact_integrity']
