"""Local persistent operator workflow; no external messages or control actions."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def database():
    path = Path(os.environ.get('NEURATWIN_DB', str(ROOT/'runtime/neuratwin.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    try:
        connection.row_factory = sqlite3.Row
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, asset_id TEXT, name TEXT, readings TEXT);
        CREATE TABLE IF NOT EXISTS configurations (asset_id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE IF NOT EXISTS work_orders (id TEXT PRIMARY KEY, asset_id TEXT, status TEXT, content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, order_id TEXT, status TEXT, note TEXT, created_at TEXT);
        ''')
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def orders():
    from . import cloud, halo_store
    if cloud.enabled(): return sorted(halo_store.records('legacy_work_order'),key=lambda r:r['created_at'],reverse=True)
    with database() as db:
        records = db.execute('SELECT * FROM work_orders ORDER BY created_at DESC').fetchall()
        return [{**json.loads(r['content']), 'id': r['id'], 'status': r['status'], 'created_at': r['created_at'],
                 'audit': [dict(a) for a in db.execute('SELECT status,note,created_at FROM audit WHERE order_id=? ORDER BY id', (r['id'],))]}
                for r in records]


def ping():
    from . import cloud
    if cloud.enabled(): return cloud.health()
    with database() as db: db.execute('SELECT 1').fetchone()
    return {'backend':'sqlite','database':'connected'}


def configuration(asset_id):
    from . import cloud, halo_store
    if cloud.enabled(): return halo_store.get('legacy_config',asset_id)
    with database() as db:
        row=db.execute('SELECT content FROM configurations WHERE asset_id=?',(asset_id,)).fetchone()
    return json.loads(row['content']) if row else None


def save_configuration(asset_id,content):
    from . import cloud, halo_store
    if cloud.enabled(): return halo_store.put('legacy_config',asset_id,content)
    with database() as db: db.execute('INSERT OR REPLACE INTO configurations VALUES (?,?)',(asset_id,json.dumps(content)))


def dataset(key,asset_id):
    from . import cloud, halo_store
    if cloud.enabled():
        row=halo_store.get('legacy_dataset',key)
        return row if row and row['asset_id']==asset_id else None
    with database() as db: row=db.execute('SELECT * FROM datasets WHERE id=? AND asset_id=?',(key,asset_id)).fetchone()
    return {**dict(row),'readings':json.loads(row['readings'])} if row else None


def datasets():
    from . import cloud, halo_store
    if cloud.enabled():
        return [{k:r[k] for k in ('id','asset_id','name','count')} for r in halo_store.records('legacy_dataset')]
    with database() as db:
        return [dict(r) for r in db.execute('SELECT id,asset_id,name,json_array_length(readings) AS count FROM datasets ORDER BY rowid DESC')]


def save_dataset(key,asset_id,name,readings):
    from . import cloud, halo_store
    if cloud.enabled():
        return halo_store.put('legacy_dataset',key,{'id':key,'asset_id':asset_id,'name':name,'readings':readings,'count':len(readings)})
    with database() as db: db.execute('INSERT INTO datasets VALUES (?,?,?,?)',(key,asset_id,name,json.dumps(readings,allow_nan=False)))


def create_order(key,asset_id,content):
    from . import cloud, halo_store
    stamp=now(); audit={'status':'open','note':'Created from recorded model evidence; no physical action executed.','created_at':stamp}
    if cloud.enabled():
        if halo_store.get('legacy_work_order',key): return False
        halo_store.put('legacy_work_order',key,{**content,'id':key,'asset_id':asset_id,'status':'open','created_at':stamp,'audit':[audit]})
        return True
    with database() as db:
        existing=db.execute('SELECT id FROM work_orders WHERE id=?',(key,)).fetchone()
        if existing:return False
        db.execute('INSERT INTO work_orders VALUES (?,?,?,?,?)',(key,asset_id,'open',json.dumps(content),stamp))
        db.execute('INSERT INTO audit(order_id,status,note,created_at) VALUES (?,?,?,?)',(key,'open',audit['note'],stamp))
    return True


def update_order(key,status,note):
    from . import cloud, halo_store
    from fastapi import HTTPException
    stamp=now()
    if cloud.enabled():
        row=halo_store.get('legacy_work_order',key)
        if not row: raise HTTPException(404,'Work order not found.')
        row['status']=status; row['audit'].append({'status':status,'note':note,'created_at':stamp})
        return halo_store.put('legacy_work_order',key,row)
    with database() as db:
        if db.execute('SELECT id FROM work_orders WHERE id=?',(key,)).fetchone() is None: raise HTTPException(404,'Work order not found.')
        db.execute('UPDATE work_orders SET status=? WHERE id=?',(status,key))
        db.execute('INSERT INTO audit(order_id,status,note,created_at) VALUES (?,?,?,?)',(key,status,note,stamp))
