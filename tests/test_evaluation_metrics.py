"""Paired evidence metrics and one-run protocol guards; no full benchmark here."""
from copy import deepcopy
import json
import pytest
from scripts import evaluation_metrics as metrics, prospective_evaluation as prospective


def method(first=10, *, critical=30, kinds=None, false=0, normal=60):
    return {'first_any_warning_min': first, 'first_warning_kinds': kinds or ['observed_threshold'],
            'false_alarm_minutes': false, 'normal_minutes': normal,
            'false_alarm_episodes': int(false > 0), 'false_alarm_episode_durations_min': [false] if false else [],
            'false_warning_kind_minutes': {'model_disagreement': false} if false else {}}


def case(full=10, baseline=20, *, critical=30, seed=1, scenario='cooling', family='nonlinear'):
    return {'critical_min': critical, 'seed': seed, 'scenario': scenario, 'family': family,
            'comparators': {'full_pipeline': method(full, kinds=['model_disagreement']),
                            'threshold_only': method(baseline), 'without_cusum': method(baseline)}}


def test_paired_lead_times_include_missing_warnings_in_explicit_denominators():
    rows = [case(), case(20, 20, seed=2), case(25, 20, seed=3), case(None, 20, seed=4),
            case(20, None, seed=5), case(None, None, seed=6), case(10, 20, critical=None, seed=7)]
    result = metrics.paired_lead_times(rows)
    assert result['all_cases'] == 7 and result['critical_cases'] == 6
    assert result['paired_warning_times'] == 3
    assert (result['full_earlier'], result['same_time'], result['full_later']) == (1, 1, 1)
    assert result['additional_lead_min']['median'] == 0
    assert result['missing_warning_times'] == {'full_missing': 1, 'baseline_missing': 1, 'both_missing': 1}
    assert result['earlier_subgroup_first_warning_kinds'] == {'model_disagreement': 1}
    assert result['early_warning_recall_pairs'] == {
        'both_warn_before_critical': 3, 'full_only_before_critical': 1,
        'baseline_only_before_critical': 1, 'neither_before_critical': 1}


def test_warning_at_or_after_critical_is_not_early_but_pair_is_retained():
    result = metrics.paired_lead_times([case(30, 31)])
    assert result['full_earlier'] == 1
    assert result['early_warning_recall_pairs']['neither_before_critical'] == 1
    assert result['critical_cases'] == 1


def test_subgroups_do_not_generalize_one_family_benefit_to_all_cases():
    result = metrics.paired_subgroups([case(), case(20, 20, seed=2, family='radiator_lag')])['threshold_only']
    assert result['overall']['full_earlier'] == 1
    assert result['by_family']['nonlinear']['additional_lead_min']['median'] == 10
    assert result['by_family']['radiator_lag']['additional_lead_min']['median'] == 0
    assert result['by_scenario']['cooling']['critical_cases'] == 2


def test_alarm_burden_uses_inactive_case_hours_and_exposes_episodes_and_durations():
    c = case(); c['comparators']['full_pipeline'] = method(false=10, normal=120)
    result = metrics.alarm_burden([c])['full_pipeline']
    assert result['false_alarm_episodes_per_100_inactive_case_hours'] == 50
    assert result['false_alarm_time_fraction'] == 10/120
    assert result['episode_duration_min']['max'] == 10
    assert result['cases_with_false_alarm'] == 1
    assert metrics.alarm_burden([])['full_pipeline']['false_alarm_time_fraction'] is None


def score(error, baseline, *, available=True, signed=None):
    return {'horizon_min': 5, 'available': available, 'model_error_c': error,
            'persistence_error_c': baseline, 'true_temperature_error_c': error,
            'signed_error_c': signed, 'reason_code': '' if available else 'thermal_deviation'}


def test_forecast_coverage_and_optimistic_error_tails_keep_missing_targets():
    result = metrics.forecast_summary([score(1, 2, signed=-1), score(5, 3, signed=5),
                                       score(2, 2, signed=-2), score(None, None, available=False)])[0]
    assert result['scored'] == 3 and result['possible'] == 4 and result['coverage_fraction'] == .75
    assert result['withheld_reasons'] == {'thermal_deviation': 1}
    assert result['underprediction_c']['max'] == 2
    assert result['p95_error_c'] == 5 and result['error_distribution_c']['median'] == 2
    assert (result['paired_model_wins'], result['paired_ties'], result['paired_model_losses']) == (1, 1, 1)
    assert result['persistence_mae_c'] == 7/3


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    hashes = {'test-source.py': 'a'*64}
    monkeypatch.setattr(prospective.benchmark, 'source_hashes', lambda: deepcopy(hashes))
    monkeypatch.setattr(prospective, 'choose_seeds', lambda excluded, count: [10_123_456, 10_123_457][:count])
    reports = tmp_path/'reports'; reports.mkdir()
    (reports/'known.json').write_text(json.dumps({'seeds': [9999], 'cases': [{'seed': 8888}]}))
    path = tmp_path/'evaluation'/'protocol.json'
    protocol = prospective.freeze(path, count=2, reports=reports)
    return path, protocol, hashes


def test_protocol_freezes_before_generation_and_cannot_overwrite(frozen):
    path, protocol, _ = frozen
    assert prospective.checked_protocol(path) == protocol
    assert protocol['method']['horizons_min'] == [5, 15, 30]
    assert protocol['known_seed_count_at_freeze'] >= 62
    assert 'Not externally supplied' in protocol['scope']
    with pytest.raises(FileExistsError): prospective.freeze(path)
    assert not path.with_name('protocol-claim.json').exists()


def test_source_change_blocks_run_before_consuming_protocol(frozen):
    path, _, hashes = frozen; hashes['test-source.py'] = 'b'*64
    with pytest.raises(ValueError, match='source changed'): prospective.run(path)
    assert not path.with_name('protocol-claim.json').exists()


def test_protocol_tampering_is_rejected(frozen):
    path, protocol, _ = frozen
    protocol['seeds'][0] += 1; path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match='digest'): prospective.run(path)


def test_single_run_report_and_raw_files_bind_to_protocol(frozen, monkeypatch):
    path, protocol, hashes = frozen; called = []
    def evaluate(split, *, seeds, protocol_binding):
        called.append((split, seeds, protocol_binding))
        return {'source_sha256': deepcopy(hashes), 'protocol_binding': protocol_binding}, [{'error': 10.0}], [{'warning': 'model_disagreement'}]
    monkeypatch.setattr(prospective.benchmark, 'evaluate', evaluate)
    result = prospective.run(path)
    assert result['status'] == 'complete' and result['protocol_sha256'] == protocol['sha256']
    assert set(result['files']) == {'benchmark.json', 'forecasts.csv', 'decisions.csv'}
    assert called[0][0] == 'prospective_synthetic' and called[0][1] == protocol['seeds']
    binding = json.loads((path.parent/'protocol-run'/'benchmark.json').read_text())['protocol_binding']
    assert binding['sha256'] == protocol['sha256'] and binding['run_id'] == result['run_id']
    with pytest.raises(FileExistsError): prospective.run(path)
    assert len(called) == 1


def test_failure_remains_visible_and_does_not_enable_a_retry(frozen, monkeypatch):
    path, _, _ = frozen
    def fail(*args, **kwargs): raise RuntimeError('Synthetic forced failure')
    monkeypatch.setattr(prospective.benchmark, 'evaluate', fail)
    with pytest.raises(RuntimeError): prospective.run(path)
    failed = json.loads((path.parent/'protocol-run'/'failed.json').read_text())
    assert failed['status'] == 'failed_or_interrupted' and failed['error_type'] == 'RuntimeError'
    with pytest.raises(FileExistsError): prospective.run(path)
