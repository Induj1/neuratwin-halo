import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { math, createBuffer, create } = require('../web/halo-esp32.js');

const reading = (extra = {}) => ({
  device_id: 'HALO-ESP32', boot_id: 'b1', sequence: 7, uptime_ms: 1000, mains_present: true,
  primary_v: 229.4, primary_current_a: 0.05, primary_current_method: 'calculated', secondary_v: 11.9, current_a: 0.61, expected_current_a: 0.61,
  surface_c: 31.2, temperature_probe_ok: true, current_calibrated: true, calibration_status: 'OK',
  loads: { load1: true, load2: true, load4: false, loads_on: 2 }, relay_states: [true, true, false, false], quality_flags: [], ...extra,
});

test('live reply becomes a live packet with primary/secondary channels and loads', () => {
  const p = math.normalize({ live: true, stale: false, reading: reading() }, Date.parse('2026-10-10T10:00:00Z'));
  assert.equal(p.available, true); assert.equal(p.live, true); assert.equal(p.stale, false);
  assert.equal(p.primary.v, 229.4); assert.equal(p.primary.i_method, 'calculated');
  assert.equal(p.secondary.i, 0.61); assert.equal(p.surface_c, 31.2);
  assert.deepEqual(p.loads, { load1: true, load2: true, load4: false, loads_on: 2 });
  assert.equal(p.age_s, 0);
});
test('stale reply keeps the cached values, marks them stale and ages them from readings_at', () => {
  const now = Date.parse('2026-10-10T10:00:30Z');
  const p = math.normalize({ live: false, stale: true, error: 'ESP32 unreachable', readings_at: '2026-10-10T10:00:00Z', reading: reading() }, now);
  assert.equal(p.stale, true); assert.equal(p.live, false); assert.equal(p.error, 'ESP32 unreachable');
  assert.equal(Math.round(p.age_s), 30); assert.equal(p.secondary.v, 11.9);
});
test('missing reading or non-numeric channels become unavailable, not zero', () => {
  assert.equal(math.normalize({ live: true, reading: null }).available, false);
  const p = math.normalize({ live: true, reading: reading({ surface_c: null, temperature_probe_ok: false, primary_v: '229', relay_states: [true] }) });
  assert.equal(p.surface_c, null); assert.equal(p.probe_ok, false); assert.equal(p.primary.v, null); assert.equal(p.relay_states, null);
});
test('a reading older than three poll intervals is treated as stale even after a successful call', () => {
  const p = math.normalize({ live: true, reading: reading() });
  assert.equal(math.freshness({ ...p, age_s: 5 }, 2).stale, false);
  assert.equal(math.freshness({ ...p, age_s: 7 }, 2).stale, true);
  assert.equal(math.freshness({ ...p, age_s: 7 }, 2).live, false);
});
test('buffer ignores duplicate (boot, sequence), keeps order and clears on reboot', () => {
  const b = createBuffer(3);
  const p = seq => math.normalize({ live: true, reading: reading({ sequence: seq }) });
  assert.equal(b.push(p(1)), true); assert.equal(b.push(p(1)), false); assert.equal(b.push(p(2)), true);
  b.push(p(3)); b.push(p(4));
  assert.deepEqual(b.rows().map(r => r.sequence), [2, 3, 4]);
  assert.equal(b.push(math.normalize({ live: true, reading: reading({ boot_id: 'b2', sequence: 1 }) })), true);
  assert.deepEqual(b.rows().map(r => r.sequence), [1]);
  assert.equal(b.push(math.normalize({ live: false, stale: false, reading: null })), false);
});
test('firmware-calculated primary current is not exposed as measured', () => {
  const live = math.normalize({ live: true, reading: reading() });
  const s = math.scopePacket(live, [], { configured: true });
  assert.equal(s.values.primary_i, null); assert.match(s.notes.primary_i, /No primary/); assert.equal(s.quality, 'live');assert(s.values.primary_i_expected>0);
  const measured = math.scopePacket(math.normalize({ live: true, reading: reading({ primary_current_method: 'measured' }) }), [], { configured: true });
  assert.equal(measured.notes.primary_i, 'measured');
  assert.equal(math.scopePacket(math.math ? null : null, [], { configured: false }).quality, 'integration off');
  assert.equal(math.scopePacket(null, [], { configured: true }).quality, 'unreachable');
  assert.equal(math.scopePacket({ ...live, stale: true }, [], { configured: true }).quality, 'stale');
});
test('thermometer packet is surface-only, respects probe validity and uses prototype thresholds', () => {
  const live = math.normalize({ live: true, reading: reading() });
  const t = math.thermoPacket(live, [{ at: live.at, values: { surface_c: 31.2 } }], { temperature_warning: 50, temperature_critical: 55 });
  assert.equal(t.value_c, 31.2); assert.equal(t.valid, true); assert.equal(t.kind, 'surface'); assert.match(t.label, /Surface/);
  assert.equal(t.warning_c, 50); assert.equal(t.critical_c, 55); assert.equal(t.trend.length, 1);
  const bad = math.thermoPacket(math.normalize({ live: true, reading: reading({ surface_c: 85, quality_flags: ['surface_invalid'] }) }), [], {});
  assert.equal(bad.valid, false); assert.equal(bad.value_c, null); assert.match(bad.reason, /invalid/);
  assert.equal(math.thermoPacket(null, [], null).warning_c, null);
});
test('effective resistance is 39 Ω divided by the branches that are on', () => {
  assert.equal(math.effectiveResistance(1), 39); assert.equal(math.effectiveResistance(2), 19.5); assert.equal(math.effectiveResistance(3), 13);
  assert.equal(math.effectiveResistance(0), null); assert.equal(math.effectiveResistance(null), null);
});
test('measured zero remains zero in the scope and history alongside independent estimates', () => {
  const zero = seq => math.normalize({ live: true, reading: reading({ sequence: seq, current_a: 0, primary_current_a: 0, secondary_v: 11.7, primary_v: 230, loads: { load1: true, load2: true, load4: false, loads_on: 2 } }) });
  const b = createBuffer(); for (const s of [1, 2, 3]) b.push(zero(s));
  const d = math.deriveCurrents(zero(3), b.rows());
  assert.equal(d.active, true); assert.equal(d.r_eff, 19.5);
  assert.ok(Math.abs(d.secondary_i - 11.7 / 19.5) < 1e-9);
  assert.ok(Math.abs(d.primary_i - 11.7 * (11.7 / 19.5) / 230) < 1e-9);
  const s = math.scopePacket(zero(3), b.rows(), { configured: true });
  assert.equal(s.values.secondary_i,0);assert.equal(s.values.primary_i,null);assert.ok(Math.abs(s.values.secondary_i_expected-.6)<1e-9);
  assert.ok(s.history.every(r=>r.values.secondary_i===0&&r.values.secondary_i_expected>.5));assert.equal(s.derived.disagreement,true);
});
test('estimates are independent of current and require live voltage and active loads', () => {
  const live = math.normalize({ live: true, reading: reading() });
  const b = createBuffer(); b.push(live);
  assert.equal(math.deriveCurrents(live, b.rows()).active, true);
  const zero = seq => math.normalize({ live: true, reading: reading({ sequence: seq, current_a: 0, primary_current_a: 0 }) });
  const short = createBuffer(); short.push(zero(1));
  assert.equal(math.deriveCurrents(zero(1), short.rows()).active, true);
  assert.equal(math.deriveCurrents({...live,live:false,stale:true},b.rows()).active,false);
  const off = math.normalize({ live: true, reading: reading({ current_a: 0, primary_current_a: 0, loads: { load1: false, load2: false, load4: false, loads_on: 0 } }) });
  const offBuffer = createBuffer(); for (let i = 1; i <= 3; i++) offBuffer.push(Object.assign({}, off, { sequence: i }));
  const d = math.deriveCurrents(off, offBuffer.rows());
  assert.equal(d.active, false); assert.equal(d.r_eff, null);
  assert.equal(math.scopePacket(off, offBuffer.rows(), { configured: true }).values.secondary_i, 0, 'zero with no load is a genuine zero');
});
test('client never throws from poll: unconfigured, unreachable and live paths', async () => {
  const calls = [];
  let configured = false, fail = false;
  const api = async (path, body) => {
    calls.push([path, body]);
    if (path === '/esp32/status') return { configured, poll_seconds: 2, control_enabled: true };
    if (path === '/esp32/readings') { if (fail) { const e = Error('ESP32 unreachable'); e.status = 503; throw e; } return { live: true, stale: false, reading: reading() }; }
    if (path === '/esp32/loads') return { ok: true, loads: { load1: false, load2: true, load4: false, loads_on: 1 } };
    throw Error('unexpected ' + path);
  };
  const client = create(api, { statusEveryMs: 0 });
  let p = await client.poll();
  assert.equal(p.available, false); assert.equal(calls.filter(c => c[0] === '/esp32/readings').length, 0);
  configured = true; fail = true; p = await client.poll();
  assert.equal(p.available, false); assert.equal(p.unreachable, true); assert.equal(p.status_code, 503);
  fail = false; p = await client.poll();
  assert.equal(p.live, true); assert.equal(client.history().length, 1);
  const r = await client.setLoads({ load: 1, state: false });
  assert.deepEqual(calls.at(-1), ['/esp32/loads', { load: 1, state: false }]);
  assert.deepEqual(client.applyLoads(r.loads).loads, { load1: false, load2: true, load4: false, loads_on: 1 });
});

test('report snapshots separate observed zero or missing from estimates and hold conflicted screening', () => {
  for (const raw of [0, null]) {
    const b=createBuffer();let p;
    for (let sequence=1;sequence<=3;sequence++) {
      p=math.normalize({live:true,reading:reading({sequence,current_a:raw,primary_current_a:raw,loads:{load1:true,load2:true,load4:false,loads_on:2}})});b.push(p);
    }
    const snapshot=math.displaySnapshot(p,b.rows(),{configured:true}),scope=math.scopePacket(p,b.rows(),{configured:true});
    assert.equal(snapshot.channels.secondary_current.value,scope.values.secondary_i);
    assert.equal(snapshot.channels.secondary_current.raw,raw);
    assert.equal(snapshot.version,'prototype-display-2');assert.equal(snapshot.channels.secondary_current.value,raw);
    assert.equal(snapshot.channels.secondary_current.source,raw===null?'unavailable':'measured');
    assert(snapshot.estimates.secondary_current.value>0);assert.equal(snapshot.disagreement,raw===0);
    assert.equal(snapshot.loading_percent,raw===null?null:0);assert.equal(snapshot.demo_health,null);
    assert.equal(snapshot.estimated_loading_percent,100*snapshot.estimates.secondary_current.value);
    const stale=math.displaySnapshot({...p,stale:true,live:false},b.rows(),{configured:true});
    assert.equal(stale.loading_percent,null);assert.equal(stale.demo_health,null);
    assert.equal(stale.channels.secondary_current.quality,'stale');
    assert.equal(stale.channels.secondary_current.value,null);assert.equal(stale.estimates.secondary_current.value,null);
  }
});

test('invalid channels stay distinct from missing and cannot drive estimates',()=>{
 const p=math.normalize({live:true,reading:reading({current_a:99,secondary_v:99})});
 const s=math.displaySnapshot(p,[],{configured:true});
 assert.equal(s.channels.secondary_current.value,null);assert.equal(s.channels.secondary_current.raw,99);assert.equal(s.channels.secondary_current.quality,'invalid');
 assert.equal(s.estimates.secondary_current.value,null);assert.equal(s.channels.secondary_voltage.quality,'invalid');
});
test('history retains each estimate and supplied acquisition timestamp without rewriting observations',()=>{
 const b=createBuffer();let p;
 for(const [sequence,current_a,secondary_v] of [[1,0,12],[2,.3,6],[3,null,10]]){
  p=math.normalize({live:true,readings_at:`2026-10-10T10:00:0${sequence}Z`,reading:reading({sequence,current_a,secondary_v})},Date.parse('2026-10-10T10:00:04Z'));b.push(p);
 }
 const before=b.rows(),s=math.scopePacket(p,b.rows(),{configured:true});
 assert.deepEqual(s.history.map(r=>r.values.secondary_i),[0,.3,null]);assert.deepEqual(s.history.map(r=>r.values.secondary_i_expected),[12/19.5,6/19.5,10/19.5]);
 assert.equal(s.history[0].at,'2026-10-10T10:00:01.000Z');assert.deepEqual(b.rows(),before);
});
test('report display buffer is bounded, duplicate-safe and cleared on board reboot', async () => {
  let sequence=0,boot_id='first';
  const client=create(async path=>path==='/esp32/status'?{configured:true}:{live:true,reading:reading({sequence,boot_id})});
  for(sequence=0;sequence<305;sequence++)await client.poll();
  assert.equal(client.displayHistory().length,300);
  sequence=304;await client.poll();assert.equal(client.displayHistory().length,300);
  boot_id='second';sequence=0;await client.poll();
  assert.equal(client.displayHistory().length,1);assert.equal(client.displayHistory()[0].boot_id,'second');
  client.reset();assert.deepEqual(client.displayHistory(),[]);
});
