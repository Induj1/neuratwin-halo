"""Versioned records and immutable telemetry, sharing the local SQLite store."""
import json
from .storage import database, now


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
    with database() as db:
        initialise(db)
        row = db.execute('SELECT content FROM halo_records WHERE kind=? AND id=?', (kind,key)).fetchone()
    return json.loads(row['content']) if row else default


def put(kind, key, content):
    with database() as db:
        initialise(db)
        db.execute('INSERT OR REPLACE INTO halo_records VALUES (?,?,?,?)',
                   (kind, key, json.dumps(content, allow_nan=False), now()))
    return content


def records(kind):
    with database() as db:
        initialise(db)
        rows = db.execute('SELECT content FROM halo_records WHERE kind=? ORDER BY updated_at DESC', (kind,)).fetchall()
    return [json.loads(r['content']) for r in rows]


def event(asset_id, kind, content):
    with database() as db:
        initialise(db)
        cursor = db.execute('INSERT INTO halo_events(asset_id,kind,content,created_at) VALUES (?,?,?,?)',
                            (asset_id, kind, json.dumps(content, allow_nan=False), now()))
        return cursor.lastrowid


def events(asset_id, limit=100):
    with database() as db:
        initialise(db)
        rows = db.execute('SELECT * FROM halo_events WHERE asset_id=? ORDER BY id DESC LIMIT ?',
                          (asset_id,limit)).fetchall()
    return [{**dict(r), 'content': json.loads(r['content'])} for r in rows]


def frames(device_id, limit=600):
    with database() as db:
        initialise(db)
        rows = db.execute('SELECT content,received_at,id FROM halo_frames WHERE device_id=? ORDER BY id DESC LIMIT ?',
                          (device_id,limit)).fetchall()
    return [{**json.loads(r['content']), 'received_at':r['received_at'], 'evidence_id':f'T-{r["id"]}'} for r in reversed(rows)]
