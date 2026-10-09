"""Development-only paired v5 vs reviewed-winding candidate, seeds 3101..3112.

No frozen evaluation seeds or reports are read. The candidate changes only two
winding parameters after prefix validation; all oil/residual/CUSUM/limit code is
shared unchanged. Every eligible window, hold and later disturbance is retained.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import csv
import hashlib
import json
import statistics
import argparse
from collections import Counter
from datetime import datetime,timezone
from neuratwin import twin_core as core,twin_observer as observer,thermal_reference,thermal_adaptation as adaptation
from neuratwin.validation_plant import generate,SCENARIOS,MIXED,FAMILIES
from scripts.benchmark_pipeline import warning_kinds,comparison_case,EXPECTED
from scripts.evaluation_metrics import forecast_summary

ROOT=Path(__file__).resolve().parents[1]
SEEDS=tuple(range(3101,3113))
SOURCE_FILES=('neuratwin/twin_observer.py','neuratwin/thermal_reference.py','neuratwin/thermal_adaptation.py',
              'neuratwin/twin_core.py','neuratwin/twin_studies.py','neuratwin/validation_plant.py',
              'scripts/develop_winding_reference.py','scripts/benchmark_pipeline.py','scripts/evaluation_metrics.py')


def source_hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='reports/winding-development-projection-only')
    args=parser.parse_args();initial_hashes=source_hashes()
    started=datetime.now(timezone.utc).isoformat();cases=[];scores=[];decisions=[]
    for family in FAMILIES:
        for seed in SEEDS:
            for scenario in (*SCENARIOS,*MIXED):
                rows,truth,meta=generate(seed,scenario,family=family,variable_event=True)
                base=core.Settings().model_dump();oil=thermal_reference.fit(observer.reference_rows(rows[:70]))
                if oil['identified'] and oil['beats_persistence']:
                    base.update(rated_oil_rise_c=oil['rated_oil_rise_c'],oil_tau_min=oil['oil_tau_min'])
                fit=adaptation.fit_winding(observer.winding_reference_rows(rows[:70]),base,reviewed_healthy=True)
                candidate=adaptation.apply_winding(base,fit)
                traces={'v5':[],'candidate':[]};event=meta['event_min']
                for minute in range(70,181):
                    original=observer.assess(rows[:minute+1],base,30)
                    pair={'v5':original,'candidate':observer.assess(rows[:minute+1],candidate,30) if fit['qualified'] else original}
                    for name,value in pair.items():
                        warnings=warning_kinds(value)
                        traces[name].append({'minute':minute,'active':truth[minute]['active'],'signals':value['hypotheses'],'warnings':warnings})
                        decisions.append({'family':family,'seed':seed,'scenario':scenario,'minute':minute,'method':name,
                            'available':value['available'],'active':truth[minute]['active'],'signals':'|'.join(value['hypotheses']),
                            'warnings':'|'.join(warnings),'holds':'|'.join(value['validity']['holds'])})
                        if minute in (75,90,105,120,135,150):
                            for horizon in (5,15,30):
                                actual=rows[minute+horizon]['hotspot_c'];available=value['available'] and actual is not None
                                prediction=value['forecast']['points'][horizon]['temperature_c'] if available else None
                                partition='healthy' if scenario=='healthy' else 'before_disturbance' if minute+horizon<event else 'crosses_disturbance' if minute<event else 'after_disturbance'
                                scores.append({'family':family,'seed':seed,'scenario':scenario,'method':name,'origin_min':minute,'horizon_min':horizon,
                                    'target':'hotspot_c','partition':partition,'available':available,
                                    'model_error_c':abs(prediction-actual) if available else None,'signed_error_c':prediction-actual if available else None,
                                    'actual_c':actual,'predicted_c':prediction,'persistence_error_c':abs(actual-rows[minute]['hotspot_c']) if available else None,
                                    'true_temperature_error_c':abs(prediction-truth[minute+horizon]['hotspot_c']) if available else None,
                                    'reason_code':'' if available else value['hypothesis'] if not value['available'] else 'future_observation_missing'})
                expected=[EXPECTED[k] for k in MIXED.get(scenario,(scenario,)) if k in EXPECTED]
                critical=next((i for i in range(event,181) if truth[i]['hotspot_c']>=125),None)
                cases.append({**meta,'fit':fit,'oil_fit_qualified':oil['identified'] and oil['beats_persistence'],
                    'critical_min':critical,'methods':{name:comparison_case(trace,event,critical,expected) for name,trace in traces.items()}})
            print(f'completed {family} development seed {seed}',flush=True)
    lookup={(r['family'],r['seed'],r['scenario'],r['origin_min'],r['horizon_min'],r['method']):r for r in scores}
    paired=[]
    for row in scores:
        if row['method']!='v5':continue
        alt=lookup[(*[row[k] for k in ('family','seed','scenario','origin_min','horizon_min')],'candidate')]
        if row['available'] and alt['available']:paired.extend([row,alt])
    summary={}
    for name in ('v5','candidate'):
        group=[c['methods'][name] for c in cases]
        summary[name]={'forecasts':forecast_summary([r for r in scores if r['method']==name]),
            'paired_identical_targets':forecast_summary([r for r in paired if r['method']==name]),
            'healthy_forecasts':forecast_summary([r for r in scores if r['method']==name and r['partition']=='healthy']),
            'by_family':{family:forecast_summary([r for r in scores if r['method']==name and r['family']==family]) for family in FAMILIES},
            'by_partition':{part:forecast_summary([r for r in scores if r['method']==name and r['partition']==part]) for part in ('healthy','before_disturbance','crosses_disturbance','after_disturbance')},
            'completed_signal_sets':sum(r['expected_signal_set_complete'] for r in group),
            'warnings_before_critical':sum(r['any_warning_before_critical'] for r in group),
            'false_alarm_minutes':sum(r['false_alarm_minutes'] for r in group),'false_alarm_episodes':sum(r['false_alarm_episodes'] for r in group)}
    losses=[{'family':c['family'],'seed':c['seed'],'scenario':c['scenario']} for c in cases
            if c['methods']['v5']['expected_signal_set_complete'] and not c['methods']['candidate']['expected_signal_set_complete']]
    report={'role':'Development tuning only; never fresh evaluation or measured field evidence.','started_at':started,
        'finished_at':datetime.now(timezone.utc).isoformat(),'seeds':list(SEEDS),'case_count':len(cases),
        'qualified_cases':sum(c['fit']['qualified'] for c in cases),'qualified_distinct_prefixes':sum(c['fit']['qualified'] for c in cases if c['scenario']=='healthy'),
        'candidate_version':adaptation.VERSION,'baseline':'v5-equivalent observer with oil reference and no winding projection metadata; all screening, thresholds and holds unchanged.',
        'candidate_scope':'Reviewed prefix fit changes eligible winding projections only, never diagnostic screening parameters.',
        'rejected_development_candidate':'reports/winding-development-candidate/benchmark.json replaced screening parameters and lost six complete sensor-bias detections; not promoted.',
        'comparison':summary,'lost_complete_detections':losses,
        'coverage_changes':dict(Counter((r['available'],lookup[(*[r[k] for k in ('family','seed','scenario','origin_min','horizon_min')],'candidate')]['available']) for r in scores if r['method']=='v5')),
        'cases':cases,'limits':['Same two internal synthetic plant families; overlapping targets and shared prefixes are dependent.',
            'Fitting sees only 70 healthy-protocol observations. Truth/scenario labels enter scoring only.',
            'No online adaptation, bias subtraction, CUSUM margin relaxation or future-input access.',
            'Coverage uses all 4320 method-specific target windows; paired comparison additionally uses identical jointly scorable targets.']}
    report['coverage_changes']={str(key):value for key,value in report['coverage_changes'].items()}
    report['source_sha256']=initial_hashes
    report['source_sha256_at_finish']=source_hashes()
    report['source_unchanged_during_run']=initial_hashes==report['source_sha256_at_finish']
    destination=(ROOT/args.output).resolve();destination.mkdir(exist_ok=True)
    (destination/'benchmark.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    for filename,data in (('forecasts.csv',scores),('decisions.csv',decisions)):
        with (destination/filename).open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    print(json.dumps({k:report[k] for k in ('case_count','qualified_cases','qualified_distinct_prefixes','lost_complete_detections','coverage_changes','source_unchanged_during_run')},indent=2))


if __name__=='__main__':main()
