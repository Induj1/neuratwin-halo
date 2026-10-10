import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { components, changeNote, replaySnapshot, dialState, planPresentation, temperatureReading, reviewContext, sameReviewSource, sameObservationSource } = require('../web/halo-command.js');
const stress = { thermal: 23, electrical: 0, loading: 41, historical: 7, environmental: 12, oil: 4 };
const currentTime = '2026-10-08T10:05:00Z';
const oldTime = '2026-10-08T10:00:00Z';
const qualified = { quality: 'qualified', timestamp: currentTime, transformer_temperature: 76, primary_voltage: 11000, secondary_voltage: 12, loading_percent: 92, ambient_temperature: 31, oil_condition: 96 };
const byKey = rows => Object.fromEntries(rows.map(row => [row.key, row.value]));

test('held health never promotes a reassuring stress value to the dial score',()=>{
  const d=dialState({health_index:null,operating_stress_index:97,status:'CRITICAL'});
  assert.equal(d.score,null);assert.equal(d.held,true);assert.equal(d.status,'CRITICAL');assert.equal(d.stress,97);
  assert.equal(dialState({health_index:0,status:'CRITICAL'}).score,0);
  assert.equal(dialState({health_index:NaN}).held,true);
});
test('unqualified changing readings cannot produce a thermal recovery explanation',()=>{
  assert.match(changeNote({telemetry:{quality:'stale',timestamp:currentTime,transformer_temperature:50},history:[{timestamp:oldTime,transformer_temperature:80}]}),/qualified/);
});

test('industrial components retain valid zero and reported stress values', () => {
  const result = byKey(components({ telemetry: qualified, analysis: { stress } }, 'industrial'));
  assert.deepEqual(result, stress);
});
test('prototype never presents oil or accumulated insulation stress as measured', () => {
  const result = byKey(components({ telemetry: qualified, analysis: { stress } }, 'prototype'));
  assert.equal(result.oil, null);
  assert.equal(result.historical, null);
  assert.equal(result.thermal, 23);
  assert.equal(result.loading, 41);
});
test('unqualified physical channels do not produce available component bars', () => {
  for (const quality of ['unverified', 'stale', 'disconnected', undefined]) {
    const result = components({ telemetry: { ...qualified, quality }, analysis: { stress } }, 'prototype');
    assert.ok(result.every(row => row.value === null), quality);
  }
});
test('component availability requires actual numbers and corresponding observations', () => {
  const telemetry = { ...qualified, transformer_temperature: null, secondary_voltage: undefined, loading_percent: '92', ambient_temperature: NaN };
  assert.ok(components({ telemetry, analysis: { stress } }, 'prototype').every(row => row.value === null));
  assert.ok(components({ telemetry: qualified, analysis: {} }, 'industrial').every(row => row.value === null));
  assert.equal(byKey(components({ telemetry: qualified, analysis: { stress: { ...stress, electrical: Infinity } } }, 'industrial')).electrical, null);
});
test('prototype electrical availability uses secondary channel rather than primary voltage', () => {
  assert.equal(byKey(components({ telemetry: { ...qualified, primary_voltage: null }, analysis: { stress } }, 'prototype')).electrical, 0);
  assert.equal(byKey(components({ telemetry: { ...qualified, secondary_voltage: null }, analysis: { stress } }, 'prototype')).electrical, null);
});
test('change note excludes same-time and future observations from comparison', () => {
  const s = { telemetry: qualified, history: [{ ...qualified, timestamp: currentTime, loading_percent: 250 }, { ...qualified, timestamp: '2026-10-08T11:00:00Z', loading_percent: 250 }], analysis: { status: 'NORMAL' } };
  assert.match(changeNote(s), /First observation/);
});
test('change note distinguishes thermal lag, demand changes, imbalance and missing evidence', () => {
  const before = { ...qualified, timestamp: oldTime };
  const cases = [
    [{ transformer_temperature: 78 }, /Temperature rising/],
    [{ transformer_temperature: 74 }, /Temperature falling/],
    [{ loading_percent: 100 }, /Load increased/],
    [{ loading_percent: 80 }, /Load reduced/],
    [{ phase_imbalance_percent: 8 }, /Phase currents differ/],
    [{}, /No large change/],
  ];
  for (const [update, pattern] of cases) assert.match(changeNote({ telemetry: { ...qualified, ...update }, history: [before], analysis: { status: 'NORMAL' } }), pattern);
  assert.match(changeNote({ telemetry: qualified, history: [before], analysis: { status: 'UNKNOWN' } }), /insufficient/);
});
function source() {
  return {
    id: 'asset-live', source: 'industrial', revision: 9,
    telemetry: { ...qualified }, analysis: { health_index: 99, operating_stress_index: 99, stress, status: 'NORMAL' },
    inputs: { load_percent: 77 }, settings: { critical_temperature: 125 },
    fault: { kind: 'cooling_failure', until_s: 800 }, trip: { reason: 'Later trip' }, scenario: 'current-scenario',
    prediction: { minutes_to_critical: 9 }, elapsed_s: 900, breaker: 'OPEN', running: true,
    condition: { equivalent_age_hours: 123, insulation_consumed_percent: 9 },
    events: [{ timestamp: '2026-10-08T09:59:00Z', id: 'old' }, { timestamp: '2026-10-08T10:03:00Z', id: 'later' }],
    history: [{ ...qualified, timestamp: oldTime, transformer_temperature: 65, status: 'WARNING', breaker: 'CLOSED', elapsed_s: 0, component_data_available: false }, { ...qualified, timestamp: currentTime }],
  };
}
test('legacy replay does not substitute latest health, settings, inputs, age or forecast', () => {
  const live = source(), replay = replaySnapshot(live, 0);
  assert.equal(replay.analysis.health_index, null);
  assert.deepEqual(replay.analysis.stress, {});
  assert.equal(replay.analysis.operating_stress_index, undefined);
  assert.deepEqual(replay.settings, {});
  assert.deepEqual(replay.inputs, {});
  assert.equal(replay.condition.equivalent_age_hours, null);
  assert.equal(replay.prediction.minutes_to_critical, null);
  assert.equal(replay.telemetry.transformer_temperature, 65);
  assert.equal(replay.elapsed_s, 0);
  assert.equal(replay.breaker, 'CLOSED');
  assert.equal(replay.running, false);
  assert.equal(replay.replay, true);
  assert.equal(replay.component_data_available, false);
  assert.ok(components(replay, 'industrial').every(c => c.value === null));
});
test('recorded replay uses the analysis and configuration retained at that observation', () => {
  const live = source();
  Object.assign(live.history[0], {
    component_data_available: true,
    analysis: { health_index: 62, status: 'WARNING', stress: { ...stress, thermal: 74 } },
    settings: { critical_temperature: 115 }, inputs: { load_percent: 105 },
    prediction: { minutes_to_critical: 17 }, equivalent_age_hours: 3,
    input_context: { revision: 3, scenario: 'recorded-scenario', fault: null, trip: null },
  });
  const snapshot = replaySnapshot(live, 0);
  assert.equal(snapshot.analysis.health_index, 62);
  assert.equal(snapshot.analysis.stress.thermal, 74);
  assert.equal(snapshot.settings.critical_temperature, 115);
  assert.equal(snapshot.inputs.load_percent, 105);
  assert.equal(snapshot.prediction.minutes_to_critical, 17);
  assert.equal(snapshot.condition.equivalent_age_hours, 3);
  assert.equal(snapshot.revision, 3);
  assert.equal(snapshot.scenario, 'recorded-scenario');
  assert.equal(snapshot.fault, null);
});
test('legacy replay cannot inherit a future fault or trip from the live state', () => {
  const live = source(), replay = replaySnapshot(live, 0);
  assert.ok(replay.fault == null, 'Unrecorded fault must be unavailable, not copied from the current run');
  assert.ok(replay.trip == null, 'Unrecorded trip must be unavailable, not copied from the current run');
  assert.notEqual(replay.scenario, live.scenario);
});
test('replay slices observations and events causally without mutating the source', () => {
  const live = source(), original = structuredClone(live), snapshot = replaySnapshot(live, 0);
  assert.equal(snapshot.history.length, 1);
  assert.deepEqual(snapshot.events.map(e => e.id), ['old']);
  assert.deepEqual(live, original);
  assert.equal(live.analysis.health_index, 99);
  assert.equal(live.telemetry.transformer_temperature, 76);
  assert.equal(replaySnapshot(live, -1), null);
  assert.equal(replaySnapshot(live, 100), null);
});
test('replay does not import later actions at the same simulation instant', () => {
  const live = source();
  live.history[0].event_cursor = 1;
  live.events = [{id:1,timestamp:live.history[0].timestamp},{id:2,timestamp:live.history[0].timestamp}];
  assert.deepEqual(replaySnapshot(live,0).events.map(e=>e.id),[1]);
  delete live.history[0].event_cursor;
  assert.deepEqual(replaySnapshot(live,0).events,[]);
});
test('change note uses an earlier identified action while simulation time is paused',()=>{
  const s={revision:2,analysis:{status:'WARNING'},telemetry:{timestamp:'2026-10-08T00:00:00Z',loading_percent:112,transformer_temperature:79},history:[{timestamp:'2026-10-08T00:00:00Z',loading_percent:70,transformer_temperature:79,input_context:{revision:1}}]};
  assert.match(changeNote(s),/^Load increased/);
});

test('zero-reduction study has one unchanged-input trajectory and no intervention affordance',()=>{
  const baseline=[{minute:0,temperature_c:79},{minute:60,temperature_c:83}];
  const p={available:true,baseline:{points:baseline},recommendation:{reduction_pct:0,points:structuredClone(baseline)}};
  const result=planPresentation(p);
  assert.equal(result.reduction,false);
  assert.equal(result.series.length,1);
  assert.equal(result.series[0].label,'Continue unchanged');
  assert.deepEqual(result.series[0].points,baseline);
  assert.match(result.status,/No intervention proposed/);
  assert.match(result.status,/not a safety clearance/);
});

test('real reduction preserves two distinct trajectories and the actual reduction label',()=>{
  const p={available:true,baseline:{points:[{minute:60,temperature_c:127}]},recommendation:{reduction_pct:20,points:[{minute:60,temperature_c:103}]}};
  const result=planPresentation(p);
  assert.equal(result.reduction,true);
  assert.equal(result.series.length,2);
  assert.equal(result.series[1].label,'Reduce demand 20%');
  assert.equal(result.series[1].points[0].temperature_c,103);
  assert.match(result.status,/simulated action/);
});

test('a held study cannot expose a stale recommendation as an actionable trajectory',()=>{
  const result=planPresentation({available:false,holds:['Declared input missing'],recommendation:{reduction_pct:30,points:[{minute:5,temperature_c:90}]}});
  assert.equal(result.available,false);
  assert.equal(result.reduction,false);
  assert.deepEqual(result.series,[]);
  assert.equal(result.status,'Declared input missing');
  assert.equal(planPresentation({available:true,recommendation:null}).series.length,0);
});

test('the prominent temperature uses its threshold breach even when combined health appears normal',()=>{
  const result=temperatureReading({telemetry:{quality:'qualified',transformer_temperature:131},settings:{temperature_warning:105,temperature_critical:125},analysis:{status:'NORMAL',health_index:91}},'industrial');
  assert.equal(result.value,131);
  assert.equal(result.critical,125);
  assert.equal(result.level,'CRITICAL');
  assert.equal(result.label,'Modelled hot-spot');
});

test('surface or unqualified channels are not promoted to modelled hot-spot observations',()=>{
  const s={telemetry:{quality:'qualified',transformer_temperature:0},settings:{temperature_warning:45,temperature_critical:55}};
  assert.deepEqual(temperatureReading(s,'prototype'),{value:0,warning:45,critical:55,level:'NORMAL',label:'Measured surface'});
  for(const quality of ['stale','unverified',undefined]){
    const result=temperatureReading({...s,telemetry:{quality,transformer_temperature:60}},'prototype');
    assert.equal(result.value,null);
    assert.equal(result.level,'UNKNOWN');
  }
  assert.equal(temperatureReading({telemetry:{quality:'qualified',transformer_temperature:80}},'industrial').critical,null);
});

test('a live surface probe remains visible without inventing a qualified condition',()=>{
  const s={telemetry:{quality:'unverified',transformer_temperature:20},settings:{temperature_warning:45,temperature_critical:55}};
  const packet={available:true,live:true,stale:false,probe_ok:true,surface_c:60};
  const reading=temperatureReading(s,'prototype',packet);
  assert.equal(reading.value,60);
  assert.equal(reading.label,'Measured surface');
  assert.equal(reading.level,'UNKNOWN');
  for(const invalid of [{stale:true},{live:false},{probe_ok:false},{surface_c:null}])assert.equal(temperatureReading(s,'prototype',{...packet,...invalid}).value,null);
  assert.equal(temperatureReading(s,'industrial',packet).value,null);
});

test('prototype health explains actual holds without substituting a score',()=>{
  const {healthHoldNote}=require('../web/halo-command.js');
  const s={connection:'live',analysis:{health_index:null},configuration_binding:{state:'unbound'}};
  assert.match(healthHoldNote(s,'prototype',{live:true,current_calibrated:false,calibration_status:'FAULT: No load current.'}),/No load current.*configuration/);
  assert.match(healthHoldNote({...s,connection:'stale'},'prototype'),/fresh ESP32/);
  assert.equal(healthHoldNote({...s,analysis:{health_index:0}},'prototype'),null);
  assert.equal(healthHoldNote(s,'industrial'),null);
});

test('prototype loading uses the 1 A rating and existing display current without changing its source',()=>{
  const {prototypeLoading}=require('../web/halo-command.js');
  const scope={values:{secondary_i:.6},derived:{active:true},history:[
    {at:oldTime,values:{secondary_i:0}},
    {at:currentTime,values:{secondary_i:1.25}},
    {at:currentTime,values:{secondary_i:null}}
  ]};
  const before=structuredClone(scope),result=prototypeLoading({},scope);
  assert.equal(result.value,60);assert.equal(result.ratedCurrent,1);assert.equal(result.estimated,true);
  assert.deepEqual(result.history.map(r=>r.loading_percent),[0,125,null]);
  assert.deepEqual(scope,before);
  assert.equal(prototypeLoading({connection:'stale',telemetry:{secondary_current:1}},null).value,null);
  assert.equal(prototypeLoading({connection:'live',telemetry:{secondary_current:0}},null).value,0);
  assert.equal(prototypeLoading({replay:true,telemetry:{secondary_current:.4}},null).value,40);
});

test('current-only demo health follows frontend loading without altering physical health holds',()=>{
  const {demoCurrentHealth}=require('../web/halo-command.js');
  for(const value of [0,60,80])assert.deepEqual(demoCurrentHealth({value}),{held:false,score:100,stress:0,status:'NORMAL',title:'Demo health'});
  assert.equal(demoCurrentHealth({value:90}).status,'WARNING');
  assert.equal(demoCurrentHealth({value:100}).score,80);
  assert.equal(demoCurrentHealth({value:120}).score,60);
  assert.equal(demoCurrentHealth({value:120}).status,'CRITICAL');
  assert.equal(demoCurrentHealth({value:250}).score,0);
  for(const value of [null,undefined,NaN,-1])assert.equal(demoCurrentHealth({value}).held,true);
  assert.equal(dialState({health_index:null,operating_stress_index:100}).held,true);
});

test('guided review remains on its selected simulation source while the revision advances',()=>{
  const context=reviewContext({id:'run-a',revision:3},'industrial');
  assert.equal(context.available,true);
  assert.equal(sameReviewSource(context,{id:'run-a',revision:4},'industrial'),true);
  assert.equal(sameReviewSource(context,{id:'run-b',revision:3},'industrial'),false);
  assert.equal(sameReviewSource(context,{id:'run-a'},'prototype'),false);
  assert.equal(sameReviewSource(context,{id:'run-a'},'industrial',true),false);
});

test('physical, missing and replay sources cannot launch the simulation review flow',()=>{
  const s={id:'asset-a',revision:3};
  for(const context of [reviewContext(null,'industrial'),reviewContext(s,'prototype'),reviewContext(s,'industrial',true)]){
    assert.equal(context.available,false);
    assert.equal(sameReviewSource(context,s,'industrial'),false);
  }
  assert.match(reviewContext(s,'prototype').note,/Simulation actions do not apply/);
  assert.match(reviewContext(s,'industrial',true).note,/Recorded evidence remains unchanged/);
});

test('observation response cannot survive changed inputs, a clock step, replay or source change',()=>{
  const pending=reviewContext({id:'run-a',revision:3},'industrial');
  assert.equal(sameObservationSource(pending,{id:'run-a',revision:3},'industrial'),true);
  assert.equal(sameObservationSource(pending,{id:'run-a',revision:4},'industrial'),false);
  assert.equal(sameObservationSource(pending,{id:'run-b',revision:3},'industrial'),false);
  assert.equal(sameObservationSource(pending,{id:'run-a',revision:3},'industrial',true),false);
  assert.equal(sameObservationSource(pending,{id:'run-a',revision:3},'prototype'),false);
  assert.equal(sameObservationSource({...pending,revision:null},{id:'run-a',revision:null},'industrial'),false);
});
