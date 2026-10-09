import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { math } = require('../web/halo-waveform.js');
const close = (actual, expected, tolerance = 1e-9) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test('50 Hz sinusoid uses RMS-to-peak conversion and a 20 ms period', () => {
  close(math.instant(12, 5), 12 * Math.SQRT2);
  close(math.instant(12, 15), -12 * Math.SQRT2);
  close(math.instant(12, 25), math.instant(12, 5));
  const values = Array.from({ length: 1000 }, (_, i) => math.instant(12, i * .02));
  close(Math.sqrt(values.reduce((sum, n) => sum + n * n, 0) / values.length), 12);
});
test('balanced three-phase currents cancel at every sampled point', () => {
  const phase = [0, -2 * Math.PI / 3, 2 * Math.PI / 3];
  close(math.neutralPhasor([100, 100, 100]).rms, 0);
  for (let t = 0; t <= 40; t += .37) close(phase.reduce((sum, p) => sum + math.instant(100, t, p), 0), 0);
});
test('unbalanced neutral is a phasor sum, not a sum of RMS magnitudes', () => {
  const rms = [120, 100, 80], phase = [0, -2 * Math.PI / 3, 2 * Math.PI / 3];
  const n = math.neutralPhasor(rms);
  close(n.rms, Math.sqrt(1200));
  for (let t = 0; t <= 40; t += .63) close(rms.reduce((sum, r, i) => sum + math.instant(r, t, phase[i]), 0) + math.instant(n.rms, t, n.phase), 0);
});
test('zero is valid data; missing, negative, strings and nonfinite values are unavailable', () => {
  assert.equal(math.instant(0, 5), 0);
  for (const value of [null, undefined, NaN, Infinity, -1, '12']) assert.equal(math.finiteRms(value), null);
  assert.equal(math.neutralPhasor([10, null, 10]), null);
  const model = math.buildChannels({ mode: 'prototype', telemetry: { secondary_current: 0, primary_current: null } });
  assert.equal(model.channels[1].rms, 0);
  assert.equal(model.channels[0].rms, null);
});
test('prototype does not manufacture three-phase channels or missing primary current', () => {
  const model = math.buildChannels({ mode: 'prototype', telemetry: { current_a: .31, primary_v: 230, secondary_v: 12 } });
  assert.equal(model.channels.length, 2);
  assert.equal(model.channels[0].rms, null);
  assert.equal(model.channels[1].rms, .31);
  assert.equal(model.unit, 'A');
  const voltage = math.buildChannels({ mode: 'prototype', telemetry: { primary_v: 230, secondary_v: 12 } }, 'voltage');
  assert.deepEqual(voltage.channels.map(c => c.rms), [230, 12]);
  assert.equal(voltage.unit, 'V');
});
test('industrial phase data is required; scalar current and line voltage do not create phase traces', () => {
  const p = { mode: 'industrial', telemetry: { secondary_current: 30, primary_voltage: 11000 } };
  assert.ok(math.buildChannels(p).channels.every(c => c.rms === null));
  assert.ok(math.buildChannels(p, 'voltage').channels.every(c => c.rms === null));
});
test('neutral trace requires supplied, consistent neutral RMS and complete phase currents', () => {
  const packet = { mode: 'industrial', telemetry: { phase_current_a: 120, phase_current_b: 100, phase_current_c: 80, neutral_current: Math.sqrt(1200) } };
  close(math.buildChannels(packet).channels[3].rms, Math.sqrt(1200));
  packet.telemetry.neutral_current = 300;
  assert.equal(math.buildChannels(packet).channels[3].rms, null);
  delete packet.telemetry.neutral_current;
  assert.equal(math.buildChannels(packet).channels[3].rms, null);
});
test('axis stays finite for missing and zero channels and contains nonzero peaks', () => {
  assert.equal(math.axisLimit([{ rms: null }, { rms: 0 }]), 1);
  const bound = math.axisLimit([{ rms: 12 }, { rms: 230 }]);
  assert.ok(Number.isFinite(bound) && bound > 230 * Math.SQRT2);
});
test('industrial current scale holds its rated reference as loading changes', () => {
  const packet = { mode: 'industrial', referenceCurrent: 100 };
  const low = math.axisScale([{ rms: 20 }, { rms: 0 }], packet);
  const high = math.axisScale([{ rms: 150 }, { rms: 30 }], packet);
  close(low.limit, 160 * Math.SQRT2);
  close(high.limit, low.limit);
  assert.equal(low.kind, 'nameplate');
  assert.equal(high.expanded, false);
  const empty = math.axisScale([{ rms: null }], packet);
  close(empty.limit, low.limit);
  assert.ok(math.buildChannels({ ...packet, telemetry: {} }).channels.every(c => c.rms === null));
});
test('current scale expands only when an available peak exceeds the rated reference', () => {
  const packet = { mode: 'industrial', referenceCurrent: 100 };
  const boundary = math.axisScale([{ rms: 160 }], packet);
  assert.equal(boundary.expanded, false);
  const overload = math.axisScale([{ rms: 190 }], packet);
  assert.equal(overload.expanded, true);
  assert.ok(overload.limit > 190 * Math.SQRT2);
});
test('prototype, voltage and missing-rating views retain explicit auto scaling', () => {
  const channels = [{ rms: 12 }];
  for (const packet of [{ mode: 'prototype', referenceCurrent: 100 }, { mode: 'industrial' }, { mode: 'industrial', referenceCurrent: 0 }, { mode: 'industrial', referenceCurrent: NaN }]) {
    const result = math.axisScale(channels, packet);
    assert.equal(result.kind, 'auto');
    close(result.limit, math.axisLimit(channels));
  }
  assert.equal(math.axisScale(channels, { mode: 'industrial', referenceCurrent: 100 }, 'voltage').kind, 'auto');
});
