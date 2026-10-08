/* Local procedural geometry. Illustrative assembly, never a wiring reference. */
class HaloTwin {
  constructor(canvas, onSelect = () => {}, options = {}) {
    this.options = options;
    this.canvas = canvas;
    this.onSelect = onSelect;
    this.parts = [];
    this.angle = 0.48;
    this.pitch = 0.7;
    this.distance = 11.5;
    try {
      const T = window.THREE;
      if (!T) throw Error("Three unavailable");
      this.target = new T.Vector3(0, 0.45, 0);
      this.renderer = new T.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
      });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.6));
      this.renderer.outputEncoding = T.sRGBEncoding;
      this.renderer.toneMapping = T.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1;
      this.scene = new T.Scene();
      this.camera = new T.PerspectiveCamera(38, 1, 0.1, 80);
      if (window.HaloStudio)
        window.HaloStudio(T, this.scene, this.renderer, -0.38);
      this.renderer.toneMappingExposure = 0.8;
      this.scene.traverse((o) => {
        if (o.isDirectionalLight) o.intensity *= 0.65;
      });
      this.root = new T.Group();
      this.scene.add(this.root);
      this.build(false);
      this.resize = new ResizeObserver(() => this.draw());
      this.resize.observe(canvas);
      let drag = null;
      canvas.addEventListener("pointerdown", (e) => {
        drag = { x: e.clientX, y: e.clientY, moved: 0 };
        canvas.setPointerCapture(e.pointerId);
      });
      canvas.addEventListener("pointermove", (e) => {
        if (!drag) return;
        const dx = e.clientX - drag.x,
          dy = e.clientY - drag.y;
        drag.moved += Math.abs(dx) + Math.abs(dy);
        this.angle -= dx * 0.009;
        this.pitch = Math.max(0.12, Math.min(1.3, this.pitch + dy * 0.005));
        drag.x = e.clientX;
        drag.y = e.clientY;
        this.draw();
      });
      canvas.addEventListener("pointerup", (e) => {
        if (drag?.moved < 5) this.pick(e);
        drag = null;
      });
      canvas.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          this.distance = Math.max(
            6,
            Math.min(18, this.distance + e.deltaY * 0.005),
          );
          this.draw();
        },
        { passive: false },
      );
      canvas.style.touchAction = "pan-y";
      canvas.tabIndex = 0;
      canvas.addEventListener("pointercancel", () => {
        drag = null;
      });
      canvas.addEventListener("keydown", (e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          this.angle += e.key === "ArrowLeft" ? -0.12 : 0.12;
          this.draw();
        } else if (e.key === "0") this.reset();
      });
      this.draw();
    } catch (e) {
      this.failed = true;
      const fallback = canvas.parentElement.querySelector(".model-fallback");
      if (fallback) fallback.hidden = false;
    }
  }
  box(x, y, z, w, h, d, color, part, metal = 0.15) {
    const T = THREE,
      r = Math.min(0.045, w * 0.12, h * 0.12, d * 0.12),
      s = new T.Shape(),
      a = w / 2 - r,
      b = h / 2 - r;
    s.moveTo(-a, -b);
    s.lineTo(a, -b);
    s.lineTo(a, b);
    s.lineTo(-a, b);
    s.closePath();
    const geo = new T.ExtrudeGeometry(s, {
      depth: d - 2 * r,
      bevelEnabled: true,
      bevelSize: r,
      bevelThickness: r,
      bevelSegments: 2,
      steps: 1,
    });
    geo.translate(0, 0, -d / 2 + r);
    const mesh = new T.Mesh(
      geo,
      new T.MeshStandardMaterial({ color, roughness: 0.36, metalness: metal }),
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.position.set(x, y, z);
    mesh.userData.part = part;
    this.root.add(mesh);
    if (part) this.parts.push(mesh);
    return mesh;
  }
  cylinder(x, y, z, r, h, color, part, rotation = 0) {
    const T = THREE,
      m = new T.Mesh(
        new T.CylinderGeometry(r, r, h, 28),
        new T.MeshStandardMaterial({ color, roughness: 0.42, metalness: 0.2 }),
      );
    m.castShadow = true;
    m.receiveShadow = true;
    m.position.set(x, y, z);
    m.rotation.z = rotation;
    m.userData.part = part;
    this.root.add(m);
    if (part) this.parts.push(m);
    return m;
  }
  wire(points, color) {
    const T = THREE,
      curve = new T.CatmullRomCurve3(points.map((p) => new T.Vector3(...p)));
    this.root.add(
      new T.Mesh(
        new T.TubeGeometry(curve, 24, 0.026, 7, false),
        new T.MeshStandardMaterial({ color }),
      ),
    );
  }
  label(text, x, y, z, part) {
    const c = document.createElement("canvas");
    c.width = 384;
    c.height = 96;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#e6e9dc";
    ctx.fillRect(0, 0, 384, 96);
    ctx.strokeStyle = "#bac3ab";
    ctx.lineWidth = 3;
    ctx.strokeRect(2, 2, 380, 92);
    ctx.font = "500 35px monospace";
    ctx.fillStyle = "#46523b";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 192, 48);
    const texture = new THREE.CanvasTexture(c);
    texture.encoding = THREE.sRGBEncoding;
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 0.25),
      new THREE.MeshStandardMaterial({
        map: texture,
        side: THREE.DoubleSide,
        roughness: 0.8,
        metalness: 0.05,
      }),
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, y, z);
    m.userData.part = part;
    this.root.add(m);
    if (part) this.parts.push(m);
  }
  details(distribution) {
    for (const x of [-3.22, 3.22])
      for (const z of [-2.02, 2.02])
        this.cylinder(x, 0.02, z, 0.08, 0.09, 0xbfc4b5);
    this.box(0, -0.27, 0, 7.2, 0.07, 4.8, 0xa6af98, undefined, 0.55);
    if (!distribution) {
      for (const x of [-2.28, -0.33])
        for (const z of [-0.67, 0.67])
          this.cylinder(x, 1.66, z, 0.04, 0.13, 0x89a2ae, "transformer");
      for (const x of [-1.82, -0.78]) {
        this.cylinder(x, 1.6, 0, 0.06, 0.2, 0xd6ae73, "transformer");
        this.box(x, 0.08, 0, 0.65, 0.06, 1.5, 0x616c5e, "transformer");
      }
      for (let i = 0; i < 4; i++) {
        const x = 0.62 + i * 0.53;
        this.box(x, 0.58, -1, 0.31, 0.025, 0.36, 0x364536, "relay");
        this.box(x, 0.59, -1, 0.18, 0.02, 0.05, 0xadbd95, "relay");
        for (const z of [-1.32, -0.69])
          this.cylinder(x, 0.27, z, 0.045, 0.06, 0xb6a57d, "relay");
      }
      this.box(0.85, 0.3, 1.5, 0.23, 0.15, 0.19, 0xb9c5c7, "controller", 0.7);
      this.wire(
        [
          [-2.5, 0.94, 0.3],
          [-2.65, 0.75, 0.4],
          [-2.7, 0.13, 0.75],
          [-1.9, 0.12, 1.5],
        ],
        0x8d9c7d,
      );
      this.label("TRANSFORMER", -1.3, 0.015, 1.25, "transformer");
      this.label("LOAD BANK", 1.35, 0.015, 0.93, "relay");
      this.label("ESP32", 1.35, 0.015, 2.02, "controller");
      this.label("CURRENT", -0.2, 0.015, -2.03, "current");
    } else {
      for (const x of [-1.18, 0.38])
        this.box(x, 0.05, 0, 0.22, 0.18, 2.05, 0x616c5e, "transformer");
      this.label("TRANSFORMER", -0.4, 0.015, 1.74, "transformer");
      this.label("CONTROLLER", 2, 0.015, 1.4, "controller");
    }
  }
  build(distribution) {
    this.distribution = distribution;
    const resources = new Set();
    this.root.traverse((mesh) => {
      if (mesh.geometry) resources.add(mesh.geometry);
      [
        mesh.material,
        mesh.userData.baseMaterial,
        mesh.userData.selectedMaterial,
        mesh.userData.thermalMaterial,
      ]
        .flat()
        .filter(Boolean)
        .forEach((material) => {
          if (material.map) resources.add(material.map);
          resources.add(material);
        });
    });
    resources.forEach((resource) => resource.dispose());
    while (this.root.children.length) {
      const m = this.root.children[0];
      this.root.remove(m);
    }
    this.parts = [];
    this.cutawayParts = [];
    this.bench = null;
    if (!distribution && window.HaloBenchModel) {
      this.bench = HaloBenchModel(THREE);
      this.root.add(this.bench.root);
      this.parts = this.bench.parts;
      this.body = this.bench.body;
      this.cover = this.bench.cover;
      this.cutawayParts = this.bench.cutawayParts;
      this.draw();
      return;
    }
    this.box(0, -0.13, 0, 7, 0.24, 4.6, 0xc5cbb8);
    if (distribution) {
      this.body = this.box(
        -0.4,
        1.1,
        0,
        2.2,
        2.2,
        1.65,
        0x647b80,
        "transformer",
        0.5,
      );
      for (let i = 0; i < 12; i++) {
        this.box(
          -1.55 + i * 0.22,
          1.05,
          1,
          0.08,
          1.8,
          0.35,
          0x83968f,
          "transformer",
          0.45,
        );
      }
      this.cover = this.box(
        -0.4,
        2.27,
        0,
        2.4,
        0.16,
        1.85,
        0x324c50,
        "transformer",
        0.4,
      );
      for (let x = -1.1; x < 0.8; x += 0.7) {
        this.cylinder(x, 2.7, 0, 0.13, 0.75, 0xae7451, "transformer");
        for (let y = 2.4; y < 3; y += 0.14)
          this.cylinder(x, y, 0, 0.21, 0.07, 0xc4946c, "transformer");
      }
      this.cylinder(0.8, 2.3, 0, 0.23, 0.9, 0xb85b2f, "surface");
      this.box(2, 0.6, 0, 1.4, 1.2, 1.5, 0xe6dfc8, "controller");
    } else {
      for (let i = 0; i < 20; i++) {
        const plate = this.box(
          -1.3,
          0.75,
          -0.76 + i * 0.08,
          2.2,
          1.4,
          0.055,
          i % 2 ? 0x536565 : 0x798985,
          "transformer",
          0.65,
        );
        if (i > 8) this.cutawayParts.push(plate);
      }
      for (let x of [-1.82, -0.78]) {
        this.cylinder(x, 0.85, 0, 0.42, 1.35, 0xab5c31, "transformer");
        for (let y = 0.25; y < 1.48; y += 0.07)
          this.cylinder(x, y, 0, 0.44, 0.035, 0xc5824e, "transformer");
      }
      this.cover = this.box(
        -1.3,
        1.55,
        0,
        2.38,
        0.13,
        1.8,
        0xb3a56b,
        "transformer",
        0.7,
      );
      this.body = this.cover;
      this.box(-1.3, 0.06, 0, 2.5, 0.14, 1.95, 0xb3a56b, "transformer", 0.7);
      this.box(-2.51, 0.9, 0.3, 0.12, 0.46, 0.3, 0xe7e0ce, "surface");
      this.box(1.42, 0.16, -1, 2.25, 0.12, 0.8, 0x657a60, "relay");
      for (let i = 0; i < 4; i++) {
        const x = 0.62 + i * 0.53;
        this.box(x, 0.39, -1, 0.43, 0.36, 0.53, 0x819874, "relay");
        this.cylinder(
          x,
          0.42,
          0.57,
          0.14,
          0.7,
          i === 3 ? 0xada492 : 0x74906d,
          "relay",
          Math.PI / 2,
        );
        this.wire(
          [
            [x, 0.3, -0.65],
            [x, 0.12, -0.2],
            [x - 0.28, 0.16, 0.57],
          ],
          0x9e694a,
        );
      }
      this.box(1.4, 0.18, 1.48, 1.4, 0.13, 0.62, 0x40543f, "controller");
      this.box(1.35, 0.3, 1.48, 0.65, 0.14, 0.49, 0xa4afad, "controller", 0.8);
      for (let x = 0.8; x < 2.1; x += 0.13) {
        this.box(x, 0.22, 1.1, 0.04, 0.17, 0.1, 0xbeab77, "controller");
        this.box(x, 0.22, 1.85, 0.04, 0.17, 0.1, 0xbeab77, "controller");
      }
      this.box(-0.22, 0.23, -1.57, 0.66, 0.12, 0.5, 0x788f69, "current");
      this.box(-0.24, 0.36, -1.57, 0.3, 0.15, 0.25, 0x93b4a2, "current");
      for (const z of [-1.4, 1.4]) {
        this.box(-2.9, 0.2, z, 0.45, 0.1, 0.85, 0x708766, "voltage");
        this.box(-2.9, 0.39, z, 0.35, 0.3, 0.4, 0x93a788, "voltage");
      }
      this.wire(
        [
          [-1.8, 1.58, 0],
          [-1.8, 1.95, -0.5],
          [-0.25, 0.4, -1.5],
        ],
        0x476b8a,
      );
      this.wire(
        [
          [-0.8, 1.58, 0],
          [-0.6, 1.88, -0.65],
          [0.6, 0.55, -1],
        ],
        0xb3634c,
      );
    }
    for (const x of [-2.85, 2.85])
      for (const z of [-1.75, 1.75])
        this.cylinder(x, -0.32, z, 0.18, 0.13, 0x59674f);
    for (const z of [-2.25, 2.25])
      this.box(0, 0.006, z, 6.8, 0.02, 0.025, 0x96a487);
    for (const x of [-3.35, 3.35])
      this.box(x, 0.006, 0, 0.025, 0.02, 4.5, 0x96a487);
    this.details(distribution);
    this.draw();
  }
  setDistribution(value) {
    if (!this.failed && value !== this.distribution) this.build(value);
  }
  setCutaway(value) {
    if (this.failed) return;
    if (this.bench) {
      this.bench.setCutaway(value);
      this.draw();
      return;
    }
    this.cover.visible = !value;
    this.cutawayParts.forEach((m) => (m.visible = !value));
    this.draw();
  }
  select(part) {
    if (this.failed) return;
    this.parts.forEach((m) => {
      if (!m.userData.baseMaterial) m.userData.baseMaterial = m.material;
      m.userData.isSelected = m.userData.part === part;
      if (m.userData.part === part) {
        if (!m.userData.selectedMaterial) {
          m.userData.selectedMaterial = m.userData.baseMaterial.clone();
          m.userData.selectedMaterial.emissive?.setHex(0x163b36);
        }
        m.material = m.userData.selectedMaterial;
      } else m.material = m.userData.baseMaterial;
      if (m.userData.thermalActive) m.material = m.userData.thermalMaterial;
    });
    this.onSelect(part);
    this.draw();
  }
  temperature(value, severity = "normal") {
    if (this.failed) return;
    this.surfaceTemperature = value;
    if (this.bench) {
      this.bench.setTemperature(value, severity);
      this.draw();
      return;
    }
    this.body.material.color.setHex(
      value == null
        ? 0xa4aaa4
        : value > 55
          ? 0xba6845
          : value > 40
            ? 0xbc935e
            : this.distribution
              ? 0x647b80
              : 0xb3a56b,
    );
    this.draw();
  }
  setExplosion(value) {
    if (this.bench) {
      this.bench.setExplosion(value);
      this.draw();
    }
  }
  setThermal(value) {
    this.bench?.setThermal(value);
    this.draw();
  }
  setProjection(value) {
    this.orthographic = value === "ortho";
    this.draw();
  }
  focus(part) {
    if (!this.bench) return;
    cancelAnimationFrame(this.focusFrame);
    const from = this.target.clone(),
      to = this.bench.focus(part),
      startDistance = this.distance;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const started = performance.now();
    const move = (time) => {
      const progress = reduced ? 1 : Math.min(1, (time - started) / 650);
      const eased = 1 - Math.pow(1 - progress, 3);
      this.target.lerpVectors(from, to, eased);
      this.distance = startDistance + (6.8 - startDistance) * eased;
      this.draw();
      if (progress < 1) this.focusFrame = requestAnimationFrame(move);
    };
    this.focusFrame = requestAnimationFrame(move);
    this.select(part);
  }
  reset() {
    cancelAnimationFrame(this.focusFrame);
    this.target.set(0, 0.45, 0);
    this.angle = 0.48;
    this.pitch = 0.7;
    this.distance = 11.5;
    this.draw();
  }
  pick(e) {
    const r = this.canvas.getBoundingClientRect(),
      p = new THREE.Vector2(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        (-(e.clientY - r.top) / r.height) * 2 + 1,
      ),
      ray = new THREE.Raycaster();
    ray.setFromCamera(p, this.camera);
    const hit = ray.intersectObjects(this.parts).find((h) => {
      let o = h.object;
      while (o) {
        if (!o.visible) return false;
        o = o.parent;
      }
      return true;
    });
    if (hit) this.select(hit.object.userData.part);
  }
  draw() {
    if (!this.renderer || this.failed) return;
    const w = this.canvas.clientWidth,
      h = this.canvas.clientHeight;
    if (!w || !h) return;
    if (this.renderWidth !== w || this.renderHeight !== h) {
      this.renderer.setSize(w, h, false);
      this.renderWidth = w;
      this.renderHeight = h;
    }
    if (this.orthographic && !this.camera.isOrthographicCamera)
      this.camera = new THREE.OrthographicCamera(-6, 6, 4, -4, 0.1, 80);
    if (!this.orthographic && !this.camera.isPerspectiveCamera)
      this.camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 80);
    if (this.orthographic) {
      const half = this.distance * 0.31 * Math.max(1, 1.38 / (w / h));
      this.camera.left = (-half * w) / h;
      this.camera.right = (half * w) / h;
      this.camera.top = half;
      this.camera.bottom = -half;
    } else this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    const distance = this.distance * Math.max(1, 1.38 / (w / h));
    this.camera.position.set(
      Math.sin(this.angle) * Math.cos(this.pitch) * distance,
      Math.sin(this.pitch) * distance,
      Math.cos(this.angle) * Math.cos(this.pitch) * distance,
    );
    this.camera.position.add(this.target);
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
    this.overlay?.layout();
  }
}
window.HaloTwin = HaloTwin;
