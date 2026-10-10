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
          secondary_i: packet.secondary.i, secondary_i_expected: packet.secondary.i_expected, surface_c: packet.surface_c } });
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

  /* Packet for HaloScope (prototype preset). */
  function scopePacket(packet, history, status) {
    const p = packet && packet.available ? packet : null;
    return {
      values: { primary_v: p ? p.primary.v : null, secondary_v: p ? p.secondary.v : null, primary_i: p ? p.primary.i : null,
        secondary_i: p ? p.secondary.i : null, secondary_i_expected: p ? p.secondary.i_expected : null },
      notes: { primary_i: p ? (p.primary.i_method === 'measured' ? 'measured' : 'calculated from secondary power') : '',
        secondary_i: p && !p.current_calibrated ? 'current sensor not calibrated' : '',
        secondary_i_expected: 'V × branches ÷ 39 Ω' },
      history: Array.isArray(history) ? history : [], quality: quality(packet, status), sourceLabel: SOURCE,
    };
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
    let status = null, statusAt = 0, packet = empty();
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
        if (packet.available) buffer.push(packet);
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
    return { poll, refreshStatus, setLoads, applyLoads, status: () => status, packet: () => packet, history: () => buffer.rows(), reset: () => buffer.clear() };
  }

  const api = { create, createBuffer, math: { normalize, freshness, scopePacket, thermoPacket, quality, empty }, SOURCE };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.HaloEsp32 = api;
})(typeof window !== 'undefined' ? window : globalThis);
