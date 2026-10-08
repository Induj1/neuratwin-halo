/* Photo-informed prototype geometry. Component positions and cable paths are illustrative. */
window.HaloBenchModel = function (T) {
  const root = new T.Group(),
    groups = [],
    parts = [],
    covers = [],
    leds = [],
    coils = [];
  const mats = {};
  function mat(color, metal = 0.15, rough = 0.45) {
    const key = [color, metal, rough].join("/");
    return (
      mats[key] ||
      (mats[key] = new T.MeshStandardMaterial({
        color: new T.Color(color).convertSRGBToLinear(),
        metalness: metal,
        roughness: rough,
      }))
    );
  }
  const silver = mat("#9fa9ac", 0.82, 0.3),
    gold = mat("#aa9359", 0.78, 0.3),
    steel = mat("#40474a", 0.75, 0.44),
    copper = mat("#bb6330", 0.75, 0.29),
    blue = mat("#146087", 0.15, 0.35),
    pcbBlue = mat("#164e68", 0.2, 0.48),
    black = mat("#1f2528", 0.12, 0.55),
    green = mat("#316f45", 0.08, 0.62),
    cream = mat("#d5d4c6", 0.05, 0.65);
  function mesh(parent, geometry, material, x = 0, y = 0, z = 0) {
    const m = new T.Mesh(geometry, material);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  }
  function box(g, w, h, d, x, y, z, m, r = 0.025) {
    r = Math.min(r, w * 0.2, h * 0.2, d * 0.2);
    const a = w / 2 - r,
      b = h / 2 - r,
      s = new T.Shape();
    s.moveTo(-a, -h / 2);
    s.lineTo(a, -h / 2);
    s.quadraticCurveTo(w / 2, -h / 2, w / 2, -b);
    s.lineTo(w / 2, b);
    s.quadraticCurveTo(w / 2, h / 2, a, h / 2);
    s.lineTo(-a, h / 2);
    s.quadraticCurveTo(-w / 2, h / 2, -w / 2, b);
    s.lineTo(-w / 2, -b);
    s.quadraticCurveTo(-w / 2, -h / 2, -a, -h / 2);
    const geo = new T.ExtrudeGeometry(s, {
      depth: Math.max(0.001, d - 2 * r),
      bevelEnabled: true,
      bevelSize: r * 0.5,
      bevelThickness: r,
      bevelSegments: 2,
      steps: 1,
      curveSegments: 3,
    });
    geo.translate(0, 0, -d / 2 + r);
    return mesh(g, geo, m, x, y, z);
  }
  function cyl(g, r, h, x, y, z, m, n = 20) {
    return mesh(g, new T.CylinderGeometry(r, r, h, n), m, x, y, z);
  }
  function wire(g, points, m = copper, r = 0.019) {
    return mesh(
      g,
      new T.TubeGeometry(
        new T.CatmullRomCurve3(points.map((p) => new T.Vector3(...p))),
        30,
        r,
        7,
        false,
      ),
      m,
    );
  }
  function screw(g, x, y, z, r = 0.044) {
    cyl(g, r, 0.025, x, y, z, silver, 12);
    box(g, r * 1.3, 0.005, 0.009, x, y + 0.014, z, steel, 0.001);
  }
  function label(
    g,
    text,
    w,
    h,
    x,
    y,
    z,
    bg = "#d8d9d1",
    fg = "#263036",
    front = false,
  ) {
    const c = document.createElement("canvas");
    c.width = 768;
    c.height = 256;
    const ctx = c.getContext("2d");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.fillStyle = fg;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const lines = text.split("\n");
    ctx.font = `500 ${lines.length === 1 ? 70 : 52}px Arial`;
    lines.forEach((l, i) =>
      ctx.fillText(l, 384, 128 + (i - (lines.length - 1) / 2) * 72),
    );
    const tex = new T.CanvasTexture(c);
    tex.encoding = T.sRGBEncoding;
    const m = mesh(
      g,
      new T.PlaneGeometry(w, h),
      new T.MeshStandardMaterial({ map: tex, roughness: 0.6, metalness: 0.05 }),
      x,
      y,
      z,
    );
    if (!front) m.rotation.x = -Math.PI / 2;
    return m;
  }
  function group(id, category, pos, spread) {
    const g = new T.Group();
    g.name = id;
    g.position.fromArray(pos);
    g.userData = {
      part: category,
      home: new T.Vector3(...pos),
      spread: new T.Vector3(...spread),
    };
    root.add(g);
    groups.push(g);
    return g;
  }
  function board(g, w, d, color = pcbBlue) {
    box(g, w, 0.055, d, 0, 0.14, 0, color, 0.018);
    for (const x of [-w / 2 + 0.065, w / 2 - 0.065])
      for (const z of [-d / 2 + 0.07, d / 2 - 0.07]) {
        cyl(g, 0.049, 0.018, x, 0.177, z, gold);
        cyl(g, 0.027, 0.02, x, 0.188, z, black);
        cyl(g, 0.04, 0.11, x, 0.06, z, gold);
      }
  }
  function chip(g, x, z, w = 0.18, d = 0.22) {
    box(g, w, 0.06, d, x, 0.205, z, black, 0.008);
    for (let i = 0; i < 4; i++)
      for (const side of [-1, 1])
        box(
          g,
          0.048,
          0.018,
          0.017,
          x + side * (w / 2 + 0.018),
          0.19,
          z - d * 0.35 + i * d * 0.23,
          silver,
          0.002,
        );
  }
  function terminal(g, x, z, count = 2) {
    box(g, count * 0.13, 0.22, 0.22, x, 0.285, z, mat("#277252"), 0.012);
    for (let i = 0; i < count; i++) {
      const px = x + (i - (count - 1) / 2) * 0.13;
      cyl(g, 0.042, 0.011, px, 0.401, z, black);
      screw(g, px, 0.405, z, 0.03);
      box(g, 0.075, 0.065, 0.009, px, 0.26, z + 0.115, black, 0.003);
    }
  }
  function headers(g, x, z, count, alongZ = true) {
    for (let i = 0; i < count; i++) {
      const px = x + (alongZ ? 0 : i * 0.09),
        pz = z + (alongZ ? i * 0.09 : 0);
      box(g, 0.08, 0.09, 0.08, px, 0.22, pz, black, 0.005);
      box(g, 0.022, 0.2, 0.022, px, 0.31, pz, gold, 0.002);
    }
  }

  // Laminated centre-tapped transformer, matching the gold clamp and dark bobbin in the photo.
  const tr = group(
    "transformer",
    "transformer",
    [-1.6, 0, -0.35],
    [-0.5, 0.7, -0.2],
  );
  box(tr, 2.05, 0.09, 1.62, 0, 0.075, 0, gold, 0.035);
  for (const x of [-0.88, 0.88])
    for (const z of [-0.63, 0.63]) screw(tr, x, 0.135, z, 0.065);
  for (let i = 0; i < 33; i++) {
    const z = -0.58 + i * 0.036;
    box(tr, 1.7, 0.21, 0.027, 0, 0.28, z, i % 3 ? steel : silver, 0.004);
    box(tr, 1.7, 0.21, 0.027, 0, 1.46, z, i % 3 ? steel : silver, 0.004);
    for (const x of [-0.71, 0.71])
      box(tr, 0.27, 1.07, 0.027, x, 0.875, z, i % 3 ? steel : silver, 0.003);
  }
  const bobbin = box(tr, 1.06, 0.99, 1.3, 0, 0.87, 0, black, 0.045);
  covers.push(bobbin);
  for (let i = 0; i < 43; i++) {
    const c = mesh(
      tr,
      new T.TorusGeometry(0.39, 0.018, 7, 40),
      copper,
      0,
      0.87,
      -0.55 + i * 0.026,
    );
    c.scale.set(1.1, 1, 1);
    coils.push(c);
  }
  box(tr, 0.36, 0.62, 1.28, 0, 0.86, 0, steel, 0.02);
  const top = box(tr, 1.95, 0.075, 1.47, 0, 1.65, 0, gold, 0.05);
  covers.push(top);
  for (const x of [-0.91, 0.91]) {
    const clamp = box(tr, 0.065, 1.44, 1.42, x, 0.9, 0, gold, 0.014);
    covers.push(clamp);
  }
  const plate = label(
    tr,
    "EXP-PRO\n12-0-12",
    0.95,
    0.36,
    0,
    1.05,
    0.662,
    "#d9d9cf",
    "#1b334e",
    true,
  );
  covers.push(plate);
  for (const x of [-0.57, -0.28, 0, 0.28, 0.57])
    box(tr, 0.08, 0.25, 0.14, x, 1.28, 0.69, cream, 0.01);
  for (const [x, color] of [
    [-0.48, "#234d87"],
    [0, "#24262b"],
    [0.48, "#b13f39"],
  ])
    wire(
      tr,
      [
        [x, 1.3, 0.66],
        [x * 0.9, 1.65, 0.85],
        [x + 0.15, 0.55, 1.15],
      ],
      mat(color),
      0.033,
    );
  for (const x of [-0.66, 0.66]) {
    screw(tr, x, 1.71, -0.5, 0.05);
    screw(tr, x, 1.71, 0.5, 0.05);
  }

  // Four-channel relay module and four separate 39-ohm cylindrical loads.
  const rel = group(
    "relay-module",
    "relay",
    [1.45, 0, -0.85],
    [0.6, 0.2, -0.3],
  );
  board(rel, 2.25, 1.12);
  for (let i = 0; i < 4; i++) {
    const x = -0.8 + i * 0.535;
    box(rel, 0.46, 0.47, 0.57, x, 0.42, -0.03, blue, 0.025);
    label(
      rel,
      "RELAY\n" + (i + 1),
      0.4,
      0.35,
      x,
      0.666,
      -0.03,
      "#1e5a80",
      "#b2cbd4",
    );
    terminal(rel, x, -0.46, 3);
    chip(rel, x, 0.37, 0.12, 0.17);
    const led = cyl(rel, 0.023, 0.022, x - 0.17, 0.188, 0.3, mat("#9a3f28"));
    leds.push(led);
  }
  headers(rel, -0.26, 0.49, 6, false);
  const load = group(
    "load-resistors",
    "relay",
    [1.5, 0, 0.8],
    [0.65, 0.45, 0.45],
  );
  for (let i = 0; i < 4; i++) {
    const x = -0.84 + i * 0.56;
    const resistor = cyl(load, 0.15, 0.95, x, 0.28, 0, green, 28);
    resistor.rotation.x = Math.PI / 2;
    for (const z of [-0.48, 0.48]) {
      const cap = cyl(load, 0.119, 0.025, x, 0.28, z, steel, 24);
      cap.rotation.x = Math.PI / 2;
      wire(
        load,
        [
          [x, 0.28, z],
          [x, 0.28, z + Math.sign(z) * 0.2],
          [x, 0.12, z + Math.sign(z) * 0.32],
        ],
        silver,
        0.012,
      );
    }
    label(load, "39 Ω / 10 W", 0.42, 0.14, x, 0.435, 0, "#316f45", "#d6dfcc");
  }
  // The ESP32 reference uses a black board, RF can, micro USB and two long pin headers.
  const esp = group("esp32", "controller", [0, 0, 1.65], [0, 0.8, 0.85]);
  board(esp, 0.9, 1.65, black);
  box(esp, 0.56, 0.09, 0.69, 0, 0.245, -0.22, silver, 0.025);
  label(esp, "ESP-32", 0.5, 0.31, 0, 0.297, -0.22, "#a9afb0", "#414b50");
  box(esp, 0.52, 0.025, 0.21, 0, 0.183, -0.67, black, 0.005);
  for (let i = 0; i < 5; i++)
    box(esp, 0.37, 0.005, 0.015, 0, 0.2, -0.75 + i * 0.035, gold, 0.001);
  chip(esp, 0, 0.38, 0.27, 0.27);
  box(esp, 0.18, 0.055, 0.1, -0.21, 0.21, 0.2, silver, 0.012);
  headers(esp, -0.38, -0.69, 16);
  headers(esp, 0.38, -0.69, 16);
  box(esp, 0.28, 0.14, 0.24, 0, 0.24, 0.79, silver, 0.018);
  box(esp, 0.21, 0.075, 0.015, 0, 0.239, 0.922, black, 0.009);
  for (const x of [-0.3, 0.3]) {
    box(esp, 0.12, 0.05, 0.14, x, 0.21, 0.68, silver, 0.008);
    cyl(esp, 0.035, 0.024, x, 0.25, 0.68, black);
  }
  // Two voltage and two current modules. These reproduce the visible module shapes, not pin assignments.
  for (let i = 0; i < 2; i++) {
    const g = group(
      "voltage-" + i,
      "voltage",
      [-3.25, 0, -1.15 + i * 1.65],
      [-0.8, 0.4, i ? 0.3 : -0.4],
    );
    board(g, 0.63, 1.25);
    box(g, 0.53, 0.4, 0.48, 0, 0.385, -0.18, blue, 0.018);
    label(g, "AC VOLTAGE", 0.48, 0.22, 0, 0.593, -0.18, "#146087", "#b6d4df");
    terminal(g, 0, -0.53);
    box(g, 0.22, 0.16, 0.22, 0, 0.275, 0.28, blue, 0.014);
    screw(g, 0, 0.369, 0.28, 0.037);
    chip(g, 0, 0.51, 0.12, 0.13);
    headers(g, -0.13, 0.6, 4, false);
    const c = group(
      "current-" + i,
      "current",
      [-0.25 + i * 1.32, 0, -2.05],
      [i ? 0.3 : -0.2, 0.6, -0.7],
    );
    board(c, 0.57, 0.93);
    terminal(c, 0, -0.3);
    chip(c, 0, 0.02, 0.22, 0.24);
    headers(c, -0.09, 0.4, 3, false);
    label(c, "CURRENT", 0.46, 0.12, 0, 0.178, 0.22, "#164e68", "#d2e5e6");
  }
  const temp = group(
    "surface-probe",
    "surface",
    [-2.48, 0.88, 0.28],
    [-0.8, 0.45, 0.2],
  );
  const probe = cyl(temp, 0.045, 0.48, 0, 0, 0, silver);
  probe.rotation.z = Math.PI / 2;
  box(temp, 0.21, 0.06, 0.17, 0, -0.02, 0, mat("#665147"), 0.015);
  wire(
    temp,
    [
      [0.25, 0, 0],
      [0.4, -0.15, 0.15],
      [0.45, -0.7, 0.3],
    ],
    black,
    0.018,
  );
  const optional = group(
    "optional-dividers",
    "controller",
    [2.9, 0, 1.65],
    [0.6, 0.15, 0.7],
  );
  board(optional, 0.75, 0.8, mat("#805c37"));
  for (let i = 0; i < 4; i++) {
    const r = cyl(
      optional,
      0.027,
      0.26,
      -0.23 + i * 0.15,
      0.22,
      0,
      mat("#bba07a"),
    );
    r.rotation.x = Math.PI / 2;
    for (const z of [-0.17, 0.17])
      box(
        optional,
        0.009,
        0.07,
        0.07,
        -0.23 + i * 0.15,
        0.195,
        z,
        silver,
        0.001,
      );
  }
  label(optional, "OPTIONAL", 0.6, 0.13, 0, 0.18, 0.3, "#805c37", "#eee4d3");
  // Neutral presentation plate and non-electrical routing cues.
  const base = new T.Group();
  root.add(base);
  box(base, 8.2, 0.13, 5.55, -0.2, -0.12, 0, mat("#d6d8d6", 0.48, 0.35), 0.06);
  for (const x of [-4.05, 3.65])
    for (const z of [-2.53, 2.53]) screw(base, x, -0.035, z, 0.05);
  for (const g of groups)
    g.traverse((m) => {
      if (m.isMesh) {
        m.userData.part = g.userData.part;
        m.userData.component = g.name;
        parts.push(m);
      }
    });
  const cables = new T.Group();
  root.add(cables);
  wire(
    cables,
    [
      [-0.25, 0.03, -2.05],
      [0.3, 0.03, -1.8],
      [0.25, 0.03, 0.7],
      [0, 0.06, 1.3],
    ],
    mat("#3d4e5c"),
    0.018,
  );
  wire(
    cables,
    [
      [1.4, 0.03, -0.25],
      [1.6, 0.03, 0.15],
      [1.8, 0.03, 0.32],
    ],
    mat("#a44939"),
    0.026,
  );
  wire(
    cables,
    [
      [0, 0.22, 2.55],
      [0, 0.25, 2.9],
      [-1, 0.05, 3.1],
    ],
    mat("#e1e3df"),
    0.045,
  );
  const glow = mesh(
    temp,
    new T.SphereGeometry(0.15, 24, 16),
    new T.MeshBasicMaterial({
      color: "#c15d32",
      transparent: true,
      opacity: 0,
      depthWrite: false,
    }),
    0,
    0,
    0,
  );
  glow.scale.set(2, 1, 1);
  let exploded = 0,
    cutaway = false;
  return {
    root,
    parts,
    groups,
    body: top,
    cover: top,
    cutawayParts: covers,
    setTemperature(value, severity = "normal") {
      // One surface probe drives an equipment-level cue, not a spatial heat map.
      const active =
        Number.isFinite(value) && ["warning", "critical"].includes(severity);
      const color = new T.Color(
        severity === "critical" ? "#f04420" : "#ee941d",
      ).convertSRGBToLinear();
      for (const m of parts.filter((part) =>
        ["transformer", "surface"].includes(part.userData.part),
      )) {
        m.userData.baseMaterial ||= m.material;
        m.userData.thermalActive = active;
        if (active) {
          m.userData.thermalMaterial ||= m.userData.baseMaterial.clone();
          const material = m.userData.thermalMaterial;
          material.color.copy(m.userData.baseMaterial.color).lerp(color, 0.64);
          material.emissive.copy(color);
          material.emissiveIntensity = severity === "critical" ? 0.8 : 0.45;
          m.material = material;
        } else {
          m.material =
            (m.userData.isSelected && m.userData.selectedMaterial) ||
            m.userData.baseMaterial;
        }
      }
      glow.material.color.copy(color);
      glow.material.opacity = active ? 0.5 : this.highlight ? 0.45 : 0;
    },
    setExplosion(value) {
      exploded = value;
      groups.forEach((g) =>
        g.position
          .copy(g.userData.home)
          .addScaledVector(g.userData.spread, value),
      );
      cables.visible = value < 0.1;
    },
    setCutaway(value) {
      cutaway = value;
      covers.forEach((m) => (m.visible = !value));
    },
    setThermal(value) {
      this.highlight = value;
      glow.material.opacity = parts.some((m) => m.userData.thermalActive)
        ? 0.5
        : value
          ? 0.45
          : 0;
    },
    setRelays(states) {
      leds.forEach((l, i) => {
        l.material = mat(states?.[i] ? "#cd6339" : "#62392e");
      });
    },
    select(part) {
      groups.forEach((g) => {
        g.visible = true;
      });
    },
    focus(part) {
      return (
        groups.find((g) => g.userData.part === part)?.position.clone() ||
        new T.Vector3()
      );
    },
  };
};
