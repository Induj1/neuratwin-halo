(() => {
  const canvas = document.getElementById("twin-3d");
  if (!canvas || !window.HaloTwin) return;
  const caption = document.getElementById("bench-component");
  const names = {
    transformer: "12-0-12 V transformer",
    controller: "ESP32 & optional interface",
    voltage: "Primary & secondary voltage sensors",
    current: "Primary & secondary current sensors",
    surface: "Transformer surface probe",
    relay: "Four-channel relay & 39 Ω loads",
  };
  const twin = new HaloTwin(canvas, (part) => {
    caption.textContent = names[part] || "Prototype assembly";
    document
      .querySelectorAll("[data-bench-part]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.benchPart === part)),
      );
  });
  window.HaloLandingTwin = twin;
  if (twin.failed) {
    document.querySelector(".bench-tools").hidden = true;
    return;
  }
  document.querySelector(".twin-canvas").classList.add("three-ready");
  twin.angle = 0.42;
  twin.pitch = 0.68;
  twin.distance = 12.4;
  twin.draw();
  document.querySelectorAll("[data-bench-part]").forEach((b) =>
    b.addEventListener("click", () => {
      twin.focus(b.dataset.benchPart);
      paused = true;
      updatePause();
    }),
  );
  const explode = document.getElementById("bench-explode");
  explode.addEventListener("input", () => {
    twin.setExplosion(Number(explode.value) / 100);
  });
  document
    .getElementById("model-cutaway")
    .addEventListener("click", function () {
      const active = this.getAttribute("aria-pressed") !== "true";
      this.setAttribute("aria-pressed", String(active));
      twin.setCutaway(active);
    });
  document.getElementById("bench-reset").addEventListener("click", () => {
    twin.reset();
    twin.distance = 12.4;
    twin.draw();
    caption.textContent = "Prototype assembly";
    document
      .querySelectorAll("[data-bench-part]")
      .forEach((b) => b.setAttribute("aria-pressed", "false"));
  });
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let paused = motion.matches,
    visible = true,
    last = 0;
  const pause = document.getElementById("model-motion");
  function updatePause() {
    pause.textContent = paused ? "Rotate" : "Pause";
    pause.setAttribute("aria-pressed", String(paused));
    pause.setAttribute(
      "aria-label",
      paused ? "Start model rotation" : "Pause model rotation",
    );
  }
  pause.addEventListener("click", () => {
    paused = !paused;
    updatePause();
  });
  canvas.addEventListener("pointerdown", () => {
    paused = true;
    updatePause();
  });
  motion.addEventListener("change", () => {
    paused = motion.matches;
    updatePause();
  });
  updatePause();
  new IntersectionObserver((entries) => {
    visible = entries[0].isIntersecting;
  }).observe(canvas);
  function frame(t) {
    requestAnimationFrame(frame);
    if (paused || !visible || document.hidden || t - last < 40) return;
    last = t;
    twin.angle += 0.0025;
    twin.draw();
  }
  requestAnimationFrame(frame);
})();
