"""Versioned records and immutable telemetry, sharing the local SQLite store."""
import json
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from .storage import database, now
from . import cloud

_local_transaction = ContextVar('halo_local_transaction', default=None)


@contextmanager
def transaction():
    """Atomic read/check/write across records and events, including local workers."""
    if cloud.enabled():
        with cloud.transaction() as unit:
            yield unit
        return
    current = _local_transaction.get()
    if current is not None:
        yield current
        return
    with database() as db:
        initialise(db)
        db.execute('BEGIN IMMEDIATE')
        token = _local_transaction.set(db)
        try:
            yield db
        finally:
            _local_transaction.reset(token)


@contextmanager
def connection():
    current = _local_transaction.get()
    if current is not None:
        yield current
    else:
        with database() as db:
            initialise(db)
            yield db


@contextmanager
def independent_transaction():
    """Commit durable queue ownership outside an HTTP request's cloud UOW."""
    if _local_transaction.get() is not None:
        raise RuntimeError('Independent queue transaction cannot nest inside a local write transaction.')
    token=cloud.current.set(None)
    try:
        with transaction() as unit:yield unit
    finally:cloud.current.reset(token)


def create_unique(kind, key, content):
    """Idempotent creation; never replace different content at an existing identity."""
    with transaction():
        prior = get(kind, key)
        if prior is not None:
            if prior != content:
                raise ValueError('Record identity already exists with different content.')
            return prior
        return put(kind, key, deepcopy(content))


def initialise(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS halo_records (
        kind TEXT, id TEXT, content TEXT, updated_at TEXT, PRIMARY KEY(kind,id));
    CREATE TABLE IF NOT EXISTS halo_frames (
        id INTEGER PRIMARY KEY, device_id TEXT, boot_id TEXT, sequence INTEGER,
        timestamp TEXT, received_at TEXT, content TEXT,
        UNIQUE(device_id,boot_id,sequence));
    CREATE INDEX IF NOT EXISTS halo_device_time ON halo_frames(device_id,id);
    CREATE TABLE IF NOT EXISTS halo_events (
        id INTEGER PRIMARY KEY, asset_id TEXT, kind TEXT, content TEXT, created_at TEXT);
    ''')


def get(kind, key, default=None):
    if cloud.enabled(): return cloud.call('get',kind,key,default)
    with connection() as db:
        row = db.execute('SELECT content FROM halo_records WHERE kind=? AND id=?', (kind,key)).fetchone()
    return json.loads(row['content']) if row else default


def put(kind, key, content):
    if cloud.enabled(): return cloud.call('put',kind,key,content)
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO halo_records VALUES (?,?,?,?)',
                   (kind, key, json.dumps(content, allow_nan=False), now()))
    return content


def records(kind):
    if cloud.enabled(): return cloud.call('records',kind)
    with connection() as db:
        rows = db.execute('SELECT content FROM halo_records WHERE kind=? ORDER BY updated_at DESC', (kind,)).fetchall()
    return [json.loads(r['content']) for r in rows]


def due_analysis_jobs(at,limit=25):
    """Bounded oldest-first selection; deferred/leased jobs never block ready work."""
    limit=max(1,min(int(limit),100))
    if cloud.enabled():
        conditions=(f'and(content->>status.eq.pending,or(content->>next_attempt_at.is.null,content->>next_attempt_at.lte.{at})),'
                    f'and(content->>status.eq.processing,or(content->>lease_until.is.null,content->>lease_until.lte.{at}))')
        rows=cloud.rows('halo_records',{'kind':'eq.analysis_job','or':'('+conditions+')',
            'select':'content','order':'content->>created_at.asc,id.asc'},limit)
        return [r['content'] for r in rows]
    with connection() as db:
        rows=db.execute('''SELECT content FROM halo_records WHERE kind='analysis_job' AND
            ((json_extract(content,'$.status')='pending' AND
              (json_extract(content,'$.next_attempt_at') IS NULL OR json_extract(content,'$.next_attempt_at')<=?)) OR
             (json_extract(content,'$.status')='processing' AND
              (json_extract(content,'$.lease_until') IS NULL OR json_extract(content,'$.lease_until')<=?)))
            ORDER BY json_extract(content,'$.created_at'),id LIMIT ?''',(at,at,limit)).fetchall()
    return [json.loads(r['content']) for r in rows]


def analysis_queue_sample(limit=8):
    """Bounded diagnostics, never raw frames or claim tokens; count is not inferred."""
    limit=max(1,min(int(limit),25))
    if cloud.enabled():
        rows=cloud.rows('halo_records',{'kind':'eq.analysis_job','content->>status':'in.(pending,processing)',
            'select':'content','order':'content->>created_at.asc,id.asc'},limit)
        jobs=[r['content'] for r in rows]
    else:
        with connection() as db:
            rows=db.execute('''SELECT content FROM halo_records WHERE kind='analysis_job'
                AND json_extract(content,'$.status') IN ('pending','processing')
                ORDER BY json_extract(content,'$.created_at'),id LIMIT ?''',(limit,)).fetchall()
        jobs=[json.loads(r['content']) for r in rows]
    return [{k:j.get(k) for k in ('id','status','created_at','attempts','last_attempt_at','next_attempt_at','lease_until','last_error_code')} for j in jobs]


def event(asset_id, kind, content):
    if cloud.enabled(): return cloud.call('event',asset_id,kind,content)
    with connection() as db:
        cursor = db.execute('INSERT INTO halo_events(asset_id,kind,content,created_at) VALUES (?,?,?,?)',
                            (asset_id, kind, json.dumps(content, allow_nan=False), now()))
        return cursor.lastrowid


def events(asset_id, limit=100):
    if cloud.enabled(): return cloud.events(asset_id,limit)
    with connection() as db:
        rows = db.execute('SELECT * FROM halo_events WHERE asset_id=? ORDER BY id DESC LIMIT ?',
                          (asset_id,limit)).fetchall()
    return [{**dict(r), 'content': json.loads(r['content'])} for r in rows]


def frames(device_id, limit=600):
    if cloud.enabled(): return cloud.frames(device_id,limit)
    with connection() as db:
        rows = db.execute('SELECT content,received_at,id FROM halo_frames WHERE device_id=? ORDER BY id DESC LIMIT ?',
                          (device_id,limit)).fetchall()
    return [{**json.loads(r['content']), 'received_at':r['received_at'], 'evidence_id':f'T-{r["id"]}'} for r in reversed(rows)]


def report_frames(device_id, captured_at):
    """All immutable retained acquisitions at a fixed cutoff, not the UI window."""
    if cloud.enabled():
        found=cloud.rows('halo_frames',{'device_id':'eq.'+device_id,'received_at':'lte.'+captured_at,
            'order':'id.asc','select':'id,content,received_at'})
        return [{**r['content'],'received_at':r['received_at'],'evidence_id':f'T-{r["id"]}'} for r in found]
    with connection() as db:
        found=db.execute('SELECT id,content,received_at FROM halo_frames WHERE device_id=? AND received_at<=? ORDER BY id',
                         (device_id,captured_at)).fetchall()
    return [{**json.loads(r['content']),'received_at':r['received_at'],'evidence_id':f'T-{r["id"]}'} for r in found]


def report_events(asset_id, captured_at):
    if cloud.enabled():
        return cloud.rows('halo_events',{'asset_id':'eq.'+asset_id,'created_at':'lte.'+captured_at,'order':'created_at.asc,id.asc'})
    with connection() as db:
        found=db.execute('SELECT * FROM halo_events WHERE asset_id=? AND created_at<=? ORDER BY id',(asset_id,captured_at)).fetchall()
    return [{**dict(r),'content':json.loads(r['content'])} for r in found]


def photo(value, data):
    """Store already validated JPEG/PNG bytes; return metadata without bytes."""
    value=dict(value)
    if cloud.enabled():
        path=value['incident_id']+'/'+value['id']+('.png' if value['mime']=='image/png' else '.jpg')
        cloud.upload(path,data,value['mime']);value['object_path']=path;value.pop('data',None)
    else: value['data']=base64.b64encode(data).decode()
    put('attachment',value['id'],value)
    return {k:v for k,v in value.items() if k!='data'}
