"""Persistent fleet recordings, evidence cards and operator-owned triage cases."""
import csv
from copy import deepcopy
import io
import json
from uuid import uuid4
from typing import Literal
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field, ValidationError
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from .halo_contracts import Contract
from .halo_api import operator, WRITE_LOCK
from . import halo_store as store, fleet_model as model
from .storage import now
from .twin_studies import digest

router = APIRouter(prefix='/api/halo/fleet', dependencies=[Depends(operator)])


def record(key):
    value = store.get('fleet_recording', key)
    if not value: raise HTTPException(404, 'Fleet recording not found.')
    return value


def member(value, asset):
    item = next((a for a in value['report']['assets'] if a['asset']['asset_id']==asset), None)
    if item is None: raise HTTPException(404, 'Asset does not belong to this fleet recording.')
    return item


def summary(value):
    return {k: value[k] for k in ('id', 'name', 'created_at', 'source', 'sha256')} | {'summary': value['report']['summary']}


def save(portfolio, actor):
    report = model.analyse(portfolio)
    value = {'id': 'FLEET-'+uuid4().hex, 'name': portfolio.name, 'source': portfolio.source,
        'created_at': now(), 'created_by': actor, 'portfolio': portfolio.model_dump(mode='json'), 'report': report}
    value['sha256'] = digest({'portfolio': value['portfolio'], 'report': report})
    with WRITE_LOCK, store.transaction():
        store.put('fleet_recording', value['id'], value)
        store.put('fleet_catalog', value['id'], summary(value))
        store.event(value['id'], 'fleet_recording_created', {'sha256': value['sha256'], 'actor': actor})
    return {**summary(value), 'report': report}


@router.get('/recordings')
def recordings():
    return {'recordings': store.records('fleet_catalog')}


class Demo(Contract):
    seed: int = Field(20261011, ge=0, le=2147483647)


@router.post('/demo')
def demonstration(payload: Demo, actor=Depends(operator)):
    return save(model.demonstration(payload.seed), actor)


@router.post('/recordings')
def create(payload: model.Portfolio, actor=Depends(operator)):
    return save(payload, actor)


class Import(Contract):
    name: str = Field(min_length=3, max_length=120)
    source_note: str = Field(min_length=5, max_length=1000)
    csv_text: str = Field(max_length=4_000_000)


@router.post('/import')
def import_csv(payload: Import, actor=Depends(operator)):
    reader = csv.DictReader(io.StringIO(payload.csv_text.lstrip('\ufeff')))
    required = {'asset_id', 'name', 'rated_kva', 'timestamp', 'load_pu', 'ambient_c', 'oil_c'}
    optional = {'tie_group', 'criticality', 'construction', 'oil_limit_c', 'max_loading_pu', 'voltage_pu'}
    columns = reader.fieldnames or []
    if not required.issubset(columns) or set(columns)-required-optional or len(columns)!=len(set(columns)):
        raise HTTPException(422, 'Use the fleet CSV template. Required columns: '+', '.join(sorted(required)))
    grouped = {}
    try:
        for line, row in enumerate(reader, 2):
            if line > 20001: raise ValueError('At most 20,000 samples.')
            if None in row or any(v is None for v in row.values()): raise ValueError('Row has a different number of fields from the header.')
            metadata = {k: row[k] for k in ('asset_id', 'name', 'rated_kva', 'tie_group', 'criticality', 'construction', 'oil_limit_c', 'max_loading_pu') if row.get(k, '').strip()}
            sample = {k: row[k] if row[k].strip() else None for k in ('timestamp', 'load_pu', 'ambient_c', 'oil_c', 'voltage_pu') if k in row}
            key = row['asset_id']
            if key not in grouped: grouped[key] = {**metadata, 'samples': []}
            if {k: v for k, v in grouped[key].items() if k!='samples'} != metadata:
                raise ValueError('Asset metadata changed between rows; use one declared configuration per recording.')
            grouped[key]['samples'].append(sample)
        portfolio = model.Portfolio(name=payload.name, source='imported', source_note=payload.source_note, assets=list(grouped.values()))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, 'Invalid fleet recording: '+str(exc)[:600]) from exc
    return save(portfolio, actor)


@router.get('/template.csv')
def template():
    return Response('asset_id,name,rated_kva,tie_group,criticality,construction,oil_limit_c,max_loading_pu,timestamp,load_pu,ambient_c,oil_c,voltage_pu\nDT-01,Example feeder,250,TIE-1,3,sealed,95,1,2026-10-08T00:00:00+05:30,0.8,28,62,1\nDT-01,Example feeder,250,TIE-1,3,sealed,95,1,2026-10-08T00:05:00+05:30,0.82,28,62.1,1\n', media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="fleet-template.csv"'})


@router.get('/recordings/{key}')
def read(key: str):
    value = record(key)
    return {**summary(value), 'report': value['report']}


@router.get('/recordings/{key}/assets/{asset}')
def asset_detail(key: str, asset: str):
    value = record(key); item = member(value, asset)
    source = next(a for a in value['portfolio']['assets'] if a['asset_id']==asset)
    labs = store.get('fleet_lab', key+':'+asset, {'samples': []})
    return {**item, 'samples': source['samples'], 'labs': labs,
        'lab_trend': model.lab_trend([model.LabSample(**s) for s in labs['samples']]) if labs['samples'] else None}


def save_study(key, kind, inputs, result, actor):
    value = {'id': 'STUDY-'+uuid4().hex, 'recording_id': key, 'kind': kind,
        'created_at': now(), 'created_by': actor, 'inputs': inputs, 'result': result}
    value['sha256'] = digest(value)
    with WRITE_LOCK, store.transaction():
        store.put('fleet_study', value['id'], value)
    return {**result, 'study_id': value['id'], 'sha256': value['sha256']}


@router.post('/recordings/{key}/transfer')
def transfer(key: str, payload: model.Transfer, actor=Depends(operator)):
    try: result = model.transfer(record(key)['report'], payload)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    return save_study(key, 'load_transfer', payload.model_dump(mode='json'), result, actor)


class CostStudy(model.Costs):
    recording_id: str | None = None


@router.post('/costs')
def costs(payload: CostStudy, actor=Depends(operator)):
    if payload.recording_id: record(payload.recording_id)
    result = model.costs(payload)
    return save_study(payload.recording_id, 'deployment_cost', payload.model_dump(mode='json'), result, actor)


@router.post('/recordings/{key}/assets/{asset}/lab')
def add_lab(key: str, asset: str, payload: model.LabSample, actor=Depends(operator)):
    member(record(key), asset)
    with WRITE_LOCK, store.transaction():
        labs = store.get('fleet_lab', key+':'+asset, {'samples': [], 'trail': []})
        if len(labs['samples'])>=100: raise HTTPException(422, 'At most 100 laboratory samples per asset recording.')
        samples = [model.LabSample(**s) for s in labs['samples']]+[payload]
        try: trend = model.lab_trend(samples)
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc
        labs['samples'].append(payload.model_dump(mode='json'))
        labs['trail'].append({'actor': actor, 'recorded_at': now(), 'sample_sha256': digest(payload.model_dump(mode='json'))})
        store.put('fleet_lab', key+':'+asset, labs)
    return {'labs': labs, 'lab_trend': trend}


class NewCase(Contract):
    asset_id: str
    owner: str = Field(min_length=2, max_length=80)
    note: str = Field(min_length=5, max_length=2000)


@router.get('/cases')
def cases():
    return {'cases': store.records('fleet_case')}


@router.post('/recordings/{key}/cases')
def create_case(key: str, payload: NewCase, actor=Depends(operator)):
    value = record(key); item = member(value, payload.asset_id)
    case_id = key+':'+payload.asset_id
    with WRITE_LOCK, store.transaction():
        if store.get('fleet_case', case_id): raise HTTPException(409, 'This asset recording already has a triage case. Update the existing case.')
        case = {'id': case_id, 'recording_id': key, 'asset_id': payload.asset_id, 'owner': payload.owner,
            'source': value['source'], 'recording_sha256': value['sha256'], 'frozen_evidence': deepcopy(item),
            'revision': 0, 'status': 'open', 'created_at': now(),
            'trail': [{'at': now(), 'actor': actor, 'status': 'open', 'note': payload.note}]}
        store.put('fleet_case', case_id, case)
    return case


class CaseUpdate(Contract):
    revision: int = Field(ge=0)
    status: Literal['open', 'inspection_recorded', 'followup_required', 'review_complete']
    note: str = Field(min_length=5, max_length=2000)


@router.post('/recordings/{key}/cases/{asset}')
def update_case(key: str, asset: str, payload: CaseUpdate, actor=Depends(operator)):
    with WRITE_LOCK, store.transaction():
        case = store.get('fleet_case', key+':'+asset)
        if not case: raise HTTPException(404, 'Triage case not found.')
        if case['revision'] != payload.revision: raise HTTPException(409, 'Case changed. Reload before saving your update.')
        case['revision'] += 1; case['status'] = payload.status
        case['trail'].append({'at': now(), 'actor': actor, 'status': payload.status, 'note': payload.note})
        store.put('fleet_case', case['id'], case)
    return case


@router.get('/recordings/{key}/export')
def export(key: str):
    value = deepcopy(record(key))
    value['cases'] = [v for v in store.records('fleet_case') if v['recording_id']==key]
    value['studies'] = [v for v in store.records('fleet_study') if v['recording_id']==key]
    value['laboratory'] = {a['asset']['asset_id']: store.get('fleet_lab', key+':'+a['asset']['asset_id']) for a in value['report']['assets']}
    value['export_sha256'] = digest(value)
    value['integrity_note'] = 'Digest checks retained content, not authorship or third-party validation. Source recording remains immutable; case/lab/study additions are timestamped separately.'
    return Response(json.dumps(value, indent=2, allow_nan=False), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="halo-fleet-evidence.json"'})


@router.get('/recordings/{key}/report.pdf')
def pdf(key: str):
    value = record(key); report = value['report']; out = io.BytesIO()
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 9
    styles['BodyText'].leading = 12
    para = lambda text, style='BodyText': Paragraph(escape(str(text).replace('–', '-').replace('—', '-')), styles[style])
    story = [para('NeuraTwin Halo | Fleet evidence', 'Title'), para(value['name'], 'Heading2'),
        para(f'Source: {value["source"]} | Recording reference: {report["reference_time"]}'),
        para(report['source_note']), para(report['scope']), Spacer(1, 14)]
    for row in report['assets']:
        a, c, p = row['asset'], row['card'], row['priority']
        block = [para(a['asset_id']+' | '+a['name'], 'Heading2'), para(f'Triage: {p["score"]}/100 ({p["status"]}) | Model: {c["status"]}')]
        block += [para(reason) for reason in p['reasons']]
        m = c.get('metrics')
        if m:
            table = Table([['MAE / persistence', f'{m["mae_c"]:.2f} / {m["persistence_mae_c"]:.2f} C'],
                ['Test trajectory coverage', f'{m["test_trajectory_coverage"]:.0%} ({m["test_windows"]} windows)'],
                ['Frozen band radius', f'{m["band_radius_c"]:.2f} C']], colWidths=[240, 220])
            table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.grey),('BOTTOMPADDING',(0,0),(-1,-1),8)])); block.append(table)
        block += [para('Hold: '+h) for h in c['holds']]
        block += [para(c['scope']), Spacer(1, 10)]
        story.append(KeepTogether(block))
    story.append(KeepTogether([para('Methods and integrity', 'Heading2'), para('60% fit / 20% calibration / 20% test. Frozen approximately 30-minute constant-input predictions; disjoint calibration and test trajectories. Nominal 90% empirical bands; observed coverage is reported separately. No field validation or hardware actuation.'), para('This PDF summarizes model qualification. Download Complete evidence for samples, cases, laboratory additions and saved studies.'), para('Recording SHA-256: '+value['sha256'])]))
    def footer(canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#52605b'))
        canvas.drawString(72, 38, 'NeuraTwin Halo | '+value['source'].upper()+' RECORDING | Not field validated')
        canvas.drawRightString(doc.pagesize[0]-72, 38, 'Page '+str(doc.page)); canvas.restoreState()
    SimpleDocTemplate(out, title='Halo Fleet Evidence', author='Neura Rangers').build(story, onFirstPage=footer, onLaterPages=footer)
    return Response(out.getvalue(), media_type='application/pdf', headers={'Content-Disposition':'attachment; filename="halo-fleet-report.pdf"'})
