/* Spatial annotations and read-only playback of the existing bench heating fixture. */
(() => {
  const finite = Number.isFinite;
  const reading = (value, unit, digits = 1) =>
    finite(value) ? `${value.toFixed(digits)} ${unit}` : "Unavailable";
  const definitions = [
    {
      group: "transformer",
      part: "transformer",
      title: "Transformer",
      y: 1.7,
      dx: -155,
      dy: -65,
      mobile: true,
    },
    {
      group: "voltage-1",
      part: "voltage",
      title: "Voltage sensors",
      y: 0.4,
      dx: -175,
      dy: -5,
    },
    {
      group: "current-1",
      part: "current",
      title: "Current sensors",
      y: 0.3,
      dx: 55,
      dy: -85,
    },
    {
      group: "relay-module",
      part: "relay",
      title: "Relay module",
      y: 0.5,
      dx: 120,
      dy: -15,
    },
    {
      group: "load-resistors",
      part: "relay",
      title: "Load bank",
      y: 0.4,
      dx: 115,
      dy: 25,
      mobile: true,
    },
    {
      group: "esp32",
      part: "controller",
      title: "ESP32",
      y: 0.25,
      dx: -155,
      dy: 38,
      mobile: true,
    },
  ];
  class ThermalOverlay {
    constructor(twin) {
      this.twin = twin;
      this.stage = twin.canvas.parentElement;
      this.layer = document.createElement("div");
      this.layer.className = "twin-annotations";
      this.layer.setAttribute("aria-label", "Model components");
      this.lines = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "svg",
      );
      this.lines.setAttribute("aria-hidden", "true");
      this.layer.append(this.lines);
      this.labels = definitions.map((def) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "twin-label";
        button.dataset.anchor = def.group;
        const title = document.createElement("span"),
          value = document.createElement("b");
        title.textContent = def.title;
        button.append(title, value);
        button.addEventListener("click", () => {
          twin.pauseRotation?.();
          twin.focus(def.part);
        });
        const line = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "line",
        );
        const dot = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "circle",
        );
        dot.setAttribute("r", "3");
        this.lines.append(line, dot);
        this.layer.append(button);
        return { ...def, button, value, line, dot };
      });
      this.alert = document.createElement("div");
      this.alert.className = "twin-thermal-alert";
      this.alert.hidden = true;
      this.alert.setAttribute("role", "status");
      this.alert.setAttribute("aria-live", "polite");
      this.alert.setAttribute("aria-atomic", "true");
      this.alert.innerHTML =
        '<span class="thermal-alert-icon" aria-hidden="true">!</span><div><strong></strong><p></p></div>';
      this.stage.append(this.layer, this.alert);
      this.twin.overlay = this;
    }
    update(snapshot, offline = false) {
      this.snapshot = snapshot;
      if (!this.twin.bench) {
        this.layer.hidden = true;
        this.alert.hidden = true;
        return;
      }
      const c = snapshot?.current || {},
        limit = snapshot?.limits?.surface_c;
      const calibrated = snapshot?.evidence?.find(
        (e) => e.channel === "surface_c",
      )?.calibrated;
      const stale =
        offline || ["stale", "disconnected"].includes(snapshot?.connection);
      const valid = finite(c.surface_c) && !stale && calibrated;
      const near = valid && finite(limit) && c.surface_c >= limit - 10;
      const rapid =
        valid && snapshot.alerts?.some((a) => a.code === "temperature_change");
      const critical =
        valid && snapshot.alerts?.some((a) => a.code === "surface_limit");
      const level = critical
        ? "critical"
        : near || rapid
          ? "warning"
          : "normal";
      this.level = level;
      this.stage.dataset.thermal = level;
      this.twin.temperature(c.surface_c, level);
      const source =
        snapshot?.source === "simulated"
          ? "Simulation"
          : snapshot?.source === "replayed"
            ? "Recording"
            : "Measured";
      this.labels[0].value.textContent = finite(c.surface_c)
        ? `Surface · ${reading(c.surface_c, "°C")}${stale ? " · stale" : !calibrated ? " · unverified" : ""}`
        : "Surface · unavailable";
      this.labels[0].button.dataset.level = level;
      this.labels[1].value.textContent = finite(c.secondary_v)
        ? `Secondary · ${reading(c.secondary_v, "V", 2)}`
        : "Primary + secondary";
      this.labels[2].value.textContent = finite(c.current_a)
        ? `Load · ${reading(c.current_a, "A", 3)}`
        : "Primary + secondary";
      this.labels[3].value.textContent = Array.isArray(c.relay_states)
        ? `${c.relay_states.filter(Boolean).length} / 4 reported on`
        : "4 channels";
      this.labels[4].value.textContent = "4 × 39 Ω / 10 W";
      this.labels[5].value.textContent = stale ? "Offline" : "";
      this.alert.hidden = level === "normal" || !this.twin.bench;
      this.alert.dataset.level = level;
      // Announce state transitions, not every changing decimal in a replay.
      const alertKey = `${level}:${source}:${limit}:${!!rapid}`;
      if (alertKey !== this.alertKey) {
        this.alertKey = alertKey;
        this.alert.querySelector("strong").textContent = critical
          ? "Surface temperature limit exceeded"
          : rapid
            ? "Surface temperature rising rapidly"
            : "Approaching surface limit";
        this.alert.querySelector("p").textContent =
          `${source} · ${finite(limit) ? `${limit.toFixed(0)}°C surface limit` : "Surface probe"} · ${critical ? "Review thermal condition" : rapid ? "Verify with an independent probe" : "Within 10°C of the limit"}`;
      }
      this.layout();
    }
    layout() {
      const twin = this.twin,
        canvas = twin.canvas,
        w = canvas.clientWidth,
        h = canvas.clientHeight;
      this.layer.hidden = !twin.bench;
      if (!twin.bench || !w || !h) {
        this.alert.hidden = true;
        return;
      }
      this.lines.setAttribute("viewBox", `0 0 ${w} ${h}`);
      const mobile = w < 600,
        placed = [];
      const bottomSpace = mobile ? 170 : 130;
      const origin = canvas.getBoundingClientRect();
      for (const element of this.stage.querySelectorAll(
        ".twin-thermal-alert,.bench-stage-caption,.stage-caption,.bench-tools,.assembly-tools,.view-projection,.bench-part-nav",
      )) {
        if (element.hidden) continue;
        const box = element.getBoundingClientRect();
        if (box.width && box.height)
          placed.push({
            x: box.left - origin.left,
            y: box.top - origin.top,
            w: box.width,
            h: box.height,
          });
      }
      for (const item of this.labels) {
        const group = twin.bench.groups.find((g) => g.name === item.group);
        const point = group
          ?.localToWorld(new THREE.Vector3(0, item.y, 0))
          .project(twin.camera);
        const visible =
          point &&
          point.z > -1 &&
          point.z < 1 &&
          Math.abs(point.x) < 1.08 &&
          Math.abs(point.y) < 1.08 &&
          (!mobile || item.mobile);
        item.button.hidden = !visible;
        item.line.style.display = item.dot.style.display = visible
          ? ""
          : "none";
        if (!visible) continue;
        const ax = ((point.x + 1) * w) / 2,
          ay = ((1 - point.y) * h) / 2;
        const bw = item.button.offsetWidth,
          bh = item.button.offsetHeight;
        const dx = mobile
          ? item.group === "load-resistors"
            ? 40
            : -110
          : item.dx;
        let x = Math.max(12, Math.min(w - bw - 12, ax + dx));
        let y = Math.max(
          mobile ? 65 : 68,
          Math.min(h - bh - bottomSpace, ay + item.dy),
        );
        const xs = [
          x,
          12,
          w - bw - 12,
          ax - bw - 20,
          ax + 20,
          ...placed.flatMap((r) => [r.x - bw - 10, r.x + r.w + 10]),
        ];
        const ys = [
          y,
          ...placed.flatMap((r) => [r.y - bh - 10, r.y + r.h + 10]),
        ];
        const candidates = xs
          .flatMap((cx) =>
            ys.map((cy) => ({
              x: cx,
              y: cy,
              score: (cx - x) ** 2 + (cy - y) ** 2,
            })),
          )
          .filter(
            (c) =>
              c.x >= 12 &&
              c.x + bw <= w - 12 &&
              c.y >= 12 &&
              c.y + bh <= h - 12 &&
              !placed.some(
                (r) =>
                  c.x < r.x + r.w + 8 &&
                  c.x + bw + 8 > r.x &&
                  c.y < r.y + r.h + 8 &&
                  c.y + bh + 8 > r.y,
              ),
          )
          .sort((a, b) => a.score - b.score);
        if (!candidates.length) {
          item.button.hidden = true;
          item.line.style.display = item.dot.style.display = "none";
          continue;
        }
        ({ x, y } = candidates[0]);
        placed.push({ x, y, w: bw, h: bh });
        item.button.style.transform = `translate(${x}px, ${y}px)`;
        item.line.setAttribute("x1", ax);
        item.line.setAttribute("y1", ay);
        item.line.setAttribute(
          "x2",
          x + (ax < x ? 0 : ax > x + bw ? bw : bw / 2),
        );
        item.line.setAttribute("y2", y + bh / 2);
        item.dot.setAttribute("cx", ax);
        item.dot.setAttribute("cy", ay);
      }
    }
  }
  window.HaloThermalOverlay = ThermalOverlay;

  function mount(twin, workspace) {
    if (!twin || twin.failed) return;
    const overlay = new ThermalOverlay(twin),
      stage = twin.canvas.parentElement;
    const bar = document.createElement("div");
    bar.className = "thermal-demo-bar";
    bar.innerHTML =
      '<button type="button" class="thermal-demo-run"><span aria-hidden="true">▷</span> Run heat simulation</button><span class="thermal-demo-note" role="status" hidden></span><button type="button" class="thermal-label-toggle" aria-pressed="true">Labels</button>';
    stage.before(bar);
    const run = bar.querySelector(".thermal-demo-run"),
      note = bar.querySelector(".thermal-demo-note"),
      toggle = bar.querySelector(".thermal-label-toggle");
    let active = false,
      epoch = 0,
      timer,
      controller;
    const frames = [
      100, 140, 180, 220, 260, 300, 340, 380, 420, 460, 500, 560, 620, 680, 720,
    ];
    function allowed() {
      const ctx = workspace?.context();
      return (
        !workspace ||
        (!workspace.challenge &&
          ctx.mode === "replay" &&
          !ctx.dataset_id &&
          !workspace.offline())
      );
    }
    function stop(message) {
      active = false;
      epoch++;
      clearTimeout(timer);
      controller?.abort();
      run.innerHTML = '<span aria-hidden="true">▷</span> Run heat simulation';
      run.setAttribute("aria-pressed", "false");
      note.textContent = message || "";
      note.hidden = !message;
    }
    async function sample(cursor, start, ticket) {
      if (workspace) {
        await workspace.setThermalDemoFrame(cursor, start);
        if (ticket !== epoch) return;
        if (workspace.offline())
          throw Error("Reconnect to run the simulation.");
        return workspace.snapshot();
      }
      controller = new AbortController();
      const response = await fetch(
        `/api/halo/snapshot?mode=replay&scenario=heating&cursor=${cursor}`,
        { signal: controller.signal, cache: "no-store" },
      );
      if (!response.ok) throw Error("Simulation unavailable. Try again.");
      const snapshot = await response.json();
      if (ticket === epoch) overlay.update(snapshot);
      return snapshot;
    }
    async function step(index, ticket) {
      if (!active || ticket !== epoch) return;
      try {
        const snapshot = await sample(frames[index], index === 0, ticket);
        if (ticket !== epoch || !active) return;
        if (index === frames.length - 1) {
          stop();
          run.innerHTML = '<span aria-hidden="true">↻</span> Replay heating';
        } else timer = setTimeout(() => step(index + 1, ticket), 850);
      } catch (error) {
        if (ticket === epoch)
          stop(error.name === "AbortError" ? "" : error.message);
      }
    }
    run.addEventListener("click", () => {
      if (active) {
        stop();
        return;
      }
      if (!allowed()) return;
      active = true;
      const ticket = ++epoch;
      run.innerHTML = '<span aria-hidden="true">Ⅱ</span> Stop simulation';
      run.setAttribute("aria-pressed", "true");
      note.textContent = "";
      note.hidden = true;
      // Keep labels steady while the heating sequence is being demonstrated.
      twin.pauseRotation?.();
      step(0, ticket);
    });
    toggle.addEventListener("click", () => {
      const show = toggle.getAttribute("aria-pressed") !== "true";
      toggle.setAttribute("aria-pressed", String(show));
      overlay.layer.classList.toggle("labels-hidden", !show);
      if (show) twin.draw();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && active) stop();
    });
    if (workspace) {
      const sync = () => {
        const snapshot = workspace.snapshot();
        overlay.update(snapshot, workspace.offline());
        run.disabled = !allowed();
        toggle.disabled = !twin.bench;
        bar.hidden = !twin.bench;
        if (!allowed()) stop();
        run.title = allowed()
          ? ""
          : "Select a built-in bench replay to simulate";
      };
      window.addEventListener("halo:snapshot", sync);
      window.addEventListener("halo:view", () => {
        if (active) stop();
      });
      for (const id of ["mode", "scenario", "dataset", "cursor", "play"]) {
        const element = document.getElementById(id);
        element?.addEventListener(
          id === "play" ? "click" : id === "cursor" ? "input" : "change",
          () => stop(),
        );
      }
      sync();
    } else {
      overlay.update(null);
      sample(100, false, epoch).catch(() => {});
    }
  }
  // This file loads after the page-specific twin has been constructed.
  mount(window.HaloLandingTwin || window.HaloActiveTwin, window.HaloWorkspace);
})();
