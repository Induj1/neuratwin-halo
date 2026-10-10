import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const A=createRequire(import.meta.url)('../web/halo-alarms.js');
const input=(temperature=40)=>({key:'prototype:bench',mode:'prototype',snapshot:{settings:{temperature_warning:50,temperature_critical:60}},display:{live:true,channels:{surface_temperature:{value:temperature}}},result:{available:true,live:true,oil_c:40,pressure_kpa:10,level_percent:100,stage:'normal'},settings:{tank:'sealed',oil_limit_c:95,pressure_limit_kpa:50}});

test('missing limits do not mislabel a valid temperature as sensor loss or recovery',()=>{
 const i=input(85);i.snapshot.settings={temperature_warning:null,temperature_critical:null};
 const s=A.evaluate(A.createState(),i);
 assert.equal(s.status,'unavailable');assert.equal(s.title,'Surface limits not configured');
 assert.equal(s.alerts.length,0);assert.match(s.detail,/commissioning/);
});
test('surface thresholds retain warning and critical until 2 C recovery margin',()=>{
 let s=A.createState();for(const [temperature,status] of [[40,'normal'],[50,'warning'],[49,'warning'],[60,'critical'],[59,'critical'],[58,'warning'],[48,'recovered']]){
  s=A.evaluate(s,input(temperature));assert.equal(s.status,status);assert.equal(s.thermal,status==='recovered'?'normal':status);
 }
});
test('acknowledgement persists across samples; escalation and new faults rearm',()=>{
 let s=A.acknowledge(A.evaluate(A.createState(),input(52)));
 s=A.evaluate(s,input(53));assert(s.alerts.every(a=>a.acknowledged));
 s=A.evaluate(s,input(61));assert.equal(s.alerts[0].acknowledged,false);
 s=A.acknowledge(s);const i=input(61);i.result.pressure_kpa=55;s=A.evaluate(s,i);
 assert(s.alerts.find(a=>a.id==='surface').acknowledged);assert(!s.alerts.find(a=>a.id==='pressure').acknowledged);
});
test('offline and missing probe cannot report recovery or play a cached critical alarm',()=>{
 let s=A.evaluate(A.createState(),input(65));const i=input(30);i.display.live=false;
 s=A.evaluate(s,i);assert.equal(s.status,'unavailable');assert.equal(s.title,'Connection lost');assert.equal(s.alerts.length,0);assert(!s.recovered);
 i.display.live=true;i.display.channels.surface_temperature.value=null;s=A.evaluate(s,i);
 assert.equal(s.status,'unavailable');assert(!s.recovered);
 s=A.evaluate(s,input(40));assert.equal(s.status,'recovered');
});
test('surface alarm works when the virtual model is unavailable',()=>{
 const i=input(65);i.result=null;const s=A.evaluate(A.createState(),i);
 assert.equal(s.status,'critical');assert.equal(s.alerts[0].basis,'Measured');assert.match(s.missing,/Model output unavailable/);
});
test('modelled faults never colour the physical surface as overheated',()=>{
 const i=input(30);i.result.pressure_kpa=70;i.result.stage='trip';i.fault='surge';
 const s=A.evaluate(A.createState(),i);assert.equal(s.status,'critical');assert.equal(s.thermal,'normal');
 assert.equal(s.alerts.find(a=>a.id==='trip').basis,'Injected scenario');
});
test('source changes isolate episodes and industrial oil temperatures are modelled',()=>{
 let s=A.acknowledge(A.evaluate(A.createState(),input(65)));const i=input();i.key='industrial:run';i.mode='industrial';i.snapshot={telemetry:{}};i.result.oil_c=99;
 s=A.evaluate(s,i);assert.equal(s.alerts[0].id,'oil');assert.equal(s.alerts[0].basis,'Modelled');assert(!s.alerts[0].acknowledged);assert(!s.levels.surface);
});
test('low oil thresholds handle hysteresis and reject missing values',()=>{
 let s=A.createState();for(const [level,status] of [[100,'normal'],[94,'warning'],[89,'critical'],[91,'critical'],[92,'warning'],[97,'recovered']]){const i=input();i.result.level_percent=level;s=A.evaluate(s,i);assert.equal(s.status,status);}
 const i=input();i.result.level_percent=null;const missing=A.evaluate(s,i);assert(!missing.alerts.some(a=>a.id==='level'));assert.equal(missing.status,'unavailable');
});
test('latched model trips stay red until explicitly reset and cannot be cleared by acknowledgement',()=>{
 const i=input();i.result.stage='trip';let s=A.acknowledge(A.evaluate(A.createState(),i));
 s=A.evaluate(s,i);assert.equal(s.status,'critical');assert(s.alerts[0].acknowledged);
 i.result.stage='normal';s=A.evaluate(s,i);assert.equal(s.status,'recovered');
});
test('replay never triggers audible alarms or claims recovery',()=>{
 const i=input(70);i.replay=true;const s=A.evaluate(A.createState(),i);assert.equal(s.status,'unavailable');assert.equal(s.alerts.length,0);assert.match(s.title,/Replay/);
});
test('leak and gas injections warn before thresholds, then escalate and reset',()=>{
 for(const fault of ['leak','gas']){
  const i=input();i.mode='industrial';i.key='industrial:run';i.snapshot={telemetry:{},running:false};i.fault=fault;i.fault_at='first';i.result.fault=fault;
  if(fault==='gas'){i.settings.tank='conservator';i.result.level_percent=50;i.result.gas_ml=0;}
  let s=A.evaluate(A.createState(),i);assert.equal(s.status,'warning');assert.equal(s.alerts[0].basis,'Injected scenario');assert.match(s.detail,/Advance source/);
  s=A.acknowledge(s);s=A.evaluate(s,i);assert(s.alerts.every(a=>a.acknowledged));
  if(fault==='leak')i.result.level_percent=89;else i.result.gas_ml=210;
  s=A.evaluate(s,i);assert.equal(s.status,'critical');assert(!s.alerts[0].acknowledged);
  i.result.level_percent=fault==='gas'?50:100;i.result.gas_ml=0;i.fault=i.result.fault='none';s=A.evaluate(s,i);assert.equal(s.status,'recovered');
 }
});
test('unconfirmed, offline and incompatible gas injections cannot raise a scenario alarm',()=>{
 const i=input();i.fault='gas';i.result.fault='gas';i.result.gas_ml=0;
 assert.equal(A.evaluate(A.createState(),i).alerts.length,0);
 i.settings.tank='conservator';i.result.level_percent=50;i.result.fault='none';assert.equal(A.evaluate(A.createState(),i).alerts.length,0);
 i.result.fault='gas';i.display.live=false;assert.equal(A.evaluate(A.createState(),i).alerts.length,0);
});
