"""Descriptive paired synthetic evaluation statistics, not field confidence bounds."""
from collections import Counter
import math
import statistics

COMPARATORS = ('full_pipeline', 'without_cusum', 'threshold_only')
HORIZONS = (5, 15, 30)


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0, 'mean': None, 'median': None, 'p95': None, 'min': None, 'max': None}
    return {'count': len(values), 'mean': statistics.mean(values), 'median': statistics.median(values),
            'p95': values[min(len(values)-1, int(.95*len(values)))], 'min': values[0], 'max': values[-1]}


def forecast_summary(subset):
    """Keep unavailable targets in coverage, and compare baselines on paired rows."""
    result = []
    for horizon in HORIZONS:
        rows = [r for r in subset if r['horizon_min'] == horizon]
        valid = [r for r in rows if r['available']]
        errors = [r['model_error_c'] for r in valid]
        error_distribution = distribution(errors)
        signed = [r['signed_error_c'] for r in valid if r.get('signed_error_c') is not None]
        paired = [r['persistence_error_c']-r['model_error_c'] for r in valid]
        result.append({
            'horizon_min': horizon, 'scored': len(valid), 'possible': len(rows),
            'coverage_fraction': len(valid)/len(rows) if rows else None,
            'model_mae_c': error_distribution['mean'],
            'persistence_mae_c': statistics.mean(r['persistence_error_c'] for r in valid) if valid else None,
            'true_temperature_mae_c': statistics.mean(r['true_temperature_error_c'] for r in valid) if valid else None,
            'withheld_reasons': dict(Counter(r['reason_code'] for r in rows if not r['available'])),
            'p95_error_c': error_distribution['p95'], 'error_distribution_c': error_distribution,
            'rmse_c': math.sqrt(statistics.mean(e*e for e in errors)) if errors else None,
            'underprediction_c': distribution([max(0., -e) for e in signed]),
            'signed_error_c': distribution(signed),
            'paired_absolute_error_improvement_c': distribution(paired),
            'paired_model_wins': sum(d > 1e-9 for d in paired),
            'paired_ties': sum(abs(d) <= 1e-9 for d in paired),
            'paired_model_losses': sum(d < -1e-9 for d in paired),
            'scoring_note': 'Signed error is prediction minus observation; negative is underprediction. '
                            'Missing targets are not imputed. Errors and baseline comparison use the same scored rows. '
                            'P95 uses sorted[min(n-1, floor(.95*n))], retaining the historical report definition.',
        })
    return result


def alarm_burden(cases):
    """Rates use labelled inactive case-time, not independent assets or field hours."""
    result = {}
    for method in COMPARATORS:
        rows = [c['comparators'][method] for c in cases]
        normal = sum(r['normal_minutes'] for r in rows)
        minutes = sum(r['false_alarm_minutes'] for r in rows)
        episodes = sum(r['false_alarm_episodes'] for r in rows)
        durations = [d for r in rows for d in r.get('false_alarm_episode_durations_min', [])]
        result[method] = {
            'cases': len(cases), 'cases_with_false_alarm': sum(r['false_alarm_episodes'] > 0 for r in rows),
            'inactive_case_minutes': normal, 'false_alarm_minutes': minutes, 'false_alarm_episodes': episodes,
            'false_alarm_time_fraction': minutes/normal if normal else None,
            'false_alarm_episodes_per_100_inactive_case_hours': episodes*6000/normal if normal else None,
            'episode_duration_min': distribution(durations),
            'false_warning_kind_minutes': dict(sum((Counter(r.get('false_warning_kind_minutes', {})) for r in rows), Counter())),
            'note': 'One-minute synthetic observations. Inactive minutes include healthy controls and pre-onset '
                    'periods. Simultaneous warning kinds can overlap; rates are not a field false-alarm forecast.',
        }
    return result


def paired_lead_times(cases, baseline='threshold_only'):
    """Retain missed warnings; lead comparisons only pair known warning times."""
    critical = [c for c in cases if c['critical_min'] is not None]
    pairs = []; missing = Counter(); recall = Counter()
    for case in critical:
        full, other = (case['comparators'][name] for name in ('full_pipeline', baseline))
        a, b = full['first_any_warning_min'], other['first_any_warning_min']
        full_early = a is not None and a < case['critical_min']
        baseline_early = b is not None and b < case['critical_min']
        recall['both_warn_before_critical' if full_early and baseline_early else
               'full_only_before_critical' if full_early else
               'baseline_only_before_critical' if baseline_early else 'neither_before_critical'] += 1
        if a is None or b is None:
            missing['both_missing' if a is None and b is None else 'full_missing' if a is None else 'baseline_missing'] += 1
            continue
        pairs.append({'scenario': case['scenario'], 'family': case['family'], 'seed': case['seed'],
                      'critical_min': case['critical_min'], 'full_first_warning_min': a,
                      'baseline_first_warning_min': b, 'additional_lead_min': b-a,
                      'full_first_warning_kinds': full['first_warning_kinds'],
                      'baseline_first_warning_kinds': other['first_warning_kinds']})
    differences = [p['additional_lead_min'] for p in pairs]
    earlier = [p for p in pairs if p['additional_lead_min'] > 0]
    return {'baseline': baseline, 'all_cases': len(cases), 'critical_cases': len(critical),
            'paired_warning_times': len(pairs),
            'full_earlier': sum(x > 0 for x in differences), 'same_time': sum(x == 0 for x in differences),
            'full_later': sum(x < 0 for x in differences),
            'missing_warning_times': {k: missing[k] for k in ('full_missing', 'baseline_missing', 'both_missing')},
            'early_warning_recall_pairs': {k: recall[k] for k in ('both_warn_before_critical', 'full_only_before_critical', 'baseline_only_before_critical', 'neither_before_critical')},
            'additional_lead_min': distribution(differences),
            'earlier_subgroup_additional_lead_min': distribution(p['additional_lead_min'] for p in earlier),
            'earlier_subgroup_first_warning_kinds': dict(Counter(k for p in earlier for k in p['full_first_warning_kinds'])),
            'pairs': pairs,
            'note': 'Difference = baseline first warning minus full-pipeline first warning, among cases with a true '
                    'synthetic critical crossing and both warning timestamps. Positive means full pipeline warned '
                    'earlier. Missing timestamps remain explicit, not zero. First-warning categories can overlap. '
                    'An earlier discrepancy warning is not necessarily a forecast-derived benefit.',
            }


def paired_subgroups(cases):
    return {baseline: {
        'overall': paired_lead_times(cases, baseline),
        'by_family': {family: paired_lead_times([c for c in cases if c['family'] == family], baseline)
                      for family in sorted({c['family'] for c in cases})},
        'by_scenario': {scenario: paired_lead_times([c for c in cases if c['scenario'] == scenario], baseline)
                        for scenario in sorted({c['scenario'] for c in cases})},
    } for baseline in ('threshold_only', 'without_cusum')}
