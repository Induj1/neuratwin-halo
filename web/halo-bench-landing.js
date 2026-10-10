(() => {
  const canvas = document.getElementById("twin-3d");
  if (!canvas || !window.HaloTwin) return;
  const twin = new HaloTwin(canvas, (part) => {
    document
      .querySelectorAll("[data-bench-part]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.benchPart === part)),
      );
  });
  window.HaloLandingTwin = twin;
  if (twin.failed) return;
  document.querySelector(".twin-canvas").classList.add("three-ready");
  twin.angle = 0.42;
  twin.pitch = 0.68;
  twin.distance = 12.4;
  twin.draw();
  document.querySelectorAll("[data-bench-part]").forEach((b) =>
    b.addEventListener("click", () => {
      twin.focus(b.dataset.benchPart);
      paused = true;
    }),
  );
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let paused = motion.matches,
    visible = true,
    last = 0;
  twin.pauseRotation = () => {
    paused = true;
  };
  canvas.addEventListener("pointerdown", twin.pauseRotation);
  canvas.addEventListener("keydown", twin.pauseRotation);
  motion.addEventListener("change", () => {
    paused = motion.matches;
  });
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
