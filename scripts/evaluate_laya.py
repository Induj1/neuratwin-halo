"""Local integration evaluation on synthetic cases, not transformer accuracy."""
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuratwin import halo_ai as ai, halo_engine as engine

def main():
    output=Path(__file__).resolve().parents[1]/'reports/halo-laya-evaluation.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    os.environ['HALO_AI_ENABLED']='1'
    with tempfile.TemporaryDirectory() as directory:
        os.environ['NEURATWIN_DB']=str(Path(directory)/'evaluation.sqlite3')
        results=[]
        for case in ('normal','overload','heating','sensor','dropout'):
            snap=engine.snapshot(engine.demonstration(case,210),'simulated','EVAL')
            r=ai.assess(snap,[],True)
            results.append({'case_revealed_after_assessment':case,**{k:r[k] for k in ('provider','hypothesis','inspection','distributions','raw_model_choices','abstained','policy_override','latency_ms','prompt_version','usage','fallback_reason')}})
        report={'scope':'Five synthetic integration cases. No field diagnostic accuracy, life prediction or calibration claim.',
                'model':'convaiinnovations/laya','cases':results,'all_local_model':all(r['provider']=='laya' for r in results),
                'all_typed':all(r['hypothesis'] in ai.HYPOTHESES and r['inspection'] in ai.INSPECTIONS for r in results),
                'dropout_withheld':results[-1]['hypothesis']=='insufficient_evidence'}
        output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
        for r in results: print(r['case_revealed_after_assessment'],r['provider'],r['hypothesis'],r['inspection'],r['latency_ms'])
        if not(report['all_local_model'] and report['all_typed'] and report['dropout_withheld']):raise SystemExit(1)

if __name__=='__main__':main()
