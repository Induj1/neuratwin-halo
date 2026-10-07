/* Landing interactions. All displayed forecasts come from the read-only study API. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let controller,
    timer,
    serial = 0;

  function plot(snapshot) {
    const base = snapshot.forecast,
      alt = snapshot.alternative;
    if (
      !Array.isArray(base) ||
      !Array.isArray(alt) ||
      !base.length ||
      !alt.length ||
      !snapshot.comparison
    )
      throw Error("No forecast available");
    const limit = Number(snapshot.asset.hotspot_limit_c);
    const values = [...base, ...alt].map((p) => p.hotspot_c);
    if (!values.every(Number.isFinite) || !Number.isFinite(limit))
      throw Error("Invalid forecast");
    const min = Math.floor((Math.min(...values, limit) - 8) / 10) * 10;
    const max = Math.ceil((Math.max(...values, limit) + 8) / 10) * 10;
    const duration = Math.max(
      ...base.map((p) => p.minute),
      ...alt.map((p) => p.minute),
    );
    const x = (m) => 40 + (m / duration) * 596,
      y = (v) => 280 - ((v - min) / (max - min)) * 250;
    const path = (rows) =>
      rows
        .map(
          (p, i) =>
            `${i ? "L" : "M"}${x(p.minute).toFixed(2)},${y(p.hotspot_c).toFixed(2)}`,
        )
        .join(" ");
    let markup = "";
    for (let i = 0; i <= 4; i++) {
      const v = min + ((max - min) * i) / 4;
      markup += `<line x1="40" x2="636" y1="${y(v)}" y2="${y(v)}" stroke="#e4e6dd"/><text x="0" y="${y(v) + 4}" fill="#646a60" font-size="12">${Math.round(v)}</text>`;
    }
    markup += `<line x1="40" x2="636" y1="${y(limit)}" y2="${y(limit)}" stroke="#9b9f91" stroke-dasharray="4 5"/><text x="635" y="${y(limit) - 8}" text-anchor="end" fill="#646a60" font-size="11">Configured limit · ${limit}°C</text>`;
    markup += `<path d="${path(base)}" fill="none" stroke="#3d493a" stroke-width="3"/><path d="${path(alt)}" fill="none" stroke="#a34a2b" stroke-width="3"/>`;
    $("forecast-chart").innerHTML = markup;
    document.querySelector(".chart-axis").innerHTML =
      `<span>Now</span><span>${duration / 2} min</span><span>${duration} min</span>`;
    const c = snapshot.comparison;
    $("peak-reduction").textContent = c.peak_reduction_c.toFixed(1);
    $("forecast-summary").textContent =
      `Peak: ${c.baseline.peak_hotspot_c.toFixed(1)}°C at current load, ${c.alternative.peak_hotspot_c.toFixed(1)}°C with ${$("load-reduction").value}% reduction.`;
    $("forecast-chart").setAttribute(
      "aria-label",
      $("forecast-summary").textContent +
        ` Over ${duration} minutes. Synthetic study.`,
    );
    $("chart-state").hidden = true;
    if (window.NeuraTwin3D) window.NeuraTwin3D.sync(snapshot);
  }

  async function compare() {
    const request = ++serial;
    controller?.abort();
    controller = new AbortController();
    const requestController = controller;
    const abort = setTimeout(() => requestController.abort(), 15000);
    $("forecast-panel").setAttribute("aria-busy", "true");
    $("retry-forecast").hidden = true;
    $("chart-state").hidden = false;
    $("chart-state").textContent = "Calculating both futures…";
    $("peak-reduction").textContent = "…";
    $("forecast-summary").textContent = "Updating the comparison.";
    try {
      const params = new URLSearchParams({
        asset_id: "NR-104",
        scenario: "overload",
        cursor: "148",
        reduction: $("load-reduction").value,
        delay: "10",
      });
      const response = await fetch("/api/snapshot?" + params, {
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) throw Error("Study unavailable");
      const snapshot = await response.json();
      if (request === serial) plot(snapshot);
    } catch (error) {
      if (request !== serial) return;
      $("chart-state").textContent =
        "Comparison unavailable. Please try again.";
      $("peak-reduction").textContent = "–";
      $("forecast-summary").textContent = "The study could not be loaded.";
      $("retry-forecast").hidden = false;
    } finally {
      clearTimeout(abort);
      if (request === serial)
        $("forecast-panel").setAttribute("aria-busy", "false");
    }
  }
  $("load-reduction").addEventListener("input", () => {
    $("load-value").value = $("load-reduction").value + "%";
    // Invalidate immediately so an older request cannot render against the new input.
    serial++;
    controller?.abort();
    clearTimeout(timer);
    $("forecast-panel").setAttribute("aria-busy", "true");
    $("chart-state").hidden = false;
    $("chart-state").textContent = "Calculating both futures…";
    $("peak-reduction").textContent = "…";
    $("forecast-summary").textContent = "Updating the comparison.";
    timer = setTimeout(compare, 180);
  });
  $("retry-forecast").addEventListener("click", compare);
  compare();

  if ("IntersectionObserver" in window && !motion.matches) {
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("visible");
            observer.unobserve(e.target);
          }
        }),
      { threshold: 0.08 },
    );
    document
      .querySelectorAll(
        ".intro h2, .capability-line, .forecast-copy, .evidence-content, .section-heading, .field-copy, .closing>div:first-child",
      )
      .forEach((el) => {
        el.classList.add("reveal");
        observer.observe(el);
      });
  }

  // A small architectural study, built locally; no external 3D downloads.
  function city() {
    if (!window.THREE) return;
    const T = window.THREE,
      canvas = $("grid-3d");
    let renderer;
    try {
      renderer = new T.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    renderer.outputEncoding = T.sRGBEncoding;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.8;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    const scene = new T.Scene(),
      camera = new T.PerspectiveCamera(34, 1, 0.1, 100),
      group = new T.Group();
    scene.add(group);
    camera.position.set(9.5, 9.5, 12);
    camera.lookAt(0, 0.5, 0);
    scene.add(new T.HemisphereLight(0xffffff, 0xa8b29b, 0.9));
    const sun = new T.DirectionalLight(0xfff7e9, 1.8);
    sun.position.set(-5, 12, 7);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, {
      left: -7,
      right: 7,
      top: 7,
      bottom: -7,
    });
    sun.shadow.normalBias = 0.04;
    scene.add(sun);
    const white = new T.MeshStandardMaterial({
        color: 0xe8e9df,
        roughness: 0.6,
      }),
      sage = new T.MeshStandardMaterial({ color: 0x87977e, roughness: 0.65 }),
      trim = new T.MeshStandardMaterial({ color: 0x606e5c, roughness: 0.6 }),
      copper = new T.MeshStandardMaterial({
        color: 0xa34a2b,
        metalness: 0.35,
        roughness: 0.4,
      });
    function box(w, h, d, x, y, z, mat) {
      const mesh = new T.Mesh(new T.BoxGeometry(w, h, d), mat);
      mesh.position.set(x, y, z);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
      return mesh;
    }
    box(8, 0.16, 7, 0, -0.15, 0, white);
    // Roads and distribution routes, deliberately illustrative rather than a live map.
    box(7.7, 0.025, 0.5, 0, -0.05, 0, sage);
    box(0.55, 0.025, 6.7, 0.2, -0.05, 0, sage);
    const buildings = [
      [-2.6, -2.1, 1.1, 1.25, 1.1],
      [-1, -2.3, 1.15, 1.8, 1.2],
      [1.6, -2.15, 1.4, 2.35, 1.2],
      [3, -1.8, 0.9, 1.15, 1.45],
      [-2.7, 1.65, 1.1, 0.85, 1.3],
      [-1.1, 2, 1.15, 1.35, 1.25],
      [1.4, 1.7, 1.15, 0.9, 1.5],
      [2.95, 1.8, 0.9, 1.8, 1.2],
    ];
    buildings.forEach(([x, z, w, h, d], i) => {
      box(w, h, d, x, h / 2, z, white);
      box(w + 0.08, 0.08, d + 0.08, x, h + 0.04, z, sage);
      for (let floor = 0.32; floor < h - 0.1; floor += 0.36)
        for (let col = -w / 2 + 0.2; col < w / 2 - 0.1; col += 0.3)
          box(0.13, 0.15, 0.02, x + col, floor, z + d / 2 + 0.015, trim);
      if (i % 2 === 0) {
        box(w * 0.65, 0.12, d * 0.4, x, h + 0.12, z, trim);
      }
    });
    box(0.85, 1.05, 0.7, 0.2, 0.53, 0.1, sage);
    for (let i = 0; i < 6; i++)
      box(0.055, 0.75, 0.86, -0.14 + i * 0.135, 0.5, 0.1, trim);
    for (let i = 0; i < 3; i++)
      box(0.075, 0.3, 0.075, -0.04 + i * 0.23, 1.15, 0.1, copper);
    const routes = [];
    buildings.forEach(([x, z], index) => {
      const pts = [
        new T.Vector3(0.2, 0.04, 0.1),
        new T.Vector3(x, 0.04, 0.1),
        new T.Vector3(x, 0.04, z + (z < 0 ? 0.8 : -0.8)),
      ];
      const curve = new T.CurvePath();
      curve.add(new T.LineCurve3(pts[0], pts[1]));
      curve.add(new T.LineCurve3(pts[1], pts[2]));
      group.add(
        new T.Mesh(new T.TubeGeometry(curve, 16, 0.018, 5, false), copper),
      );
      const packet = new T.Mesh(new T.SphereGeometry(0.06, 8, 8), copper);
      group.add(packet);
      packet.position.copy(curve.getPoint(index / 8));
      routes.push({ curve, packet, offset: index / 8 });
    });
    for (const [x, z] of [
      [-3.5, -0.7],
      [-3.5, 2.8],
      [3.4, 0.7],
      [0.8, 2.9],
      [-1.8, -0.7],
    ]) {
      box(0.06, 0.4, 0.06, x, 0.2, z, trim);
      const tree = new T.Mesh(new T.IcosahedronGeometry(0.27, 1), sage);
      tree.position.set(x, 0.58, z);
      tree.castShadow = true;
      group.add(tree);
    }
    group.rotation.y = -0.18;
    let visible = false,
      dirty = true,
      last = 0;
    function resize() {
      const r = canvas.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      camera.aspect = r.width / r.height;
      camera.position
        .set(9.5, 9.5, 12)
        .multiplyScalar(camera.aspect < 1 ? 1.2 : 1);
      camera.lookAt(0, 0.5, 0);
      camera.updateProjectionMatrix();
      dirty = true;
    }
    resize();
    window.addEventListener("resize", resize, { passive: true });
    canvas.closest(".grid-scene").classList.add("grid-ready");
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      canvas.style.display = "none";
      canvas.closest(".grid-scene").classList.remove("grid-ready");
      visible = false;
    });
    const observer = new IntersectionObserver(
      (entries) => {
        visible = entries[0].isIntersecting;
        dirty = true;
      },
      { rootMargin: "100px" },
    );
    observer.observe(canvas);
    motion.addEventListener("change", () => {
      dirty = true;
    });
    function animate(t) {
      requestAnimationFrame(animate);
      if (!visible || document.hidden || t - last < 40) return;
      last = t;
      if (motion.matches && !dirty) return;
      if (!motion.matches)
        routes.forEach((r) =>
          r.packet.position.copy(
            r.curve.getPoint((t * 0.00009 + r.offset) % 1),
          ),
        );
      renderer.render(scene, camera);
      dirty = false;
    }
    requestAnimationFrame(animate);
  }
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          observer.disconnect();
          city();
        }
      },
      { rootMargin: "500px" },
    );
    observer.observe($("grid-3d"));
  } else city();
})();
