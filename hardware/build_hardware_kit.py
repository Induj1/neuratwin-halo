from pathlib import Path
import csv
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'output' / 'pdf'
HARDWARE_DIR = ROOT / 'round2' / 'hardware'
OUT_DIR.mkdir(parents=True, exist_ok=True)
HARDWARE_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = OUT_DIR / 'neuratwin-hardware-instruction-kit.pdf'
MD_PATH = HARDWARE_DIR / 'NEURATWIN_HARDWARE_INSTRUCTION_KIT.md'
BOM_PATH = HARDWARE_DIR / 'bom.csv'
PINMAP_PATH = HARDWARE_DIR / 'pinmap.csv'

font_regular = 'Helvetica'
font_bold = 'Helvetica-Bold'
for family, path in [('Aptos', r'C:\Windows\Fonts\Aptos.ttf'), ('Aptos-Bold', r'C:\Windows\Fonts\Aptosbd.ttf')]:
    if Path(path).exists():
        pdfmetrics.registerFont(TTFont(family, path))
        if family == 'Aptos': font_regular = 'Aptos'
        else: font_bold = 'Aptos-Bold'

PAGE_W, PAGE_H = A4
INK = HexColor('#17221f'); PAPER = HexColor('#f3efe6'); PANEL = HexColor('#fffdf8')
WARM = HexColor('#e9dfd0'); ORANGE = HexColor('#c65e12'); ORANGE_DARK = HexColor('#96450d')
BLUE = HexColor('#2c6d7a'); MINT = HexColor('#5f876d'); RED = HexColor('#b94336')
MUTED = HexColor('#606760'); LINE = HexColor('#d5cfc4'); DARK = HexColor('#101714'); WHITE = colors.white

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='CoverKicker', fontName=font_bold, fontSize=9, leading=12, textColor=ORANGE, tracking=1.8, spaceAfter=12))
styles.add(ParagraphStyle(name='CoverTitle', fontName=font_bold, fontSize=33, leading=34, textColor=INK, spaceAfter=12))
styles.add(ParagraphStyle(name='CoverSub', fontName=font_regular, fontSize=13, leading=19, textColor=MUTED, spaceAfter=18))
styles.add(ParagraphStyle(name='H1x', fontName=font_bold, fontSize=22, leading=25, textColor=INK, spaceAfter=8))
styles.add(ParagraphStyle(name='H2x', fontName=font_bold, fontSize=14, leading=17, textColor=INK, spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name='H3x', fontName=font_bold, fontSize=10.5, leading=13, textColor=ORANGE_DARK, spaceBefore=5, spaceAfter=4))
styles.add(ParagraphStyle(name='Bodyx', fontName=font_regular, fontSize=9.2, leading=13.5, textColor=INK, spaceAfter=6))
styles.add(ParagraphStyle(name='BodySmall', fontName=font_regular, fontSize=8, leading=11, textColor=MUTED, spaceAfter=4))
styles.add(ParagraphStyle(name='SmallMono', fontName='Courier', fontSize=7.4, leading=10, textColor=INK))
styles.add(ParagraphStyle(name='TableHead', fontName=font_bold, fontSize=7.6, leading=9.5, textColor=WHITE))
styles.add(ParagraphStyle(name='TableCell', fontName=font_regular, fontSize=7.6, leading=10, textColor=INK))
styles.add(ParagraphStyle(name='TableCellSmall', fontName=font_regular, fontSize=7.1, leading=9.1, textColor=INK))
styles.add(ParagraphStyle(name='Callout', fontName=font_regular, fontSize=9.2, leading=13, textColor=INK))
styles.add(ParagraphStyle(name='StepNum', fontName=font_bold, fontSize=16, leading=18, textColor=ORANGE))

def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
def P(text, style='Bodyx'): return Paragraph(text, styles[style])
def bullet(text, style='Bodyx'): return P('&bull;&nbsp; ' + text, style)

def table(data, widths, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
    ts = [('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.35,LINE),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),('BACKGROUND',(0,0),(-1,0),INK if header else PANEL)]
    if header:
        ts += [('TEXTCOLOR',(0,0),(-1,0),WHITE),('FONTNAME',(0,0),(-1,0),font_bold)]
        if len(data) > 1: ts += [('ROWBACKGROUNDS',(0,1),(-1,-1),[PANEL,HexColor('#f7f2e9')])]
    t.setStyle(TableStyle(ts)); return t

class Diagram(Flowable):
    def __init__(self, kind, width=165*mm, height=62*mm):
        Flowable.__init__(self); self.kind=kind; self.width=width; self.height=height
    def box(self,c,x,y,w,h,title,sub,fill,accent=ORANGE,dark=False):
        c.setStrokeColor(accent); c.setLineWidth(.9); c.setFillColor(fill); c.roundRect(x,y,w,h,5,stroke=1,fill=1)
        c.setFillColor(WHITE if dark else INK); c.setFont(font_bold,8.5); c.drawString(x+8,y+h-14,title)
        c.setFillColor(HexColor('#d3ded7') if dark else MUTED); c.setFont(font_regular,6.6)
        for i,line in enumerate(sub.split('\n')[:3]): c.drawString(x+8,y+h-25-(i*9),line)
    def draw(self):
        c=self.canv; w,h=self.width,self.height; c.setFillColor(PAPER); c.roundRect(0,0,w,h,8,fill=1,stroke=0)
        if self.kind=='architecture':
            self.box(c,8,h-45,95,34,'SAFE BENCH','12/24 V isolated\ntransformer surrogate',WARM)
            self.box(c,122,h-45,95,34,'EDGEBOX X1','ESP32-S3 + sensor bus\nNFC + local buffer',INK,BLUE,True)
            self.box(c,236,h-45,95,34,'TWIN ENGINE','thermal state +\nquality + forecast',PANEL)
            self.box(c,350,h-45,95,34,'OPERATOR UI','overview + incident\n+ action comparison',PANEL,MINT)
            for label,x in [('3P V/I',14),('PT100',72),('vibration',126),('leak/level',198),('NFC',275)]:
                c.setFillColor(WHITE); c.setStrokeColor(LINE); c.roundRect(x,8,55,14,7,fill=1,stroke=1); c.setFillColor(MUTED); c.setFont('Courier',6.2); c.drawCentredString(x+27.5,13,label)
            c.setStrokeColor(ORANGE); c.setFillColor(ORANGE); c.setLineWidth(1.2)
            for x1,x2 in [(103,122),(217,236),(331,350)]: c.line(x1,h-28,x2,h-28); c.line(x2-4,h-31,x2,h-28); c.line(x2-4,h-25,x2,h-28)
            c.setFillColor(MUTED); c.setFont(font_regular,6.5)
            for x,label in [(55,'physical signals'),(169,'timestamped packet'),(283,'explained state'),(397,'maintenance action')]: c.drawCentredString(x,h-55,label)
        elif self.kind=='bench':
            c.setFillColor(DARK); c.setStrokeColor(ORANGE); c.roundRect(14,24,150,112,7,fill=1,stroke=1); c.setFillColor(WHITE); c.setFont(font_bold,9); c.drawString(24,120,'NEURATWIN EDGEBOX X1'); c.setFont('Courier',6.5); c.setFillColor(HexColor('#cbd6cf')); c.drawString(24,108,'IP65 ABS / DIN RAIL / 12 V SELV')
            self.box(c,24,73,58,24,'MCU','ESP32-S3',HexColor('#293b36'),MINT,True); self.box(c,91,73,58,24,'I/O','RS485 + SPI',HexColor('#293b36'),BLUE,True); self.box(c,24,39,58,24,'NFC','PN532',HexColor('#293b36'),ORANGE,True); self.box(c,91,39,58,24,'POWER','fuse + buck',HexColor('#293b36'),RED,True)
            c.setFillColor(WARM); c.setStrokeColor(ORANGE); c.roundRect(207,38,170,97,7,fill=1,stroke=1); c.setFillColor(INK); c.setFont(font_bold,9); c.drawString(219,119,'TABLETOP TRANSFORMER BAY'); c.setFillColor(MUTED); c.setFont(font_regular,7); c.drawString(219,106,'isolated low-voltage loop')
            c.setFillColor(HexColor('#786a57')); c.rect(248,57,56,38,fill=1,stroke=0); c.setFillColor(HexColor('#a58a62')); c.rect(267,95,18,28,fill=1,stroke=0); c.setStrokeColor(ORANGE); c.circle(276,78,28,stroke=1,fill=0)
            for label,x,y,col in [('PT100',225,48,RED),('PT100',307,48,RED),('ACCEL',322,82,BLUE),('FAN',224,91,MINT)]: c.setFillColor(col); c.circle(x,y,3,fill=1,stroke=0); c.setFillColor(MUTED); c.setFont('Courier',6); c.drawString(x+6,y-2,label)
            c.setStrokeColor(ORANGE); c.setLineWidth(1); c.line(164,87,207,87); c.line(203,84,207,87); c.line(203,90,207,87); c.setFillColor(MUTED); c.setFont(font_regular,6.5); c.drawString(171,94,'sensor harness')
        else:
            steps=[('1','SCAN','NFC tap\nloads asset'),('2','STRESS','knob / replay\nraises load'),('3','EXPLAIN','evidence +\ntrust score'),('4','ACT','fan / action\nchanges forecast'),('5','HAND OFF','work order\nwith proof')]; x=8; boxw=82
            for i,(num,title,sub) in enumerate(steps):
                self.box(c,x,37,boxw,52,f'{num}  {title}',sub,PANEL,[ORANGE,RED,BLUE,MINT,ORANGE][i])
                if i<len(steps)-1: c.setStrokeColor(ORANGE); c.setLineWidth(1); c.line(x+boxw+3,63,x+boxw+18,63); c.line(x+boxw+14,60,x+boxw+18,63); c.line(x+boxw+14,66,x+boxw+18,63)
                x += 101
            c.setFillColor(MUTED); c.setFont(font_regular,7); c.drawCentredString(w/2,20,'One coherent loop from measurement to accountable maintenance action')

class Rule(Flowable):
    def __init__(self,color=ORANGE,width=170*mm): Flowable.__init__(self); self.width=width; self.height=1; self.color=color
    def draw(self): self.canv.setStrokeColor(self.color); self.canv.setLineWidth(1.1); self.canv.line(0,0,self.width,0)

class HardwareDoc(BaseDocTemplate):
    def __init__(self,filename,**kwargs):
        BaseDocTemplate.__init__(self,filename,pagesize=A4,**kwargs)
        frame=Frame(17*mm,17*mm,PAGE_W-34*mm,PAGE_H-33*mm,id='normal',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        self.addPageTemplates([PageTemplate(id='all',frames=frame,onPage=self.on_page)])
    def on_page(self,canv,doc):
        canv.saveState()
        if doc.page==1:
            canv.setFillColor(PAPER); canv.rect(0,0,PAGE_W,PAGE_H,fill=1,stroke=0); canv.setFillColor(DARK); canv.rect(0,PAGE_H-35*mm,PAGE_W,35*mm,fill=1,stroke=0); canv.setFillColor(ORANGE); canv.rect(0,PAGE_H-35*mm,9*mm,35*mm,fill=1,stroke=0); canv.setStrokeColor(ORANGE); canv.circle(PAGE_W-29*mm,PAGE_H-17*mm,11*mm,fill=0,stroke=1); canv.circle(PAGE_W-29*mm,PAGE_H-17*mm,5*mm,fill=0,stroke=1)
        else:
            canv.setFillColor(PAPER); canv.rect(0,0,PAGE_W,PAGE_H,fill=1,stroke=0); canv.setFillColor(DARK); canv.rect(0,PAGE_H-11*mm,PAGE_W,11*mm,fill=1,stroke=0); canv.setFillColor(ORANGE); canv.rect(0,PAGE_H-11*mm,7*mm,11*mm,fill=1,stroke=0); canv.setFillColor(HexColor('#d7d1c7')); canv.setFont('Courier',6.4); canv.drawRightString(PAGE_W-17*mm,PAGE_H-7.5*mm,'NEURATWIN EDGEBOX X1  /  HARDWARE INSTRUCTION KIT'); canv.setStrokeColor(LINE); canv.setLineWidth(.5); canv.line(17*mm,14*mm,PAGE_W-17*mm,14*mm); canv.setFillColor(MUTED); canv.setFont('Courier',6.6); canv.drawString(17*mm,8.5*mm,'ROUND 2  /  NEURA RANGERS  /  PROTOTYPE BUILD'); canv.drawRightString(PAGE_W-17*mm,8.5*mm,f'{doc.page:02d}')
        canv.restoreState()

bom = [
['Core','ESP32-S3 DevKitC-1, 8 MB or larger','1','Required','Wi-Fi, BLE, USB and enough GPIO for the sensor bus.','700-1,500'],
['Core','IP65 ABS enclosure, DIN rail plate, cable glands','1','Required','Makes the build look like a field gateway.','1,000-2,000'],
['Power','12 V DC 3 A isolated adapter + fuse + 5 V buck','1','Required','SELV power domain for the bench and fan.','800-1,500'],
['Electrical','SDM630-Modbus V2 three-phase meter','1','Preferred','Certified Modbus source for V, A, kW, PF and frequency. Electrician install only.','4,000-8,000'],
['Electrical','Isolated RS485 transceiver module','1','Required with meter','Separates the meter bus from the MCU.','500-1,500'],
['Electrical fallback','3 split-core CTs, 50 A class + isolated voltage set','1 set','Fallback','Only with a safe low-voltage harness or certified panel.','1,500-4,000'],
['Thermal','PT100 Class A stainless probes, 3-wire','2','Required','Tank surrogate and ambient channels.','700-1,500'],
['Thermal','MAX31865 PT100 breakout','2','Required','RTD conversion with open/short fault detection.','500-1,000'],
['Condition','ADXL345 or industrial accelerometer breakout','1','Recommended','Adds vibration trend as a supporting health signal.','150-600'],
['Condition','Float switch or capacitive leak sensor + clear tray','1','Recommended','Tangible level/leak signal without oil in electronics.','250-700'],
['Interaction','PN532 NFC reader + 3 NTAG213/215 tags','1 + 3','Required','Tap-to-open asset passport and handoff.','500-1,200'],
['Interaction','12 V fan + logic MOSFET + flyback diode','1','Required','Physical cooling intervention on the bench.','400-900'],
['Interaction','RGB status LED, buzzer, 0.96 inch OLED','1 each','Recommended','Physical state cue for judges.','300-800'],
['Bench','12/24 V isolated transformer + fused load bank','1','Required','Safe current and thermal behavior.','2,000-5,000'],
['Bench','10 k potentiometer + two pushbuttons + terminals','1 set','Recommended','Physical overload and sensor-drift controls.','150-400'],
['Connectivity','SIM7600-H/A-H LTE board + antenna + SIM','1','Stretch','Field-backhaul story; Wi-Fi stays the demo default.','2,500-5,500'],
['Assembly','Ferrules, JST headers, shielded cable, heat-shrink, labels','1 kit','Required','Readable, serviceable wiring.','500-1,200'],
]

pinmap = [
['Function','ESP32-S3','Electrical connection','Notes'],
['PT100 oil / tank','SPI SCK 12, MISO 13, MOSI 11, CS 10','MAX31865 #1','3-wire RTD; route away from fan PWM.'],
['PT100 ambient','SPI shared, CS 14','MAX31865 #2','Use a second chip select.'],
['PN532 NFC','I2C SDA 8, SCL 9','PN532 module','Antenna on plastic face, away from metal.'],
['OLED status','I2C SDA 8, SCL 9','0.96 inch OLED','Typical address 0x3C; confirm variant.'],
['Accelerometer','I2C SDA 8, SCL 9','ADXL345','Typical address 0x53; one set of pull-ups.'],
['RS485 meter','UART2 TX 17, RX 18, DE/RE 16','Isolated RS485 A/B','Read meter manual before changing baud/parity.'],
['Leak / float','GPIO 4','Dry contact to GND','Use INPUT_PULLUP; debounce and require persistence.'],
['Fan / cooling','GPIO 6 -> MOSFET gate','12 V fan on fused rail','SELV common ground; diode across inductive loads.'],
['Alarm LED','GPIO 7','RGB LED driver','Amber warning, red critical, green trusted.'],
['Load injection knob','ADC GPIO 1 through divider','10 k pot','Software control only; never drive a mains switch.'],
]

def write_support_files():
    md = '''# NeuraTwin EdgeBox X1 - Hardware instruction kit

**Round 2 track:** Digital Twin for Intelligent Health Monitoring and Predictive Maintenance of Distribution Transformers
**Team:** Neura Rangers
**Build target:** a safe tabletop transformer surrogate with industrial-style sensing, NFC asset identity, a physical cooling intervention, and a digital-twin dashboard that explains the evidence behind each alert.

## The build judges should see

1. Tap an NFC tag on the enclosure. The dashboard opens the matching asset passport.
2. Turn the load knob or select the labelled overload replay. Phase voltage/current, load and thermal state move together.
3. The twin forecasts a thermal limit approach and shows the evidence chain.
4. Introduce sensor drift or a disconnected probe. The sensor-trust panel changes and the system distinguishes measurement quality from equipment condition.
5. Start the 12 V fan or choose the recommended load reduction. The counterfactual forecast improves and a maintenance work order is created.

This is a prototype decision-support system. It must never switch, probe or control a live distribution transformer.

## Recommended architecture

- **Physical bay:** certified 12/24 V isolated transformer surrogate, a fused low-voltage load, two PT100 probes, a fan, an accelerometer, a leak/level test point and three labelled fault controls.
- **EdgeBox X1:** ESP32-S3, protected 12 V to 5 V power, isolated RS485, two MAX31865 RTD converters, I2C NFC/OLED/accelerometer bus, local status LED and a ring buffer.
- **Electrical source:** preferred: an electrician-installed SDM630-Modbus V2 on a safe test panel. Fallback: labelled replay data or a certified isolated low-voltage harness. Never connect a DIY ADC front-end to mains.
- **Uplink:** Wi-Fi first; optional SIM7600 LTE/GPRS module for a field-backhaul story.
- **Twin:** physical thermal state plus data-quality checks, anomaly evidence, forecast bands and a comparison of continue versus recommended action.

## Build sequence

### 0. Inventory and label - 30 minutes
Label every part `POWER`, `SENSE`, `BUS`, `ACTUATE` or `NFC`. Put the ESP32 and converters on a labelled carrier plate before wiring. Keep the high-energy test panel separate from the EdgeBox.

### 1. Power first - 45 minutes
Bring 12 V into the enclosure through a fuse and strain-relieved cable gland. Generate 5 V for the ESP32 and modules with a buck converter. Verify rails before inserting the MCU. Add one emergency power switch.

### 2. Thermal channels - 60 minutes
Connect the tank/transformer PT100 to MAX31865 #1 and ambient PT100 to #2. Route shielded cable away from the fan and modem antenna. Test open, short and unplugged states; these lower confidence and raise a sensor-quality alert.

### 3. Identity and local status - 45 minutes
Install PN532 behind a non-metallic face panel and attach an NTAG tag labelled `NR-104`. Add OLED and RGB LED. NFC payload contains only an asset ID and versioned configuration reference.

### 4. Electrical telemetry - 60 to 120 minutes
Preferred: read the certified meter over isolated RS485. If it is not available, run the same firmware with the replay adapter and label the electrical stream `SIMULATED REPLAY`.

### 5. Physical intervention - 45 minutes
Drive a 12 V fan with a logic-level MOSFET and flyback diode. Attach the fan to the surrogate bay so the thermal response changes visibly. Never connect it to a transformer control circuit.

### 6. Firmware and integration - 90 minutes
Sample thermal and vibration at 1 Hz; electrical at 1 to 5 Hz; publish a 5-second packet and retain a local ring buffer. Add timestamps, units, sequence number, firmware version and quality flags to every packet.

## Calibration and acceptance

- RTD: compare a room point and ice-water point; record offset and probe serial.
- Electrical: compare each R/Y/B channel against a reference. The supplied draft workbook uses a <=1% check; confirm the final procedure with CPRI.
- Current trip: the draft workbook lists a 50 A set-current check. Do not create 50 A on a student bench. Demonstrate the same logic with replay or a certified current source.
- Temperature trip: the draft workbook lists 60 deg C checks. Use a software threshold or controlled low-energy heater; do not heat transformer oil.
- Data quality: disconnect a probe, duplicate a timestamp, send an out-of-order packet and hold a stale value. Each must change confidence and appear in the incident view.
- Intervention: start the fan and show a lower counterfactual temperature trajectory; log the action and its assumptions.

## Judge runbook

1. **Identity:** tap NFC; show asset passport and provenance.
2. **Baseline:** show measured versus inferred temperature tracking with lag.
3. **Stress:** trigger overload; show phase values, health index, warning and forecast window.
4. **Explain:** open the causal chain from measured signal to state, risk and action.
5. **Trust:** inject a probe fault; show a measurement-quality alert rather than an invented transformer diagnosis.
6. **Act:** run the fan or load-reduction what-if; show improved forecast.
7. **Handoff:** create a work order with asset, evidence, urgency and verification step.

## Safety boundary

- No live transformer connection is part of this student prototype.
- Mains measurement is only by a certified meter, in an enclosed test panel, installed and checked by a licensed electrician.
- Keep the EdgeBox on an SELV supply. Keep mains, meter CTs and student electronics in separate enclosures.
- Do not use a breadboard for mains, expose terminals, defeat fusing or put NFC electronics on a metal tank wall.

## References

- CPRI/PowerNext draft files: `Track 2 - DT/DT Problem Statement.pdf` and `Track 2 - DT/Draft Data for Condition Monitoring.xlsx`.
- ESP32-S3: https://documentation.espressif.com/esp32-s3_datasheet_en.pdf
- ADS131M04: https://www.ti.com/lit/ds/symlink/ads131m04.pdf
- MAX31865: https://www.analog.com/en/products/max31865.html
- PN532: https://www.nxp.com/docs/en/nxp/data-sheets/PN532_C1.pdf
- SIM7600: https://www.simcom.com/product/SIM7600NAG.html
- SDM630 manual: https://www.eastrongroup.com/eastrongroup/2024/08/21/eastronsdm630modbusv2usermanual2020v1.4.pdf
- IEC 60076-7: https://webstore.iec.ch/en/publication/34351
'''
    MD_PATH.write_text(md, encoding='utf-8')
    with BOM_PATH.open('w', newline='', encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['Category','Part','Qty','Priority','Why / substitute','Indicative INR band']); w.writerows(bom)
    with PINMAP_PATH.open('w', newline='', encoding='utf-8') as f:
        w=csv.writer(f); w.writerows(pinmap)

def build_pdf():
    story=[]
    story += [Spacer(1,16*mm),P('NEURATWIN / EDGEBOX X1','CoverKicker'),P('Hardware instruction kit','CoverTitle'),P('A build-ready physical layer for the Round 2 transformer digital twin.','CoverSub'),Rule(ORANGE),Spacer(1,8*mm)]
    cover_rows=[[P('<b>Build goal</b>','Bodyx'),P('One safe physical loop that turns transformer signals into an explained maintenance decision.','Bodyx')],[P('<b>Winning moment</b>','Bodyx'),P('Tap NFC -> stress the asset -> expose evidence -> change the cooling state -> recompute the forecast -> hand off the work order.','Bodyx')],[P('<b>Default mode</b>','Bodyx'),P('12/24 V isolated tabletop surrogate with replay fallback for electrical channels.','Bodyx')]]
    t=Table(cover_rows,colWidths=[38*mm,127*mm]); t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.35,LINE),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)])); story += [t,Spacer(1,8*mm)]
    s=Table([[P('<b>SAFETY BOUNDARY</b><br/>This is a student tabletop prototype. Do not connect it to an energized distribution transformer. Mains measurement requires a certified instrument, an enclosed test panel and a licensed electrician.','Callout')]],colWidths=[165*mm]); s.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#f8e4d8')),('BOX',(0,0),(-1,-1),.9,RED),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)])); story += [s,Spacer(1,8*mm),P('<b>Prepared for Neura Rangers</b><br/>Round 2 | Digital Twin for Intelligent Health Monitoring and Predictive Maintenance of Distribution Transformers<br/>Build version 1.0 | 01 October 2026','BodySmall'),PageBreak()]

    story += [P('01 / THE BUILD WE WILL SHOW','H3x'),P('One physical loop, five judge-visible proof points.','H1x'),P('The kit is split into a safe bench, a sealed sensor gateway and the existing NeuraTwin software. That gives judges something physical to touch without pretending a student prototype is a field-certified transformer monitor.','Bodyx'),Diagram('architecture',height=60*mm),Spacer(1,5*mm)]
    proof=[[P(x,'TableHead') for x in ['Proof point','What the judge sees','Why it matters']],[P('<b>Identity</b>','TableCell'),P('NFC tap opens NR-104 asset passport, nameplate and provenance.','TableCell'),P('Connects a physical asset to a traceable software record.','TableCell')],[P('<b>Measurement</b>','TableCell'),P('PT100, electrical packet, vibration and leak inputs appear with timestamps and quality flags.','TableCell'),P('Shows real sensing rather than a static dashboard.','TableCell')],[P('<b>Explanation</b>','TableCell'),P('Causal chain links measured signal -> thermal state -> risk -> action.','TableCell'),P('Makes the digital twin inspectable.','TableCell')],[P('<b>Intervention</b>','TableCell'),P('12 V fan changes the surrogate thermal response and counterfactual forecast.','TableCell'),P('Demonstrates predictive maintenance as a decision loop.','TableCell')],[P('<b>Handoff</b>','TableCell'),P('Work order inherits evidence, urgency and verification step.','TableCell'),P('Ends in an operational action, not only a chart.','TableCell')]]
    story += [table(proof,[29*mm,75*mm,61*mm]),Spacer(1,5*mm),P('<b>Use the app you already have:</b> the current `/app` console contains the asset passport, telemetry, fault theatre, causal chain, forecast duel and maintenance queue. This kit supplies the physical signals and the judge story around them.','BodySmall'),PageBreak()]

    story += [P('02 / WINNING BUILD SPEC','H3x'),P('Build the EdgeBox X1, not a loose pile of modules.','H1x'),P('The visual quality of the hardware is part of the pitch. Mount modules on a labelled plate, use ferrules and terminal blocks, and keep a one-page wiring card inside the lid.','Bodyx')]
    spec=[[P(x,'TableHead') for x in ['Layer','Build','Role in the demo']],[P('Physical bay','TableCell'),P('Certified 12/24 V isolated transformer surrogate, fused low-voltage load, clear tray, fan and two probe points.','TableCell'),P('Provides a safe thermal and current response the judges can see.','TableCell')],[P('EdgeBox','TableCell'),P('ESP32-S3, 12 V fuse, 5 V buck, isolated RS485, two MAX31865 boards, labelled terminal blocks.','TableCell'),P('Reads, timestamps and buffers the evidence at the edge.','TableCell')],[P('Measurement','TableCell'),P('PT100 tank + ambient, SDM630 Modbus preferred, accelerometer, leak/level contact.','TableCell'),P('Covers organizer inputs and adds two supporting health signals.','TableCell')],[P('Identity','TableCell'),P('PN532 reader, three NTAG tags, OLED and RGB status LED.','TableCell'),P('Makes the system feel like an operational asset tool.','TableCell')],[P('Intervention','TableCell'),P('12 V fan driven by a MOSFET; optional knob and buttons for labelled fault injection.','TableCell'),P('Creates a physical before/after for the action comparison.','TableCell')],[P('Backhaul','TableCell'),P('Wi-Fi first. SIM7600 LTE/GPRS board as optional field uplink.','TableCell'),P('Shows extension path without making the demo depend on a SIM.','TableCell')]]
    story += [table(spec,[31*mm,78*mm,56*mm]),Spacer(1,5*mm)]
    role=Table([[P('<b>Minimum winning hardware</b><br/>ESP32-S3 + 2 PT100/MAX31865 + PN532 + fan/MOSFET + accelerometer + leak/float + enclosure + power.','Bodyx'),P('<b>Full hardware story</b><br/>Add SDM630 Modbus, isolated RS485, OLED/LED and SIM7600 after the core loop works.','Bodyx')]],colWidths=[82*mm,83*mm]); role.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),HexColor('#f7e3c7')),('BACKGROUND',(1,0),(1,0),HexColor('#e0ece6')),('BOX',(0,0),(-1,-1),.5,LINE),('INNERGRID',(0,0),(-1,-1),.5,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)])); story += [role,PageBreak()]

    story += [P('03 / BILL OF MATERIALS','H3x'),P('Buy in this order.','H1x'),P('Core items make a credible physical demo. The preferred meter and cellular modem are stretch items; they must never delay the thermal, NFC and intervention loop.','Bodyx')]
    br=[[P(x,'TableHead') for x in ['Category','Part','Qty','Priority','Why / substitute','INR band']]]+[ [P(esc(x),'TableCellSmall') for x in row] for row in bom]
    story += [table(br,[22*mm,43*mm,12*mm,18*mm,52*mm,18*mm]),Spacer(1,4*mm),P('Indicative INR bands are planning numbers, not quotes. Verify the exact board variant, connector, supply voltage and certification before wiring.','BodySmall'),PageBreak()]

    story += [P('04 / ENCLOSURE AND BENCH LAYOUT','H3x'),P('Make the physical system readable from two metres away.','H1x'),P('A judge should immediately understand which side is the asset, which side is the edge gateway and where the safe intervention happens. Use large labels: `NR-104`, `SENSE`, `BUS`, `ACTUATE`, `NFC TAP`.','Bodyx'),Diagram('bench',height=70*mm),Spacer(1,6*mm)]
    layout=[[P(x,'TableHead') for x in ['Zone','Placement','Build rule']],[P('Bay A / asset surrogate','TableCell'),P('Transformer, thermal probe points, clear tray, fan and low-voltage load.','TableCell'),P('No accessible mains; use an isolated low-voltage supply and fuse.','TableCell')],[P('Bay B / EdgeBox','TableCell'),P('MCU and converters on a removable plate inside the IP65 box.','TableCell'),P('Keep modem antenna and NFC coil away from metal and switching noise.','TableCell')],[P('Bay C / operator controls','TableCell'),P('NFC face, OLED, RGB LED, overload knob, drift button and fan button.','TableCell'),P('Controls have printed labels and match app scenario names.','TableCell')],[P('Service lid','TableCell'),P('Printed pin map, fuse rating, firmware version, asset ID and QR to the app.','TableCell'),P('Make maintenance evidence visible before opening the box.','TableCell')]]
    story += [table(layout,[31*mm,69*mm,65*mm]),Spacer(1,4*mm),P('<b>Visual trick:</b> use one amber light bar for warning, one red bar for critical and one green bar for trusted. Every color must be a named state in the dashboard.','Bodyx'),PageBreak()]

    story += [P('05 / WIRING AND PIN MAP','H3x'),P('Wire the safe side once, then expand by connector.','H1x'),P('Use a common ground only on the SELV side. The RS485 path to a certified meter should be isolated. Every sensor cable gets a label at both ends.','Bodyx')]
    pr=[[P(x,'TableHead') for x in pinmap[0]]]+[[P(esc(x),'TableCellSmall') for x in row] for row in pinmap[1:]]
    story += [table(pr,[30*mm,39*mm,46*mm,50*mm]),Spacer(1,5*mm)]
    power=[[P(x,'TableHead') for x in ['Power domain','Connection','Acceptance check']],[P('12 V SELV','TableCell'),P('Adapter -> fuse -> terminal block -> fan/MOSFET and buck input.','TableCell'),P('Fuse matches adapter and fan load. No warm terminals.','TableCell')],[P('5 V logic','TableCell'),P('Buck output -> ESP32 and 5 V-capable modules.','TableCell'),P('5.0 V +/- 0.1 V at board under load.','TableCell')],[P('3.3 V logic','TableCell'),P('ESP32 3.3 V -> MAX31865, PN532, OLED and accelerometer if supported.','TableCell'),P('Confirm each breakout voltage before plugging it in.','TableCell')],[P('Mains/test panel','TableCell'),P('Separate enclosure and cable path. Never on the breadboard or carrier plate.','TableCell'),P('Licensed electrician checks isolation, fusing, earth and enclosure.','TableCell')]]
    story += [table(power,[34*mm,77*mm,54*mm]),Spacer(1,4*mm),P('<b>Do not improvise:</b> if the SDM630 is not already in a safe test panel, use replay mode. A complete software demo with labelled replay is stronger than an unsafe half-wired meter.','BodySmall'),PageBreak()]

    story += [P('06 / FIRMWARE AND DATA CONTRACT','H3x'),P('Every number needs a timestamp, unit and confidence.','H1x'),P('Edge firmware should be deterministic: sample, validate, buffer and publish. The twin engine remains the place where health scores, forecasts and recommendations are calculated.','Bodyx')]
    fw=[[P(x,'TableHead') for x in ['Loop','Cadence','Output']],[P('Sensor scan','TableCell'),P('1 Hz thermal/vibration; 1-5 Hz electrical','TableCell'),P('Raw values plus sensor fault flags.','TableCell')],[P('Quality gate','TableCell'),P('Every packet','TableCell'),P('Stale, out-of-order, missing, impossible range and sequence checks.','TableCell')],[P('Edge buffer','TableCell'),P('Continuous','TableCell'),P('At least 8 hours of compact packets in flash or SD when network is down.','TableCell')],[P('Publish','TableCell'),P('Every 5 seconds','TableCell'),P('One canonical JSON packet to Wi-Fi API; queue when offline.','TableCell')],[P('Actuator guard','TableCell'),P('On command','TableCell'),P('Only a 12 V fan/LED on the bench; require local confirmation and log the action.','TableCell')]]
    story += [table(fw,[31*mm,33*mm,101*mm]),Spacer(1,5*mm)]
    js='''{<br/>&nbsp;&nbsp;&quot;asset_id&quot;: &quot;NR-104&quot;, &quot;timestamp&quot;: &quot;2026-10-01T12:20:00+05:30&quot;,<br/>&nbsp;&nbsp;&quot;electrical&quot;: {&quot;v_r&quot;: 259.1, &quot;v_y&quot;: 260.0, &quot;v_b&quot;: 264.5, &quot;i_r&quot;: 49.9, &quot;i_y&quot;: 49.9, &quot;i_b&quot;: 49.9, &quot;load_pct&quot;: 88.0},<br/>&nbsp;&nbsp;&quot;thermal&quot;: {&quot;oil_c&quot;: 48.6, &quot;ambient_c&quot;: 31.2},<br/>&nbsp;&nbsp;&quot;condition&quot;: {&quot;vibration_rms_g&quot;: 0.018, &quot;leak&quot;: false, &quot;level_ok&quot;: true},<br/>&nbsp;&nbsp;&quot;quality&quot;: {&quot;stale&quot;: false, &quot;out_of_order&quot;: false, &quot;sensor_faults&quot;: [], &quot;source&quot;: &quot;edgebox&quot;},<br/>&nbsp;&nbsp;&quot;edge&quot;: {&quot;nfc_uid&quot;: &quot;04-A1-B2-C3&quot;, &quot;fw&quot;: &quot;0.1.0&quot;, &quot;rssi_dbm&quot;: -54}<br/>}'''
    jb=Table([[P('<b>Canonical packet</b>','H3x')],[P(js,'SmallMono')]],colWidths=[165*mm]); jb.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),HexColor('#e0ece6')),('BACKGROUND',(0,1),(-1,1),PANEL),('BOX',(0,0),(-1,-1),.6,BLUE),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)])); story += [jb,Spacer(1,5*mm),P('Firmware rule: never silently replace a missing measurement with zero. Set the quality flag, lower confidence and let the dashboard explain what is missing.','Bodyx'),PageBreak()]

    story += [P('07 / BUILD SEQUENCE','H3x'),P('A six-hour core build, then stretch.','H1x'),P('Assign one person to power and wiring, one to firmware, one to the dashboard and one to the demo story. Every block ends with a visible checkpoint.', 'Bodyx')]
    steps=[('01','Inventory and labels','30 min','Parts separated into POWER / SENSE / BUS / ACTUATE / NFC. Enclosure has asset ID and fuse label.'),('02','Power and carrier plate','45 min','12 V and 5 V verified with a meter before the MCU is inserted.'),('03','Thermal and quality sensors','60 min','Both PT100 channels read; unplugged/open/short states are visible faults.'),('04','NFC and local status','45 min','NFC returns NR-104; OLED and LED mirror the dashboard state.'),('05','Electrical path or replay','60-120 min','SDM630 reads through isolated RS485, or clearly labelled replay drives the schema.'),('06','Cooling intervention','45 min','Fan changes the surrogate response and dashboard records the action.'),('07','Software integration','90 min','One packet, warning, forecast, what-if and work order complete end to end.'),('08','Judge rehearsal','45 min','No menus are searched live; the team follows the runbook.')]
    sr=[[P('','TableHead'),P('Task','TableHead'),P('Time','TableHead'),P('Done means','TableHead')]]+[[P(a,'StepNum'),P(b,'TableCell'),P(c,'TableCell'),P(d,'TableCell')] for a,b,c,d in steps]
    story += [table(sr,[13*mm,39*mm,22*mm,91*mm]),Spacer(1,5*mm),P('<b>Cut line:</b> if the meter or modem blocks the build after two hours, switch to replay mode and spend the saved time on calibration, NFC, evidence quality and the physical fan intervention.','Bodyx'),PageBreak()]

    story += [P('08 / CALIBRATION AND ACCEPTANCE','H3x'),P('Prove the signals before you demo the intelligence.','H1x'),P('The supplied workbook is marked as draft data for condition monitoring. It lists three-phase voltage/current comparisons, a 50 A current-trip check, 60 deg C temperature-trip checks, oil-leakage sensing and GPRS/master-number communication. Treat these as organizer hints, not field-certified limits.','Bodyx')]
    cr=[[P(x,'TableHead') for x in ['Test','Method','Pass condition','Evidence to show']],[P('RTD offset','TableCell'),P('Room point and ice-water point; record probe serial and offset.','TableCell'),P('Stable reading; offset stored in asset config.','TableCell'),P('Calibration row in passport.','TableCell')],[P('Phase comparison','TableCell'),P('Compare meter or certified reference with each R/Y/B channel.','TableCell'),P('Draft workbook target is <=1% difference; confirm with CPRI.','TableCell'),P('Three green checks and raw values.','TableCell')],[P('Current trip logic','TableCell'),P('Use replay or certified current source. Do not generate 50 A on a student bench.','TableCell'),P('Alert at configured setpoint with timestamp.','TableCell'),P('Incident event and threshold provenance.','TableCell')],[P('Temperature trip logic','TableCell'),P('Use software threshold or controlled low-energy heater. Do not heat transformer oil.','TableCell'),P('Alert at configured 60 deg C test threshold if confirmed.','TableCell'),P('Threshold shown as configuration.','TableCell')],[P('Sensor quality','TableCell'),P('Unplug probe, duplicate timestamp, out-of-order packet, stale value.','TableCell'),P('Confidence drops; quality alert explains cause.','TableCell'),P('Evidence panel and event log.','TableCell')],[P('Action response','TableCell'),P('Start fan or select load reduction from the same initial state.','TableCell'),P('Forecast exposure falls; action is logged.','TableCell'),P('Forecast duel and work order.','TableCell')]]
    story += [table(cr,[28*mm,57*mm,43*mm,37*mm]),Spacer(1,5*mm)]
    w=Table([[P('<b>Do not overclaim:</b> the thermal model is a screening and decision-support model. A predicted limit approach is conditional on the future load and ambient scenario; it is not time to transformer failure or remaining useful life.','Callout')]],colWidths=[165*mm]); w.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#e0ece6')),('BOX',(0,0),(-1,-1),.8,MINT),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)])); story += [w,PageBreak()]

    story += [P('09 / JUDGE MODE RUNBOOK','H3x'),P('Seven actions. Ninety seconds. No searching.','H1x'),P('Keep one person on the hardware and one on the console. The hardware person performs the physical action; the console person narrates the evidence and model assumptions.','Bodyx'),Diagram('flow',height=53*mm),Spacer(1,4*mm)]
    run=[[P(x,'TableHead') for x in ['Time','Physical action','Console narration']],[P('0:00-0:12','TableCell'),P('Tap NR-104 NFC tag.','TableCell'),P('The tag resolves the same asset identity used by the twin, including rating, probe serials and provenance.','TableCell')],[P('0:12-0:25','TableCell'),P('Show green status and baseline.','TableCell'),P('Measured oil and ambient values are separate from the inferred hot-spot; the baseline is visible before any alert.','TableCell')],[P('0:25-0:40','TableCell'),P('Turn overload knob or trigger labelled replay.','TableCell'),P('The stress enters as a timestamped signal, not a hard-coded chart. The twin projects the configured thermal limit.','TableCell')],[P('0:40-0:54','TableCell'),P('Open incident evidence.','TableCell'),P('This is the causal chain: load signal, estimated state, conditional risk and a feasible action.','TableCell')],[P('0:54-1:06','TableCell'),P('Press sensor-drift or unplug a probe.','TableCell'),P('The system raises measurement quality uncertainty instead of inventing a transformer fault.','TableCell')],[P('1:06-1:20','TableCell'),P('Start fan or choose load reduction.','TableCell'),P('Both futures start from the same state. The safer action lowers forecast exposure, and the action is recorded.','TableCell')],[P('1:20-1:30','TableCell'),P('Create the work order.','TableCell'),P('The final handoff carries the asset, evidence, urgency and verification step for the technician.','TableCell')]]
    story += [table(run,[25*mm,60*mm,80*mm]),Spacer(1,4*mm),P('<b>One sentence to memorize:</b> NeuraTwin does not only say that a transformer is hot; it shows whether the signal is trustworthy, what the thermal state is likely to do next and which logged action changes the outcome.','Bodyx'),PageBreak()]

    story += [P('10 / TROUBLESHOOTING','H3x'),P('Fix the failure mode a judge is most likely to notice.','H1x')]
    tr=[[P(x,'TableHead') for x in ['Symptom','Likely cause','Fast fix']],[P('No sensor values','TableCell'),P('5 V rail missing, wrong SPI chip select or probe open.','TableCell'),P('Measure rails, run the MAX31865 fault check, then test one probe at a time.','TableCell')],[P('NFC does not scan','TableCell'),P('Coil beside metal, wrong interface mode or 5 V logic level.','TableCell'),P('Move antenna to plastic face, confirm interface mode and use 3.3 V logic.','TableCell')],[P('RS485 values are garbage','TableCell'),P('A/B swapped, wrong parity, missing termination or non-isolated adapter.','TableCell'),P('Read meter manual, try 9600 8E1, terminate at both bus ends and isolate.','TableCell')],[P('Dashboard says healthy during unplug','TableCell'),P('Missing value coerced to zero or stale value not flagged.','TableCell'),P('Reject packet, lower confidence and show quality alert.','TableCell')],[P('Fan does not start','TableCell'),P('MOSFET gate lacks common SELV ground, wrong polarity or no diode.','TableCell'),P('Test fan from fused 12 V, then MOSFET gate, then firmware command.','TableCell')],[P('Forecast jumps too far','TableCell'),P('Replay cursor and telemetry clock are out of sync.','TableCell'),P('Freeze initial state, add sequence numbers and recompute both paths together.','TableCell')],[P('Build looks like a prototype','TableCell'),P('Loose wires, no labels and no service card.','TableCell'),P('Use ferrules, glands, lid card, visible asset tag and one clean harness.','TableCell')]]
    story += [table(tr,[42*mm,56*mm,67*mm]),Spacer(1,7*mm)]
    rv=Table([[P('<b>Before the demo:</b> take one photo of the closed box, one photo of the open service lid and one screenshot of the same asset in the app. Put all three in the pitch deck.','Callout')]],colWidths=[165*mm]); rv.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),HexColor('#f7e3c7')),('BOX',(0,0),(-1,-1),.8,ORANGE),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)])); story += [rv,PageBreak()]

    story += [P('11 / SAFETY, LIMITS AND SOURCES','H3x'),P('The winning build is credible because its boundaries are visible.','H1x'),P('The hardware demonstrates the telemetry path and decision loop. It is not a field installation and it does not execute grid switching. Keeping that boundary explicit makes the technical story stronger.','Bodyx')]
    safe=[[P(x,'TableHead') for x in ['Rule','Required practice']],[P('No live transformer','TableCell'),P('No connection to an energized distribution transformer in the student demo. Use a low-voltage surrogate, replay or certified test panel.','TableCell')],[P('Separate energy domains','TableCell'),P('Keep mains/test-panel wiring physically separate from the SELV EdgeBox. Use fusing, strain relief and an enclosure.','TableCell')],[P('No improvised CT/VT','TableCell'),P('Do not build or expose a raw mains front-end. Use a certified meter or replay.','TableCell')],[P('Honest labels','TableCell'),P('Label simulated channels, estimated hot-spot, conditional forecast and draft thresholds in the UI.','TableCell')],[P('No unsafe actuation','TableCell'),P('Only control the low-voltage fan/LED demonstrator. Log the command and require local confirmation.','TableCell')]]
    story += [table(safe,[43*mm,122*mm]),Spacer(1,5*mm),P('Component and engineering references','H2x')]
    refs=['PowerNext / CPRI draft problem statement and draft measurement workbook supplied with the track.','Espressif ESP32-S3 datasheet: https://documentation.espressif.com/esp32-s3_datasheet_en.pdf','Texas Instruments ADS131M04 optional precision ADC: https://www.ti.com/lit/ds/symlink/ads131m04.pdf','Analog Devices MAX31865 RTD converter: https://www.analog.com/en/products/max31865.html','NXP PN532 NFC controller: https://www.nxp.com/docs/en/nxp/data-sheets/PN532_C1.pdf','SIMCom SIM7600 LTE/GPRS module: https://www.simcom.com/product/SIM7600NAG.html','Eastron SDM630-Modbus V2 manual: https://www.eastrongroup.com/eastrongroup/2024/08/21/eastronsdm630modbusv2usermanual2020v1.4.pdf','IEC 60076-7:2018 loading guide scope: https://webstore.iec.ch/en/publication/34351']
    for ref in refs: story.append(bullet(esc(ref),'BodySmall'))
    story += [Spacer(1,6*mm),Rule(BLUE),Spacer(1,4*mm),P('<b>Ship these four artifacts:</b> the closed EdgeBox, the one-page wiring card, the labelled replay file and the live `/app` console. That combination gives judges a physical object, a reproducible data source, an engineering explanation and a visible decision surface.','Bodyx')]
    HardwareDoc(str(PDF_PATH),leftMargin=17*mm,rightMargin=17*mm,topMargin=17*mm,bottomMargin=17*mm).build(story)

if __name__ == '__main__':
    write_support_files(); build_pdf(); print(PDF_PATH); print(MD_PATH); print(BOM_PATH); print(PINMAP_PATH)
