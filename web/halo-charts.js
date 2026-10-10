/* Interruptible SVG transitions. Final coordinates always remain the supplied data. */
(() => {
  const NS = "http://www.w3.org/2000/svg",
    frames = new WeakMap();
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const numbers = /-?\d*\.?\d+(?:e[-+]?\d+)?/gi;
  function interpolate(from, to) {
    let a = from.match(numbers)?.map(Number);
    const b = to.match(numbers)?.map(Number);
    if (!a || !b) return null;
    if (
      a.length !== b.length &&
      /^[ML\d.,\s+-]+$/.test(from) &&
      /^[ML\d.,\s+-]+$/.test(to) &&
      (from.match(/M/g) || []).length === 1 &&
      (to.match(/M/g) || []).length === 1 &&
      a.length % 2 === 0 &&
      b.length % 2 === 0
    ) {
      const source = a,
        count = b.length / 2;
      a = Array.from({ length: b.length }, (_, i) => {
        const t =
            (Math.floor(i / 2) / Math.max(1, count - 1)) *
            (source.length / 2 - 1),
          low = Math.floor(t),
          high = Math.min(low + 1, source.length / 2 - 1),
          axis = i % 2;
        return (
          source[low * 2 + axis] +
          (source[high * 2 + axis] - source[low * 2 + axis]) * (t - low)
        );
      });
    } else if (from.replace(numbers, "#") !== to.replace(numbers, "#"))
      return null;
    if (a.length !== b.length) return null;
    return (t) => {
      let i = 0;
      return to.replace(numbers, () => {
        const j = i++;
        return (a[j] + (b[j] - a[j]) * t).toFixed(3);
      });
    };
  }
  function render(svg, markup, duration = 170) {
    if (!svg) return;
    cancelAnimationFrame(frames.get(svg));
    const next = document.createElementNS(NS, "svg");
    next.innerHTML = markup;
    const old = [...svg.children],
      incoming = [...next.children];
    // Changed gap topology is installed immediately rather than joining missing data.
    if (
      duration <= 0 ||
      motion.matches ||
      document.hidden ||
      !old.length ||
      old.length !== incoming.length ||
      old.some((n, i) => n.tagName !== incoming[i].tagName)
    ) {
      svg.replaceChildren(...incoming);
      return;
    }
    const tweens = [];
    for (let i = 0; i < incoming.length; i++) {
      const node = old[i],
        target = incoming[i];
      for (const attribute of [...node.attributes])
        if (!target.hasAttribute(attribute.name))
          node.removeAttribute(attribute.name);
      for (const { name, value } of target.attributes) {
        const current = node.getAttribute(name);
        const tween =
          current &&
          [
            "d",
            "points",
            "x",
            "y",
            "x1",
            "y1",
            "x2",
            "y2",
            "cx",
            "cy",
          ].includes(name)
            ? interpolate(current, value)
            : null;
        if (tween)
          tweens.push((t) =>
            node.setAttribute(name, t === 1 ? value : tween(t)),
          );
        else node.setAttribute(name, value);
      }
      const numericText =
        node.tagName === "text" &&
        /^-?\d+(\.\d+)?$/.test(node.textContent) &&
        /^-?\d+(\.\d+)?$/.test(target.textContent);
      if (numericText) {
        const from = Number(node.textContent),
          to = Number(target.textContent),
          digits = target.textContent.split(".")[1]?.length || 0;
        tweens.push((t) => {
          node.textContent =
            t === 1
              ? target.textContent
              : (from + (to - from) * t).toFixed(digits);
        });
      } else node.textContent = target.textContent;
    }
    const started = performance.now();
    function draw(now) {
      const p = Math.min(1, (now - started) / duration),
        eased = 1 - (1 - p) ** 3;
      tweens.forEach((fn) => fn(eased));
      if (p < 1 && !document.hidden && !motion.matches)
        frames.set(svg, requestAnimationFrame(draw));
      else {
        tweens.forEach((fn) => fn(1));
        frames.delete(svg);
      }
    }
    frames.set(svg, requestAnimationFrame(draw));
  }
  // Same nine-parameter-scenario recurrence as neuratwin/thermal.py.
  // It only projects the API's existing state; it does not infer new measurements.
  function forecast(snapshot, reduction) {
    if (!snapshot.forecast?.length || !snapshot.comparison)
      throw Error("Forecast unavailable");
    const asset = snapshot.asset,
      first = snapshot.forecast[0],
      history = snapshot.history;
    const ambient = [...history]
      .reverse()
      .find((r) => Number.isFinite(r.ambient_c))?.ambient_c;
    const voltage = [...history]
      .reverse()
      .find((r) => Number.isFinite(r.voltage_pu))?.voltage_pu;
    if (
      ![ambient, voltage, reduction].every(Number.isFinite) ||
      reduction < 0 ||
      reduction > 50
    )
      throw Error("Invalid forecast inputs");
    const states = Array.from({ length: 9 }, (_, i) => ({
      factor: 0.9 + i * 0.025,
      oil: first.oil_c,
      gradient: first.hotspot_c - first.oil_c,
    }));
    const alternative = [{ ...first }];
    for (
      let minute = 1;
      minute <= snapshot.intervention.horizon_min;
      minute++
    ) {
      const load =
        minute > snapshot.intervention.delay_min
          ? first.load_pu * (1 - reduction / 100)
          : first.load_pu;
      for (const state of states) {
        const f = state.factor;
        const oil =
          ambient +
          asset.rated_oil_rise_c *
            f *
            ((voltage ** 2 + asset.loss_ratio * load ** 2) /
              (1 + asset.loss_ratio)) **
              asset.oil_exponent;
        const gradient =
          asset.rated_winding_gradient_c * f * load ** asset.winding_exponent;
        state.oil =
          oil + (state.oil - oil) * Math.exp(-1 / (asset.oil_tau_min / f));
        state.gradient =
          gradient +
          (state.gradient - gradient) * Math.exp(-1 / asset.winding_tau_min);
      }
      const temps = states.map((s) => s.oil + s.gradient);
      alternative.push({
        minute,
        oil_c: states[4].oil,
        hotspot_c: temps[4],
        low_c: Math.min(...temps),
        high_c: Math.max(...temps),
        load_pu: load,
      });
    }
    const peak = Math.max(...alternative.map((r) => r.hotspot_c)),
      limit = asset.hotspot_limit_c;
    const metrics = {
      peak_hotspot_c: peak,
      minutes_to_limit:
        alternative.find((r) => r.hotspot_c >= limit)?.minute ?? null,
      minutes_above_limit: alternative
        .slice(1)
        .filter((r) => r.hotspot_c >= limit).length,
      exposure_c_min: alternative
        .slice(1)
        .reduce((sum, r) => sum + Math.max(0, r.hotspot_c - limit), 0),
    };
    return {
      ...snapshot,
      alternative,
      intervention: { ...snapshot.intervention, reduction_pct: reduction },
      comparison: {
        ...snapshot.comparison,
        alternative: metrics,
        peak_reduction_c: snapshot.comparison.baseline.peak_hotspot_c - peak,
        exposure_reduction_c_min:
          snapshot.comparison.baseline.exposure_c_min - metrics.exposure_c_min,
      },
    };
  }
  window.HaloCharts = { render, forecast };
})();
