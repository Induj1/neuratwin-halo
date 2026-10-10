from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from neuratwin import lifetime_scenario as life, halo_store as store, twin_core as core
from neuratwin.app import app
from neuratwin.halo_api import LOCAL_TOKEN
from neuratwin.briefing_api import PDFRequest, report_snapshot

OP={'Authorization':'Bearer '+LOCAL_TOKEN}


def observations(temperature=50,current=1,voltage=12,count=31):
    start=datetime(2026,10,10,tzinfo=timezone.utc)
    return [dict(timestamp=(start+timedelta(seconds=2*i)).isoformat(),sample_key=str(i),boot_id='test',
        temperature_c=temperature,current_a=current,voltage_v=voltage,current_source='frontend_estimated',quality='live') for i in range(count)]


def assess(rows,**kwargs):
    return life.assess(rows,life.Assumptions(**kwargs),mode='prototype',source_status='live')


def test_hotter_heavier_exposure_reduces_life_and_increases_risk():
    cool=assess(observations(35,.6));hot=assess(observations(65,1.4))
    assert hot['failure_probability']>cool['failure_probability']
    assert hot['remaining_life_years']<cool['remaining_life_years']
    assert hot['condition_score']<cool['condition_score']
    assert hot['minutes_to_limit']==0
    assert cool['limit_state']=='no_crossing'


def test_survival_probability_and_conditional_median_match_closed_form_at_equilibrium():
    a=life.Assumptions(ambient_c=30,rated_rise_c=10,temperature_offset_c=20,reference_temperature_c=60)
    rows=observations(40,1,count=1)
    r=life.assess(rows,a,mode='prototype',source_status='live')
    assert r['projected_steady_ageing_rate']==1
    h=a.risk_horizon_days/365.25
    expected=1-math.exp(-(((5+h)/20)**3-(5/20)**3))
    assert r['failure_probability']==pytest.approx(expected)
    median=(5**3+math.log(2)*20**3)**(1/3)-5
    assert r['remaining_life_years']==pytest.approx(median)


def test_repeated_export_does_not_accumulate_age_or_mutate_input():
    rows=observations();copy=deepcopy(rows)
    first=assess(rows);second=assess(rows+rows)
    assert first==second
    assert rows==copy
    assert first['observations']['integrated_seconds']==60


def test_missing_channels_and_gaps_do_not_become_healthy_or_ageing_exposure():
    rows=observations();rows[-1]['current_a']=None
    r=assess(rows);assert not r['available'] and r['condition_score'] is None
    assert r['failure_probability'] is None
    rows=observations(count=2);rows[1]['timestamp']='2026-10-11T00:00:00+00:00'
    r=assess(rows);assert r['observations']['integrated_seconds']==0
    assert r['observations']['observed_equivalent_age_hours']==0
    assert r['observations']['skipped_gap_seconds']==86400


def test_peak_and_mean_square_exposure_are_retained():
    rows=observations(current=0,count=3);rows[1]['current_a']=2
    r=assess(rows)
    assert r['observations']['recent_averages']['current_a']==pytest.approx(math.sqrt(2))
    assert r['observations']['recent_peaks']['current_a']==2
    assert r['observations']['recent_overload_seconds']==2
    assert r['condition_components']['loading']['stress']==100


def test_fault_domain_holds_and_horizon_risk_monotonicity():
    r=assess(observations(current=20));assert r['condition_score'] is not None
    assert not r['available'] and r['failure_probability'] is None
    normal=assess(observations());p=[v['probability'] for v in normal['risk_curve']]
    assert p==sorted(p) and p[0]==0 and all(0<=x<=1 for x in p)


def test_reference_age_changes_risk_and_remaining_life_without_changing_readings():
    rows=observations();young=assess(rows,initial_equivalent_age_years=1);old=assess(rows,initial_equivalent_age_years=15)
    assert old['failure_probability']>young['failure_probability']
    assert old['remaining_life_years']<young['remaining_life_years']
    assert old['observations']==young['observations']


def test_temperature_limit_crossing_is_analytic_and_unreachable_limit_is_explicit():
    rows=observations(35,1)
    r=assess(rows,limit_temperature_c=50)
    assert r['minutes_to_limit']==pytest.approx(-15*math.log((50-55)/(35-55)))
    assert assess(rows,limit_temperature_c=60)['limit_state']=='no_crossing'
    with pytest.raises(ValueError):life.Assumptions(ambient_c=40,limit_temperature_c=35)


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('NEURATWIN_DB',str(tmp_path/'lifetime.sqlite3'))
    monkeypatch.setenv('HALO_STORAGE_BACKEND','sqlite');monkeypatch.setenv('HALO_ESP32_URL','')
    monkeypatch.setenv('HALO_ALLOW_CONTROL','0')
    with TestClient(app) as c:yield c


def display_sample():
    channels={k:dict(value=v,raw=0 if 'current' in k else v,unit=unit,source='frontend_estimated' if 'current' in k else 'measured',method='fixture',quality='live') for k,v,unit in [('primary_voltage',230,'V'),('secondary_voltage',12,'V'),('primary_current',.03,'A'),('secondary_current',.6,'A'),('surface_temperature',40,'C')]}
    return dict(timestamp='2026-10-10T00:00:00Z',device_id='HALO-ESP32',boot_id='test',sequence=1,version='prototype-display-1',quality='live',
        live=True,probe_valid=True,channels=channels,loading_percent=60,demo_health=100,demo_health_version='current-only-1',scope='Test captured display')


def test_prototype_uses_existing_display_current_and_preserves_stale_status(client):
    empty=display_sample();empty.update(timestamp=None,live=False,loading_percent=None,demo_health=None)
    waiting=client.post('/api/halo/twin/lifetime/BENCH-001',headers=OP,json={'display_current':empty}).json()
    assert waiting['source_status']=='unavailable' and not waiting['available']
    sample=display_sample();r=client.post('/api/halo/twin/lifetime/BENCH-001',headers=OP,json={'display_current':sample})
    assert r.status_code==200,r.text
    result=r.json();assert result['available']
    assert result['observations']['recent_averages']['current_a']==.6
    assert result['current_sources']==['frontend_estimated']
    sample.update(live=False,quality='stale',loading_percent=None,demo_health=None)
    sample['channels']['surface_temperature']['value']=None
    result=client.post('/api/halo/twin/lifetime/BENCH-001',headers=OP,json={'display_current':sample}).json()
    assert result['source_status']=='cached' and result['available']
    sample['probe_valid']=False
    assert not client.post('/api/halo/twin/lifetime/BENCH-001',headers=OP,json={'display_current':sample}).json()['available']


def test_industrial_scenario_is_readonly_revision_bound_and_in_pdf(client):
    s=client.post('/api/halo/twin/runs',headers=OP,json={'request_id':'lifetime-run-test'}).json()
    before=deepcopy(store.get('twin_run',s['id']));path='/api/halo/twin/lifetime/'+s['id']
    r=client.post(path,headers=OP,json={'revision':s['revision']})
    assert r.status_code==200,r.text
    assert r.json()['available'] and r.json()['assumptions']['temperature_offset_c']==0
    assert store.get('twin_run',s['id'])==before
    assert client.post(path,headers=OP,json={'revision':s['revision']+1}).status_code==409
    snap=report_snapshot(s['id'],PDFRequest(lifetime_assumptions=life.defaults('industrial',s['settings'])))
    assert snap['assessment']['lifetime_scenario_at_export']==r.json()
    pdf=client.post('/api/halo/twin/reports/'+s['id']+'/pdf',headers=OP,json={'revision':s['revision']})
    assert pdf.status_code==200,pdf.text[:200]
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert 'Lifetime scenario at export' in text and 'Failure probability' in text


def test_prototype_pdf_and_preview_share_assumptions_and_inputs(client):
    sample=display_sample();a=life.Assumptions(initial_equivalent_age_years=12)
    preview=client.post('/api/halo/twin/lifetime/BENCH-001',headers=OP,json={'assumptions':a.model_dump(),'display_current':sample}).json()
    snapshot=report_snapshot('BENCH-001',PDFRequest(display_current=sample,lifetime_assumptions=a))
    assert snapshot['assessment']['lifetime_scenario_at_export']==preview
