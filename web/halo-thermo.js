/* Thermometer instrument. Shows one temperature in °C with warning/critical ticks,
   validity, and a short trend. Labels come from the caller; the prototype uses it
   for the DS18B20 surface probe only and never renames it oil or winding. */
(function (root) {
  'use strict';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, d) => (finite(v) ? Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d }) : '—');

  function level(value, warning, critical) {
    if (!finite(value)) return 'UNKNOWN';
    if (finite(critical) && value >= critical) return 'CRITICAL';
    if (finite(warning) && value >= warning) return 'WARNING';
    return 'NORMAL';
  }
  function fillFraction(value, floor, ceiling) {
    if (!finite(value) || !finite(floor) || !finite(ceiling) || ceiling <= floor) return 0;
    return Math.max(0, Math.min(1, (value - floor) / (ceiling - floor)));
  }
  /* Sparkline path over the last `seconds`; gaps where the value is missing. */
  function sparkline(trend, seconds, width, height) {
    const rows = (Array.isArray(trend) ? trend : []).filter(r => r && finite(Date.parse(r.at)));
    const valid = rows.filter(r => finite(r.value_c));
    if (!valid.length) return { d: '', min: null, max: null };
    const end = Date.parse(rows[rows.length - 1].at), start = end - seconds * 1000;
    let min = Math.min(...valid.map(r => r.value_c)), max = Math.max(...valid.map(r => r.value_c));
    if (max - min < 2) { const mid = (max + min) / 2; min = mid - 1; max = mid + 1; }
    const x = at => Math.max(0, Math.min(1, (Date.parse(at) - start) / (seconds * 1000))) * (width - 4) + 2;
    const y = v => height - 4 - (v - min) / (max - min) * (height - 8);
    let d = '', connected = false;
    for (const r of rows) {
      if (!finite(r.value_c) || Date.parse(r.at) < start) { connected = false; continue; }
      d += `${connected ? 'L' : 'M'}${x(r.at).toFixed(1)},${y(r.value_c).toFixed(1)} `; connected = true;
    }
    return { d, min, max };
  }

  let serial = 0;
  function create(host, options) {
    if (!host || !host.ownerDocument) throw new TypeError('A DOM host is required.');
    const opts = Object.assign({ floor: 0, ceiling: 100, eyebrow: 'TEMPERATURE', trendSeconds: 600 }, options || {});
    const doc = host.ownerDocument, id = `ht-${++serial}`;
    const TUBE = { x: 36, w: 18, top: 18, bottom: 196, bulbY: 222, bulbR: 23 };
    const panel = doc.createElement('section'); panel.className = 'halo-thermo'; panel.setAttribute('aria-labelledby', `${id}-title`);
    const ticks = []; for (let t = opts.floor; t <= opts.ceiling; t += (opts.ceiling - opts.floor) / 5) ticks.push(t);
    const yFor = v => TUBE.bottom - fillFraction(v, opts.floor, opts.ceiling) * (TUBE.bottom - TUBE.top);
    panel.innerHTML = `<div class="ht-heading"><div><p class="ht-eyebrow">${opts.eyebrow}</p><h3 id="${id}-title">Temperature</h3></div><span class="ht-origin"></span></div>
      <div class="ht-body">
        <svg class="ht-gauge" viewBox="0 0 120 252" role="img" aria-labelledby="${id}-title">
          <rect class="ht-tube" x="${TUBE.x}" y="${TUBE.top}" width="${TUBE.w}" height="${TUBE.bottom - TUBE.top + 8}" rx="9"/>
          <circle class="ht-bulb-back" cx="${TUBE.x + TUBE.w / 2}" cy="${TUBE.bulbY}" r="${TUBE.bulbR}"/>
          <rect class="ht-fill" x="${TUBE.x + 4}" y="${TUBE.bottom}" width="${TUBE.w - 8}" height="0" rx="5"/>
          <circle class="ht-bulb" cx="${TUBE.x + TUBE.w / 2}" cy="${TUBE.bulbY}" r="${TUBE.bulbR - 5}"/>
          <g class="ht-ticks">${ticks.map(t => `<line x1="${TUBE.x + TUBE.w + 4}" x2="${TUBE.x + TUBE.w + 10}" y1="${yFor(t)}" y2="${yFor(t)}"/><text x="${TUBE.x + TUBE.w + 14}" y="${yFor(t) + 4}">${fmt(t, 0)}</text>`).join('')}</g>
          <g class="ht-limits"></g>
        </svg>
        <div class="ht-readout"><div class="ht-value-row"><strong class="ht-value">—</strong><span class="ht-unit">°C</span></div><p class="ht-label"></p><p class="ht-status" role="status"></p><p class="ht-limits-text"></p>
          <svg class="ht-spark" viewBox="0 0 220 56" preserveAspectRatio="none" aria-hidden="true"><path class="ht-spark-path" d=""/></svg><p class="ht-spark-note"></p></div>
      </div>`;
    host.replaceChildren(panel);
    const q = s => panel.querySelector(s), fill = q('.ht-fill'), limits = q('.ht-limits'), spark = q('.ht-spark-path');
    const ns = 'http://www.w3.org/2000/svg';
    function limitMark(value, cls, text) {
      const y = yFor(value), g = doc.createElementNS(ns, 'g'); g.setAttribute('class', cls);
      const line = doc.createElementNS(ns, 'line'); for (const [k, v] of Object.entries({ x1: TUBE.x - 12, x2: TUBE.x + TUBE.w + 2, y1: y, y2: y })) line.setAttribute(k, v);
      const label = doc.createElementNS(ns, 'text'); label.setAttribute('x', TUBE.x - 14); label.setAttribute('y', y + 4); label.setAttribute('text-anchor', 'end'); label.textContent = text;
      g.append(line, label); return g;
    }
    function update(next) {
      const p = Object.assign({ value_c: null, valid: false, reason: '', label: 'Temperature', warning_c: null, critical_c: null, trend: [], quality: '', sourceLabel: '' }, next || {});
      const value = p.valid && finite(p.value_c) ? p.value_c : null, lvl = level(value, p.warning_c, p.critical_c);
      panel.dataset.level = lvl; panel.dataset.quality = p.quality || '';
      q('h3').textContent = p.label; q('.ht-origin').textContent = [p.sourceLabel, p.quality].filter(Boolean).join(' · ');
      const top = yFor(value === null ? opts.floor : value); fill.setAttribute('y', top); fill.setAttribute('height', Math.max(0, TUBE.bottom - top + 6));
      q('.ht-value').textContent = value === null ? '—' : fmt(value, 1);
      q('.ht-label').textContent = value === null ? 'Unavailable' : lvl === 'CRITICAL' ? 'Critical limit reached' : lvl === 'WARNING' ? 'Above warning level' : 'Within limits';
      q('.ht-status').textContent = value === null ? (p.reason || 'No valid reading.') : (p.reason || '');
      limits.replaceChildren();
      if (finite(p.warning_c)) limits.append(limitMark(p.warning_c, 'ht-warning', `W ${fmt(p.warning_c, 0)}`));
      if (finite(p.critical_c)) limits.append(limitMark(p.critical_c, 'ht-critical', `C ${fmt(p.critical_c, 0)}`));
      q('.ht-limits-text').textContent = finite(p.critical_c) ? `Warning ${fmt(p.warning_c, 0)} °C · critical ${fmt(p.critical_c, 0)} °C (commissioned surface limit)` : 'Critical reference unavailable · no commissioned limit';
      const line = sparkline(p.trend, opts.trendSeconds, 220, 56);
      spark.setAttribute('d', line.d);
      q('.ht-spark-note').textContent = line.d ? `Last ${Math.round(opts.trendSeconds / 60)} min · ${fmt(line.min, 1)}–${fmt(line.max, 1)} °C` : 'No trend yet';
      panel.setAttribute('aria-label', `${p.label}: ${value === null ? 'unavailable' : fmt(value, 1) + ' degrees Celsius'} · ${lvl}`);
    }
    update(null);
    return { update, destroy() { panel.remove(); } };
  }

  const api = { create, math: { level, fillFraction, sparkline } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloThermo = api;
})(typeof window !== 'undefined' ? window : globalThis);
