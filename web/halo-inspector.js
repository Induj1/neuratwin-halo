(() => {
  const getTwin = () => window.HaloActiveTwin;
  document.querySelectorAll("[data-projection]").forEach((button) =>
    button.addEventListener("click", () => {
      getTwin()?.setProjection(button.dataset.projection);
      document
        .querySelectorAll("[data-projection]")
        .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    }),
  );
  document
    .getElementById("assembly-thermal")
    .addEventListener("click", function () {
      const active = this.getAttribute("aria-pressed") !== "true";
      this.setAttribute("aria-pressed", String(active));
      getTwin()?.setThermal(active);
    });
  window.addEventListener("halo:snapshot", () => {
    const twin = getTwin(),
      disabled = !!twin?.distribution;
    document.getElementById("assembly-thermal").disabled = disabled;
    if (!disabled) {
      twin?.setCutaway(
        document.getElementById("cutaway").getAttribute("aria-pressed") ===
          "true",
      );
      twin?.setThermal(
        document
          .getElementById("assembly-thermal")
          .getAttribute("aria-pressed") === "true",
      );
    }
  });
})();
