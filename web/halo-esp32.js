/* Wi-Fi ESP32 data layer for the Physical prototype view.
   Reads the backend proxy routes under /api/halo/esp32 and normalises the board
   reply into one hardware packet. Instruments never fetch; they receive packets. */
(function (root) {
  'use strict';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const num = v => (finite(v) ? v : null);
  const SOURCE = 'Physical prototype · Wi-Fi ESP32';
  const BUFFER_LIMIT = 300; // ≈10 min at the default 2 s poll

  function empty(extra) {
    return Object.assign({ available: false, live: false, stale: false, error: null, at: null, age_s: null,
      device_id: null, boot_id: null, sequence: null, flags: [], loads: null, relay_states: null,
      primary: { v: null, i: null, i_method: 'calculated' }, secondary: { v: null, i: null, i_expected: null },
      surface_c: null, probe_ok: false, mains_present: false, current_calibrated: false, calibration_status: '' }, extra || {});
  }

  /* Map a GET /esp32/readings reply to the hardware packet. */
  function normalize(reply, receivedAt) {
    const now = finite(receivedAt) ? receivedAt : Date.now();
    const r = reply && reply.reading;
    if (!r || typeof r !== 'object') return empty({ error: reply && reply.error || null });
    const stale = !!reply.stale;
    const stamped = stale && reply.readings_at ? Date.parse(reply.readings_at) : NaN;
    const at = finite(stamped) ? stamped : now;
    const loads = r.loads && typeof r.loads === 'object' ? r.loads : {};
    const load1 = !!loads.load1, load2 = !!loads.load2, load4 = !!loads.load4;
    return {
      available: true, live: !!reply.live && !stale, stale, error: reply.error || null,
      at: new Date(at).toISOString(), age_s: Math.max(0, (now - at) / 1000),
      device_id: r.device_id == null ? null : String(r.device_id), boot_id: r.boot_id == null ? null : String(r.boot_id),
      sequence: finite(r.sequence) ? r.sequence : null, uptime_ms: num(r.uptime_ms),
      mains_present: !!r.mains_present,
      primary: { v: num(r.primary_v), i: num(r.primary_current_a), i_method: r.primary_current_method === 'measured' ? 'measured' : 'calculated' },
      secondary: { v: num(r.secondary_v), i: num(r.current_a), i_expected: num(r.expected_current_a) },
      surface_c: num(r.surface_c), probe_ok: !!r.temperature_probe_ok,
      current_calibrated: !!r.current_calibrated, calibration_status: typeof r.calibration_status === 'string' ? r.calibration_status : '',
      loads: { load1, load2, load4, loads_on: finite(loads.loads_on) ? loads.loads_on : [load1, load2, load4].filter(Boolean).length },
      relay_states: Array.isArray(r.relay_states) && r.relay_states.length === 4 ? r.relay_states.map(Boolean) : null,
      flags: Array.isArray(r.quality_flags) ? r.quality_flags.map(String) : [],
    };
  }

  /* A reading older than three poll intervals is stale even if the last HTTP call succeeded. */
  function freshness(packet, pollSeconds) {
    if (!packet || !packet.available) return packet;
    const limit = 3 * (finite(pollSeconds) && pollSeconds > 0 ? pollSeconds : 2);
    if (finite(packet.age_s) && packet.age_s > limit && !packet.stale) return Object.assign({}, packet, { stale: true, live: false });
    return packet;
  }

  /* Rolling buffer keyed by (boot_id, sequence); duplicates add nothing, a reboot clears it. */
  function createBuffer(limit) {
    const max = finite(limit) && limit > 0 ? limit : BUFFER_LIMIT;
    let rows = [], lastKey = null, bootId = null;
    return {
      push(packet) {
        if (!packet || !packet.available) return false;
        const key = packet.boot_id + ':' + packet.sequence;
        if (key === lastKey) return false;
        if (bootId !== null && packet.boot_id !== bootId) rows = [];
        bootId = packet.boot_id; lastKey = key;
        rows.push({ at: packet.at, sequence: packet.sequence, values: {
          primary_v: packet.primary.v, secondary_v: packet.secondary.v, primary_i: packet.primary.i,
          secondary_i: packet.secondary.i, secondary_i_expected: packet.secondary.i_expected, surface_c: packet.surface_c,
          loads_on: packet.loads ? packet.loads.loads_on : null } });
        if (rows.length > max) rows = rows.slice(rows.length - max);
        return true;
      },
      rows: () => rows.slice(),
      clear() { rows = []; lastKey = null; bootId = null; },
      size: () => rows.length,
    };
  }

  function quality(packet, status) {
    if (!status || !status.configured) return 'integration off';
    if (!packet || !packet.available) return 'unreachable';
    return packet.stale ? 'stale' : 'live';
  }

  /* Load bank: identical 39 Ω branches in parallel, so R_eff = 39 Ω ÷ branches on. */
  const BRANCH_OHMS = 39;
  const ZERO_AMPS = 0.005;
  function effectiveResistance(loadsOn, branchOhms) {
    const ohms = finite(branchOhms) && branchOhms > 0 ? branchOhms : BRANCH_OHMS;
    return finite(loadsOn) && loadsOn > 0 ? ohms / loadsOn : null;
  }
  const zeroCurrent = v => v === null || v === undefined || (finite(v) && Math.abs(v) < ZERO_AMPS);
  function estimateFrom(secondaryV, primaryV, loadsOn) {
    const rEff = effectiveResistance(loadsOn);
    if (rEff === null || !finite(secondaryV) || secondaryV <= 0) return { r_eff: rEff, secondary_i: null, primary_i: null };
    const secondaryI = secondaryV / rEff;
    const primaryI = finite(primaryV) && primaryV > 0 ? secondaryV * secondaryI / primaryV : null;
    return { r_eff: rEff, secondary_i: secondaryI, primary_i: primaryI };
  }
  /* Frontend estimate used only when the board reports a flat 0 A on both currents while loads are on.
     Secondary: V_s ÷ R_eff. Primary: V_s·I_s ÷ V_p (ideal transformer, unity power factor). */
  function deriveCurrents(packet, history, options) {
    const opts = options || {}, minSamples = finite(opts.minSamples) ? opts.minSamples : 3;
    const p = packet && packet.available ? packet : null;
    const out = { active: false, r_eff: null, loads_on: null, secondary_i: null, primary_i: null, reason: '' };
    if (!p) return out;
    out.loads_on = p.loads ? p.loads.loads_on : null;
    out.r_eff = effectiveResistance(out.loads_on);
    if (out.r_eff === null || !finite(p.secondary.v) || p.secondary.v <= 0) return out;
    const recent = (Array.isArray(history) ? history : []).slice(-minSamples);
    const flatNow = zeroCurrent(p.secondary.i) && zeroCurrent(p.primary.i);
    const flatRecent = recent.length >= minSamples && recent.every(r => zeroCurrent(r.values.secondary_i) && zeroCurrent(r.values.primary_i));
    if (!flatNow || !flatRecent) return out;
    const est = estimateFrom(p.secondary.v, p.primary.v, out.loads_on);
    out.secondary_i = est.secondary_i; out.primary_i = est.primary_i; out.active = out.secondary_i !== null;
    if (out.active) out.reason = [p.secondary.i,p.primary.i].some(v=>!finite(v))
      ? `Current channel missing; showing V ÷ R_eff estimates with ${out.loads_on} active branches`
      : `Reported current is near zero with ${out.loads_on} active branches; showing V ÷ R_eff estimates`;
    return out;
  }

  /* Packet for HaloScope (prototype preset). */
  function scopePacket(packet, history, status) {
    const p = packet && packet.available ? packet : null;
    const rows = Array.isArray(history) ? history : [];
    const d = deriveCurrents(packet, rows);
    const values = { primary_v: p ? p.primary.v : null, secondary_v: p ? p.secondary.v : null, primary_i: p ? p.primary.i : null,
      secondary_i: p ? p.secondary.i : null, secondary_i_expected: p ? p.secondary.i_expected : null };
    const notes = { primary_i: p ? (p.primary.i_method === 'measured' ? 'measured' : 'calculated from secondary power') : '',
      secondary_i: p && !p.current_calibrated ? 'current sensor not calibrated' : '',
      secondary_i_expected: 'V × branches ÷ 39 Ω' };
    let mapped = rows;
    if (d.active) {
      values.secondary_i = d.secondary_i; values.primary_i = d.primary_i;
      const rawNote=[p.secondary.i,p.primary.i].some(v=>!finite(v))?'current channel missing':'reported current near zero';
      notes.secondary_i = `estimated V ÷ R_eff ${d.r_eff.toFixed(1)} Ω · ${rawNote}`;
      notes.primary_i = `estimated from secondary power · ${rawNote}`;
      mapped = rows.map(r => {
        const v = r.values;
        if (!(zeroCurrent(v.secondary_i) && zeroCurrent(v.primary_i))) return r;
        const est = estimateFrom(v.secondary_v, v.primary_v, v.loads_on);
        return Object.assign({}, r, { values: Object.assign({}, v, { secondary_i: est.secondary_i, primary_i: est.primary_i }) });
      });
    }
    return { values, notes, history: mapped, quality: quality(packet, status), sourceLabel: SOURCE, derived: d };
  }

  /* Packet for HaloThermo. Thresholds come from /twin/prototype settings (surface limit − 5 / limit). */
  function thermoPacket(packet, history, settings) {
    const p = packet && packet.available ? packet : null;
    const invalidFlag = !!p && p.flags.includes('surface_invalid');
    const valid = !!p && p.probe_ok && finite(p.surface_c) && !invalidFlag;
    return {
      value_c: valid ? p.surface_c : null, valid,
      reason: !p ? 'No board reading.' : !p.probe_ok || !finite(p.surface_c) ? 'Probe disconnected or returned a sentinel value.' : invalidFlag ? 'Surface reading flagged invalid by the board.' : '',
      label: 'Surface temperature · DS18B20', kind: 'surface',
      warning_c: num(settings && settings.temperature_warning), critical_c: num(settings && settings.temperature_critical),
      trend: (Array.isArray(history) ? history : []).map(r => ({ at: r.at, value_c: r.values.surface_c })),
      quality: p ? (p.stale ? 'stale' : 'live') : 'unavailable', sourceLabel: SOURCE,
    };
  }

  /* Client bound to HaloWorkspace.api. Never throws from poll(); failures become packet state. */
  function create(api, options) {
    if (typeof api !== 'function') throw new TypeError('An api(path, body?) function is required.');
    const opts = options || {}, buffer = createBuffer(opts.bufferLimit), statusEvery = finite(opts.statusEveryMs) ? opts.statusEveryMs : 10000;
    let status = null, statusAt = 0, packet = empty(), displayRows=[], displayBoot=null;
    async function refreshStatus(force) {
      if (!force && status && Date.now() - statusAt < statusEvery) return status;
      try { status = await api('/esp32/status'); }
      catch (e) { status = { configured: false, unavailable: true, error: e.message }; }
      statusAt = Date.now();
      return status;
    }
    async function poll() {
      await refreshStatus(false);
      if (!status || !status.configured) { packet = empty({ configured: false }); return packet; }
      try {
        const reply = await api('/esp32/readings');
        packet = freshness(normalize(reply), status.poll_seconds);
        if (packet.available) {
          const added=buffer.push(packet);
          if(displayBoot!==packet.boot_id){displayRows=[];displayBoot=packet.boot_id;}
          if(added){displayRows.push(displaySnapshot(packet,buffer.rows(),status));if(displayRows.length>BUFFER_LIMIT)displayRows.shift();}
        }
      } catch (e) {
        packet = empty({ error: e.message, unreachable: true, status_code: e.status || null });
      }
      return packet;
    }
    async function setLoads(body) { return api('/esp32/loads', body); }
    function applyLoads(loads) {
      if (!packet.available || !loads || typeof loads !== 'object') return packet;
      const load1 = !!loads.load1, load2 = !!loads.load2, load4 = !!loads.load4;
      packet = Object.assign({}, packet, { loads: { load1, load2, load4, loads_on: finite(loads.loads_on) ? loads.loads_on : [load1, load2, load4].filter(Boolean).length } });
      return packet;
    }
    return { poll, refreshStatus, setLoads, applyLoads, status: () => status, packet: () => packet, history: () => buffer.rows(),
      displaySnapshot:()=>displaySnapshot(packet,buffer.rows(),status),displayHistory:()=>structuredClone(displayRows),
      reset: () => {buffer.clear();displayRows=[];displayBoot=null;} };
  }

  function displaySnapshot(packet,history,status){
    const scope=scopePacket(packet,history,status),p=packet||empty(),d=scope.derived;
    const live=!!(p.available&&p.live&&!p.stale),loading=live&&finite(scope.values.secondary_i)?100*scope.values.secondary_i:null;
    const channel=(value,raw,unit,source,method)=>({value:num(value),raw:num(raw),unit,
      source:finite(value)?source:'unavailable',method,quality:scope.quality});
    return {timestamp:p.at,device_id:p.device_id,boot_id:p.boot_id,sequence:p.sequence,
      version:'prototype-display-1',quality:scope.quality,age_s:p.age_s,
      active_branches:p.loads?.loads_on??null,resistance_ohms:d.r_eff,branch_ohms:BRANCH_OHMS,
      reason:d.active?d.reason:null,calibrated:!!p.current_calibrated,probe_valid:!!p.probe_ok,
      live,relay_states:p.relay_states||null,loads:p.loads||null,
      channels:{
        primary_voltage:channel(scope.values.primary_v,p.primary?.v,'V','measured','board_rms'),
        secondary_voltage:channel(scope.values.secondary_v,p.secondary?.v,'V','measured','board_rms'),
        secondary_current:channel(scope.values.secondary_i,p.secondary?.i,'A',d.active?'frontend_estimated':'measured',d.active?'V_secondary / R_eff':'board_rms'),
        primary_current:channel(scope.values.primary_i,p.primary?.i,'A',d.active?'frontend_estimated':p.primary?.i_method==='measured'?'measured':'firmware_calculated',d.active?'V_secondary * I_secondary_est / V_primary; unity PF, no losses':p.primary?.i_method==='measured'?'board_rms':'firmware power balance; configured efficiency 0.80'),
        surface_temperature:channel(live&&p.probe_ok?p.surface_c:null,p.surface_c,'C','measured','surface_probe')
      },rating_a:1,loading_percent:loading,
      demo_health:loading===null?null:100-Math.max(0,Math.min(100,loading-80)),
      demo_health_version:'current-only-1',scope:'Bounded browser display snapshot; not the complete acquisition history'};
  }

  const api = { create, createBuffer, math: { normalize, freshness, scopePacket, thermoPacket, quality, empty, effectiveResistance, deriveCurrents, estimateFrom, displaySnapshot }, SOURCE, BRANCH_OHMS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloEsp32 = api;
})(typeof window !== 'undefined' ? window : globalThis);
