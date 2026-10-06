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
    with database() as db:
        records = db.execute('SELECT * FROM work_orders ORDER BY created_at DESC').fetchall()
        return [{**json.loads(r['content']), 'id': r['id'], 'status': r['status'], 'created_at': r['created_at'],
                 'audit': [dict(a) for a in db.execute('SELECT status,note,created_at FROM audit WHERE order_id=? ORDER BY id', (r['id'],))]}
                for r in records]
