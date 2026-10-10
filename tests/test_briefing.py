from copy import deepcopy
from datetime import datetime, timezone, timedelta
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from fastapi.testclient import TestClient
from neuratwin.app import app
from neuratwin import twin_core as core, halo_store as store, halo_engine as bench
from neuratwin import electrical_diagnostics as diagnostics
from neuratwin.electrical_model import terminal_fault
from neuratwin.briefing_api import report_snapshot, PDFRequest
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.halo_contracts import Frame

OP={'Authorization':'Bearer '+LOCAL_TOKEN}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'briefing.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite')
    monkeypatch.setenv('HALO_ESP32_URL','')
    monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c


def new_run(client):
    r=client.post('/api/halo/twin/runs',json={'request_id':'briefing-test-run'},headers=OP)
    assert r.status_code==200,r.text
    return r.json()


def test_impedance_changes_fault_current_on_one_consistent_base():
    p=core.Settings().model_dump();a=terminal_fault(p)
    assert a['prospective_rms_a']==pytest.approx(20*a['rated_secondary_a'])
    assert terminal_fault({**p,'impedance_percent':10})['prospective_rms_a']==pytest.approx(a['prospective_rms_a']/2)
    assert terminal_fault({**p,'source_impedance_percent':5,'source_xr':p['transformer_xr']})['prospective_rms_a']==pytest.approx(a['prospective_rms_a']/2)
    for bad in (0,-1,float('nan'),float('inf')):
        with pytest.raises(ValueError):core.Settings(impedance_percent=bad)


def test_short_circuit_uses_impedance_and_demand_reduction_does_not_remove_fault():
    s=core.create_state('test');s['inputs']['protection_enabled']=False
    s['inputs']['phase_imbalance_percent']=40
    core.inject(s,'short_circuit');fault=terminal_fault(s['settings'])
    assert s['telemetry']['secondary_current']==pytest.approx(fault['prospective_rms_a'])
    assert core.reduce_demand(s,100)['secondary_current']==pytest.approx(fault['prospective_rms_a'])
    assert s['telemetry']['secondary_voltage']==0
    assert s['telemetry']['phase_current_a']==s['telemetry']['phase_current_c']
    assert s['telemetry']['phase_imbalance_percent']==0


def test_pressure_warning_hysteresis_stays_latched_until_release(monkeypatch):
    s=core.create_state('pressure-hysteresis');s['inputs']['protection_enabled']=False
    for value,expected in [(31,True),(28,True),(27,True),(24,False),(28,False)]:
        monkeypatch.setattr(core,'pressure_signal',lambda _:dict(pressure_kpa=value,pressure_rate_kpa_s=0,pressure_quality='simulated'))
        core.evaluate(s,5)
        assert any(a['code']=='tank_pressure' for a in s['analysis']['alerts'])==expected


def test_pressure_is_distinct_from_gas_and_logs_appropriate_actions():
    s=core.create_state('pressure');core.inject(s,'pressure');s['running']=True
    core.advance(s,20)
    assert s['breaker']=='OPEN'
    assert any(a['code']=='tank_pressure' for a in s['analysis']['alerts'])
    assert any('pressure' in n.lower() for n in s['analysis']['maintenance'])
    assert s['telemetry']['pressure_quality']=='simulated'
    g=core.create_state('gas');core.inject(g,'gas')
    assert g['telemetry']['pressure_kpa']==5
    assert not any(a['code']=='tank_pressure' for a in g['analysis']['alerts'])
    core.inject(g,'pressure_sensor')
    assert g['telemetry']['pressure_kpa'] is None
    assert any(a['code']=='pressure_sensor' for a in g['analysis']['alerts'])


def test_prototype_cannot_assert_pressure():
    with pytest.raises(ValueError):
        core.Telemetry(timestamp=datetime.now(timezone.utc),source='prototype',transformer_id='BENCH-001',temperature_kind='surface',pressure_kpa=5)


@pytest.mark.parametrize('kind',diagnostics.CLASSES)
def test_electrical_observer_uses_signals_not_labels(kind):
    rows,context,_=diagnostics.generate(551,kind)
    result=diagnostics.assess(rows,context)
    assert result['classification']==kind
    lied=[{**r,'fault':'normal','scenario':'normal','future_fault':'normal'} for r in rows]
    assert diagnostics.assess(lied,context)==result
    if kind in ('inrush','external_fault','suspected_internal_fault'):
        assert diagnostics.assess(rows,{**context,'independent_currents':False})['abstained']


def test_blind_electrical_result_freezes_before_reveal(client):
    c=client.post('/api/halo/twin/challenges',json={'request_id':'electrical-blind-test','domain':'electrical'},headers=OP).json()
    assert 'truth' not in c and 'reveal' not in c and 'seed' not in c
    path='/api/halo/twin/challenges/'+c['id']
    assert client.post(path+'/reveal',json={},headers=OP).status_code==409
    frozen=client.post(path+'/assess',json={},headers=OP).json()['assessment']
    assert client.post(path+'/assess',json={},headers=OP).json()['assessment']==frozen
    reveal=client.post(path+'/reveal',json={},headers=OP).json()
    assert reveal['commitment_verified']
    assert client.get(path).json()['assessment']==frozen


def test_paired_thermal_study_preserves_source_and_differs_only_in_initial_state(client):
    s=new_run(client);before=deepcopy(store.get('twin_run',s['id']))
    r=client.post('/api/halo/twin/runs/'+s['id']+'/thermal-pair',json={'revision':s['revision']},headers=OP)
    assert r.status_code==200,r.text
    pair=r.json();assert pair['cases'][0]['forecast']['peak_c']<pair['cases'][1]['forecast']['peak_c']
    assert store.get('twin_run',s['id'])==before
    assert len(store.records('twin_thermal_pair'))==1


def fill_frames(count):
    device=bench.config().device_id;start=datetime.now(timezone.utc)-timedelta(hours=2)
    with store.connection() as db:
        for n in range(count):
            at=(start+timedelta(seconds=n)).isoformat()
            value=Frame(device_id=device,boot_id='report-test',sequence=n,uptime_ms=n*1000,timestamp=at,
                        primary_v=240,secondary_v=12,current_a=0,surface_c=30).model_dump(mode='json')
            db.execute('INSERT INTO halo_frames(device_id,boot_id,sequence,timestamp,received_at,content) VALUES(?,?,?,?,?,?)',
                       (device,'report-test',n,at,at,json.dumps(value)))
    for n in range(125):store.event('BENCH-001','test_event',{'number':n})


def test_pdf_contains_full_retained_prototype_history_beyond_ui_limits(client):
    fill_frames(625)
    r=client.post('/api/halo/twin/reports/BENCH-001/pdf',json={},headers=OP)
    assert r.status_code==200,r.text[:300]
    assert r.content.startswith(b'%PDF')
    doc=PdfReader(BytesIO(r.content));text='\n'.join(p.extract_text() for p in doc.pages)
    assert '625 retained readings' in text and '125 events' in text
    assert 'T-625' in text and 'T-1' in text
    snap=client.get('/api/halo/twin/reports/'+r.headers['x-report-sha256']+'/snapshot').json()
    assert len(snap['readings'])==625 and len(snap['events'])==125
    assert all(x['loading_percent'] is None for x in snap['readings'])
    assert snap['display_history']==[]


def test_pdf_time_range_and_industrial_reports(client):
    s=new_run(client)
    r=client.post('/api/halo/twin/reports/'+s['id']+'/pdf',json={'revision':s['revision']},headers=OP)
    assert r.status_code==200,r.text[:200]
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    assert 'Industrial transformer report' in text
    assert 'Prospective' not in text or 'RMS' in text
    bad=client.post('/api/halo/twin/reports/'+s['id']+'/pdf',json={'revision':s['revision']+1},headers=OP)
    assert bad.status_code==409
    empty=report_snapshot(s['id'],PDFRequest(start=datetime.now(timezone.utc)+timedelta(days=1)))
    assert empty['readings']==[] and empty['coverage']['records']==0


def test_snapshot_does_not_change_when_live_records_change(client):
    s=new_run(client);snapshot=report_snapshot(s['id'],PDFRequest());before=deepcopy(snapshot)
    newer=store.get('twin_run',s['id']);newer['history'][0]['secondary_current']=12345;store.put('twin_run',s['id'],newer)
    assert snapshot==before


def test_evaluation_reports_denominators_and_abstention():
    r=diagnostics.evaluate(range(3000,3002))
    assert r['count']==14 and r['normal_event_denominator']==2
    assert r['coverage']<1
    assert sum(sum(row.values()) for row in r['confusion_matrix'].values())==14
