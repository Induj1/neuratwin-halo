"""Offline, printable case summary. The accompanying JSON retains full detail."""
from html import escape


def report_html(case):
    def text(value):
        return escape(str(value if value is not None else 'Unavailable'))

    def table(headers, rows):
        body=''.join('<tr>'+''.join('<td>'+text(v)+'</td>' for v in row)+'</tr>' for row in rows)
        return '<table><thead><tr>'+''.join('<th>'+text(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table>' if body else '<p class="empty">No record available for this asset.</p>'

    snap=case['snapshot']; records=case['records']; investigation=case['investigation']; ledger=case['ledger']
    sections=[]
    sections.append('<h2>01 · Measurement evidence</h2>'+table(['Channel','Reading','Unit','Source','Verification'],[
        [e['channel'],e['value'],e['unit'],e['source'],e.get('verification','Unverified')] for e in snap['evidence']]))
    sections.append('<h2>02 · Investigation</h2><p>'+text(investigation.get('reason') or investigation['method'])+'</p>'+
                    ''.join('<article><h3>'+text(c['title'])+'</h3><p>'+text(c['support'])+'</p><p><b>Next check:</b> '+text(c['check'])+'</p></article>' for c in investigation['hypotheses']))
    sections.append('<h2>03 · Intervention decisions</h2>'+table(['Record / source','Recommendation','Horizon','Assumptions'],[
        [p['id']+' / '+p['source'],(p.get('recommendation') or {}).get('label','No qualifying candidate'),str(p['horizon_min'])+' min',p['note']] for p in records['plan']]))
    forecast_rows=[]
    for f in records['forecast']:
        scores=[s for s in records['forecast_score'] if s['forecast_id']==f['id']]
        score=scores[0] if scores else None
        summary=score['all_observations'] if score else {}
        forecast_rows.append([f['id'],f['origin'],f['target'],str(f['horizon_min'])+' min',score['status'] if score else 'Not scored',summary.get('count'),summary.get('mae_c'),summary.get('persistence_mae_c')])
    sections.append('<h2>04 · Frozen forecasts and outcomes</h2>'+table(['Record','Origin','Measured target','Horizon','Status','Samples','MAE °C','Persistence °C'],forecast_rows))
    sections.append('<h2>05 · Rolling evaluation</h2>'+table(['Record','Source','Horizon min','Origins','Observations','Model MAE °C','Persistence MAE °C'],[
        [r['id'],r['source'],s['horizon_min'],s['origin_count'],s['observations'],s['mae_c'],s['persistence_mae_c']] for r in records['benchmark'] for s in r['summary']]))
    sections.append('<h2>06 · Acceptance observations</h2>'+table(['Reviewer / source','Instrument / calibration','Check','Reference','Observed','Unit','Absolute error %','Result','Response evidence'],[
        [r['reviewer']+' / '+r['source'],r['reference_instrument']+' / '+r['calibration_reference'],c['name'],c['reference'],c['observed'],c['unit'],c['absolute_error_pct'],c['status'],c.get('response_kind','not_observed')] for r in records['acceptance'] for c in r['checks']]))
    sections.append('<h2>07 · Condition and ageing</h2>'+table(['Indicator','Result'],[
        ['Operating-stress index',ledger['operating_index']],['Observed channels',f"{ledger['available_channels']} / {ledger['total_channels']}"],
        ['Conditional equivalent ageing hours',ledger.get('equivalent_hours')],['Actual remaining useful life','Unavailable']])+'<p>'+text(ledger['reason'])+'</p>')
    sections.append('<h2>08 · Reviewed laboratory evidence</h2>'+table(['Report / laboratory','Sample time','Evidence type','Analyte','Value','Unit','Laboratory flag','Reviewed notes'],[
        [r['report_reference']+' / '+r['laboratory'],r['sample_at'],r['evidence_type'],v['analyte'],v['value'],v['unit'],v['laboratory_flag'],r['note']] for r in records['lab_report'] for v in r['values']]))
    sections.append('<h2>09 · Maintenance trail</h2>'+table(['Incident','State','Source'],[
        [r['id'],r['state'],r.get('source','See case.json')] for r in case['maintenance']]))
    sections.append('<h2>Commissioning holds</h2>'+(''.join('<p>• '+text(h)+'</p>' for h in snap['holds']) or '<p>No physical commissioning clearance is implied by this study.</p>'))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NeuraTwin Halo · evidence case</title><style>'
            'body{font:15px/1.55 system-ui,sans-serif;margin:36px auto;padding:24px;max-width:1160px;color:#26353d;background:#fffef9}h1{font-size:40px;letter-spacing:-.04em;margin:10px 0}h2{font-size:23px;border-top:2px solid #c55b32;padding-top:20px;margin-top:40px}h3{font-size:18px}table{border-collapse:collapse;width:100%;font-size:12px;overflow-wrap:anywhere}td,th{text-align:left;vertical-align:top;border-bottom:1px solid #d9ddd8;padding:10px 8px}th{background:#ecebe3}article{padding:12px 0}button{background:#ae481f;color:white;border:0;padding:12px 20px;border-radius:6px;cursor:pointer}.eyebrow{font-size:12px;letter-spacing:.12em;color:#a44120}.context{background:#efece2;padding:18px}.empty{color:#69756f}@media print{body{margin:0;padding:0;font-size:11px}h1{font-size:30px}h2{break-after:avoid;font-size:18px}tr{break-inside:avoid}td,th{font-size:9px;padding:6px}button{display:none}@page{size:A4 landscape;margin:14mm}}'
            '</style></head><body><p class="eyebrow">NEURA RANGERS / CPRI TRACK 2 / EVIDENCE CASE</p><h1>NeuraTwin Halo</h1><p class="context"><b>'+text(snap['asset_id'])+'</b> · '+text(snap['source'])+'<br>Generated '+text(case['created_at'])+'<br>Observation '+text((snap.get('current') or {}).get('timestamp'))+'</p><button onclick="window.print()">Print / save PDF</button><p>Saved analysis and reviewer-entered evidence. Scenario results do not certify physical equipment. Hypotheses are not confirmed faults; predictions are conditional.</p>'+''.join(sections)+'<h2>Reproducibility and limits</h2><p>'+text(case['limitations'])+'</p><p>The accompanying case.json contains the full readings, model assumptions, hypothesis trace, frozen forecasts, scores and evidence references. manifest.json contains file checksums. Checksums detect changes against a retained manifest; they do not attest that measurements are true.</p></body></html>').encode('utf-8')
