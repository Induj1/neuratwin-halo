"""Self-contained PDF from a frozen report snapshot; no network reads in rendering."""
from io import BytesIO
import json
import math
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, PageBreak, KeepTogether
from reportlab.graphics.shapes import Drawing, Line, String, PolyLine, Circle


def chart(rows,key,label,unit):
    d=Drawing(345,155);valid=[(i,r.get(key)) for i,r in enumerate(rows) if isinstance(r.get(key),(int,float)) and math.isfinite(r[key])]
    d.add(String(8,139,label+' ('+unit+')',fontName='Helvetica-Bold',fontSize=10,fillColor=colors.HexColor('#214b40')))
    if not valid:d.add(String(20,70,'Unavailable in selected records',fontSize=9));return d
    low=min(v for _,v in valid);high=max(v for _,v in valid);pad=max(.1,(high-low)*.1);low-=pad;high+=pad
    x=lambda i:48+280*i/max(1,len(rows)-1)
    y=lambda v:25+(v-low)/(high-low)*98
    for k in range(4):
        v=low+(high-low)*k/3;yy=y(v)
        d.add(Line(48,yy,328,yy,strokeColor=colors.HexColor('#d9e3df')))
        d.add(String(2,yy-3,f'{v:.2f}',fontSize=7))
    # Every selected point is retained; missing observations break paths.
    path=[]
    for i,r in enumerate(rows):
        v=r.get(key)
        if not isinstance(v,(int,float)) or not math.isfinite(v):
            if len(path)>2:d.add(PolyLine(path,strokeColor=colors.HexColor('#28795e'),strokeWidth=1.3))
            path=[];continue
        path.extend((x(i),y(v)))
    if len(path)>2:d.add(PolyLine(path,strokeColor=colors.HexColor('#28795e'),strokeWidth=1.3))
    i,v=valid[-1];d.add(Circle(x(i),y(v),2,fillColor=colors.HexColor('#28795e'),strokeWidth=0))
    d.add(String(48,8,'First selected sample',fontSize=7));d.add(String(248,8,'Last selected sample',fontSize=7))
    return d


def render(snapshot):
    buf=BytesIO();styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CellSmall',fontName='Helvetica',fontSize=7,leading=10,wordWrap='CJK'))
    styles.add(ParagraphStyle(name='ReportBody',fontName='Helvetica',fontSize=9,leading=13,spaceAfter=7))
    def text(value):
        if value is None:return 'Unavailable'
        if isinstance(value,bool):return 'Yes' if value else 'No'
        if isinstance(value,float):return f'{value:.5g}'
        return str(value)
    def label(key):return str(key).replace('_',' ').strip().capitalize()
    def para(value,style='ReportBody'):return Paragraph(escape(text(value)).replace('\n','<br/>'),styles[style])
    def table(headers,rows,widths):
        content=[[para(h,'CellSmall') for h in headers]]+[[para(v,'CellSmall') for v in row] for row in rows]
        t=LongTable(content,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8f0ec')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#8bad9e')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f8f7')]),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]));return t
    def fields(value):
        """Readable nested records, with sampled trajectories in repeated-header tables."""
        if not isinstance(value,dict):return [para(value)]
        output=[]
        simple=[(label(k),v) for k,v in value.items() if not isinstance(v,(dict,list))]
        if simple:output.append(table(['Field','Recorded value'],simple,[170,565]))
        for key,item in value.items():
            if not isinstance(item,(dict,list)):continue
            output.append(para(label(key),'Heading3'))
            if key=='physics_and_protection' and isinstance(item,dict):
                output.extend(fields({k:v for k,v in item.items() if k not in ('curves','mitigated','history','matrix','matrix_columns')}))
                if item.get('available'):
                    output.append(para('Virtual model forecasts - model minutes, constant future loading','Heading3'))
                    after={v['minute']:v for v in item['mitigated']}
                    output.append(table(['Model min','Oil C - continue','Oil C - reduced','kPa gauge - continue','kPa gauge - reduced'],
                        [[v['minute'],v['oil_c'],after[v['minute']]['oil_c'],v['pressure_kpa'],after[v['minute']]['pressure_kpa']] for v in item['curves']],[75,165,165,165,165]))
                    output.append(para('Integrated virtual model history','Heading3'))
                    keys=['timestamp','minute','oil_c','bulk_oil_c','pressure_kpa','level_percent','gas_ml','valid']
                    output.append(table([label(k) for k in keys],[[v.get(k) for k in keys] for v in item['history']],[150,80,80,85,85,85,85,85]))
                    output.append(para('Source matrix - current provenance retained','Heading3'))
                    output.append(table(item['matrix_columns'],item['matrix'],[200,110,110,315]))
            elif isinstance(item,dict):output.extend(fields(item))
            elif not item:output.append(para('None recorded.'))
            elif all(isinstance(v,dict) for v in item):
                keys=list(dict.fromkeys(k for row in item for k in row))
                if len(keys)<=10 and all(not isinstance(v,(list,dict)) for row in item for v in row.values()):
                    output.append(table([label(k) for k in keys],[[row.get(k) for k in keys] for row in item],[735/len(keys)]*len(keys)))
                else:
                    for n,row in enumerate(item):
                        output.append(para('Record '+str(n+1),'Heading4'));output.extend(fields(row))
            else:output.extend(para(v) for v in item)
        return output
    interval=snapshot['requested_interval'];coverage=snapshot['coverage']
    interval_text=(text(interval['start'])+' to '+text(interval['end'])) if any(interval.values()) else 'All retained records'
    coverage_text=(text(coverage['first'])+' to '+text(coverage['last'])) if coverage['records'] else 'No retained readings in this interval'
    story=[Paragraph('NeuraTwin Halo',styles['Title']),para(snapshot['mode'].title()+' transformer report','Heading2'),
        para('Asset / run: '+snapshot['asset_id']),para('Generated: '+snapshot['generated_at']+' | Timezone: UTC'),
        para('Requested interval: '+interval_text),para('Recorded coverage: '+coverage_text),
        para(f"{len(snapshot['readings'])} retained readings | {len(snapshot['events'])} events | {len(snapshot['display_history'])} captured browser display samples"),
        para('Snapshot SHA-256: '+snapshot['sha256']),para('Sources and scope','Heading2')]
    story.extend(para(note) for note in snapshot['notes'])
    story.append(para('Configuration and calculation versions','Heading2'))
    story.extend(fields(snapshot['configuration']))
    story.append(para('Assessment at snapshot','Heading2'))
    story.extend(fields(snapshot['assessment']))
    rows=snapshot['readings']
    story.append(PageBreak());story.append(para('Recorded response','Heading1'))
    charts=[chart(rows,k,l,u) for k,l,u in [('primary_voltage','Primary voltage','V'),('secondary_voltage','Secondary voltage','V'),
        ('primary_current','Raw primary current','A'),('secondary_current','Raw secondary current','A'),('transformer_temperature','Temperature','C'),('loading_percent','Recorded loading','%')]
        + ([('pressure_kpa','Pressure scenario','kPa gauge')] if snapshot['mode']=='industrial' else [])]
    for i in range(0,len(charts),2):story.append(KeepTogether([LongTable([charts[i:i+2]],colWidths=[365,365]),Spacer(1,8)]))
    story.append(PageBreak());story.append(para('Readings appendix - complete selected records','Heading1'))
    columns=[('sample_id','Sample'),('timestamp','Timestamp UTC'),('primary_voltage','Primary V'),('primary_current','Raw primary A'),
        ('secondary_voltage','Secondary V'),('secondary_current','Raw secondary A'),('transformer_temperature','Temperature C'),('loading_percent','Loading %'),('quality','Quality')]
    if rows:story.append(table([h for _,h in columns],[[r.get(k) for k,_ in columns] for r in rows],[65,130,65,65,65,65,70,60,100]))
    else:story.append(para('No retained readings in the selected interval.'))
    if snapshot['mode']=='industrial':
        story.append(PageBreak());story.append(para('Industrial channels - same selected records','Heading1'))
        cols=[('sample_id','Sample'),('oil_temperature','Oil C'),('hotspot_temperature','Hot-spot C'),('phase_current_a','Phase A'),('phase_current_b','Phase B'),('phase_current_c','Phase C'),('pressure_kpa','kPa gauge'),('pressure_rate_kpa_s','kPa/s'),('health_index','Recorded condition')]
        if rows:story.append(table([h for _,h in cols],[[r.get(k) for k,_ in cols] for r in rows],[65,65,70,70,70,70,70,70,110]))
        story.append(para('Additional industrial observations','Heading2'))
        cols=[('sample_id','Sample'),('ambient_temperature','Ambient C'),('neutral_current','Neutral A'),('phase_imbalance_percent','Imbalance %'),('max_phase_loading_percent','Peak phase %'),('thermal_loading_percent','Thermal loading %'),('oil_level_percent','Oil level %'),('breaker','Simulated breaker'),('pressure_quality','Pressure source')]
        if rows:story.append(table([h for _,h in cols],[[r.get(k) for k,_ in cols] for r in rows],[65,70,70,80,85,85,70,80,85]))
    else:
        story.append(PageBreak());story.append(para('Acquisition context - same selected records','Heading1'))
        cols=[('sample_id','Sample'),('boot_id','Board boot'),('sequence','Sequence'),('ambient_temperature','Ambient C'),('ambient_source','Ambient source'),('relay_states','Reported relay commands'),('hardware_config_status','Configuration status')]
        if rows:story.append(table([h for _,h in cols],[[r.get(k) for k,_ in cols] for r in rows],[65,120,65,75,100,160,105]))
        story.append(para('Relay command states do not establish verified contact state.','ReportBody'))
        story.append(para('Configuration references and raw acquisition channels','Heading2'))
        cols=[('sample_id','Sample'),('config_id','Configuration reference'),('calibration_id','Calibration reference'),('raw_channels','Raw channels (as reported)')]
        if rows:story.append(table([h for _,h in cols],[[r.get(k) for k,_ in cols] for r in rows],[65,205,135,285]))
        story.append(PageBreak());story.append(para('Captured browser display history','Heading1'))
        story.append(para('Bounded browser samples. Values are the captured display results; raw acquisition remains separate.'))
        captured=snapshot['display_history']
        if captured:
            story.append(table(['Time UTC','Primary V','Primary A','Secondary V','Secondary A','Surface C','Loading %','Demo score','Current sources / quality'],
                [[r['timestamp'],r['channels']['primary_voltage']['value'],r['channels']['primary_current']['value'],r['channels']['secondary_voltage']['value'],r['channels']['secondary_current']['value'],r['channels']['surface_temperature']['value'],r['loading_percent'],r['demo_health'],r['channels']['primary_current']['source']+' / '+r['channels']['secondary_current']['source']+' / '+r['quality']] for r in captured],
                [130,55,60,65,65,60,60,60,170]))
        else:story.append(para('No browser display history supplied.'))
        separated=[r for r in captured if r.get('version')=='prototype-display-2']
        if separated:
            story.append(para('Measured and estimated currents - separate series','Heading2'))
            story.append(para('Estimates use the declared resistive load bank and ideal primary power balance. They never replace measured zero. Raw values may be stale, invalid or firmware-calculated; consult each channel basis.'))
            story.append(table(['Time UTC','Measured primary A','Estimated primary A','Measured secondary A','Estimated secondary A','Measured loading %','Estimated loading %','Disagreement'],
                [[r['timestamp'],r['channels']['primary_current']['value'],r['estimates']['primary_current']['value'],r['channels']['secondary_current']['value'],r['estimates']['secondary_current']['value'],r['loading_percent'],r['estimated_loading_percent'],r['disagreement']] for r in separated],
                [130,80,80,80,80,80,80,95]))
    for title,values in [('Current browser display snapshot',[snapshot['display_current']] if snapshot['display_current'] else []),
                         ('Events',snapshot['events']),
                         ('Forecasts, comparisons, diagnoses and work orders',snapshot['decisions'])]:
        if values:story.append(PageBreak())
        story.append(para(title,'Heading1'))
        if not values:story.append(para('No retained records for this section.'))
        for value in values:
            story.extend(fields(value))
            story.append(Spacer(1,9))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#527063'))
        canvas.drawString(36,20,'NeuraTwin Halo | '+snapshot['mode']+' | '+snapshot['sha256'][:16])
        canvas.drawRightString(806,20,f'Page {doc.page}');canvas.restoreState()
    SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=36,leftMargin=36,topMargin=32,bottomMargin=34,
        title='NeuraTwin Halo '+snapshot['mode']+' report',author='Neura Rangers').build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()
