"""Compare the retained v5 and v6 fixed corpus on exactly the same target rows."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parents[1]


def main():
    paths={key:ROOT/'reports'/name for key,name in {
        'old_forecasts':'pipeline-v5-before-v6-forecasts.csv','new_forecasts':'pipeline-forecasts.csv',
        'old_decisions':'pipeline-v5-before-v6-decisions.csv','new_decisions':'pipeline-decisions.csv'}.items()}
    records={key:list(csv.DictReader(path.open(encoding='utf-8',newline=''))) for key,path in paths.items()}
    identity=('family','seed','scenario','origin_min','horizon_min','target')
    old={tuple(r[k] for k in identity):r for r in records['old_forecasts']}
    new={tuple(r[k] for k in identity):r for r in records['new_forecasts']}
    assert len(old)==len(records['old_forecasts']) and old.keys()==new.keys()
    coverage_changes=sum(a['available']!=new[key]['available'] for key,a in old.items())
    rows=[]
    for horizon in ('5','15','30'):
        matched=[(a,new[key]) for key,a in old.items() if a['target']=='hotspot_c' and a['horizon_min']==horizon]
        scored=[(a,b) for a,b in matched if a['available']=='True' and b['available']=='True']
        a=mean(float(a['model_error_c']) for a,b in scored);b=mean(float(b['model_error_c']) for a,b in scored)
        rows.append({'horizon_min':int(horizon),'same_scored_targets':len(scored),'possible':len(matched),
                     'v5_mae_c':a,'v6_mae_c':b,'mae_reduction_percent':100*(a-b)/a})
    dkey=('family','seed','scenario','minute')
    old_d={tuple(r[k] for k in dkey):r for r in records['old_decisions']}
    new_d={tuple(r[k] for k in dkey):r for r in records['new_decisions']}
    assert old_d.keys()==new_d.keys()
    screening_changes=sum(any(a[k]!=new_d[key][k] for k in ('hypotheses','holds','forecast_available','observed_status')) for key,a in old_d.items())
    report={'scope':'Paired known-corpus regression, not fresh evidence or a competitor accuracy comparison.',
        'forecast_identity_rows':len(old),'coverage_changed_rows':coverage_changes,'diagnostic_decision_rows':len(old_d),
        'changed_screening_decisions':screening_changes,'reported_hotspot':rows,
        'source_files':{key:{'file':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for key,path in paths.items()},
        'limits':'Only eligible reported-hotspot projections change. All target identities are paired; error gains do not establish safe countdowns, field performance or fivefold superiority.'}
    (ROOT/'reports/model-v6-upgrade.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_files'},indent=2))


if __name__=='__main__':main()
