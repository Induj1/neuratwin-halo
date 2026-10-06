(function () {
  var api = {
    ready: false,
    latest: null,
    timer: null,
    attempts: 0,
    mode: "thermal",
    init: init,
    sync: sync,
    setMode: setMode
  };

  var scene, camera, renderer, rig, heatMaterial, warmLight, heatHalo, orbitA, orbitB, sensorPoints;
  var pointer = { x: 0, y: 0, drag: false, lastX: 0, lastY: 0 };
  var prefersReduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

  function material(T, color, emissive, intensity, metalness, roughness, opacity) {
    return new T.MeshStandardMaterial({
      color: color,
      emissive: emissive || 0x000000,
      emissiveIntensity: intensity || 0,
      metalness: metalness == null ? .7 : metalness,
      roughness: roughness == null ? .35 : roughness,
      transparent: opacity != null,
      opacity: opacity == null ? 1 : opacity
    });
  }

  function addBox(T, parent, size, position, mat, bevel) {
    var mesh = new T.Mesh(new T.BoxGeometry(size[0], size[1], size[2]), mat);
    mesh.position.set(position[0], position[1], position[2]);
    if (bevel) mesh.rotation.y = bevel;
    parent.add(mesh);
    return mesh;
  }

  function addCylinder(T, parent, radius, height, position, mat, segments) {
    var mesh = new T.Mesh(new T.CylinderGeometry(radius, radius * 1.08, height, segments || 20), mat);
    mesh.position.set(position[0], position[1], position[2]);
    parent.add(mesh);
    return mesh;
  }

  function addTransformer(T) {
    var group = new T.Group();
    group.position.y = .1;
    var tank = material(T, 0x37312a, 0x17120c, .35, .86, .28);
    var edge = material(T, 0x6c5a43, 0x2c1c0c, .55, .82, .25);
    var radiator = material(T, 0x62594b, 0x21170e, .42, .88, .29);
    var ceramic = material(T, 0x332d26, 0x16100a, .3, .6, .25);
    var copper = material(T, 0xb86b3d, 0x4b1a0a, .75, .88, .2);
    heatMaterial = material(T, 0xff6642, 0xff3a21, 1.5, .55, .2, .88);
    var cyan = material(T, 0xe4b86c, 0x8c4d16, 1.45, .55, .19);

    addBox(T, group, [3.25, 2.22, 1.86], [0, 1.7, 0], tank);
    addBox(T, group, [3.02, .12, 1.72], [0, 2.84, 0], edge);
    addBox(T, group, [3.08, .10, 1.77], [0, .56, 0], edge);
    addBox(T, group, [2.82, .09, .07], [0, 2.18, -.96], cyan);
    addBox(T, group, [2.45, .07, .07], [0, 1.1, -.96], heatMaterial);

    var i, fin;
    for (i = -5; i <= 5; i += 1) {
      fin = addBox(T, group, [.13, 1.9, .22], [i * .29 - 1.48, 1.69, 1.02], radiator);
      fin.rotation.z = (i % 2 ? -.015 : .015);
      addBox(T, group, [.13, 1.9, .22], [i * .29 - 1.48, 1.69, -1.02], radiator);
    }

    addBox(T, group, [.2, 1.85, .2], [1.89, 1.7, .52], radiator);
    addBox(T, group, [.2, 1.85, .2], [1.89, 1.7, 0], radiator);
    addBox(T, group, [.2, 1.85, .2], [1.89, 1.7, -.52], radiator);
    addBox(T, group, [.2, 1.85, .2], [-1.89, 1.7, .52], radiator);
    addBox(T, group, [.2, 1.85, .2], [-1.89, 1.7, 0], radiator);
    addBox(T, group, [.2, 1.85, .2], [-1.89, 1.7, -.52], radiator);

    [-1.05, 0, 1.05].forEach(function (x, index) {
      addCylinder(T, group, .19, .92, [x, 3.4, 0], ceramic, 24);
      addCylinder(T, group, .25, .08, [x, 3.87, 0], copper, 24);
      var cap = addCylinder(T, group, .13, .25, [x, 4.04, 0], edge, 20);
      cap.rotation.z = index === 1 ? .02 : -.02;
    });

    [-.63, .63].forEach(function (x) {
      var coil = new T.Mesh(new T.TorusGeometry(.44, .065, 14, 54), copper);
      coil.position.set(x, 1.73, -1.01);
      coil.rotation.x = Math.PI / 2;
      group.add(coil);
      var coilInner = new T.Mesh(new T.TorusGeometry(.25, .035, 12, 48), heatMaterial);
      coilInner.position.set(x, 1.73, -1.045);
      coilInner.rotation.x = Math.PI / 2;
      group.add(coilInner);
    });

    heatHalo = new T.Mesh(new T.SphereGeometry(1.05, 32, 20), new T.MeshBasicMaterial({ color: 0xff5134, transparent: true, opacity: .06, blending: T.AdditiveBlending, depthWrite: false }));
    heatHalo.position.set(.45, 1.7, -.72);
    group.add(heatHalo);

    sensorPoints = [];
    [[-1.6, .62, -1.07], [1.54, 2.62, -.96], [1.9, 1.18, .68], [-1.85, 2.55, .2]].forEach(function (pos, index) {
      var sensor = new T.Mesh(new T.SphereGeometry(.07, 16, 16), index === 1 ? heatMaterial : cyan);
      sensor.position.set(pos[0], pos[1], pos[2]);
      group.add(sensor);
      sensorPoints.push(sensor);
    });
    return group;
  }

  function addParticles(T) {
    var positions = [], i;
    for (i = 0; i < 95; i += 1) {
      positions.push((Math.random() - .5) * 9, Math.random() * 4.6, (Math.random() - .5) * 6);
    }
    var geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
    var points = new T.Points(geometry, new T.PointsMaterial({ color: 0xcaa56f, size: .025, transparent: true, opacity: .45, depthWrite: false }));
    points.name = "ambient-particles";
    scene.add(points);
    return points;
  }

  function init() {
    var canvas = document.getElementById("twin-3d");
    if (!canvas || api.ready) return;
    if (!window.THREE) {
      api.attempts += 1;
      if (api.attempts < 9 && !api.timer) api.timer = window.setTimeout(function () { api.timer = null; init(); }, 700);
      return;
    }
    var T = window.THREE;
    try {
      renderer = new T.WebGLRenderer({ canvas: canvas, alpha: true, antialias: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setClearColor(0x000000, 0);
      if (T.SRGBColorSpace) renderer.outputColorSpace = T.SRGBColorSpace;
      scene = new T.Scene();
      camera = new T.PerspectiveCamera(33, 1, .1, 100);
      camera.position.set(5.2, 3.6, 7.4);
      camera.lookAt(0, 1.9, 0);
      scene.add(new T.HemisphereLight(0xd8c5a6, 0x090807, 1.35));
      var key = new T.DirectionalLight(0xffd7a0, 2.2); key.position.set(-4, 7, 5); scene.add(key);
      warmLight = new T.PointLight(0xff7140, 2.4, 7); warmLight.position.set(1.4, 2.1, 1.7); scene.add(warmLight);
      rig = addTransformer(T);
      scene.add(rig);
      orbitA = new T.Mesh(new T.TorusGeometry(2.65, .009, 8, 100), new T.MeshBasicMaterial({ color: 0xe4b86c, transparent: true, opacity: .55 }));
      orbitA.rotation.x = Math.PI / 2; orbitA.rotation.z = -.28; orbitA.position.y = 1.7; scene.add(orbitA);
      orbitB = new T.Mesh(new T.TorusGeometry(2.1, .008, 8, 100), new T.MeshBasicMaterial({ color: 0x9a8f70, transparent: true, opacity: .5 }));
      orbitB.rotation.x = Math.PI / 2; orbitB.rotation.z = .42; orbitB.position.y = 1.7; scene.add(orbitB);
      var floor = new T.Mesh(new T.CircleGeometry(4.5, 64), new T.MeshBasicMaterial({ color: 0x0a1d2d, transparent: true, opacity: .62 }));
      floor.rotation.x = -Math.PI / 2; floor.position.y = .04; scene.add(floor);
      addParticles(T);
      bindInput(canvas);
      resize();
      window.addEventListener("resize", resize, { passive: true });
      canvas.closest(".twin-canvas").classList.add("three-ready");
      api.ready = true;
      if (api.latest) sync(api.latest);
      animate();
    } catch (error) {
      canvas.style.display = "none";
    }
  }

  function bindInput(canvas) {
    canvas.addEventListener("pointermove", function (event) {
      var rect = canvas.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width - .5) * 2;
      pointer.y = ((event.clientY - rect.top) / rect.height - .5) * 2;
      if (pointer.drag) {
        rig.rotation.y += (event.clientX - pointer.lastX) * .008;
        rig.rotation.x = clamp(rig.rotation.x + (event.clientY - pointer.lastY) * .004, -.16, .16);
        pointer.lastX = event.clientX; pointer.lastY = event.clientY;
      }
    });
    canvas.addEventListener("pointerdown", function (event) { pointer.drag = true; pointer.lastX = event.clientX; pointer.lastY = event.clientY; canvas.setPointerCapture(event.pointerId); });
    canvas.addEventListener("pointerup", function (event) { pointer.drag = false; if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId); });
    canvas.addEventListener("pointerleave", function () { pointer.drag = false; });
  }

  function resize() {
    if (!renderer || !camera) return;
    var canvas = renderer.domElement, rect = canvas.getBoundingClientRect();
    var width = Math.max(1, rect.width), height = Math.max(1, rect.height);
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  }

  function animate() {
    window.requestAnimationFrame(animate);
    if (!renderer || !scene) return;
    if (!prefersReduced) {
      rig.rotation.y += pointer.drag ? .001 : .0022;
      rig.rotation.x += (pointer.y * -.055 - rig.rotation.x) * .025;
      rig.rotation.y += (pointer.x * .055) * .006;
      orbitA.rotation.z += .0025; orbitB.rotation.z -= .0018;
      if (heatHalo) { var pulse = 1 + Math.sin(Date.now() * .003) * .035; heatHalo.scale.setScalar(pulse); }
      sensorPoints.forEach(function (sensor, index) { sensor.scale.setScalar(1 + Math.sin(Date.now() * .004 + index) * .18); });
    }
    renderer.render(scene, camera);
  }

  function sync(snapshot) {
    api.latest = snapshot;
    if (!api.ready || !snapshot) return;
    var current = snapshot.current || {}, asset = snapshot.asset || {};
    var limit = Number(asset.hotspot_limit_c || 120), hotspot = Number(current.estimated_hotspot_c || 0);
    var ratio = clamp(hotspot / Math.max(1, limit), .55, 1.45);
    if (heatMaterial) heatMaterial.emissiveIntensity = .8 + ratio * 1.15;
    if (warmLight) warmLight.intensity = 1.1 + ratio * 1.8;
    if (heatHalo && heatHalo.material) heatHalo.material.opacity = .025 + ratio * .055;
  }

  function setMode(mode) {
    api.mode = mode || "thermal";
    if (!api.ready || !window.THREE || !heatMaterial || !warmLight) return;
    if (api.mode === "electrical") {
      heatMaterial.color.setHex(0xe5ad54); heatMaterial.emissive.setHex(0x7b4316);
      warmLight.color.setHex(0xd28d3c);
      if (heatHalo && heatHalo.material) heatHalo.material.color.setHex(0xe5ad54);
    } else {
      heatMaterial.color.setHex(0xff6642); heatMaterial.emissive.setHex(0xff3a21);
      warmLight.color.setHex(0xff7140);
      if (heatHalo && heatHalo.material) heatHalo.material.color.setHex(0xff5134);
    }
  }

  window.NeuraTwin3D = api;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
}());
