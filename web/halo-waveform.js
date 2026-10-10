/* RMS reconstruction for explanation only; never acquired waveform samples. */
(function (root) {
  'use strict';
  const TAU = Math.PI * 2, SQRT2 = Math.SQRT2;
  const PHASES = [0, -TAU / 3, TAU / 3];
  const COLORS = ['#b74d34', '#247c8c', '#725eb4', '#4c6253'];
  const finiteRms = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
  const firstRms = (object, keys) => {
    for (const key of keys) if (Object.prototype.hasOwnProperty.call(object, key)) return finiteRms(object[key]);
    return null;
  };
  function instant(rms, milliseconds, phase = 0, frequency = 50) {
    if (finiteRms(rms) === null || !Number.isFinite(milliseconds) || !Number.isFinite(phase) || !Number.isFinite(frequency) || frequency <= 0) return null;
    return SQRT2 * rms * Math.sin(TAU * frequency * milliseconds / 1000 + phase);
  }
  function neutralPhasor(values) {
    if (!Array.isArray(values) || values.length !== 3 || values.some(v => finiteRms(v) === null)) return null;
    const re = -values.reduce((sum, value, i) => sum + value * Math.cos(PHASES[i]), 0);
    const im = -values.reduce((sum, value, i) => sum + value * Math.sin(PHASES[i]), 0);
    const magnitude = Math.hypot(re, im);
    return magnitude < 1e-10 ? { rms: 0, phase: 0 } : { rms: magnitude, phase: Math.atan2(im, re) };
  }
  function buildChannels(packet = {}, group = 'current') {
    const t = packet.telemetry || {}, industrial = packet.mode === 'industrial';
    const unit = group === 'voltage' ? 'V' : 'A';
    let channels, note;
    if (industrial && group === 'current') {
      const values = ['phase_current_a', 'phase_current_b', 'phase_current_c'].map(k => finiteRms(t[k]));
      channels = values.map((rms, i) => ({ id: `phase-${i}`, label: `Phase ${'ABC'[i]}`, rms, phase: PHASES[i], color: COLORS[i], reason: rms === null ? 'Phase RMS unavailable' : '' }));
      const n = neutralPhasor(values), supplied = finiteRms(t.neutral_current);
      const consistent = n && supplied !== null && Math.abs(n.rms - supplied) <= Math.max(.01, supplied * .01);
      channels.push({ id: 'neutral', label: 'Neutral', rms: consistent ? supplied : null, phase: n?.phase || 0, color: COLORS[3], reason: supplied === null ? 'Neutral RMS unavailable' : !n ? 'Three phase values required' : !consistent ? 'Neutral differs from the assumed phase model' : '' });
      note = 'Simulated currents · 120° phase separation and unity power factor assumed. Neutral is the return sum; phase relationships are model assumptions.';
    } else if (industrial) {
      channels = ['phase_voltage_a', 'phase_voltage_b', 'phase_voltage_c'].map((key, i) => ({ id: `voltage-${i}`, label: `Phase ${'ABC'[i]}`, rms: finiteRms(t[key]), phase: PHASES[i], color: COLORS[i], reason: finiteRms(t[key]) === null ? 'Phase voltage RMS unavailable' : '' }));
      note = 'Only explicitly supplied phase-voltage RMS values can be shown. Line-to-line values are not silently converted into phase voltages.';
    } else {
      const keys = group === 'voltage' ? [['primary_voltage', 'primary_v'], ['secondary_voltage', 'secondary_v']] : [['primary_current', 'primary_current_a'], ['secondary_current', 'current_a']];
      channels = keys.map((names, i) => ({ id: `${group}-${i}`, label: i ? 'Secondary' : 'Primary', rms: firstRms(t, names), phase: 0, color: COLORS[i], reason: firstRms(t, names) === null ? `${i ? 'Secondary' : 'Primary'} ${group} unavailable` : '' }));
      note = 'Single-phase bench · relative phase and power factor are not measured. Each trace uses an arbitrary phase reference; do not infer phase shift, harmonics or power factor.';
    }
    return { channels, unit, note, frequency: 50, windowMs: 40 };
  }
  function axisLimit(channels) {
    const peak = Math.max(0, ...channels.map(c => finiteRms(c.rms) === null ? 0 : c.rms * SQRT2));
    if (!peak) return 1;
    const rough = peak * 1.18, exponent = 10 ** Math.floor(Math.log10(rough));
    return Math.ceil(rough / exponent * 2) / 2 * exponent;
  }
  function axisScale(channels, packet = {}, group = 'current') {
    const reference = finiteRms(packet.referenceCurrent);
    if (packet.mode !== 'industrial' || group !== 'current' || reference === null || reference === 0) return { limit: axisLimit(channels), kind: 'auto', expanded: false, referenceRms: null };
    const baseline = reference * 1.6 * SQRT2;
    const largestPeak = Math.max(0, ...channels.map(c => finiteRms(c.rms) === null ? 0 : c.rms * SQRT2));
    const expanded = largestPeak > baseline;
    return { limit: expanded ? largestPeak * 1.08 : baseline, kind: 'nameplate', expanded, referenceRms: reference };
  }
  const fmt = (value, digits = 2) => value === null ? 'Unavailable' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
  let serial = 0;
  function create(host) {
    if (!host || !host.ownerDocument) throw new TypeError('A DOM host is required.');
    const doc = host.ownerDocument, win = doc.defaultView || root, id = `hw-${++serial}`;
    const reduce = win.matchMedia('(prefers-reduced-motion: reduce)');
    let packet = {}, group = 'current', model = buildChannels(packet, group), selected = new Map();
    let paused = reduce.matches, visible = true, destroyed = false, frame = 0, lastTick = 0, offset = 0, cursor = 10, width = 600;
    const panel = doc.createElement('section'); panel.className = 'halo-waveform';
    panel.setAttribute('aria-labelledby', `${id}-title`);
    panel.innerHTML = `<div class="hw-heading"><div><p class="hw-eyebrow">ELECTRICAL EXPLORER</p><h3 id="${id}-title">Electrical response</h3></div><span class="hw-origin"></span></div>
      <p class="hw-disclosure"><strong>Illustrative RMS reconstruction</strong> · 50 Hz assumed. These curves are not sampled waveforms.</p>
      <div class="hw-toolbar"><div class="hw-groups" role="group" aria-label="Waveform quantity"><button type="button" data-hw-group="current" aria-pressed="true">Current <span>A</span></button><button type="button" data-hw-group="voltage" aria-pressed="false">Voltage <span>V</span></button></div><button type="button" class="hw-motion"></button></div>
      <div class="hw-channels" role="group" aria-label="Visible waveform channels"></div>
      <div class="hw-plot"><svg role="img" aria-labelledby="${id}-plot-title ${id}-plot-desc" preserveAspectRatio="none"><title id="${id}-plot-title">Illustrative alternating current over two cycles</title><desc id="${id}-plot-desc">Sine curves reconstructed from RMS amplitudes. Use the inspection slider for exact illustrative values.</desc><g class="hw-grid"></g><g class="hw-traces"></g><g class="hw-cursor"></g></svg><p class="hw-empty" hidden></p></div>
      <p class="hw-scale-note"></p><div class="hw-inspection"><label for="${id}-cursor">Inspect time <output class="hw-time" for="${id}-cursor">10.0 ms</output></label><input id="${id}-cursor" type="range" min="0" max="40" step="0.1" value="10" aria-label="Inspect reconstructed waveform time in milliseconds"><p class="hw-inspect-hint">Drag across the plot or use the slider arrow keys. Inspection pauses visual motion.</p></div>
      <details class="hw-details"><summary>Values & model assumptions</summary><div class="hw-readout" aria-label="Illustrative values at inspection time"></div><p class="hw-model-note"></p></details><p class="hw-footnote">Motion is slowed for explanation. Pausing holds the visual sweep; RMS values still follow the selected data.</p>`;
    host.replaceChildren(panel);
    const q = selector => panel.querySelector(selector), svg = q('svg'), grid = q('.hw-grid'), traces = q('.hw-traces'), cross = q('.hw-cursor');
    const motion = q('.hw-motion'), slider = q('input'), origin = q('.hw-origin');
    const ns = 'http://www.w3.org/2000/svg';
    function element(name, attributes, text) { const node = doc.createElementNS(ns, name); for (const [key, value] of Object.entries(attributes || {})) node.setAttribute(key, String(value)); if (text !== undefined) node.textContent = text; return node; }
    const shown = () => model.channels.filter(c => c.rms !== null && selected.get(c.id) !== false);
    function motionState() { motion.textContent = paused ? 'Play visual motion' : 'Pause visual motion'; motion.setAttribute('aria-pressed', String(!paused)); }
    function stopFrame() { if (frame) win.cancelAnimationFrame(frame); frame = 0; lastTick = 0; }
    function canAnimate() { return !destroyed && !paused && visible && !doc.hidden && shown().length > 0 && panel.getClientRects().length > 0; }
    function schedule() { if (canAnimate() && !frame) frame = win.requestAnimationFrame(tick); }
    function tick(time) {
      frame = 0; if (!canAnimate()) { lastTick = 0; return; }
      if (!lastTick) lastTick = time;
      if (time - lastTick >= 32) { offset = (offset + Math.min(time - lastTick, 100) * .003) % 20; lastTick = time; draw(false); }
      schedule();
    }
    function pause() { paused = true; stopFrame(); motionState(); draw(true); }
    function resume() { paused = false; motionState(); renderReadout(); schedule(); }
    const leftMargin = () => host.closest?.('#view-physics') ? 88 : 56;
    function draw(readout = true) {
      const channels = shown(), left = leftMargin(), right = width - 18, top = 20, bottom = 211, middle = (top + bottom) / 2;
      const scale = axisScale(channels, packet, group), limit = scale.limit, x = ms => left + ms / 40 * (right - left), y = value => middle - value / limit * (bottom - top) / 2;
      q('.hw-scale-note').textContent = scale.kind === 'nameplate' ? `Scale ±${fmt(limit, 1)} A peak · ${scale.expanded ? 'expanded above' : 'fixed at 160% of'} rated phase current (${fmt(scale.referenceRms, 1)} A RMS).` : `Auto scale · selected ${group} channels${packet.mode === 'industrial' && group === 'current' ? ' · rated-current reference unavailable' : ''}.`;
      svg.setAttribute('viewBox', `0 0 ${width} 247`); grid.replaceChildren(); traces.replaceChildren(); cross.replaceChildren();
      for (const fraction of [-1, -.5, 0, .5, 1]) {
        const value = limit * fraction, yp = y(value);
        grid.append(element('line', { x1: left, x2: right, y1: yp, y2: yp, class: fraction === 0 ? 'hw-zero' : 'hw-gridline' }));
        grid.append(element('text', { x: left - 9, y: yp + 4, 'text-anchor': 'end' }, fmt(value, limit < 2 ? 2 : 1)));
      }
      for (const ms of (width<400?[0,20,40]:[0,10,20,30,40])) { grid.append(element('line', { x1: x(ms), x2: x(ms), y1: top, y2: bottom, class: 'hw-gridline' })); grid.append(element('text', { x: x(ms), y: 235, 'text-anchor': ms === 0 ? 'start' : ms === 40 ? 'end' : 'middle' }, `${ms} ms`)); }
      grid.append(element('text', { x: 12, y: 13 }, model.unit));
      for (const channel of channels) {
        let d = '';
        for (let i = 0; i <= 240; i++) { const ms = i / 6, value = instant(channel.rms, ms + offset, channel.phase); d += `${i ? 'L' : 'M'}${x(ms).toFixed(2)},${y(value).toFixed(2)} `; }
        traces.append(element('path', { d, stroke: channel.color, fill: 'none', 'stroke-width': channel.id === 'neutral' ? 2 : 2.5, 'stroke-dasharray': channel.id === 'neutral' ? '5 4' : 'none', 'vector-effect': 'non-scaling-stroke' }));
      }
      if (channels.length) {
        cross.append(element('line', { x1: x(cursor), x2: x(cursor), y1: top, y2: bottom, class: 'hw-inspect-line' }));
        for (const c of channels) cross.append(element('circle', { cx: x(cursor), cy: y(instant(c.rms, cursor + offset, c.phase)), r: 4, fill: c.color, stroke: '#fff', 'stroke-width': 1.5 }));
      }
      const empty = q('.hw-empty'); empty.hidden = channels.length > 0; empty.textContent = model.channels.some(c => c.rms !== null) ? 'Select a channel to inspect its curve.' : 'No suitable RMS measurements for this view.';
      if (readout) renderReadout();
    }
    function renderReadout() {
      q('.hw-time').textContent = `${cursor.toFixed(1)} ms`; slider.value = cursor.toFixed(1);
      slider.setAttribute('aria-valuetext', `${cursor.toFixed(1)} milliseconds in the displayed cycle window`);
      const box = q('.hw-readout'); box.replaceChildren();
      for (const channel of model.channels) {
        const card = doc.createElement('div'); card.className = 'hw-value'; card.style.setProperty('--hw-channel', channel.color);
        const label = doc.createElement('span'); label.textContent = channel.label;
        const value = doc.createElement('strong'); value.textContent = channel.rms === null ? 'Unavailable' : `${fmt(channel.rms)} ${model.unit} RMS`;
        const detail = doc.createElement('small'); detail.textContent = channel.rms === null ? channel.reason : selected.get(channel.id) === false ? 'Curve hidden' : paused ? `${fmt(instant(channel.rms, cursor + offset, channel.phase))} ${model.unit} at cursor · illustrative` : 'Pause or inspect for a value at cursor';
        card.append(label, value, detail); box.append(card);
      }
    }
    function rebuild() {
      const focusedChannel=panel.contains(doc.activeElement)?doc.activeElement.dataset.hwChannel:null;
      model = buildChannels(packet, group);
      q('.hw-model-note').textContent = model.note;
      q(`#${id}-plot-title`).textContent = `Illustrative ${group} over two 50 Hz cycles`;
      const controls = q('.hw-channels'); controls.replaceChildren();
      for (const channel of model.channels) {
        if (!selected.has(channel.id)) selected.set(channel.id, true);
        const label = doc.createElement('label'); label.className = 'hw-channel'; label.style.setProperty('--hw-channel', channel.color);
        const input = doc.createElement('input'); input.type = 'checkbox'; input.dataset.hwChannel=channel.id; input.checked = channel.rms !== null && selected.get(channel.id) !== false; input.disabled = channel.rms === null;
        input.addEventListener('change', () => { selected.set(channel.id, input.checked); draw(true); if (!shown().length) stopFrame(); else schedule(); });
        const name = doc.createElement('span'); name.textContent = channel.label;
        const unavailable = doc.createElement('small'); unavailable.textContent = channel.rms === null ? 'Unavailable' : `${fmt(channel.rms)} ${model.unit}`;
        label.title = channel.reason || `${channel.label}: ${fmt(channel.rms)} ${model.unit} RMS`; label.append(input, name, unavailable); controls.append(label);
      }
      for (const button of panel.querySelectorAll('[data-hw-group]')) { const target = button.dataset.hwGroup; button.setAttribute('aria-pressed', String(group === target)); button.disabled = !buildChannels(packet, target).channels.some(c => c.rms !== null) && target !== group; }
      q('.hw-groups').hidden=packet.mode==='industrial'&&!buildChannels(packet,'voltage').channels.some(c=>c.rms!==null);
      if(focusedChannel)panel.querySelector(`[data-hw-channel="${focusedChannel}"]:not(:disabled)`)?.focus({preventScroll:true});
      origin.textContent = packet.sourceLabel || (packet.mode === 'industrial' ? 'Industrial simulation' : 'Physical bench');
      const quality = typeof packet.quality === 'string' ? packet.quality : packet.quality?.status;
      if (quality) origin.textContent += ` · ${quality}`;
      if (packet.replay) origin.textContent += ' · replay';
      draw(true); motionState(); if (!shown().length) stopFrame(); else schedule();
    }
    for (const button of panel.querySelectorAll('[data-hw-group]')) button.addEventListener('click', () => { group = button.dataset.hwGroup; rebuild(); });
    motion.addEventListener('click', () => paused ? resume() : pause());
    function inspect(value) { cursor = Math.max(0, Math.min(40, value)); q('.hw-details').open=true; pause(); }
    slider.addEventListener('input', () => inspect(Number(slider.value)));
    function pointer(event) { const bounds = svg.getBoundingClientRect(); if (!bounds.width) return; const localX = (event.clientX - bounds.left) * width / bounds.width, left=leftMargin(); inspect((localX - left) / (width - 18 - left) * 40); }
    svg.addEventListener('pointerdown', event => { if (event.pointerType !== 'mouse' || event.button === 0) { svg.setPointerCapture?.(event.pointerId); pointer(event); } });
    svg.addEventListener('pointermove', event => { if (event.pointerType === 'mouse' || svg.hasPointerCapture?.(event.pointerId)) pointer(event); });
    svg.addEventListener('pointerup', event => { if (svg.hasPointerCapture?.(event.pointerId)) svg.releasePointerCapture(event.pointerId); });
    function visibility() { if (doc.hidden) stopFrame(); else schedule(); }
    function reduced(event) { if (event.matches) pause(); }
    doc.addEventListener('visibilitychange', visibility); reduce.addEventListener?.('change', reduced);
    const resize = win.ResizeObserver ? new win.ResizeObserver(entries => { const measured = entries[0]?.contentRect.width; if (measured > 0) { width = Math.max(280, Math.round(measured)); draw(true); schedule(); } }) : null;
    resize?.observe(q('.hw-plot'));
    const observer = win.IntersectionObserver ? new win.IntersectionObserver(entries => { visible = !!entries[0]?.isIntersecting; if (visible) schedule(); else stopFrame(); }, { threshold: 0 }) : null;
    observer?.observe(panel);
    rebuild();
    return {
      update(next) {
        if (destroyed) return;
        const changedMode = packet.mode !== next?.mode; packet = next || {};
        if (changedMode) { group = 'current'; selected = new Map(); offset = 0; }
        if (!buildChannels(packet, group).channels.some(c => c.rms !== null) && buildChannels(packet, 'voltage').channels.some(c => c.rms !== null)) group = 'voltage';
        rebuild();
      }, pause, resume,
      destroy() { destroyed = true; stopFrame(); resize?.disconnect(); observer?.disconnect(); doc.removeEventListener('visibilitychange', visibility); reduce.removeEventListener?.('change', reduced); panel.remove(); },
    };
  }
  const api = { create, math: { instant, neutralPhasor, buildChannels, axisLimit, axisScale, finiteRms } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloWaveform = api;
})(typeof window !== 'undefined' ? window : globalThis);
