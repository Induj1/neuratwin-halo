"""Readable job-card PDF with complete frozen forecast and observation appendices."""
from io import BytesIO
import base64
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape,A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle,PageBreak,Image
from . import halo_store as store, cloud
from .maintenance_model import unique_rows
from .twin_studies import digest
from .storage import now
from .pdf_report import chart


def render(job):
    out=BytesIO();styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='JobCell',fontName='Helvetica',fontSize=8,leading=11,wordWrap='CJK'))
    def text(v):
        if v is None:return 'Unavailable'
        if isinstance(v,float):return f'{v:.5g}'
        return str(v)
    def p(v,style='BodyText'):return Paragraph(escape(text(v)).replace('\n','<br/>'),styles[style])
    def table(headers,rows,widths=None):
        value=LongTable([[p(h,'JobCell') for h in headers]]+[[p(v,'JobCell') for v in row] for row in rows],colWidths=widths or [735/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
        value.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#bfc4be')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#eaf2ec')]),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6)]));return value
    d=job['decision'];v=job.get('verification');a=job.get('action');origin=d['origin'];profile=d['profile']
    story=[p('NeuraTwin Halo | Maintenance job card','Title'),p(job['title'],'Heading1'),
        table(['Asset / mode','Owner / status','Recorded'],[[job['asset_id']+' / '+job['mode'],job['owner']+' / '+job['status'].replace('_',' '),job['created_at']]]),Spacer(1,12),
        p(d['recommendation'],'Heading2'),p(d['uncertainty_action']),
        p(f"Source: {d['channel']}; current: {origin['current_source']}. Model revision {job['profile_revision']} ({d['version']})."),
        p(d['scope']),p('Acceptance: below '+text(job['acceptance']['temperature_limit_c'])+' C for '+text(job['acceptance']['stable_minutes'])+' uninterrupted comparable minutes.'),
        p('Frozen model assumptions','Heading2'),table(['Parameter','Value'],[[k.replace('_',' '),val] for k,val in profile.items()],[270,465]),
        p('Model provenance: '+d['profile_provenance']),p('Input SHA-256: '+d['input_sha256']),
        p('Recorded findings and action','Heading2'),p(job['findings'].get('note') or 'No findings recorded.'),
        p('Operator reports corrective action completed: '+str(job['findings'].get('issue_resolved',False))),
        p(a['note'] if a else 'No action recorded.'),p(('Follow-up forecast frozen at '+a['recorded_at']+', model revision '+str(a['profile_revision'])) if a else '')]
    if v:
        story.extend([p(v['outcome'].replace('_',' ').capitalize(),'Heading2'),p(v['reason']),p(v['scope']),
            table(['Comparable minutes','Forecast MAE C','Excluded readings','Gap detected'],[[v.get('coverage_minutes'),v.get('mae_c'),len(v.get('excluded',[])),v.get('gap_detected')]])])
    story.extend([PageBreak(),p('Forecasts and decision uncertainty','Heading1'),
        chart([{'temperature':r['temperature_c']} for r in d['forecast']],'temperature',d['channel']+' forecast','C'),
        table(['Cooling','Rise factor','Peak C','First crossing min','Minutes above limit','Reduction %'],[[s['cooling'],s['rise_scale'],s['peak_c'],s['first_crossing_min'],s['minutes_at_or_above_limit'],s['reduction_percent']] for s in d['scenarios']]),
        p(d['interval_kind']),p('Measurement cost comparison','Heading2'),
        table(['Measurement','Entered cost INR','Optimistic benefit bound INR','Assessment'],[[s['name'],s['total_cost'],s['maximum_avoidable_cost'],s['assessment']] for s in d['measurements']]),
        p('Perfect resolution of one scenario parameter is assumed; remaining uncertainty persists. No probabilities, expected savings or reliability improvement are established.'),
        table(['Decision / cost assumption','Recorded value'],[[k.replace('_',' '),val] for k,val in d['options'].items()],[270,465])])
    if a:story.extend([p('Frozen follow-up profile','Heading2'),table(['Parameter','Value'],[[k.replace('_',' '),val] for k,val in a['profile'].items()],[270,465]),p('Follow-up input SHA-256: '+a['input_sha256'])])
    story.extend([PageBreak(),p('Complete forecast appendix','Heading1')])
    after={r['minute']:r['temperature_c'] for r in d['after_forecast']} if d['robust_reduction_percent'] is not None else {}
    follow={r['minute']:r['temperature_c'] for r in a['forecast']} if a else {}
    minutes=sorted({r['minute'] for r in d['forecast']}|set(follow));before={r['minute']:r['temperature_c'] for r in d['forecast']}
    story.append(table(['Minutes after respective origin','Original loading C','Recommended loading C','Post-action frozen forecast C'],[[minute,before.get(minute),after.get(minute),follow.get(minute)] for minute in minutes]))
    rows=unique_rows(job['initial_readings']+job['observations']+[r for cycle in job.get('followup_cycles',[]) for r in cycle['observations']])
    story.extend([PageBreak(),p('Complete supplied readings','Heading1'),p('Initial acquisition and retained follow-up, with duplicate sample identifiers removed. Physical currents retain browser provenance; these are not raw acquisition certification.'),
        p('Primary current provenance: '+', '.join(sorted({r.get('primary_current_source','unavailable') for r in rows}))),
        table(['Timestamp UTC','Primary V','Primary A','Secondary V','Secondary A','Temperature C','Current source'],[[r['timestamp'],r.get('primary_voltage_v'),r.get('primary_current_a'),r['voltage_v'],r['current_a'],r['temperature_c'],r['current_source']] for r in rows],[165,75,75,75,75,75,195])])
    if v:
        story.extend([p('Compared observations','Heading2'),table(['Timestamp UTC','Elapsed min','Frozen prediction C','Observed C'],[[r['timestamp'],r['minute'],r['predicted_c'],r['observed_c']] for r in v['points']])])
        if v.get('excluded'):story.append(table(['Excluded timestamp','Reason'],[[r['timestamp'],r['reason']] for r in v['excluded']]))
    story.extend([PageBreak(),p('Maintenance history and audit','Heading1')])
    prior=[[r['title'],r['status'],r['findings'].get('note',''),r.get('verification')] for r in job['previous_maintenance']]
    if prior:story.append(table(['Previous job','Status','Findings','Verification'],prior))
    else:story.append(p('No previous maintenance jobs were recorded at creation.'))
    for inspection in job['prior_inspections']:story.append(p('Prior inspection: '+inspection.get('note','')))
    for work in job['prior_work']:story.append(p('Prior work order: '+work.get('title','')+' / '+work.get('status','')))
    for cycle in job.get('followup_cycles',[]):
        story.extend([p('Earlier follow-up cycle','Heading2'),p(cycle['action']['note']),p('Forecast origin: '+cycle['action']['origin']['timestamp']),
            table(['Parameter','Frozen value'],[[k.replace('_',' '),val] for k,val in cycle['action']['profile'].items()],[270,465]),
            table(['Minute','Frozen temperature C'],[[r['minute'],r['temperature_c']] for r in cycle['action']['forecast']]),
            p('Outcome: '+(cycle.get('verification') or {}).get('outcome','Not verified'))])
    story.append(table(['Time','Event','Note / outcome'],[[r['time'],r['event'],r.get('note','')+' '+r.get('verification',{}).get('outcome','')] for r in job['trail']],[170,150,415]))
    for photo in job['findings'].get('photos',[]):
        story.extend([p('Technician photo','Heading2'),p('Captured record '+photo['created_at']+' | SHA-256 '+photo['sha256'])])
        saved=store.get('attachment',photo['id'])
        if saved:
            data=cloud.download(saved['object_path']) if saved.get('object_path') else base64.b64decode(saved['data'])
            picture=Image(BytesIO(data));scale=min(350/picture.imageWidth,260/picture.imageHeight,1);picture.drawWidth=picture.imageWidth*scale;picture.drawHeight=picture.imageHeight*scale;story.append(picture)
        else:story.append(p('Stored photo bytes are unavailable.'))
    story.extend([Spacer(1,12),p('Exported '+now()),p('Frozen job record SHA-256: '+digest(job)),p('Digest detects changes relative to this record; it is not a signature, calibration certificate or proof of repair.')])
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.drawString(50,22,'NeuraTwin Halo | '+job['mode']+' | '+str(doc.page));canvas.restoreState()
    SimpleDocTemplate(out,pagesize=landscape(A4),leftMargin=50,rightMargin=50,topMargin=35,bottomMargin=38).build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()
