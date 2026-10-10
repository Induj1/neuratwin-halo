import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { MAP, ALL_OFF, math } = require('../web/halo-loads.js');

test('UI loads map M1→load1, M2→load2, M3→load4 and M4 to nothing', () => {
  assert.deepEqual(MAP.map(m => [m.ui, m.hw, m.load]), [['M1', 'load1', 1], ['M2', 'load2', 2], ['M3', 'load4', 4], ['M4', null, null]]);
  assert.deepEqual(math.requestFor('M1', true), { load: 1, state: true });
  assert.deepEqual(math.requestFor('M3', false), { load: 4, state: false });
  assert.equal(math.requestFor('M4', true), null);
  assert.equal(math.requestFor('M9', true), null);
  for (const m of MAP) if (!m.isolated) assert.notEqual(m.load, 3);
  assert.deepEqual(ALL_OFF, { load1: false, load2: false, load4: false });
  assert.ok(!('load3' in ALL_OFF));
});
test('reported state reads the board loads object by hardware name; M4 and unknown values are null', () => {
  const loads = { load1: true, load2: false, load4: true, loads_on: 2 };
  assert.equal(math.reportedState('M1', loads), true); assert.equal(math.reportedState('M2', loads), false); assert.equal(math.reportedState('M3', loads), true);
  assert.equal(math.reportedState('M4', loads), null); assert.equal(math.reportedState('M1', null), null); assert.equal(math.reportedState('M1', {}), null);
});
test('gate order: unconfigured, no reading, stale, locked, latched, cutoff, busy, then enabled', () => {
  const ok = { configured: true, available: true, stale: false, control_enabled: true, latched: false, cutoff: false, busy: false };
  assert.equal(math.gate(ok).enabled, true);
  assert.match(math.gate({ ...ok, configured: false }).reason, /HALO_ESP32_URL/);
  assert.match(math.gate({ ...ok, available: false }).reason, /No board reading/);
  assert.match(math.gate({ ...ok, stale: true }).reason, /stale/);
  assert.match(math.gate({ ...ok, control_enabled: false }).reason, /HALO_ALLOW_CONTROL/);
  assert.match(math.gate({ ...ok, latched: true }).reason, /latched/);
  assert.match(math.gate({ ...ok, cutoff: true }).reason, /Restore supply/);
  assert.equal(math.gate({ ...ok, busy: true }).enabled, false);
  assert.equal(math.gate({ ...ok, control_enabled: undefined }).enabled, true, 'unknown control flag is not treated as locked; the server answers 423');
});
test('cutoff state machine: M4 on → all-off delivered → restore; failure keeps restore blocked', () => {
  let s = math.idle();
  s = math.reduce(s, { type: 'm4_on', boot_id: 'b1', at: '2026-10-10T10:00:00Z' });
  assert.equal(s.active, true); assert.equal(s.delivered, false);
  assert.equal(math.reduce(s, { type: 'restore' }).active, true, 'cannot restore before delivery');
  const failed = math.reduce(s, { type: 'alloff_failed', reason: 'Locked: control off' });
  assert.equal(failed.delivered, false); assert.match(failed.reason, /Locked/);
  const delivered = math.reduce(s, { type: 'alloff_ok' });
  assert.equal(delivered.delivered, true); assert.equal(delivered.reason, null);
  assert.equal(math.reduce(delivered, { type: 'restore' }).active, false);
});
test('a live reading with every branch off counts as delivery; a board reboot clears the cutoff', () => {
  const s = math.reduce(math.idle(), { type: 'm4_on', boot_id: 'b1' });
  assert.equal(math.reduce(s, { type: 'reading', boot_id: 'b1', loads_on: 2 }).delivered, false);
  assert.equal(math.reduce(s, { type: 'reading', boot_id: 'b1', loads_on: 0 }).delivered, true);
  assert.equal(math.reduce(s, { type: 'reading', boot_id: 'b2', loads_on: 2 }).active, false);
  assert.equal(math.reduce(math.idle(), { type: 'reading', boot_id: 'b1', loads_on: 0 }).active, false);
  assert.equal(math.reduce(undefined, { type: 'nonsense' }).active, false);
});
test('server errors are described by status', () => {
  const e = (status, message) => Object.assign(Error(message), { status });
  assert.match(math.describeError(e(423, 'Physical load switching is locked.')), /^Locked:/);
  assert.match(math.describeError(e(503, 'ESP32 unreachable at http://x')), /^Board unreachable:/);
  assert.match(math.describeError(e(401, 'Operator session required.')), /sign-in/);
  assert.equal(math.describeError(e(500, 'boom')), 'boom');
  assert.equal(math.describeError(null), 'Request failed.');
});
