/* Oscilloscope-style instrument. Two stacked plots (voltage, current) on one time base.
   Waveform mode reconstructs √2·RMS sine curves at 50 Hz; trend mode plots RMS over time.
   The hardware supplies RMS summaries only, so neither mode is a sampled waveform. */
(function (root) {
  'use strict';
  const TAU = Math.PI * 2, SQRT2 = Math.SQRT2;
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const COLORS = { primary: '#f0a95a', secondary: '#5fd1c6', reference: '#b9c7bf', neutral: '#c9a5ff' };
  const DIVISIONS_X = 10, DIVISIONS_Y = 8;

  function instant(rms, ms, phase, frequency) {
    if (!finite(rms) || rms < 0 || !finite(ms)) return null;
    return SQRT2 * rms * Math.sin(TAU * (finite(frequency) ? frequency : 50) * ms / 1000 + (finite(phase) ? phase : 0));
  }
  /* Nice 1-2-5 step so that `span` fits within `divisions` divisions. */
  function perDivision(span, divisions) {
    if (!finite(span) || span <= 0 || !finite(divisions) || divisions <= 0) return null;
    const raw = span / divisions, exponent = 10 ** Math.floor(Math.log10(raw)), mantissa = raw / exponent;
    return (mantissa <= 1 ? 1 : mantissa <= 2 ? 2 : mantissa <= 5 ? 5 : 10) * exponent;
  }
  /* Symmetric scale for waveform mode: peak fits in the upper four divisions. */
  function waveformScale(rmsValues) {
    const peak = Math.max(0, ...rmsValues.filter(finite).map(v => v * SQRT2));
    const perDiv = perDivision(peak, DIVISIONS_Y / 2) || 1;
    return { perDiv, min: -perDiv * DIVISIONS_Y / 2, max: perDiv * DIVISIONS_Y / 2, peak };
  }
  /* Trend scale: nice bounds that include every finite value, zero-based when all values are ≥ 0. */
  function trendScale(values) {
    const v = values.filter(finite);
    if (!v.length) return { perDiv: 1, min: 0, max: DIVISIONS_Y, empty: true };
    let low = Math.min(...v), high = Math.max(...v);
    if (low >= 0) low = 0;
    if (high === low) high = low + (Math.abs(low) || 1);
    let perDiv = perDivision(high - low, DIVISIONS_Y), min = Math.floor(low / perDiv) * perDiv, max = Math.ceil(high / perDiv) * perDiv;
    if ((max - min) / perDiv > DIVISIONS_Y) { perDiv = perDivision(max - min, DIVISIONS_Y); min = Math.floor(low / perDiv) * perDiv; max = Math.ceil(high / perDiv) * perDiv; }
    if (max === min) max = min + perDiv;
    return { perDiv, min, max, empty: false };
  }
  const fmt = (value, digits) => (finite(value) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits == null ? 2 : digits }) : 'Unavailable');
  const fmtDiv = value => (value >= 100 ? fmt(value, 0) : value >= 10 ? fmt(value, 1) : fmt(value, 3));

  function prototypePreset() {
    return {
      eyebrow: 'HARDWARE SCOPE', title: 'Primary and secondary · voltage and current',
      disclosure: 'Illustrative RMS reconstruction · 50 Hz assumed. The board reports RMS summaries at poll cadence; these curves are not sampled waveforms.',
      frequency: 50, windowMs: 40, trendSeconds: 300,
      plots: [
        { id: 'voltage', label: 'Voltage', unit: 'V', channels: [
          { id: 'primary_v', label: 'Primary', color: COLORS.primary, phase: 0 },
          { id: 'secondary_v', label: 'Secondary', color: COLORS.secondary, phase: 0 } ] },
        { id: 'current', label: 'Current', unit: 'A', channels: [
          { id: 'primary_i', label: 'Primary', color: COLORS.primary, phase: 0, dashed: true },
          { id: 'secondary_i', label: 'Secondary', color: COLORS.secondary, phase: 0 },
          { id: 'secondary_i_expected', label: 'Expected', color: COLORS.reference, phase: 0, trendOnly: true, dashed: true } ] },
      ],
      note: 'Single-phase bench · relative phase and power factor are not measured. Each curve uses an arbitrary phase reference; do not infer phase shift, harmonics or power factor.',
    };
  }

  let serial = 0;
  function create(host, config) {
    if (!host || !host.ownerDocument) throw new TypeError('A DOM host is required.');
    const cfg = config || prototypePreset(), doc = host.ownerDocument, win = doc.defaultView || root, id = `hs-${++serial}`;
    const reduce = win.matchMedia ? win.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    let packet = { values: {}, notes: {}, history: [] }, mode = 'waveform', paused = !!reduce.matches, visible = true, destroyed = false;
    let frame = 0, lastTick = 0, offset = 0, width = 640;
    const selected = new Map();
    const panel = doc.createElement('section'); panel.className = 'halo-scope'; panel.setAttribute('aria-labelledby', `${id}-title`);
    panel.innerHTML = `<div class="hs-heading"><div><p class="hs-eyebrow">${cfg.eyebrow}</p><h3 id="${id}-title">${cfg.title}</h3></div><span class="hs-origin"></span></div>
      <p class="hs-disclosure">${cfg.disclosure}</p>
      <div class="hs-toolbar"><div class="hs-modes" role="group" aria-label="Scope mode"><button type="button" data-hs-mode="waveform" aria-pressed="true">Waveform <span>40 ms</span></button><button type="button" data-hs-mode="trend" aria-pressed="false">Trend <span>${Math.round(cfg.trendSeconds / 60)} min</span></button></div><button type="button" class="hs-motion"></button></div>
      <div class="hs-plots"></div>
      <p class="hs-note">${cfg.note}</p>`;
    host.replaceChildren(panel);
    const q = s => panel.querySelector(s), plotsHost = q('.hs-plots'), motion = q('.hs-motion'), origin = q('.hs-origin');
    const ns = 'http://www.w3.org/2000/svg';
    const element = (name, attrs, text) => { const n = doc.createElementNS(ns, name); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v)); if (text !== undefined) n.textContent = text; return n; };
    const plots = cfg.plots.map(plot => {
      const box = doc.createElement('div'); box.className = 'hs-plot'; box.dataset.plot = plot.id;
      box.innerHTML = `<div class="hs-plot-head"><strong>${plot.label}</strong><span class="hs-scale"></span></div>
        <div class="hs-screen"><svg role="img" aria-label="${plot.label} scope"><g class="hs-grid"></g><g class="hs-traces"></g></svg><p class="hs-empty" hidden></p></div>
        <div class="hs-channels" role="group" aria-label="${plot.label} channels"></div>`;
      plotsHost.append(box);
      for (const c of plot.channels) selected.set(c.id, true);
      return { def: plot, box, svg: box.querySelector('svg'), grid: box.querySelector('.hs-grid'), traces: box.querySelector('.hs-traces'), scale: box.querySelector('.hs-scale'), channels: box.querySelector('.hs-channels'), empty: box.querySelector('.hs-empty') };
    });
    const rms = id => (finite(packet.values[id]) && packet.values[id] >= 0 ? packet.values[id] : null);
    const activeChannels = plot => plot.def.channels.filter(c => selected.get(c.id) !== false && !(mode === 'waveform' && c.trendOnly));
    function motionState() { motion.textContent = paused ? 'Play sweep' : 'Pause sweep'; motion.setAttribute('aria-pressed', String(!paused)); motion.hidden = mode !== 'waveform'; }
    function stopFrame() { if (frame) win.cancelAnimationFrame(frame); frame = 0; lastTick = 0; }
    function canAnimate() { return !destroyed && mode === 'waveform' && !paused && visible && !doc.hidden && panel.getClientRects().length > 0; }
    function schedule() { if (canAnimate() && !frame) frame = win.requestAnimationFrame(tick); }
    function tick(time) {
      frame = 0; if (!canAnimate()) { lastTick = 0; return; }
      if (!lastTick) lastTick = time;
      if (time - lastTick >= 32) { offset = (offset + Math.min(time - lastTick, 100) * .003) % (1000 / cfg.frequency); lastTick = time; drawPlots(); }
      schedule();
    }
    function drawPlots() { for (const plot of plots) draw(plot); }
    function draw(plot) {
      const left = 54, right = width - 14, top = 10, bottom = 170, H = 190;
      plot.svg.setAttribute('viewBox', `0 0 ${width} ${H}`);
      plot.grid.replaceChildren(); plot.traces.replaceChildren();
      const channels = activeChannels(plot).filter(c => mode === 'trend' || rms(c.id) !== null);
      const scale = mode === 'waveform' ? waveformScale(channels.map(c => rms(c.id))) : trendScale(packet.history.flatMap(r => channels.map(c => r.values[c.id])));
      const y = v => bottom - (v - scale.min) / (scale.max - scale.min) * (bottom - top);
      for (let i = 0; i <= DIVISIONS_Y; i++) {
        const value = scale.min + (scale.max - scale.min) * i / DIVISIONS_Y, yp = y(value), zero = Math.abs(value) < 1e-9;
        plot.grid.append(element('line', { x1: left, x2: right, y1: yp, y2: yp, class: zero ? 'hs-zero' : 'hs-line' }));
        if (i % 2 === 0) plot.grid.append(element('text', { x: left - 6, y: yp + 4, 'text-anchor': 'end' }, fmtDiv(value)));
      }
      for (let i = 0; i <= DIVISIONS_X; i++) {
        const xp = left + (right - left) * i / DIVISIONS_X;
        plot.grid.append(element('line', { x1: xp, x2: xp, y1: top, y2: bottom, class: i === DIVISIONS_X / 2 ? 'hs-zero' : 'hs-line' }));
      }
      plot.grid.append(element('text', { x: left, y: H - 3 }, mode === 'waveform' ? '0 ms' : `−${cfg.trendSeconds} s`));
      plot.grid.append(element('text', { x: right, y: H - 3, 'text-anchor': 'end' }, mode === 'waveform' ? `${cfg.windowMs} ms` : 'now'));
      plot.grid.append(element('text', { x: 6, y: top + 4, class: 'hs-unit' }, plot.def.unit));
      let drawn = 0;
      if (mode === 'waveform') {
        const x = ms => left + ms / cfg.windowMs * (right - left);
        for (const c of channels) {
          let d = '';
          for (let i = 0; i <= 240; i++) { const ms = i / 240 * cfg.windowMs, v = instant(rms(c.id), ms + offset, c.phase, cfg.frequency); d += `${i ? 'L' : 'M'}${x(ms).toFixed(2)},${y(v).toFixed(2)} `; }
          plot.traces.append(element('path', { d, stroke: c.color, fill: 'none', 'stroke-width': 2.2, 'stroke-dasharray': c.dashed ? '6 4' : 'none', 'vector-effect': 'non-scaling-stroke' })); drawn++;
        }
        plot.scale.textContent = `${fmtDiv(scale.perDiv)} ${plot.def.unit}/div · ${fmt(cfg.windowMs / DIVISIONS_X, 1)} ms/div`;
      } else {
        const rows = packet.history, end = rows.length ? Date.parse(rows[rows.length - 1].at) : Date.now(), start = end - cfg.trendSeconds * 1000;
        const x = at => left + Math.max(0, Math.min(1, (Date.parse(at) - start) / (cfg.trendSeconds * 1000))) * (right - left);
        for (const c of channels) {
          let d = '', connected = false, points = 0;
          for (const r of rows) {
            const v = r.values[c.id];
            if (!finite(v) || Date.parse(r.at) < start) { connected = false; continue; }
            d += `${connected ? 'L' : 'M'}${x(r.at).toFixed(2)},${y(v).toFixed(2)} `; connected = true; points++;
          }
          if (!points) continue;
          plot.traces.append(element('path', { d, stroke: c.color, fill: 'none', 'stroke-width': c.trendOnly ? 1.4 : 2.2, 'stroke-dasharray': c.dashed ? '6 4' : 'none', 'vector-effect': 'non-scaling-stroke' }));
          const last = [...rows].reverse().find(r => finite(r.values[c.id]));
          if (last) plot.traces.append(element('circle', { cx: x(last.at), cy: y(last.values[c.id]), r: 3.5, fill: c.color }));
          drawn++;
        }
        plot.scale.textContent = scale.empty ? 'No samples yet' : `${fmtDiv(scale.perDiv)} ${plot.def.unit}/div · ${fmt(cfg.trendSeconds / DIVISIONS_X, 0)} s/div`;
      }
      plot.empty.hidden = drawn > 0;
      plot.empty.textContent = plot.def.channels.some(c => rms(c.id) !== null) ? 'Select a channel to display it.' : 'No measurement for this plot.';
    }
    function renderChannels() {
      for (const plot of plots) {
        const focused = plot.channels.contains(doc.activeElement) ? doc.activeElement.dataset.hsChannel : null;
        plot.channels.replaceChildren();
        for (const c of plot.def.channels) {
          const value = rms(c.id), note = packet.notes && packet.notes[c.id] || '';
          const label = doc.createElement('label'); label.className = 'hs-channel'; label.style.setProperty('--hs-channel', c.color);
          if (mode === 'waveform' && c.trendOnly) label.classList.add('hs-trend-only');
          const input = doc.createElement('input'); input.type = 'checkbox'; input.dataset.hsChannel = c.id; input.checked = value !== null && selected.get(c.id) !== false; input.disabled = value === null || (mode === 'waveform' && c.trendOnly);
          input.addEventListener('change', () => { selected.set(c.id, input.checked); draw(plot); });
          const name = doc.createElement('span'); name.textContent = c.label;
          const reading = doc.createElement('strong'); reading.textContent = value === null ? 'Unavailable' : `${fmt(value, plot.def.unit === 'A' ? 3 : 1)} ${plot.def.unit} RMS`;
          const small = doc.createElement('small'); small.textContent = note || (mode === 'waveform' && c.trendOnly ? 'trend only' : '');
          label.title = `${c.label}: ${reading.textContent}${note ? ' · ' + note : ''}`;
          label.append(input, name, reading, small); plot.channels.append(label);
        }
        if (focused) plot.channels.querySelector(`[data-hs-channel="${focused}"]:not(:disabled)`)?.focus({ preventScroll: true });
      }
    }
    function rebuild() {
      for (const button of panel.querySelectorAll('[data-hs-mode]')) button.setAttribute('aria-pressed', String(button.dataset.hsMode === mode));
      origin.textContent = (packet.sourceLabel || 'Physical prototype') + (packet.quality ? ` · ${packet.quality}` : '');
      panel.dataset.quality = packet.quality || '';
      renderChannels(); drawPlots(); motionState();
      if (canAnimate()) schedule(); else stopFrame();
    }
    for (const button of panel.querySelectorAll('[data-hs-mode]')) button.addEventListener('click', () => { mode = button.dataset.hsMode; rebuild(); });
    motion.addEventListener('click', () => { paused = !paused; motionState(); if (paused) stopFrame(); else schedule(); });
    function visibility() { if (doc.hidden) stopFrame(); else schedule(); }
    function reduced(event) { if (event.matches) { paused = true; stopFrame(); motionState(); } }
    doc.addEventListener('visibilitychange', visibility); reduce.addEventListener?.('change', reduced);
    const resize = win.ResizeObserver ? new win.ResizeObserver(entries => { const w = entries[0]?.contentRect.width; if (w > 0) { width = Math.max(300, Math.round(w)); drawPlots(); } }) : null;
    resize?.observe(plots[0].box.querySelector('.hs-screen'));
    const observer = win.IntersectionObserver ? new win.IntersectionObserver(entries => { visible = !!entries[0]?.isIntersecting; if (visible) schedule(); else stopFrame(); }, { threshold: 0 }) : null;
    observer?.observe(panel);
    rebuild();
    return {
      update(next) { if (destroyed) return; packet = Object.assign({ values: {}, notes: {}, history: [] }, next || {}); rebuild(); },
      mode: () => mode,
      destroy() { destroyed = true; stopFrame(); resize?.disconnect(); observer?.disconnect(); doc.removeEventListener('visibilitychange', visibility); reduce.removeEventListener?.('change', reduced); panel.remove(); },
    };
  }

  const api = { create, presets: { prototype: prototypePreset }, math: { instant, perDivision, waveformScale, trendScale }, COLORS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloScope = api;
})(typeof window !== 'undefined' ? window : globalThis);
