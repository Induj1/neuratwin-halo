/* Load bank panel for the Wi-Fi ESP32 board: four branches shown as M1–M4.
   M1→load1, M2→load2, M3→load4 on the board. M4 has no hardware; it is the
   physically isolated branch used to demonstrate the overload cutoff. */
(function (root) {
  'use strict';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const fmt = (v, d) => (finite(v) ? Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 2 : d }) : '—');
  const STORAGE_KEY = 'halo-esp32-cutoff';
  const MAP = Object.freeze([
    Object.freeze({ ui: 'M1', hw: 'load1', load: 1, index: 0, isolated: false }),
    Object.freeze({ ui: 'M2', hw: 'load2', load: 2, index: 1, isolated: false }),
    Object.freeze({ ui: 'M3', hw: 'load4', load: 4, index: 3, isolated: false }),
    Object.freeze({ ui: 'M4', hw: null, load: null, index: 2, isolated: true }),
  ]);
  const ALL_OFF = Object.freeze({ load1: false, load2: false, load4: false });
  const entry = ui => MAP.find(m => m.ui === ui) || null;

  /* Request body for one UI load; null for the isolated branch. */
  function requestFor(ui, state) {
    const m = entry(ui);
    if (!m || m.isolated) return null;
    return { load: m.load, state: !!state };
  }
  /* Board-reported drive state for a UI load; null when unknown. Never reads relay index 2. */
  function reportedState(ui, loads) {
    const m = entry(ui);
    if (!m || m.isolated || !loads) return null;
    return typeof loads[m.hw] === 'boolean' ? loads[m.hw] : null;
  }
  /* Whether switches may be used, with the reason shown to the operator. */
  function gate(ctx) {
    const c = ctx || {};
    if (!c.configured) return { enabled: false, reason: 'Wi-Fi board integration is off (HALO_ESP32_URL unset).' };
    if (!c.available) return { enabled: false, reason: 'No board reading yet; switching waits for a live reading.' };
    if (c.stale) return { enabled: false, reason: 'Board reading is stale; switching is paused until a live reading arrives.' };
    if (c.control_enabled === false) return { enabled: false, reason: 'Physical load switching is locked on the server. Set HALO_ALLOW_CONTROL=1 to enable it.' };
    if (c.latched) return { enabled: false, reason: 'Trip decision latched. Investigate and reset the latch before switching loads.' };
    if (c.cutoff) return { enabled: false, reason: 'Supply cut off. Restore supply before switching branches again.' };
    if (c.busy) return { enabled: false, reason: '' };
    return { enabled: true, reason: '' };
  }
  const idle = () => ({ active: false, delivered: false, reason: null, boot_id: null, since: null });
  /* Overload cutoff state machine. */
  function reduce(state, event) {
    const s = state && typeof state === 'object' ? state : idle(), e = event || {};
    switch (e.type) {
      case 'm4_on': return { active: true, delivered: false, reason: null, boot_id: e.boot_id || null, since: e.at || new Date().toISOString() };
      case 'alloff_ok': return s.active ? Object.assign({}, s, { delivered: true, reason: null }) : s;
      case 'alloff_failed': return s.active ? Object.assign({}, s, { delivered: false, reason: e.reason || 'Cutoff request failed.' }) : s;
      case 'reading':
        if (!s.active) return s;
        if (s.boot_id && e.boot_id && e.boot_id !== s.boot_id) return idle();
        if (e.loads_on === 0 && !s.delivered) return Object.assign({}, s, { delivered: true, reason: null });
        return s;
      case 'restore': return s.delivered ? idle() : s;
      default: return s;
    }
  }
  function describeError(error) {
    const status = error && error.status, message = error && error.message || 'Request failed.';
    if (status === 423) return 'Locked: ' + message;
    if (status === 503) return 'Board unreachable: ' + message;
    if (status === 401 || status === 403) return 'Operator sign-in required: ' + message;
    return message;
  }

  function create(host, handlers) {
    if (!host || !host.ownerDocument) throw new TypeError('A DOM host is required.');
    const h = handlers || {}, doc = host.ownerDocument, win = doc.defaultView || root;
    const storage = (() => { try { return win.sessionStorage; } catch (_) { return null; } })();
    let cutoff = idle(), ctx = {}, pendingUi = null, message = '';
    try { const saved = storage && storage.getItem(STORAGE_KEY); if (saved) cutoff = Object.assign(idle(), JSON.parse(saved)); } catch (_) { cutoff = idle(); }
    const persist = () => { try { if (!storage) return; if (cutoff.active) storage.setItem(STORAGE_KEY, JSON.stringify(cutoff)); else storage.removeItem(STORAGE_KEY); } catch (_) {} };
    const panel = doc.createElement('section'); panel.className = 'halo-loads'; panel.setAttribute('aria-label', 'Load bank');
    panel.innerHTML = `<div class="hl-heading"><div><p class="hl-eyebrow">LOAD CONTROLS</p><h3>Four loads</h3></div><span class="hl-origin"></span></div>
      <div class="hl-banner" role="alert" hidden><strong></strong><p></p><button type="button" class="hl-restore">Restore supply</button></div>
      <div class="hl-grid">${MAP.map(m => `<article class="hl-load" data-ui="${m.ui}" data-on="false"><header><strong>${m.ui}</strong><span class="hl-map">load ${m.ui.slice(1)}</span></header><p class="hl-desc">39 Ω / 10 W</p><p class="hl-state">—</p><button type="button" role="switch" aria-checked="false" data-hl-switch="${m.ui}"><i></i><span>OFF</span></button></article>`).join('')}</div>
      <div class="hl-footer"><span class="hl-count"></span><span class="hl-expected"></span></div>
      <p class="hl-gate" role="status"></p>
      <div class="hl-actions"><button type="button" class="hl-alloff">All loads OFF</button></div>`;
    host.replaceChildren(panel);
    const q = s => panel.querySelector(s), banner = q('.hl-banner');
    async function run(ui, fn) {
      pendingUi = ui; message = ''; paint();
      try { await fn(); }
      catch (e) { message = describeError(e); }
      finally { pendingUi = null; paint(); }
    }
    async function send(body) {
      if (typeof h.setLoads !== 'function') throw Error('Load switching is not wired.');
      return h.setLoads(body);
    }
    function onSwitch(ui) {
      const m = entry(ui);
      if (!m) return;
      if (m.isolated) {
        if (cutoff.active) return;
        cutoff = reduce(cutoff, { type: 'm4_on', boot_id: ctx.packet && ctx.packet.boot_id || null }); persist();
        run(ui, async () => {
          try { await send(Object.assign({}, ALL_OFF)); cutoff = reduce(cutoff, { type: 'alloff_ok' }); }
          catch (e) { cutoff = reduce(cutoff, { type: 'alloff_failed', reason: describeError(e) }); throw e; }
          finally { persist(); }
        });
        return;
      }
      const current = reportedState(ui, ctx.packet && ctx.packet.loads);
      run(ui, () => send(requestFor(ui, !current)));
    }
    panel.addEventListener('click', event => {
      const sw = event.target.closest('[data-hl-switch]');
      if (sw && !sw.disabled) { onSwitch(sw.dataset.hlSwitch); return; }
      if (event.target.closest('.hl-alloff') && !q('.hl-alloff').disabled) { run('all', () => send(Object.assign({}, ALL_OFF))); return; }
      if (event.target.closest('.hl-restore') && !q('.hl-restore').disabled) { cutoff = reduce(cutoff, { type: 'restore' }); persist(); message = ''; paint(); }
    });
    function paint() {
      const p = ctx.packet && ctx.packet.available ? ctx.packet : null, st = ctx.status || {};
      const g = gate({ configured: !!st.configured, available: !!p, stale: !!(p && p.stale), control_enabled: st.control_enabled, latched: !!ctx.latched, cutoff: cutoff.active, busy: !!ctx.busy || pendingUi !== null });
      const m4Gate = gate({ configured: !!st.configured, available: !!p, stale: !!(p && p.stale), control_enabled: st.control_enabled, latched: !!ctx.latched, cutoff: false, busy: !!ctx.busy || pendingUi !== null });
      q('.hl-origin').textContent = !st.configured ? 'integration off' : !p ? 'board unreachable' : p.stale ? `stale · ${fmt(p.age_s, 0)} s` : 'live';
      panel.dataset.cutoff = String(cutoff.active);
      for (const m of MAP) {
        const card = q(`.hl-load[data-ui="${m.ui}"]`), sw = card.querySelector('[data-hl-switch]');
        const on = m.isolated ? cutoff.active : reportedState(m.ui, p && p.loads);
        card.dataset.on = String(on === true); card.dataset.unknown = String(on === null);
        card.querySelector('.hl-state').textContent = m.isolated ? (cutoff.active ? 'Supply cut off' : !p ? 'State unavailable' : 'OFF') : on === null ? 'State unavailable' : (on ? 'ON' : 'OFF');
        sw.setAttribute('aria-checked', String(on === true));
        sw.querySelector('span').textContent = pendingUi === m.ui ? '…' : on === true ? 'ON' : 'OFF';
        sw.disabled = m.isolated ? !m4Gate.enabled || cutoff.active : !g.enabled;
        sw.setAttribute('aria-label', `${m.ui} load`);
      }
      q('.hl-count').textContent = p && p.loads ? `${p.loads.loads_on + (cutoff.active ? 1 : 0)} of 4 loads on` : 'Load states unavailable';
      const d = ctx.derived || null, rEff = d && finite(d.r_eff) ? `R_eff ${fmt(d.r_eff, 1)} Ω` : '';
      q('.hl-expected').textContent = d && d.active ? `${rEff} · estimated ${fmt(d.secondary_i, 3)} A (V ÷ R_eff) · measured ${fmt(p.secondary.i, 3)} A`
        : p && finite(p.secondary.i_expected) ? `${rEff ? rEff + ' · ' : ''}expected ${fmt(p.secondary.i_expected, 3)} A · measured ${fmt(p.secondary.i, 3)} A` : rEff;
      q('.hl-alloff').disabled = !st.configured || !!ctx.busy || pendingUi !== null;
      q('.hl-gate').textContent = message || g.reason;
      q('.hl-gate').dataset.error = String(!!message);
      banner.hidden = !cutoff.active;
      if (cutoff.active) {
        banner.querySelector('strong').textContent = 'Load exceeded. Supply cut off to protect the transformer.';
        banner.querySelector('p').textContent = (cutoff.delivered
          ? 'Switching M4 exceeds the transformer\'s rated load. All loads were switched OFF and the board acknowledged.'
          : `Cutoff request not delivered${cutoff.reason ? ': ' + cutoff.reason : ''}. Retry All loads OFF; Restore stays disabled until the board reports every branch off.`)
          + (cutoff.since ? ` Since ${new Date(cutoff.since).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}.` : '');
        q('.hl-restore').disabled = !cutoff.delivered || pendingUi !== null;
      }
    }
    function update(next) {
      ctx = next || {};
      const p = ctx.packet && ctx.packet.available ? ctx.packet : null;
      if (p) { const before = cutoff; cutoff = reduce(cutoff, { type: 'reading', boot_id: p.boot_id, loads_on: p.loads ? p.loads.loads_on : null }); if (cutoff !== before) persist(); }
      paint();
    }
    function setBusy(flag) { if (!!ctx.busy === !!flag) return; ctx = Object.assign({}, ctx, { busy: !!flag }); paint(); }
    paint();
    return { update, setBusy, cutoff: () => Object.assign({}, cutoff), destroy() { panel.remove(); } };
  }

  const api = { create, MAP, ALL_OFF, STORAGE_KEY, math: { requestFor, reportedState, gate, reduce, idle, describeError } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloLoads = api;
})(typeof window !== 'undefined' ? window : globalThis);
