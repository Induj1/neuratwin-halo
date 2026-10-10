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
    const stamped = reply.readings_at ? Date.parse(reply.readings_at) : NaN;
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
        const values=observedValues(packet),estimate=deriveCurrents(packet);
        rows.push({ at: packet.at, sequence: packet.sequence, quality:quality(packet,{configured:true}),values:{...values,
          primary_i_expected:estimate.primary_i,secondary_i_expected:estimate.secondary_i,
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
  function observedValues(p){
    const live=!!(p?.available&&p.live&&!p.stale),flags=p?.flags||[];
    const valid=(v,max,keys)=>live&&finite(v)&&v>=0&&v<=max&&!keys.some(k=>flags.includes(k))?v:null;
    return {primary_v:valid(p?.primary?.v,300,['primary_v_out_of_range','primary_v_invalid']),
      secondary_v:valid(p?.secondary?.v,60,['secondary_v_out_of_range','secondary_v_invalid']),
      primary_i:p?.primary?.i_method==='measured'?valid(p.primary.i,30,['primary_current_out_of_range','primary_current_invalid']):null,
      secondary_i:valid(p?.secondary?.i,30,['current_a_out_of_range','current_invalid']),
      surface_c:live&&p.probe_ok&&finite(p.surface_c)&&p.surface_c>=-55&&p.surface_c<=125&&!flags.some(f=>['surface_invalid','surface_out_of_range'].includes(f))?p.surface_c:null};
  }
  function effectiveResistance(loadsOn, branchOhms) {
    const ohms = finite(branchOhms) && branchOhms > 0 ? branchOhms : BRANCH_OHMS;
    return finite(loadsOn) && loadsOn > 0 ? ohms / loadsOn : null;
  }
  function estimateFrom(secondaryV, primaryV, loadsOn) {
    const rEff = effectiveResistance(loadsOn);
    if (rEff === null || !finite(secondaryV) || secondaryV <= 0) return { r_eff: rEff, secondary_i: null, primary_i: null };
    const secondaryI = secondaryV / rEff;
    const primaryI = finite(primaryV) && primaryV > 0 ? secondaryV * secondaryI / primaryV : null;
    return { r_eff: rEff, secondary_i: secondaryI, primary_i: primaryI };
  }
  /* Independent load-bank expectation. It never replaces an observed channel.
     Secondary: V_s / R_eff. Primary: ideal unity-PF power balance, ignoring losses. */
  function deriveCurrents(packet, history, options) {
    const p = packet && packet.available ? packet : null;
    const out = { active: false, r_eff: null, loads_on: null, secondary_i: null, primary_i: null, disagreement:false, reason: '' };
    if (!p) return out;
    out.loads_on = p.loads ? p.loads.loads_on : null;
    out.r_eff = effectiveResistance(out.loads_on);
    const observed=observedValues(p);
    if (out.r_eff === null || !finite(observed.secondary_v) || observed.secondary_v <= 0) return out;
    const est = estimateFrom(observed.secondary_v, observed.primary_v, out.loads_on);
    out.secondary_i = est.secondary_i; out.primary_i = est.primary_i; out.active = out.secondary_i !== null;
    out.disagreement=finite(observed.secondary_i)&&Math.abs(observed.secondary_i-out.secondary_i)>Math.max(.05,.2*out.secondary_i);
    if(out.active)out.reason=out.disagreement?'Measured current differs from the load-bank estimate.':!finite(observed.secondary_i)?'Measured current unavailable; estimate shown separately.':'Load-bank estimate; relay commands do not verify contact state.';
    return out;
  }

  /* Packet for HaloScope (prototype preset). */
  function scopePacket(packet, history, status) {
    const p = packet && packet.available ? packet : null;
    const rows = Array.isArray(history) ? history : [];
    const d = deriveCurrents(packet, rows);
    const values = {...observedValues(p),primary_i_expected:d.primary_i,secondary_i_expected:d.secondary_i};
    const notes = { primary_i: p?.primary.i_method==='measured'?'measured':'No primary current measurement',
      secondary_i: p && !p.current_calibrated ? 'current sensor not calibrated' : '',
      primary_i_expected:'Estimated from secondary power; unity PF, no losses',secondary_i_expected:'Estimated V × branches ÷ 39 Ω' };
    return { values, notes, history:rows, quality: quality(packet, status), sourceLabel: SOURCE, derived: d,calibrated:!!p?.current_calibrated };
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
      source:finite(value)?source:'unavailable',method,quality:!live?scope.quality:finite(value)?'live':method.startsWith('No primary')?'unavailable':finite(raw)?'invalid':'missing'});
    return {timestamp:p.at,device_id:p.device_id,boot_id:p.boot_id,sequence:p.sequence,
      version:'prototype-display-2',quality:scope.quality,age_s:p.age_s,
      active_branches:p.loads?.loads_on??null,resistance_ohms:d.r_eff,branch_ohms:BRANCH_OHMS,
      reason:d.active?d.reason:null,calibrated:!!p.current_calibrated,probe_valid:!!p.probe_ok,
      live,relay_states:p.relay_states||null,loads:p.loads||null,
      channels:{
        primary_voltage:channel(scope.values.primary_v,p.primary?.v,'V','measured','board_rms'),
        secondary_voltage:channel(scope.values.secondary_v,p.secondary?.v,'V','measured','board_rms'),
        secondary_current:channel(scope.values.secondary_i,p.secondary?.i,'A','measured','board_rms'),
        primary_current:channel(scope.values.primary_i,p.primary?.i,'A','measured',p.primary?.i_method==='measured'?'board_rms':'No primary measurement; raw is firmware-calculated'),
        surface_temperature:channel(scope.values.surface_c,p.surface_c,'C','measured','surface_probe')
      },rating_a:1,loading_percent:loading,
      estimates:{secondary_current:channel(d.secondary_i,null,'A','frontend_estimated','V_secondary / R_eff; 39-ohm branches; commanded load count'),
        primary_current:channel(d.primary_i,null,'A','frontend_estimated','V_secondary * I_secondary_est / V_primary; unity PF, no losses')},
      estimated_loading_percent:finite(d.secondary_i)?100*d.secondary_i:null,disagreement:d.disagreement,
      demo_health:loading===null||!p.current_calibrated||d.disagreement?null:100-Math.max(0,Math.min(100,loading-80)),
      demo_health_version:'observed-current-2',scope:'Separate observed and estimated channels; bounded browser history'};
  }

  const api = { create, createBuffer, math: { normalize, freshness, scopePacket, thermoPacket, quality, empty, effectiveResistance, deriveCurrents, estimateFrom, displaySnapshot,observedValues }, SOURCE, BRANCH_OHMS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloEsp32 = api;
})(typeof window !== 'undefined' ? window : globalThis);
