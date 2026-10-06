(function () {
  "use strict";

  var state = { snapshot: null, actionApplied: false };
  var $ = function (selector, root) { return (root || document).querySelector(selector); };
  var $$ = function (selector, root) { return Array.from((root || document).querySelectorAll(selector)); };
  var esc = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]; }); };
  var fmt = function (value, digits) { return value == null || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits == null ? 1 : digits); };
  var setText = function (selector, value) { var node = $(selector); if (node) node.textContent = value; };
  var bind = function (key, value) { $$('[data-bind="' + key + '"]').forEach(function (node) { node.textContent = value; }); };

  function statusLabel(snapshot) {
    return snapshot.status === "critical" ? "CRITICAL" : snapshot.status === "attention" ? "WARNING" : "HEALTHY";
  }

  function updateExperience(snapshot) {
    state.snapshot = snapshot;
    var current = snapshot.current || {}, asset = snapshot.asset || {}, comparison = snapshot.comparison && snapshot.comparison.baseline;
    var hotspot = Number(current.estimated_hotspot_c), limit = Number(asset.hotspot_limit_c || 120), margin = limit - hotspot;
    var minutes = comparison && comparison.minutes_to_limit;
    var timestamp = current.timestamp ? new Date(current.timestamp) : null;
    bind("hotspot", fmt(hotspot, 1)); bind("load-pct", current.load_pu == null ? "—" : Math.round(Number(current.load_pu) * 100)); bind("ambient", fmt(current.ambient_c, 1)); bind("limit", fmt(limit, 0));
    setText("#hero-status", statusLabel(snapshot) + " / " + (timestamp ? timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "LIVE") + " / 5 MIN TELEMETRY");
    setText("#change-minutes", minutes == null ? "—" : minutes <= 0 ? "NOW" : minutes);
    setText("#breach-minutes", minutes == null ? "—" : minutes <= 0 ? "NOW" : minutes + " MIN");
    setText("#prediction-confidence", current.confidence === "High" ? "92%" : current.confidence === "Moderate" ? "66%" : "28%");
    setText("#final-confidence", current.confidence === "High" ? "92%" : current.confidence === "Moderate" ? "66%" : "28%");
    setText("#final-model-state", current.confidence === "Low" ? "UNCERTAIN" : "SYNCHRONISED");
    var first = (snapshot.history || [])[0] || current;
    var loadDelta = current.load_pu == null || first.load_pu == null ? null : (Number(current.load_pu) - Number(first.load_pu)) * 100;
    var ambientDelta = current.ambient_c == null || first.ambient_c == null ? null : Number(current.ambient_c) - Number(first.ambient_c);
    setText("#evidence-load", loadDelta == null ? "—" : (loadDelta >= 0 ? "+" : "") + fmt(loadDelta, 0) + "%");
    setText("#evidence-ambient", ambientDelta == null ? "—" : (ambientDelta >= 0 ? "+" : "") + fmt(ambientDelta, 1) + "°C");
    setText("#evidence-response", current.residual_c != null && Number(current.residual_c) > Number(asset.residual_limit_c || 6) ? "ABNORMAL" : "WITHIN BAND");
    var reduction = snapshot.comparison && snapshot.comparison.peak_reduction_c;
    setText("#action-reduction", reduction != null && reduction > 0 ? "~" + fmt(reduction, 1) + "°C" : "~11°C");
    renderPrediction(snapshot);
    if (window.NeuraTwin3D) window.NeuraTwin3D.sync(snapshot);
  }

  function renderPrediction(snapshot) {
    var historical = snapshot.history || [], forecast = snapshot.forecast || [], historyPath = $(".p-history"), futurePath = $(".p-future");
    if (!historical.length || !historyPath || !futurePath) return;
    var width = 1000, height = 260, values = historical.concat(forecast).map(function (row) { return row.hotspot_c || row.estimated_hotspot_c; }).filter(function (value) { return value != null; });
    var min = Math.min.apply(Math, values) - 8, max = Math.max.apply(Math, values) + 8, range = Math.max(1, max - min);
    var point = function (index, value, count) { var x = index / Math.max(1, count - 1) * width; var y = height - ((Number(value) - min) / range * (height - 26) + 13); return [x, y]; };
    var makePath = function (rows, offset, total) { return rows.reduce(function (out, row, index) { var value = row.hotspot_c == null ? row.estimated_hotspot_c : row.hotspot_c; if (value == null) return out; var p = point(index + offset, value, total); return out + (out ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1) + " "; }, ""); };
    historyPath.setAttribute("d", makePath(historical.slice(-48), 0, 48 + forecast.length));
    futurePath.setAttribute("d", makePath(forecast, 47, 48 + forecast.length));
  }

  function fetchSnapshot() {
    return fetch("/api/snapshot?asset_id=NR-104&scenario=overload&cursor=148&reduction=20&delay=10", { headers: { "Content-Type": "application/json" } }).then(function (response) { if (!response.ok) throw new Error("Snapshot unavailable"); return response.json(); }).then(updateExperience).catch(function () { setText("#hero-status", "DEMONSTRATION MODE / 5 MIN TELEMETRY"); });
  }

  function setupReveal() {
    var nodes = $$(".reveal");
    if (!("IntersectionObserver" in window)) { nodes.forEach(function (node) { node.classList.add("is-visible"); }); return; }
    var observer = new IntersectionObserver(function (entries) { entries.forEach(function (entry) { if (entry.isIntersecting) { entry.target.classList.add("is-visible"); observer.unobserve(entry.target); } }); }, { threshold: .16 });
    nodes.forEach(function (node) { observer.observe(node); });
    var sections = $$(".story-section");
    var sectionObserver = new IntersectionObserver(function (entries) { entries.forEach(function (entry) { entry.target.classList.toggle("is-active", entry.isIntersecting); }); }, { threshold: .38 });
    sections.forEach(function (section) { sectionObserver.observe(section); });
  }

  function setupControls() {
    $$("[data-mode]").forEach(function (button) { button.addEventListener("click", function () { $$("[data-mode]").forEach(function (item) { item.classList.remove("active"); }); button.classList.add("active"); if (window.NeuraTwin3D) window.NeuraTwin3D.setMode(button.dataset.mode); setText("#twin-stage-status", button.dataset.mode === "electrical" ? "ELECTRICAL LAYER" : "THERMAL LAYER"); }); });
    var actionButton = $("#simulate-action");
    if (actionButton) actionButton.addEventListener("click", function () { var section = $("#action"); section.classList.add("simulated"); state.actionApplied = true; actionButton.innerHTML = "Action simulated <span>✓</span>"; setText("#action-note", "Model comparison complete. The alternative path stays below the configured thermal limit under the same ambient conditions."); var reduction = state.snapshot && state.snapshot.comparison && state.snapshot.comparison.peak_reduction_c; setText("#action-reduction", reduction != null ? "~" + fmt(reduction, 1) + "°C" : "~11°C"); });
  }

  function setupMotion() {
    window.setTimeout(function () { document.body.classList.add("loaded"); }, 120);
    var last = 0; window.addEventListener("scroll", function () { var now = Date.now(); if (now - last < 32) return; last = now; document.documentElement.style.setProperty("--scroll-y", window.scrollY + "px"); }, { passive: true });
  }

  setupMotion(); setupReveal(); setupControls(); fetchSnapshot();
}());
