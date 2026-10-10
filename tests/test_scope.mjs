import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { math, presets } = require('../web/halo-scope.js');
const thermo = require('../web/halo-thermo.js').math;

test('per-division steps are 1-2-5 and fit the span', () => {
  assert.equal(math.perDivision(4, 4), 1);
  assert.equal(math.perDivision(6, 4), 2);
  assert.equal(math.perDivision(17, 4), 5);
  assert.equal(math.perDivision(325, 4), 100);
  assert.equal(math.perDivision(0.9, 4), 0.5);
  assert.equal(math.perDivision(0, 4), null); assert.equal(math.perDivision(NaN, 4), null);
});
test('waveform scale is symmetric and holds the largest peak within four divisions', () => {
  const s = math.waveformScale([230, 12]);
  assert.ok(s.peak > 325 && s.peak < 326);
  assert.equal(s.perDiv * 4, s.max); assert.equal(s.min, -s.max); assert.ok(s.max >= s.peak);
  assert.equal(math.waveformScale([null, undefined]).perDiv, 1);
  assert.equal(math.waveformScale([0.61]).max, 2, '0.86 A peak → 0.5 A/div on the 1-2-5 ladder');
});
test('trend scale is zero-based for non-negative data and encloses every value', () => {
  const s = math.trendScale([11.2, 11.9, 12.1, null, NaN]);
  assert.equal(s.min, 0); assert.ok(s.max >= 12.1); assert.equal(s.empty, false);
  assert.ok((s.max - s.min) / s.perDiv <= 8 + 1e-9);
  const flat = math.trendScale([12, 12, 12]);
  assert.ok(flat.max >= 12 && flat.max > flat.min, 'constant data still has a non-degenerate axis');
  const negative = math.trendScale([-5, -5]);
  assert.ok(negative.min <= -5 && negative.max > negative.min);
  assert.equal(math.trendScale([]).empty, true);
});
test('reconstruction uses √2·RMS at 50 Hz', () => {
  const v = math.instant(12, 5);
  assert.ok(Math.abs(v - 12 * Math.SQRT2) < 1e-9);
  assert.equal(math.instant(null, 5), null); assert.equal(math.instant(-1, 5), null);
});
test('prototype preset distinguishes measured and dashed estimated current series', () => {
  const p = presets.prototype();
  assert.deepEqual(p.plots.map(x => x.id), ['voltage', 'current']);
  assert.deepEqual(p.plots[0].channels.map(c => c.id), ['primary_v', 'secondary_v']);
  const expected = p.plots[1].channels.find(c => c.id === 'secondary_i_expected');
  assert.equal(expected.dashed,true);assert(!expected.trendOnly);assert.match(expected.label,/estimated/);
  assert.equal(p.plots[1].channels.find(c=>c.id==='primary_i_expected').dashed,true);
  assert.ok(p.plots.every(plot => plot.channels.every(c => c.phase === 0)), 'bench channels never claim a phase relationship');
});
test('thermometer level and fill follow the thresholds', () => {
  assert.equal(thermo.level(31, 50, 55), 'NORMAL'); assert.equal(thermo.level(52, 50, 55), 'WARNING'); assert.equal(thermo.level(55, 50, 55), 'CRITICAL');
  assert.equal(thermo.level(null, 50, 55), 'UNKNOWN'); assert.equal(thermo.level(90, null, null), 'NORMAL');
  assert.equal(thermo.fillFraction(50, 0, 100), 0.5); assert.equal(thermo.fillFraction(150, 0, 100), 1); assert.equal(thermo.fillFraction(null, 0, 100), 0);
  const spark = thermo.sparkline([{ at: '2026-10-10T10:00:00Z', value_c: 30 }, { at: '2026-10-10T10:00:02Z', value_c: null }, { at: '2026-10-10T10:00:04Z', value_c: 31 }], 600, 220, 56);
  assert.equal((spark.d.match(/M/g) || []).length, 2, 'a missing sample breaks the line');
  assert.equal(thermo.sparkline([], 600, 220, 56).d, '');
});
