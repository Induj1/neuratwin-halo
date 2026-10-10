"""Evaluate the deployed observation/forecast pipeline and executed interventions."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collections import Counter
from copy import deepcopy
import csv
import hashlib
import json
import statistics
import argparse
from neuratwin import twin_core as core,twin_studies as studies,twin_observer as observer,thermal_reference,thermal_adaptation
from neuratwin.validation_plant import generate,SCENARIOS,MIXED,FAMILIES
from scripts.evaluation_metrics import forecast_summary, alarm_burden, paired_subgroups

DEVELOPMENT_SEEDS=range(3101,3113)
EVALUATION_SEEDS=range(91001,91025)
EXPECTED={'overload':'overload','cooling':'thermal_deviation','sensor_bias':'channel_disagreement','dropout':'missing_data','voltage':'voltage_deviation'}
COMPARATORS=('full_pipeline','without_cusum','threshold_only')
SOURCE_FILES=('neuratwin/twin_core.py','neuratwin/twin_studies.py','neuratwin/twin_observer.py',
              'neuratwin/electrical_model.py',
              'neuratwin/thermal_reference.py','neuratwin/thermal_adaptation.py','neuratwin/validation_plant.py','scripts/benchmark_pipeline.py',
              'scripts/evaluation_metrics.py','scripts/prospective_evaluation.py')


def source_hashes():
    root=Path(__file__).resolve().parents[1]
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def warning_kinds(result):
    """An actionable warning is distinct from completing the expected signal set."""
    kinds=[];signals=set(result.get('hypotheses',[]))
    if result.get('observed_alerts'):kinds.append('observed_threshold')
    if signals & {'missing_data','outside_model_domain','invalid_timebase','missing_phase_data','unsupported_phase_model'}:
        kinds.append('acquisition_or_domain_hold')
    if signals & {'thermal_deviation','channel_disagreement'}:kinds.append('model_disagreement')
    if result.get('available') and result.get('minutes_to_critical') is not None:kinds.append('conditional_limit_forecast')
    return kinds


def comparison_case(trace,event,critical,expected):
    """No threshold crossing is relabelled as a cooling/sensor root-cause diagnosis."""
    complete=[x['minute'] for x in trace if x['active'] and expected and all(s in x['signals'] for s in expected)]
    warned=[x for x in trace if x['active'] and x['warnings']]
    false=[x['minute'] for x in trace if not x['active'] and x['warnings']]
    first=min(complete) if complete else None
    first_warning=warned[0]['minute'] if warned else None
    episode_lengths=[]
    for i,minute in enumerate(false):
        if i==0 or minute>false[i-1]+1:episode_lengths.append(1)
        else:episode_lengths[-1]+=1
    return {'expected_signal_set_complete':bool(complete),'first_complete_min':first,
        'completion_delay_min':first-event if first is not None else None,
        'complete_before_critical':critical is not None and first is not None and first<critical,
        'any_warning':bool(warned),'first_any_warning_min':first_warning,
        'first_warning_delay_min':first_warning-event if first_warning is not None else None,
        'first_warning_kinds':warned[0]['warnings'] if warned else [],
        'any_warning_before_critical':critical is not None and first_warning is not None and first_warning<critical,
        'warning_lead_to_critical_min':critical-first_warning if critical is not None and first_warning is not None else None,
        'false_alarm_minutes':len(false),'normal_minutes':sum(not x['active'] for x in trace),
        'false_alarm_episodes':len(episode_lengths),
        'false_alarm_episode_durations_min':episode_lengths,
        'false_warning_kind_minutes':dict(Counter(k for x in trace if not x['active'] for k in x['warnings']))}


def comparison_summary(cases):
    result={}
    for name in COMPARATORS:
        rows=[c['comparators'][name] for c in cases]
        delays=[r['completion_delay_min'] for r in rows if r['completion_delay_min'] is not None]
        warning_delays=[r['first_warning_delay_min'] for r in rows if r['first_warning_delay_min'] is not None]
        result[name]={'expected_signal_set_complete':sum(r['expected_signal_set_complete'] for r in rows),
            'total':len(rows),'median_completion_delay_min':statistics.median(delays) if delays else None,
            'complete_before_critical':sum(r['complete_before_critical'] for r in rows),
            'critical_events':sum(c['critical_min'] is not None for c in cases),
            'events_with_any_warning':sum(r['any_warning'] for r in rows),
            'median_first_warning_delay_min':statistics.median(warning_delays) if warning_delays else None,
            'any_warning_before_critical':sum(r['any_warning_before_critical'] for r in rows),
            'false_alarm_minutes':sum(r['false_alarm_minutes'] for r in rows),
            'normal_minutes':sum(r['normal_minutes'] for r in rows),
            'false_alarm_episodes':sum(r['false_alarm_episodes'] for r in rows)}
    return result


def evaluate(split='evaluation', *, seeds=None, protocol_binding=None):
    initial_hashes=source_hashes()
    seeds=list(seeds if seeds is not None else DEVELOPMENT_SEEDS if split=='development' else EVALUATION_SEEDS)
    fresh=split=='prospective_synthetic'
    if fresh and not protocol_binding:raise ValueError('Fresh evaluation requires its frozen protocol binding.')
    cases=[];scores=[];decisions=[]
    for family,seed in ((family,seed) for family in FAMILIES for seed in seeds):
        for scenario in (*SCENARIOS,*MIXED):
            rows,truth,meta=generate(seed,scenario,family=family,variable_event=True);event=meta['event_min']
            fit=thermal_reference.fit(observer.reference_rows(rows[:70]));p=core.Settings().model_dump()
            fitted=fit['identified'] and fit['beats_persistence']
            if fitted:p.update(rated_oil_rise_c=fit['rated_oil_rise_c'],oil_tau_min=fit['oil_tau_min'])
            oil_settings=deepcopy(p)
            winding_fit=thermal_adaptation.fit_winding(observer.winding_reference_rows(rows[:70]),p,reviewed_healthy=True)
            p=thermal_adaptation.apply_winding(p,winding_fit)
            alarms=[];false=[];correct=[];old_correct=[];old_false=[];blocked=0;violations=0
            traces={name:[] for name in COMPARATORS}
            expected=[EXPECTED[x] for x in MIXED.get(scenario,(scenario,)) if x in EXPECTED]
            for minute in range(70,181):
                result=observer.assess(rows[:minute+1],p,30)
                old=observer.assess(rows[:minute+1],p,30,use_drift=False)
                threshold=observer.threshold_assess(rows[:minute+1],p)
                for name,assessment in (('full_pipeline',result),('without_cusum',old),('threshold_only',threshold)):
                    traces[name].append({'minute':minute,'active':truth[minute]['active'],
                        'signals':assessment['hypotheses'],'warnings':warning_kinds(assessment)})
                label=result['hypothesis'];alarm=label not in ('no_anomaly_established','insufficient_evidence')
                if alarm:alarms.append(minute)
                if alarm and not truth[minute]['active']:false.append(minute)
                signals=result['hypotheses'];old_signals=old['hypotheses']
                if truth[minute]['active'] and expected and all(x in signals for x in expected):correct.append(minute)
                if truth[minute]['active'] and expected and all(x in old_signals for x in expected):old_correct.append(minute)
                if old['hypothesis'] not in ('no_anomaly_established','insufficient_evidence') and not truth[minute]['active']:old_false.append(minute)
                if result['validity']['holds']:
                    blocked+=1;violations+=int(result['available'])
                decisions.append({'family':family,'seed':seed,'scenario':scenario,'minute':minute,'hypothesis':label,
                    'hypotheses':'|'.join(signals),'forecast_available':result['available'],'holds':'|'.join(result['validity']['holds']),
                    'observed_status':result['observed_status'],
                    'full_warning_kinds':'|'.join(traces['full_pipeline'][-1]['warnings']),
                    'without_cusum_hypotheses':'|'.join(old_signals),
                    'without_cusum_warning_kinds':'|'.join(traces['without_cusum'][-1]['warnings']),
                    'threshold_only_signals':'|'.join(threshold['hypotheses']),
                    'threshold_only_warning_kinds':'|'.join(traces['threshold_only'][-1]['warnings']),
                    'threshold_input_holds':'|'.join(threshold['validity']['holds'])})
                if minute in (75,90,105,120,135,150):
                    oil=observer.assess(rows[:minute+1],oil_settings,30,temperature_mode='oil_only')
                    for target,assessment,point_key in [('hotspot_c',result,'temperature_c'),('oil_c',oil,'oil_c')]:
                        for h in (5,15,30):
                            actual=rows[minute+h][target];initial=rows[minute][target]
                            available=assessment['available'] and actual is not None
                            partition=('healthy' if scenario=='healthy' else 'before_disturbance' if minute+h<event else 'crosses_disturbance' if minute<event else 'after_disturbance')
                            scores.append({'family':family,'seed':seed,'scenario':scenario,'origin_min':minute,'horizon_min':h,'target':target,
                                'partition':partition,'available':available,
                                'model_error_c':abs(actual-assessment['forecast']['points'][h][point_key]) if available else None,
                                'signed_error_c':assessment['forecast']['points'][h][point_key]-actual if available else None,
                                'actual_c':actual,'predicted_c':assessment['forecast']['points'][h][point_key] if available else None,
                                'persistence_error_c':abs(actual-initial) if available else None,
                                'true_temperature_error_c':abs(truth[minute+h][target]-assessment['forecast']['points'][h][point_key]) if available else None,
                                'reason_code':'' if available else assessment['hypothesis'] if not assessment['available'] else 'future_observation_missing',
                                'reason':'' if available else assessment.get('reason','Future observation unavailable')})
            episodes=sum(i==0 or x>false[i-1]+1 for i,x in enumerate(false))
            critical=next((i for i in range(event,181) if truth[i]['hotspot_c']>=125),None)
            comparisons={name:comparison_case(trace,event,critical,expected) for name,trace in traces.items()}
            first=min(correct) if correct else None
            cases.append({**meta,'fit_qualified':fitted,'winding_fit_qualified':winding_fit['qualified'],
                'winding_fit':winding_fit,'detected':bool(correct),'first_correct_min':first,
                'without_cusum_detected':bool(old_correct),'without_cusum_delay_min':min(old_correct)-event if old_correct else None,
                'without_cusum_false_alarm_episodes':sum(i==0 or x>old_false[i-1]+1 for i,x in enumerate(old_false)),
                'blocked_forecasts':blocked,'validity_violations':violations,
                'delay_min':first-event if first is not None else None,'false_alarm_minutes':len(false),'false_alarm_episodes':episodes,
                'critical_min':critical,'lead_to_critical_min':critical-first if critical is not None and first is not None else None,
                'comparators':comparisons})
    classes=[]
    for scenario in (*SCENARIOS,*MIXED):
        group=[c for c in cases if c['scenario']==scenario]
        classes.append({'scenario':scenario,'detected':sum(c['detected'] for c in group),'total':len(group),
            'without_cusum_detected':sum(c['without_cusum_detected'] for c in group),
            'median_delay_min':statistics.median(c['delay_min'] for c in group if c['detected']) if any(c['detected'] for c in group) else None,
            'without_cusum_false_alarm_episodes':sum(c['without_cusum_false_alarm_episodes'] for c in group),
            'false_alarm_minutes':sum(c['false_alarm_minutes'] for c in group),'false_alarm_episodes':sum(c['false_alarm_episodes'] for c in group),
            'critical_events':sum(c['critical_min'] is not None for c in group),
            'warned_before_critical':sum(c['lead_to_critical_min'] is not None and c['lead_to_critical_min']>0 for c in group),
            'comparators':comparison_summary(group),
            'forecasts':forecast_summary([r for r in scores if r['scenario']==scenario and r['target']=='hotspot_c'])})
    # Exercise the exact demand transition and physical-state simulator after planning.
    interventions=[]
    for load in (70,90,110,120):
        for cooling in ('normal','degraded','failed'):
            for additive in (False,True):
                s=core.create_state('benchmark-action');s['inputs'].update(load_percent=load,cooling=cooling,ambient_c=35);core.evaluate(s,0)
                if additive:core.inject(s,'overcurrent',1,20000)
                plan=studies.plan(s,60,0);rec=plan.get('recommendation')
                row={'load_percent':load,'cooling':cooling,'overcurrent':additive,'feasible':bool(rec)}
                if rec:
                    e=core.reduce_demand(s,rec['reduction_pct']);core.evaluate(s,0);s['running']=True;core.advance(s,900)
                    expected=rec['points'][15]['temperature_c']
                    row.update(reduction_pct=rec['reduction_pct'],load_error=abs(e['loading_percent']-rec['post_load_percent']),
                        temperature_error_c=abs(s['telemetry']['hotspot_temperature']-expected),breaker=s['breaker'],
                        passed=abs(e['loading_percent']-rec['post_load_percent'])<1e-8 and abs(s['telemetry']['hotspot_temperature']-expected)<1e-6 and s['breaker']=='CLOSED')
                interventions.append(row)
    hashes=source_hashes()
    if hashes!=initial_hashes:raise RuntimeError('Numerical source changed during evaluation; no benchmark may be published. Restart with settled source files.')
    role=('First and only claimed evaluation of previously unused internally generated synthetic seeds under a local frozen protocol. '
          'This is not externally supplied data, third-party preregistration, field evidence or a prospective physical experiment.' if fresh else
          'Development experiment.' if split=='development' else
          'Known fixed-corpus regression: these evaluation seeds were inspected during previous review, not fresh unseen evidence.')
    report={'version':observer.VERSION,'split':split,'evaluation_role':role,'protocol_binding':protocol_binding,
        'scope':f'Deployed observation assessment on {len(cases)} paired synthetic cases across two plant families, not independent field assets; executed-action checks are model-consistency tests.',
        'protocol':{'seeds':list(seeds),'training':'First 70 healthy rows; fit eligibility checked before use. Otherwise defaults remain labelled assumptions. CUSUM bias uses the first 60 assumed-healthy minutes; instrument noise uses the first 60 samples. Post-gap windows are never relabelled as healthy commissioning.',
            'targets':'Separate reported hot-spot and observed-oil targets. True synthetic target errors are also reported for scoring only; no hidden temperatures enter assessment.',
            'inputs':'Observed voltage, loading, oil, reported hot-spot and ambient only in this fixed corpus. Optional phase observations are covered by separate consistency regressions, not independent phase-plant accuracy claims. No scenario, cooling, fault label, future row or true plant parameter.',
            'limits':'Two synthetic plant families, overlapping origins and paired seeds; these are not independent field assets. Event onset varies from minute 90 to 115. Primary MAE retains every eligible window including future disturbances. Disjoint timing partitions expose that distinction. Cases withheld for model discrepancy remain in coverage denominators. Combined-case diagnostic completion requires all expected signals concurrently. '+role+' Threshold-only uses per-channel observed limits and the same acquisition/domain gates, without residuals, CUSUM or forecasts; without-CUSUM is a separate ablation retaining residuals. No field validation, calibrated confidence or failure probability.',
            'calibration_scope':'Each synthetic case supplies 70 assumed-healthy rows for bounded oil identification and separately qualified winding-reference identification from reported hot-spot minus oil. Chronological validation gates both fits. A qualified winding reference changes conditional projections only; residual, channel-disagreement and CUSUM screening retain their configured reference. Oil-only mode never fits or applies winding calibration. Otherwise illustrative defaults remain. The observer gets past observations, never hidden cooling/fault settings. Scenario interventions remain separate internal consistency evidence.',
            'method_reference':'https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm'},
        'comparison_contract':{
            'expected_signal_set':'Matches the predefined EXPECTED signals while the synthetic disturbance is active; threshold-only cannot diagnose cooling or sensor-bias causes from a temperature limit.',
            'any_warning':'Any valid observed threshold, acquisition/domain hold, model-disagreement signal, or qualified conditional limit forecast. Insufficient evidence alone is not counted as an alarm. Warning types are retained in the decision CSV.',
            'validity':'Both assessors use the same available-channel and time/domain gates. Valid breaches on other channels remain visible during missing-data holds. Threshold checks need no residual warm-up and do not inherit model-disagreement holds.',
            'false_alarm':'Any-warning false alarms are counted separately from historical diagnostic-only false alarms; labelled inactive synthetic minutes define the denominator.',
            'early_warning':'Only warnings after event onset and before the true synthetic critical crossing qualify. A warning is not proof of correct cause or a safe operating deadline.'},
        'comparators':comparison_summary(cases),
        'paired_lead_time':paired_subgroups(cases),
        'alarm_burden':alarm_burden(cases),
        'validity_violations':sum(c['validity_violations'] for c in cases),
        'forecasts':forecast_summary([r for r in scores if r['target']=='hotspot_c']),
        'oil_only_forecasts':forecast_summary([r for r in scores if r['target']=='oil_c']),
        'partitions':{target:{group:forecast_summary([r for r in scores if r['target']==target and r['partition']==group]) for group in ('healthy','before_disturbance','crosses_disturbance','after_disturbance')} for target in ('oil_c','hotspot_c')},
        'families':{family:forecast_summary([r for r in scores if r['target']=='hotspot_c' and r['family']==family]) for family in FAMILIES},
        'forecast_subgroups':{target:{'by_family':{family:forecast_summary([r for r in scores if r['target']==target and r['family']==family]) for family in FAMILIES},
                                     'by_scenario':{scenario:forecast_summary([r for r in scores if r['target']==target and r['scenario']==scenario]) for scenario in (*SCENARIOS,*MIXED)}} for target in ('oil_c','hotspot_c')},
        'classes':classes,'cases':cases,
        'interventions':interventions,'source_sha256':hashes}
    return report,scores,decisions


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=['development','evaluation'],default='evaluation');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];r,f,d=evaluate(args.split)
    prefix='pipeline-development' if args.split=='development' else 'pipeline'
    (root/f'reports/{prefix}-benchmark.json').write_text(json.dumps(r,indent=2,allow_nan=False),encoding='utf-8')
    for name,rows in [(prefix+'-forecasts.csv',f),(prefix+'-decisions.csv',d)]:
        with (root/'reports'/name).open('w',newline='',encoding='utf-8') as out:
            w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps({'forecasts':r['forecasts'],'detection':[{k:c[k] for k in ('scenario','detected','total','false_alarm_episodes')} for c in r['classes']],
                      'interventions_passed':sum(x.get('passed',False) for x in r['interventions']),'feasible':sum(x['feasible'] for x in r['interventions'])},indent=2))
