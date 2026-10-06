const state = {
  assetId: "NR-104",
  scenario: "overload",
  cursor: 148,
  reduction: 20,
  delay: 10,
  catalog: null,
  snapshot: null,
  fleet: null,
  orders: [],
  playing: true,
  judgeMode: false,
  loading: false,
  activeView: "dashboard"
};

const $ = function (selector, root) { return (root || document).querySelector(selector); };
const $$ = function (selector, root) { return Array.from((root || document).querySelectorAll(selector)); };
const esc = function (value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char];
  });
};
const fmt = function (n, digits) { return n == null || Number.isNaN(Number(n)) ? "—" : Number(n).toFixed(digits == null ? 1 : digits); };
const currentAsset = function () { return (state.snapshot && state.snapshot.asset) || (state.catalog && state.catalog.assets || []).find(function (asset) { return asset.asset_id === state.assetId; }) || {}; };
const confidenceScore = function (level) { return ({ High: 92, Moderate: 66, Low: 28 })[level] || 0; };

async function api(path, options) {
  const response = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options || {}));
  if (!response.ok) {
    let message = "Request failed (" + response.status + ")";
    try { const body = await response.json(); message = body.detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function setText(selector, value) { const node = $(selector); if (node) node.textContent = value; }
function bindText(key, value) { $$("[data-bind=\"" + key + "\"]").forEach(function (node) { node.textContent = value; }); }

function toast(title, body) {
  const stack = $("#toast-stack");
  const item = document.createElement("div");
  item.className = "toast";
  item.innerHTML = "<i></i><div><strong>" + esc(title) + "</strong><span>" + esc(body) + "</span></div>";
  stack.appendChild(item);
  window.setTimeout(function () {
    item.style.opacity = "0";
    item.style.transform = "translateY(7px) scale(.98)";
    item.style.transition = "opacity 180ms ease-out, transform 180ms ease-out";
    window.setTimeout(function () { item.remove(); }, 200);
  }, 4200);
}

function navigate(view) {
  const target = view || "dashboard";
  state.activeView = target;
  $$(".view").forEach(function (node) { node.classList.toggle("active", node.id === "view-" + target); });
  $$(".nav-item").forEach(function (node) { node.classList.toggle("active", node.dataset.view === target); });
  const label = $(".nav-item[data-view=\"" + target + "\"] span:nth-child(2)");
  setText("#crumb-title", label ? label.textContent : target);
  window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  $("#sidebar").classList.remove("open");
}

function drawLineChart(svg, series, options) {
  if (!svg || !series || !series.length) return;
  const width = 760, height = (options && options.height) || 220, pad = { left: 7, right: 8, top: 13, bottom: 10 };
  const all = series.reduce(function (out, line) { return out.concat(line.values.filter(function (value) { return value != null; })); }, []);
  const min = (options && options.min != null) ? options.min : Math.min.apply(Math, all);
  const max = (options && options.max != null) ? options.max : Math.max.apply(Math, all);
  const range = Math.max(.01, max - min);
  const x = function (index, length) { return pad.left + (index / Math.max(1, length - 1)) * (width - pad.left - pad.right); };
  const y = function (value) { return pad.top + (1 - (value - min) / range) * (height - pad.top - pad.bottom); };
  const pathFor = function (values) { return values.reduce(function (path, value, index) { if (value == null) return path; return path + (path ? "L" : "M") + x(index, values.length).toFixed(1) + "," + y(value).toFixed(1) + " "; }, ""); };
  const grid = [0.15, 0.4, 0.65, 0.9].map(function (ratio) {
    const pos = (pad.top + ratio * (height - pad.top - pad.bottom)).toFixed(1);
    return '<line x1="0" x2="' + width + '" y1="' + pos + '" y2="' + pos + '" stroke="#24485b" stroke-width="1" opacity=".62"/>';
  }).join("");
  const lines = series.map(function (line) {
    return '<path d="' + pathFor(line.values) + '" fill="none" stroke="' + line.color + '" stroke-width="' + (line.width || 2.5) + '" stroke-linecap="round" stroke-linejoin="round" ' + (line.dash ? 'stroke-dasharray="5 5"' : "") + ' opacity="' + (line.opacity == null ? 1 : line.opacity) + '"/>';
  }).join("");
  const dots = series.filter(function (line) { return line.dot; }).map(function (line) {
    const index = line.values.length - 1, value = line.values[index];
    return value == null ? "" : '<circle cx="' + x(index, line.values.length) + '" cy="' + y(value) + '" r="4" fill="' + line.color + '" stroke="#071420" stroke-width="2"/>';
  }).join("");
  svg.innerHTML = grid + lines + dots;
}

function renderThermalChart() {
  const history = state.snapshot && state.snapshot.history || [], recent = history.slice(-72), svg = $("#thermal-chart"), loadSvg = $("#load-chart");
  if (!recent.length || !svg) return;
  const width = 860, height = 285, pad = { left: 8, right: 8, top: 14, bottom: 12 };
  const limit = Number(currentAsset().hotspot_limit_c || 120);
  const tempValues = recent.reduce(function (out, row) { return out.concat([row.estimated_hotspot_c, row.oil_c, row.ambient_c, row.expected_oil_c, limit]); }, []).filter(function (v) { return v != null && Number.isFinite(Number(v)); });
  const min = Math.max(0, Math.floor(Math.min.apply(Math, tempValues) / 10) * 10 - 10), max = Math.ceil(Math.max.apply(Math, tempValues) / 10) * 10 + 10, range = Math.max(1, max - min);
  const x = function (index) { return pad.left + (index / Math.max(1, recent.length - 1)) * (width - pad.left - pad.right); };
  const y = function (value) { return pad.top + (1 - (Number(value) - min) / range) * (height - pad.top - pad.bottom); };
  const path = function (key) { return recent.reduce(function (out, row, index) { const value = row[key]; return value == null ? out : out + (out ? "L" : "M") + x(index).toFixed(1) + "," + y(value).toFixed(1) + " "; }, ""); };
  const grid = [0, .25, .5, .75, 1].map(function (ratio) { const pos = (pad.top + ratio * (height - pad.top - pad.bottom)).toFixed(1); return '<line x1="0" x2="' + width + '" y1="' + pos + '" y2="' + pos + '" stroke="#4a3e31" stroke-width="1" opacity=".48"/>'; }).join("");
  const limitPath = '<path d="M' + x(0) + ',' + y(limit) + ' L' + x(recent.length - 1) + ',' + y(limit) + '" fill="none" stroke="#ff6c5e" stroke-width="1.2" stroke-dasharray="5 5" opacity=".78"/>';
  const lines = [
    '<path d="' + path("ambient_c") + '" fill="none" stroke="#a89a8b" stroke-width="1.5" stroke-linecap="round" opacity=".8"/>',
    '<path d="' + path("oil_c") + '" fill="none" stroke="#eab15d" stroke-width="2.5" stroke-linecap="round"/>',
    '<path d="' + path("estimated_hotspot_c") + '" fill="none" stroke="#ff6c5e" stroke-width="2.6" stroke-linecap="round"/>',
    '<path d="' + path("expected_oil_c") + '" fill="none" stroke="#9a8f70" stroke-width="1.5" stroke-dasharray="4 4" stroke-linecap="round" opacity=".8"/>'
  ].join("");
  const currentIndex = recent.length - 1, marker = '<line x1="' + x(currentIndex) + '" x2="' + x(currentIndex) + '" y1="0" y2="' + height + '" stroke="#eab15d" stroke-width="1" opacity=".28" stroke-dasharray="3 5"/>';
  svg.innerHTML = grid + limitPath + lines + marker;
  if (loadSvg) {
    const loadY = function (value) { return 42 - Math.max(0, Math.min(1.6, Number(value || 0))) / 1.6 * 34; };
    const loadPath = recent.reduce(function (out, row, index) { return out + (out ? "L" : "M") + x(index).toFixed(1) + "," + loadY(row.load_pu).toFixed(1) + " "; }, "");
    loadSvg.innerHTML = '<line x1="0" x2="860" y1="42" y2="42" stroke="#4a3e31"/><path d="' + loadPath + '" fill="none" stroke="#c0aaff" stroke-width="2" stroke-linecap="round"/>';
  }
  setText("#load-now", recent[currentIndex].load_pu == null ? "—" : Math.round(Number(recent[currentIndex].load_pu) * 100) + "%");
  const tooltip = $("#thermal-tooltip");
  if (tooltip) {
    $$(".telemetry-hit", svg).forEach(function (node) { node.remove(); });
    recent.forEach(function (_, index) {
      const hit = document.createElementNS("http://www.w3.org/2000/svg", "rect"); hit.setAttribute("class", "telemetry-hit"); hit.setAttribute("x", Math.max(0, x(index) - (width / recent.length) / 2)); hit.setAttribute("y", 0); hit.setAttribute("width", width / recent.length); hit.setAttribute("height", height); hit.dataset.index = index; hit.style.fill = "transparent"; hit.style.pointerEvents = "all"; svg.appendChild(hit);
      hit.addEventListener("mouseenter", function () { const row = recent[Number(hit.dataset.index)], time = new Date(row.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); tooltip.innerHTML = '<b>' + time + '</b><span>Winding ' + fmt(row.estimated_hotspot_c, 1) + '°C</span><span>Oil ' + fmt(row.oil_c, 1) + '°C</span><span>Ambient ' + fmt(row.ambient_c, 1) + '°C</span><span>Load ' + fmt(Number(row.load_pu) * 100, 0) + '%</span>'; tooltip.classList.add("visible"); });
      hit.addEventListener("mousemove", function (event) { const rect = svg.getBoundingClientRect(); tooltip.style.left = Math.min(rect.width - 160, Math.max(10, event.clientX - rect.left + 12)) + "px"; tooltip.style.top = Math.max(8, event.clientY - rect.top - 20) + "px"; });
      hit.addEventListener("mouseleave", function () { tooltip.classList.remove("visible"); });
    });
  }
}

function drawForecastChart() {
  const snapshot = state.snapshot;
  if (!snapshot || !snapshot.forecast || !snapshot.alternative) return;
  const base = snapshot.forecast.map(function (row) { return row.hotspot_c; });
  const alt = snapshot.alternative.map(function (row) { return row.hotspot_c; });
  const low = snapshot.forecast.map(function (row) { return row.low_c; });
  const high = snapshot.forecast.map(function (row) { return row.high_c; });
  const limit = Number(currentAsset().hotspot_limit_c || 120);
  drawLineChart($("#forecast-chart"), [
    { values: high, color: "#f7c988", width: 1, dash: true, opacity: .75 },
    { values: low, color: "#f7c988", width: 1, dash: true, opacity: .75 },
    { values: base, color: "#f05f72", width: 2.4, dot: true },
    { values: alt, color: "#17bfa1", width: 2.6, dot: true },
    { values: Array(base.length).fill(limit), color: "#aab9c4", width: 1, dash: true, opacity: .7 }
  ], { min: Math.min.apply(Math, low.concat([limit - 6])) - 2, max: Math.max.apply(Math, high.concat([limit + 5])) + 2, height: 190 });
}

function updateRing(score) {
  const ring = $("[data-ring='health']");
  if (!ring) return;
  const circumference = 2 * Math.PI * 21;
  ring.style.strokeDasharray = circumference;
  ring.style.strokeDashoffset = circumference * (1 - score / 100);
}

function renderTwin(snapshot) {
  const current = snapshot.current || {}, asset = snapshot.asset || {}, health = current.condition_index == null ? 0 : current.condition_index;
  const status = snapshot.status, canvas = $(".twin-canvas");
  const comparison = snapshot.comparison;
  if (canvas) { canvas.classList.toggle("critical", status === "critical"); canvas.classList.toggle("attention", status === "attention"); }
  bindText("load", fmt(current.load_pu, 2)); bindText("load-pct", current.load_pu == null ? "—" : Math.round(Number(current.load_pu) * 100)); bindText("oil", fmt(current.oil_c, 1)); bindText("hotspot", fmt(current.estimated_hotspot_c, 1)); bindText("ambient", fmt(current.ambient_c, 1)); bindText("health", Math.round(health)); bindText("confidence", confidenceScore(current.confidence));
  const headroom = current.estimated_hotspot_c == null ? null : Number(asset.hotspot_limit_c) - Number(current.estimated_hotspot_c);
  bindText("headroom", headroom == null ? "—" : fmt(headroom, 1));
  const hotspotDelta = snapshot.history && snapshot.history.length > 3 ? Number(current.estimated_hotspot_c) - Number(snapshot.history[snapshot.history.length - 4].estimated_hotspot_c) : null;
  bindText("hotspot-trend", hotspotDelta == null ? "—" : (hotspotDelta >= 0 ? "+" : "") + fmt(hotspotDelta, 1) + "°C");
  setText("#ops-asset-title", "Transformer " + (asset.asset_id || state.assetId));
  setText("#ops-asset-name", asset.name || "North Industrial Feeder");
  setText("#updated-time", current.timestamp ? new Date(current.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—");
  setText("#telemetry-updated", current.timestamp ? "Updated " + new Date(current.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Updated —");
  setText("#breach-time", comparison && comparison.baseline && comparison.baseline.minutes_to_limit != null ? (comparison.baseline.minutes_to_limit <= 0 ? "now" : comparison.baseline.minutes_to_limit + " min") : "not projected");
  const statusLabel = status === "critical" ? "CRITICAL" : status === "attention" ? "WARNING" : "HEALTHY";
  const statusChip = $("#asset-status");
  if (statusChip) { statusChip.textContent = statusLabel; statusChip.className = "status-chip " + (status === "critical" ? "red" : status === "attention" ? "warn" : "teal"); }
  updateRing(health);
  const minutesToLimit = comparison && comparison.baseline ? comparison.baseline.minutes_to_limit : null;
  setText("[data-bind='limit-time']", minutesToLimit != null ? (minutesToLimit <= 0 ? "Reached now" : minutesToLimit + " min") : "Protected");
  setText("#scenario-name", state.catalog && state.catalog.scenarios && state.catalog.scenarios[state.scenario] ? state.catalog.scenarios[state.scenario].name : state.scenario);
  setText("#twin-name", (asset.asset_id || state.assetId) + " · " + (asset.name || "Transformer"));
  const provenanceMode = snapshot.provenance && snapshot.provenance.mode || "Demonstration dataset";
  const source = provenanceMode === "Synthetic replay" ? "Demonstration dataset" : provenanceMode, sourceNode = $("#source-badge");
  if (sourceNode) sourceNode.innerHTML = '<span class="source-dot"></span><span>' + esc(source) + '</span><b>·</b><span>5 min cadence</span>';
  const statusNode = $(".twin-panel .panel-kicker");
  if (statusNode) statusNode.innerHTML = '<span class="status-dot ' + (status === "critical" ? "red" : "attention") + '"></span> DIGITAL TWIN';
  renderHeroStatus(snapshot);
  if (window.NeuraTwin3D) window.NeuraTwin3D.sync(snapshot);
}

function renderHeroStatus(snapshot) {
  const current = snapshot.current || {}, alerts = snapshot.alerts || [], first = alerts[0];
  const comparison = snapshot.comparison && snapshot.comparison.baseline;
  const minutes = comparison && comparison.minutes_to_limit;
  const timeLabel = minutes == null ? "monitoring" : (minutes <= 0 ? "now" : minutes + " min");
  const clock = current.timestamp ? new Date(current.timestamp) : null;
  if (clock && !Number.isNaN(clock.getTime())) {
    const updated = clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setText("#updated-label", "Last updated: " + updated);
    setText("#updated-time", clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  }
  if (!first) {
    const banner = $(".hero-status-banner");
    if (banner) { banner.classList.remove("critical"); banner.classList.add("attention"); }
    setText("#hero-status-title", "Within operating envelope");
    setText("#hero-status-detail", "No active alert · within configured envelope");
    setText("#hero-status-time", "clear");
    return;
  }
  const critical = first.severity === "critical" || snapshot.status === "critical";
  setText("#hero-status-title", critical ? "Thermal limit breach" : "Early warning active");
  setText("#hero-status-detail", (first.title || "Evidence-linked alert") + " · " + timeLabel);
  setText("#hero-status-time", timeLabel);
  const banner = $(".hero-status-banner");
  if (banner) { banner.classList.toggle("critical", critical); banner.classList.toggle("attention", !critical); }
}

function renderAlerts(snapshot) {
  const alerts = snapshot.alerts || [], list = $("#alert-list");
  setText("#alert-count", alerts.length);
  if (!list) return;
  if (!alerts.length) { list.innerHTML = '<div class="no-alerts"><span class="no-alert-icon">✓</span><strong>All clear for this window</strong><p>No active evidence-linked alerts.</p></div>'; return; }
  list.innerHTML = alerts.slice(0, 4).map(function (alert) {
    return '<div class="alert-item" data-alert-code="' + esc(alert.code) + '"><div class="alert-item-top"><i class="alert-severity ' + (alert.severity === "critical" ? "critical" : "warning") + '"></i><span>' + esc(alert.severity.toUpperCase()) + '</span><span>' + esc(alert.code.replaceAll("_", " ")) + '</span></div><h3>' + esc(alert.title) + '</h3><p>' + esc(alert.evidence) + '</p><span class="alert-link">Inspect evidence →</span></div>';
  }).join("");
  $$(".alert-item", list).forEach(function (node) { node.addEventListener("click", function () { navigate("incident"); toast("Evidence opened", "The incident lab is focused on this active signal."); }); });
}

function renderFleet() {
  const list = $("#fleet-list"), assets = state.fleet && state.fleet.assets || [];
  if (!list) return;
  list.innerHTML = assets.map(function (entry) {
    const current = entry.current || {}, warn = entry.status === "attention", critical = entry.status === "critical", margin = current.estimated_hotspot_c == null ? null : Number(entry.asset.hotspot_limit_c) - Number(current.estimated_hotspot_c);
    const status = critical ? "Critical" : warn ? "Warning" : "Healthy";
    const updated = current.timestamp ? new Date(current.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
    return '<button class="fleet-row" data-asset-id="' + esc(entry.asset.asset_id) + '"><span class="fleet-asset"><b>' + esc(entry.asset.asset_id) + '</b><small>' + esc(entry.asset.name) + '</small></span><span class="fleet-status ' + (critical ? "critical" : warn ? "warning" : "healthy") + '"><i></i>' + status + '</span><span>' + (current.load_pu == null ? "—" : Math.round(Number(current.load_pu) * 100) + "%") + '</span><span>' + (current.estimated_hotspot_c == null ? "—" : fmt(current.estimated_hotspot_c, 1) + "°C") + '</span><span class="fleet-margin ' + (margin != null && margin < 0 ? "negative" : "") + '">' + (margin == null ? "—" : (margin > 0 ? "+" : "") + fmt(margin, 1) + "°C") + '</span><span>' + updated + '</span></button>';
  }).join("");
  $$(".fleet-row", list).forEach(function (row) { row.addEventListener("click", function () { state.assetId = row.dataset.assetId; navigate("asset"); toast("Asset monitor opened", row.dataset.assetId + " telemetry and evidence are now active."); }); });
}

function renderEvidence(snapshot) {
  const current = snapshot.current || {}, alerts = snapshot.alerts || [], evidence = $("#evidence-list");
  if (evidence) {
    const rows = [
      ["ϟ", "Electrical stress", (current.load_pu == null ? "No" : fmt(current.load_pu, 2)) + " pu load observed in the latest window.", current.load_pu > 1.05 ? "HIGH" : "LOW"],
      ["♨", "Thermal residual", (current.residual_c == null ? "No" : fmt(current.residual_c, 1)) + " deg C measured versus expected.", current.residual_c > 6 ? "HIGH" : "MED"],
      ["◌", "Measurement quality", (current.source || "Model state") + " · " + (current.flags && current.flags.length ? current.flags.join(", ") : "no active flags") + ".", (current.confidence || "HIGH").toUpperCase()]
    ];
    evidence.innerHTML = rows.map(function (row) { return '<div class="evidence-row"><span class="evi-icon">' + row[0] + '</span><div><strong>' + row[1] + '</strong><p>' + esc(row[2]) + '</p></div><span class="evi-score">' + esc(row[3]) + '</span></div>'; }).join("");
  }
  const first = alerts[0];
  setText("#incident-title", first ? first.title : "No active incident");
  setText("#diagnostic-note", first ? "“" + first.evidence + " " + first.action + "”" : "“The current window has no active evidence-linked alert.”");
  setText("#incident-provenance", snapshot.provenance && (snapshot.provenance.note || snapshot.provenance.mode) || "Demonstration dataset");
  const strip = $("#event-strip");
  if (strip) {
    const history = (snapshot.history || []).slice(-4);
    strip.innerHTML = history.map(function (row) {
      const label = row.load_pu > 1.05 ? "Load stress" : row.residual_c > 6 ? "Thermal residual" : "Twin update";
      const detail = row.oil_c == null ? "Telemetry gap" : fmt(row.oil_c, 1) + " deg C oil · " + fmt(row.load_pu, 2) + " pu load";
      return '<div class="event-block"><span>' + esc(new Date(row.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })) + '</span><strong>' + label + '</strong><small>' + detail + '</small></div>';
    }).join("");
  }
}

function renderScenarioCards() {
  const grid = $("#scenario-grid");
  if (!grid || !state.catalog || !state.catalog.scenarios) return;
  const icons = { overload: "ϟ", cooling: "♨", sensor: "◌", ambiguous: "?", dropout: "∅", normal: "✓" };
  grid.innerHTML = Object.entries(state.catalog.scenarios).map(function (pair) {
    const key = pair[0], item = pair[1];
    return '<button class="scenario-card ' + (key === state.scenario ? "active" : "") + '" data-scenario="' + esc(key) + '"><span class="scenario-icon">' + (icons[key] || "◈") + '</span><strong>' + esc(item.name) + '</strong><p>' + esc(item.description) + '</p></button>';
  }).join("");
  $$(".scenario-card", grid).forEach(function (card) { card.addEventListener("click", function () { selectScenario(card.dataset.scenario); }); });
}

function renderComparison(snapshot) {
  const comparison = snapshot.comparison, baseline = comparison && comparison.baseline, alternative = comparison && comparison.alternative;
  if (!baseline || !alternative) { setText("#baseline-peak", "Unavailable"); setText("#alt-peak", "Resolve data"); setText("#delta-peak", "Forecast paused"); setText("#delta-exposure", snapshot.forecast_unavailable_reason || "Measurement confidence is low."); return; }
  const delta = comparison.peak_reduction_c || baseline.peak_hotspot_c - alternative.peak_hotspot_c, exposure = comparison.exposure_reduction_c_min || baseline.exposure_c_min - alternative.exposure_c_min;
  const limitLabel = function (minutes) { return minutes == null ? "limit stays protected" : (minutes <= 0 ? "limit reached now" : "limit reached in " + minutes + " min"); };
  setText("#baseline-peak", fmt(baseline.peak_hotspot_c, 1) + "°C"); setText("#alt-peak", fmt(alternative.peak_hotspot_c, 1) + "°C"); setText("#baseline-limit", limitLabel(baseline.minutes_to_limit)); setText("#alt-limit", limitLabel(alternative.minutes_to_limit)); setText("#delta-peak", fmt(delta, 1) + "°C cooler peak"); setText("#delta-exposure", (exposure > 0 ? "Thermal exposure reduced" : "Exposure unchanged") + " · " + fmt(Math.abs(exposure), 0) + " deg C-min"); setText("#rec-reduction", state.reduction); drawForecastChart();
}

function renderSnapshot() { if (state.snapshot) { renderTwin(state.snapshot); renderAlerts(state.snapshot); renderThermalChart(); renderEvidence(state.snapshot); renderComparison(state.snapshot); } }

async function loadSnapshot(options) {
  if (state.loading) return;
  state.loading = true;
  try {
    state.snapshot = await api("/api/snapshot?asset_id=" + encodeURIComponent(state.assetId) + "&scenario=" + encodeURIComponent(state.scenario) + "&cursor=" + state.cursor + "&reduction=" + state.reduction + "&delay=" + state.delay);
    renderSnapshot(); if (!(options && options.silent)) renderScenarioCards();
  } catch (error) { toast("Connection issue", error.message); }
  finally { state.loading = false; }
}

async function selectScenario(scenario) { state.scenario = scenario; state.cursor = 148; renderScenarioCards(); await loadSnapshot(); toast("Scenario loaded", state.catalog.scenarios[scenario].name); }
async function loadFleet() { try { state.fleet = await api("/api/fleet?cursor=" + state.cursor); renderFleet(); } catch (error) { toast("Fleet unavailable", error.message); } }
async function loadOrders() { try { const payload = await api("/api/work-orders"); state.orders = payload.orders || []; renderOrders(); } catch (error) { toast("Work orders unavailable", error.message); } }

function renderOrders() {
  const counts = { open: 0, acknowledged: 0, planned: 0, closed: 0 };
  state.orders.forEach(function (order) { counts[order.status] = (counts[order.status] || 0) + 1; });
  setText("#open-orders", counts.open); setText("#ack-orders", counts.acknowledged); setText("#planned-orders", counts.planned); setText("#closed-orders", counts.closed); setText(".work-count", state.orders.filter(function (order) { return order.status !== "closed"; }).length);
  const list = $("#work-list"), empty = $("#empty-work");
  if (!list || !empty) return;
  empty.classList.toggle("visible", state.orders.length === 0);
  list.innerHTML = state.orders.map(function (order) {
    const content = order.content || {}, next = { open: "acknowledged", acknowledged: "planned", planned: "closed", closed: "open" }[order.status] || "acknowledged";
    return '<div class="work-row"><span class="work-status ' + esc(order.status) + '"></span><div class="work-row-main"><strong>' + esc(content.title || content.code || "Maintenance action") + '</strong><p>' + esc(content.asset_name || order.asset_id) + " · " + esc(content.action || "Review evidence and verify asset condition.") + '</p></div><span class="work-id">' + esc(order.id) + '</span><button class="work-action" data-order-id="' + esc(order.id) + '" data-next="' + next + '">' + (next === "closed" ? "Close" : next) + '</button></div>';
  }).join("");
  $$(".work-action", list).forEach(function (button) { button.addEventListener("click", function () { updateOrder(button.dataset.orderId, button.dataset.next); }); });
}

async function createWorkOrder() {
  const alert = state.snapshot && state.snapshot.alerts && state.snapshot.alerts[0];
  if (!alert) { toast("No active signal", "Run a scenario before creating a work order."); return; }
  try {
    const payload = await api("/api/work-orders", { method: "POST", body: JSON.stringify({ asset_id: state.assetId, scenario: state.scenario, cursor: state.cursor, code: alert.code, reduction: state.reduction, delay: state.delay }) });
    await loadOrders(); toast(payload.created ? "Work order created" : "Work order already exists", payload.id + " is now in the maintenance queue."); navigate("work");
  } catch (error) { toast("Could not create work order", error.message); }
}

async function updateOrder(orderId, status) {
  try { await api("/api/work-orders/" + encodeURIComponent(orderId), { method: "PATCH", body: JSON.stringify({ status: status, note: "Updated from NeuraTwin command center." }) }); await loadOrders(); toast("Work order updated", orderId + " marked " + status + "."); } catch (error) { toast("Update failed", error.message); }
}

function download(url, filename) { const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove(); }
function exportEvidence() { download("/api/export?asset_id=" + encodeURIComponent(state.assetId) + "&scenario=" + encodeURIComponent(state.scenario) + "&cursor=" + state.cursor + "&reduction=" + state.reduction + "&delay=" + state.delay, "neuratwin-evidence.json"); toast("Evidence exported", "The current state, forecast and provenance were packaged."); }

function nfcTap() {
  setText("#last-tap", "Just now");
  toast("NFC passport resolved", state.assetId + " is now active for field inspection.");
  const plate = $(".nfc-plate");
  if (plate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) plate.animate([{ transform: "scale(.96)", boxShadow: "0 0 0 0 rgba(23,199,164,0)" }, { transform: "scale(1.03)", boxShadow: "0 0 0 12px rgba(23,199,164,.16)" }, { transform: "scale(1)", boxShadow: "0 13px 28px rgba(8,17,31,.18)" }], { duration: 520, easing: "cubic-bezier(.23,1,.32,1)" });
}

function showQrFallback() {
  toast("QR fallback ready", "Use asset " + state.assetId + " at the edge node to recover the same passport.");
  const plate = $(".nfc-plate");
  if (plate) {
    plate.classList.add("fallback-pulse");
    window.setTimeout(function () { plate.classList.remove("fallback-pulse"); }, 700);
  }
}

async function runJudgeStory() {
  state.judgeMode = true;
  state.playing = false;
  state.scenario = "overload";
  state.cursor = 148;
  const playToggle = $("#play-toggle");
  if (playToggle) { playToggle.textContent = "▶"; playToggle.title = "Play replay"; }
  navigate("dashboard");
  await loadSnapshot();
  toast("Incident replay loaded", "Replay paused at the thermal decision point. Review evidence, then compare the maintenance response.");
}

function bindEvents() {
  $$(".nav-item, [data-view]").forEach(function (node) { node.addEventListener("click", function () { navigate(node.dataset.view); }); });
  $("#mobile-menu").addEventListener("click", function () { $("#sidebar").classList.toggle("open"); });
  $("#export-btn").addEventListener("click", exportEvidence); $("#download-json-btn").addEventListener("click", exportEvidence);
  $("#download-passport-btn").addEventListener("click", function () { exportEvidence(); toast("Passport exported", state.assetId + " identity, telemetry and maintenance history are included."); });
  $("#passport-btn").addEventListener("click", function () { navigate("asset"); nfcTap(); }); $("#nfc-scan-btn").addEventListener("click", nfcTap); $("#passport-action").addEventListener("click", nfcTap);
  $("#qr-btn").addEventListener("click", showQrFallback);
  $("#scenario-btn").addEventListener("click", runJudgeStory); $("#create-order-btn").addEventListener("click", createWorkOrder); $("#rec-order-btn").addEventListener("click", createWorkOrder);
  $("#ack-alert-btn").addEventListener("click", function () { this.textContent = "Acknowledged"; this.classList.add("acknowledged"); toast("Alert acknowledged", "The incident remains visible and the acknowledgement is recorded for this replay."); });
  $("#play-toggle").addEventListener("click", function () { state.playing = !state.playing; this.textContent = state.playing ? "Ⅱ" : "▶"; this.title = state.playing ? "Pause replay" : "Play replay"; toast(state.playing ? "Replay resumed" : "Replay paused", state.playing ? "Telemetry will continue advancing." : "The current evidence window is frozen."); });
  $$(".seg-button[data-twin-mode]").forEach(function (button) { button.addEventListener("click", function () { $$(".seg-button[data-twin-mode]").forEach(function (item) { item.classList.remove("active"); }); button.classList.add("active"); if (window.NeuraTwin3D) window.NeuraTwin3D.setMode(button.dataset.twinMode); toast("Twin layer switched", button.textContent + " view is active."); }); });
  $("#reduction-slider").addEventListener("input", function (event) { state.reduction = Number(event.target.value); setText("#reduction-value", state.reduction); setText("#rec-reduction", state.reduction); });
  $("#delay-slider").addEventListener("input", function (event) { state.delay = Number(event.target.value); setText("#delay-value", state.delay); });
  $("#apply-action-btn").addEventListener("click", async function () { await loadSnapshot(); toast("Comparison recalculated", state.reduction + "% reduction after " + state.delay + " minutes."); });
  $$(".filter-pills .seg-button").forEach(function (button) { button.addEventListener("click", function () { $$(".filter-pills .seg-button").forEach(function (item) { item.classList.remove("active"); }); button.classList.add("active"); }); });
}

async function tick() {
  if (!state.playing || !state.snapshot) return;
  state.cursor += 1;
  if (state.cursor >= (state.snapshot.total_readings || 288)) state.cursor = 145;
  await loadSnapshot({ silent: true });
  if (state.cursor % 3 === 0) loadFleet();
}

async function bootstrap() {
  bindEvents();
  try { state.catalog = await api("/api/catalog"); renderScenarioCards(); await loadSnapshot({ silent: true }); await Promise.all([loadFleet(), loadOrders()]); setInterval(tick, 2600); }
  catch (error) { toast("NeuraTwin is starting", error.message); window.setTimeout(bootstrap, 1800); }
}

bootstrap();
