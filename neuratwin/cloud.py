"""Server-only Supabase transport and optimistic, atomic record transactions.

No credentials are returned to clients; no automatic SQLite failover is allowed.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
import uuid
from urllib.parse import quote, urlparse
import httpx
from fastapi import HTTPException


def enabled():
    mode = os.getenv('HALO_STORAGE_BACKEND', 'sqlite')
    if mode not in ('sqlite', 'supabase'):
        raise RuntimeError('HALO_STORAGE_BACKEND must be sqlite or supabase.')
    return mode == 'supabase'


def settings():
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_SECRET_KEY', '')
    if urlparse(url).scheme != 'https' or not urlparse(url).hostname or not key:
        raise HTTPException(503, 'Supabase server configuration is incomplete.')
    return url, key


@lru_cache(maxsize=1)
def client():
    return httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False)


def request(method, path, *, payload=None, params=None, data=None, mime=None, public=False, bearer=None):
    url, key = settings()
    headers = {'apikey': os.getenv('SUPABASE_PUBLISHABLE_KEY', '') if public else key}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    if mime:
        headers['Content-Type'] = mime
    content = data
    if payload is not None:
        content = json.dumps(payload, allow_nan=False).encode()
        headers['Content-Type'] = 'application/json'
    try:
        result = client().request(method, url + path, headers=headers, params=params, content=content)
    except httpx.HTTPError:
        raise HTTPException(503, 'Supabase response unavailable. Check read-back before retrying; no automatic SQLite fallback is used.') from None
    if result.is_error:
        duplicate_object=False
        if path.startswith('/storage/') and result.status_code==400:
            try: duplicate_object=result.json().get('code')=='KeyAlreadyExists'
            except ValueError: pass
        if result.status_code == 409 or duplicate_object:
            raise HTTPException(409, 'Cloud record conflict. Refresh before retrying; telemetry retries must retain their identity.')
        if path.startswith('/auth/') and result.status_code in (400,401,403,422):
            raise HTTPException(401, 'Sign-in or session renewal failed.')
        if result.status_code == 429:
            raise HTTPException(429, 'Service rate limit reached. Please retry later.')
        if path.endswith('/halo_ingest_frame') and result.status_code == 422:
            raise HTTPException(422, 'Telemetry rejected by cloud acquisition checks.')
        raise HTTPException(503, 'Cloud operation failed. Check server configuration and the applied schema; credentials are not included in this error.')
    return result


def rpc(name, payload=None):
    return request('POST', '/rest/v1/rpc/' + name, payload=payload or {}).json()


def rows(table, params, limit=None):
    result, offset = [], 0
    while limit is None or len(result) < limit:
        batch = min(500, limit-len(result)) if limit is not None else 500
        page = request('GET', '/rest/v1/' + table, params={**params, 'offset':offset, 'limit':batch}).json()
        result.extend(page)
        if len(page) < batch:
            break
        offset += len(page)
    return result


class UnitOfWork:
    def __init__(self):
        self.reads, self.cache, self.writes, self.events = {}, {}, {}, []

    def remember(self, kind, key, row):
        pair = (kind,key)
        if pair not in self.reads:
            self.reads[pair] = row['revision'] if row else None
            self.cache[pair] = row['content'] if row else None

    def get(self, kind, key, default=None):
        pair = (kind,key)
        if pair in self.writes:
            return deepcopy(self.writes[pair])
        if pair not in self.reads:
            found = rows('halo_records', {'kind':'eq.'+kind,'id':'eq.'+key,'select':'content,revision'},1)
            self.remember(kind,key,found[0] if found else None)
        return deepcopy(self.cache[pair] if self.cache[pair] is not None else default)

    def put(self, kind, key, content):
        json.dumps(content, allow_nan=False)
        self.get(kind,key)
        self.writes[kind,key] = deepcopy(content)
        return content

    def records(self, kind):
        if (kind,None) not in self.reads:
            version=rows('halo_kind_revisions',{'kind':'eq.'+kind,'select':'revision'},1)
            self.reads[kind,None]=version[0]['revision'] if version else 0
        found = rows('halo_records', {'kind':'eq.'+kind,'select':'id,content,revision','order':'updated_at.desc,id.asc'})
        result = {}
        for row in found:
            self.remember(kind,row['id'],row)
            result[row['id']] = self.get(kind,row['id'])
        result.update({key:deepcopy(v) for (k,key),v in self.writes.items() if k==kind})
        return list(result.values())

    def event(self, asset_id, kind, content):
        key = str(uuid.uuid4())
        self.events.append({'id':key,'asset_id':asset_id,'kind':kind,'content':deepcopy(content),
                            'created_at':datetime.now(timezone.utc).isoformat()})
        return key

    def commit(self):
        if self.writes or self.events:
            rpc('halo_commit', {'p_reads':[{'kind':k,'id':i,'revision':v} for (k,i),v in self.reads.items()],
                'p_records':[{'kind':k,'id':i,'content':v} for (k,i),v in self.writes.items()], 'p_events':self.events})


current: ContextVar[UnitOfWork | None] = ContextVar('halo_cloud_transaction', default=None)


@contextmanager
def transaction():
    if not enabled() or current.get() is not None:
        yield current.get()
        return
    unit = UnitOfWork()
    token = current.set(unit)
    try:
        yield unit
        unit.commit()
    finally:
        current.reset(token)


def call(method, *args):
    with transaction() as unit:
        return getattr(unit,method)(*args)


def frames(device_id, limit):
    found = rows('halo_frames',{'device_id':'eq.'+device_id,'order':'id.desc','select':'id,content,received_at'},limit)
    return [{**r['content'],'received_at':r['received_at'],'evidence_id':f'T-{r["id"]}'} for r in reversed(found)]


def events(asset_id, limit):
    return rows('halo_events',{'asset_id':'eq.'+asset_id,'order':'created_at.desc,id.desc'},limit)


def health():
    result = rpc('halo_health')
    if result.get('schema_version') != 2 or result.get('storage') != 'private':
        raise HTTPException(503, 'Cloud schema version or evidence bucket privacy is incorrect.')
    return {'backend':'supabase',**result}


def upload(path, data, mime):
    try:
        request('POST','/storage/v1/object/halo-evidence/'+quote(path,safe='/'),data=data,mime=mime)
    except HTTPException as error:
        # A prior response may have been lost after upload. Never overwrite
        # different bytes at an existing evidence identity.
        if error.status_code != 409 or download(path) != data: raise


def download(path):
    return request('GET','/storage/v1/object/authenticated/halo-evidence/'+quote(path,safe='/')).content
