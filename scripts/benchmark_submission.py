"""Reproducible synthetic robustness benchmark, separate from the live plant.

Run from round2: python scripts/benchmark_submission.py
Do not interpret the report as field accuracy or tune thresholds on its test cases.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timezone
import csv
import hashlib
import json
import math
import random
from neuratwin import thermal_reference as model

SEEDS=tuple(range(410,416))
SCENARIOS=('healthy','overload','cooling','sensor_bias','dropout')
EVENT_MIN=100
HORIZONS=(5,15,30)


def plant(seed,scenario):
    """Hidden plant has parameter mismatch, nonlinear cooling and noisy channels."""
    rng=random.Random(seed);rise=rng.uniform(45,68);tau=rng.uniform(55,150);level=SEEDS.index(seed)
    winding_rise=rng.uniform(20,26);oil=35.;winding=8.;rows=[];truth=[]
    for minute in range(181):
        load=70+22*math.sin(minute/11) if minute<70 else 85+3*math.sin(minute/15)
        ambient=28+3*math.sin(minute/100)
        cooling=1.;bias=0.
        active=minute>=EVENT_MIN
        if active and scenario=='overload':load=(105,115,124,126,140,155)[level]
        if active and scenario=='cooling':cooling=(.95,.8,.65,.5,.35,.25)[level]
        if active and scenario=='sensor_bias':bias=(2,6,10,14,22,28)[level]*min(1,(minute-EVENT_MIN)/10)
        # Different core-loss fraction and a small nonlinear heat-loss term.
        target=ambient+rise*(.17+.83*(load/100)**2)**.8/cooling
        if minute:
            oil+=(target-oil)*(1-math.exp(-1/tau))-.00008*(oil-ambient)**1.5
            winding+=(winding_rise*(load/100)**1.6-winding)*(1-math.exp(-1/6))
        noise=(.10,.2,.35,.55,.85,1.2)[level]
        oil_m=oil+rng.gauss(0,noise);hot_m=oil+winding+bias+rng.gauss(0,noise*1.5)
        if active and scenario=='dropout' and minute%12<8:oil_m=hot_m=None
        rows.append({'elapsed_s':minute*60,'oil_c':oil_m,'hotspot_c':hot_m,
                     'ambient_c':ambient,'load_percent':load})
        truth.append({'oil_c':oil,'hotspot_c':oil+winding,'active':active and scenario!='healthy'})
    return rows,truth


def evaluate():
    cases=[];forecast_rows=[];diagnostic_rows=[]
    expected={'overload':'overload','cooling':'thermal_deviation','sensor_bias':'channel_disagreement','dropout':'missing_data'}
    for seed in SEEDS:
        for scenario in SCENARIOS:
            rows,truth=plant(seed,scenario);reference=model.fit(rows[:70])
            forecasts=[]
            for origin in (75,90,105,120,135,150):
                for horizon in HORIZONS:
                    pred=model.forecast(reference,rows[origin],horizon);target=rows[origin+horizon]['oil_c']
                    if pred is None or target is None:
                        forecasts.append({'origin_min':origin,'horizon_min':horizon,'available':False});continue
                    changed=any(abs(r['load_percent']-rows[origin]['load_percent'])>3 for r in rows[origin+1:origin+horizon+1])
                    value={'seed':seed,'scenario':scenario,'origin_min':origin,'horizon_min':horizon,'available':True,
                           'actual_c':target,'predicted_c':pred,'model_error_c':abs(target-pred),
                           'persistence_error_c':abs(target-rows[origin]['oil_c']),'load_changed':changed}
                    forecasts.append(value);forecast_rows.append(value)
            decisions=[model.residual_screen(reference,rows[:i+1]) for i in range(70,len(rows))]
            alarms=[i+70 for i,d in enumerate(decisions) if d not in ('no_anomaly_established','insufficient_evidence')]
            correct=[i+70 for i,d in enumerate(decisions) if scenario!='healthy' and i+70>=EVENT_MIN and d==expected[scenario]]
            first=min(correct) if correct else None
            false_minutes=[i for i in alarms if scenario=='healthy' or i<EVENT_MIN]
            threshold=next((i for i in range(EVENT_MIN,len(rows)) if rows[i]['hotspot_c'] is not None and rows[i]['hotspot_c']>=110),None)
            critical=next((i for i in range(EVENT_MIN,len(rows)) if truth[i]['hotspot_c']>=125),None)
            c={'seed':seed,'scenario':scenario,'reference':reference,'first_correct_detection_min':first,
               'detection_delay_min':first-EVENT_MIN if first is not None else None,
               'false_alarm_minutes':len(false_minutes),'first_threshold_warning_min':threshold,
               'actual_thermal_critical_min':critical,
               'lead_to_thermal_critical_min':critical-first if first is not None and critical is not None and first<=critical else None,
               'forecasts':forecasts}
            cases.append(c)
            for i,d in enumerate(decisions):diagnostic_rows.append({'seed':seed,'scenario':scenario,'minute':i+70,'decision':d})
    summary=[]
    for horizon in HORIZONS:
        selected=[r for r in forecast_rows if r['horizon_min']==horizon]
        summary.append({'horizon_min':horizon,'scored':len(selected),'possible':len(cases)*6,
                        'model_mae_c':sum(r['model_error_c'] for r in selected)/len(selected),
                        'persistence_mae_c':sum(r['persistence_error_c'] for r in selected)/len(selected),
                        'changed_load_windows':sum(r['load_changed'] for r in selected)})
    anomaly_cases=[c for c in cases if c['scenario']!='healthy']
    detected=sum(c['first_correct_detection_min'] is not None for c in anomaly_cases)
    false_minutes=sum(c['false_alarm_minutes'] for c in cases)
    normal_minutes=sum(111 if c['scenario']=='healthy' else 30 for c in cases)
    decisions={(r['seed'],r['scenario'],r['minute']):r['decision'] for r in diagnostic_rows}
    positives=correct_positives=0
    for r in diagnostic_rows:
        if r['decision'] not in ('no_anomaly_established','insufficient_evidence'):
            positives+=1
            if r['scenario']!='healthy' and r['minute']>=EVENT_MIN and r['decision']==expected[r['scenario']]:correct_positives+=1
    report={'version':'submission-benchmark-1','generated_at':datetime.now(timezone.utc).isoformat(),
            'scope':'30 synthetic robustness cases from a separate mismatched/noisy plant. No field data or failure probability claim.',
            'protocol':{'seeds':list(SEEDS),'scenarios':list(SCENARIOS),'event_min':EVENT_MIN,'training':'First 70 healthy samples only; internal 70/30 chronological fit check.',
                        'forecast':'Fixed inputs at each origin; no future load or hidden fault label supplied.',
                        'detector':'Fixed residual thresholds and 3/4-sample persistence; no labels provided to the detector.',
                        'difficulty':'Includes mild cooling losses, slowly drifting 2–28 °C sensor offsets, 105–155% loads and 0.1–1.2 °C oil noise; reports misses and false alarms.',
                        'limits':'Seeds are reproducible and public, not a permanently sealed test set. One plant family; horizons/origins overlap. No parameter tuning was performed on this report.'},
            'forecasts':summary,'detection':{'event_recall':detected/len(anomaly_cases),'events_detected':detected,
                                           'events_total':len(anomaly_cases),'correct_alert_precision':correct_positives/positives if positives else None,
                                           'false_alarm_minutes':false_minutes,'normal_minutes':normal_minutes,
                                           'false_alarm_rate_per_normal_minute':false_minutes/normal_minutes},
            'cases':cases,'laya':{'role':'Optional interpreter only; excluded from these predictions and protection decisions.',
                               'recorded_evaluation':'Five synthetic integration cases, five abstentions; no diagnostic improvement established.'}}
    report['protocol_sha256']=hashlib.sha256(json.dumps(report['protocol'],sort_keys=True).encode()).hexdigest()
    return report,forecast_rows,diagnostic_rows


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1];report,forecasts,diagnostics=evaluate()
    for name,value in [('submission-benchmark.json',report)]:
        (root/'reports'/name).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    for name,rows in [('submission-forecast-scores.csv',forecasts),('submission-anomaly-decisions.csv',diagnostics)]:
        with (root/'reports'/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    rows,_=plant(SEEDS[0],'healthy')
    with (root/'data'/'synthetic-oil-reference.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['elapsed_s','oil_c','ambient_c','load_percent'],extrasaction='ignore');w.writeheader();w.writerows(rows[:70])
    print(json.dumps({'forecast':report['forecasts'],'detection':report['detection']},indent=2))
