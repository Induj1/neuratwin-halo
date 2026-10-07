"""Copy existing SQLite evidence to Supabase without overwriting cloud records.

Dry run by default. Back up the SQLite file before using --apply. The source is
opened read-only. No control commands are executed and no external messages sent.
"""
import argparse
import base64
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from neuratwin import cloud


def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',default='runtime/neuratwin.sqlite3');p.add_argument('--apply',action='store_true');a=p.parse_args()
    source=Path(a.source).resolve();db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    records=[]
    if 'halo_records' in tables:
        for r in db.execute('select * from halo_records'): records.append((r['kind'],r['id'],json.loads(r['content'])))
    if 'configurations' in tables:
        records.extend(('legacy_config',r['asset_id'],json.loads(r['content'])) for r in db.execute('select * from configurations'))
    if 'datasets' in tables:
        for r in db.execute('select * from datasets'):
            readings=json.loads(r['readings']);records.append(('legacy_dataset',r['id'],{**dict(r),'readings':readings,'count':len(readings)}))
    if 'work_orders' in tables:
        for r in db.execute('select * from work_orders'):
            content={**json.loads(r['content']),'id':r['id'],'asset_id':r['asset_id'],'status':r['status'],'created_at':r['created_at'],
                     'audit':[dict(x) for x in db.execute('select status,note,created_at from audit where order_id=? order by id',(r['id'],))]}
            records.append(('legacy_work_order',r['id'],content))
    frames=list(db.execute('select content from halo_frames order by id')) if 'halo_frames' in tables else []
    events=list(db.execute('select * from halo_events order by id')) if 'halo_events' in tables else []
    print({'records':len(records),'frames':len(frames),'events':len(events),'apply':a.apply})
    if not a.apply:return
    print(cloud.health());copied=skipped=0
    for kind,key,content in records:
        # Expired command and integration state must never be reactivated.
        if kind in ('relay_command','command','integration','telegram_subscription'):skipped+=1;continue
        with cloud.transaction() as unit:
            if unit.get(kind,key) is not None:skipped+=1;continue
            if kind=='attachment' and content.get('data'):
                path=content['incident_id']+'/'+content['id']+('.png' if content['mime']=='image/png' else '.jpg')
                cloud.upload(path,base64.b64decode(content.pop('data')),content['mime']);content['object_path']=path
            unit.put(kind,key,content);copied+=1
    for r in frames:cloud.rpc('halo_ingest_frame',{'p_frame':json.loads(r['content'])})
    # Preserve old event IDs as a namespaced imported ledger, not fabricated new events.
    for r in events:
        with cloud.transaction() as unit:
            key='sqlite-'+str(r['id'])
            if unit.get('imported_audit',key) is None:unit.put('imported_audit',key,{**dict(r),'content':json.loads(r['content']),'source':'original SQLite ledger'})
    db.close();print({'records_copied':copied,'records_skipped':skipped,'frames_replayed_idempotently':len(frames)})


if __name__=='__main__':main()
