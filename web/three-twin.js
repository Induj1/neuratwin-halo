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
    var group=new T.Group();
    var shell=material(T,0xa2aea1,0,0,.55,.3), trim=material(T,0xcbd0c4,0,0,.75,.24), dark=material(T,0x323e36,0,0,.5,.34), ceramic=material(T,0xe4e6dc,0,0,.15,.23), copper=material(T,0xab764c,0,0,.75,.23), cyan=material(T,0xc28656,0x392310,.1,.65,.3);
    heatMaterial=material(T,0xc17c4b,0x4b210e,.12,.55,.3);
    function rounded(size,pos,mat,r){var x=size[0]/2,y=size[1]/2;r=Math.min(r||.06,x*.3,y*.3,size[2]*.3);var sh=new T.Shape();sh.moveTo(-x+r,-y);sh.lineTo(x-r,-y);sh.quadraticCurveTo(x,-y,x,-y+r);sh.lineTo(x,y-r);sh.quadraticCurveTo(x,y,x-r,y);sh.lineTo(-x+r,y);sh.quadraticCurveTo(-x,y,-x,y-r);sh.lineTo(-x,-y+r);sh.quadraticCurveTo(-x,-y,-x+r,-y);var geo=new T.ExtrudeGeometry(sh,{depth:size[2],bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:r*.4,bevelThickness:r*.4,curveSegments:5});geo.translate(0,0,-size[2]/2);var m=new T.Mesh(geo,mat);m.position.set(...pos);group.add(m);return m;}
    rounded([2.6,2.15,1.7],[0,1.65,0],shell,.12);rounded([2.85,.16,1.94],[0,2.82,0],trim);rounded([2.82,.15,1.92],[0,.5,0],dark);
    for(var side of [-1,1]){rounded([.32,.18,2.55],[side*.86,.24,0],trim);for(var z of [-.95,.95])rounded([.46,.17,.38],[side*.86,.1,z],dark);for(var i=0;i<10;i++)rounded([.12,1.65,.4],[-1.09+i*.242,1.56,side*1.1],shell,.025);rounded([2.65,.1,.13],[0,2.4,side*1.08],trim);rounded([2.65,.1,.13],[0,.73,side*1.08],trim);}
    for(var x of [-.87,0,.87]){addCylinder(T,group,.2,.12,[x,2.97,.06],trim,24);addCylinder(T,group,.105,.78,[x,3.39,.06],ceramic,28);for(var j=0;j<6;j++)addCylinder(T,group,.18,.065,[x,3.1+j*.12,.06],ceramic,28);addCylinder(T,group,.08,.2,[x,3.87,.06],copper,20);rounded([.2,.07,.11],[x,3.99,.06],trim);}
    var reservoir=addCylinder(T,group,.24,1.75,[0,3.15,-.7],shell,32);reservoir.rotation.z=Math.PI/2;for(var x of [-.59,.59])rounded([.1,.37,.1],[x,2.94,-.7],trim);
    for(var x of [-1.08,1.08])for(var z of [-.72,.72])addCylinder(T,group,.055,.075,[x,2.94,z],trim,12);
    var dial=addCylinder(T,group,.18,.045,[1.335,1.95,.28],dark,32);dial.rotation.z=Math.PI/2;var face=addCylinder(T,group,.14,.052,[1.365,1.95,.28],ceramic,32);face.rotation.z=Math.PI/2;
    rounded([.018,.6,.11],[1.35,1.13,-.35],trim);rounded([.03,.36,.055],[1.37,1.16,-.35],heatMaterial);rounded([.5,.23,.025],[0,2.58,.88],dark);rounded([.34,.025,.035],[0,2.6,.902],cyan);rounded([.22,.02,.035],[0,2.53,.902],trim);
    heatHalo=new T.Mesh(new T.SphereGeometry(.7,24,16),new T.MeshBasicMaterial({color:0x27c7ff,transparent:true,opacity:.025,blending:T.AdditiveBlending,depthWrite:false}));heatHalo.position.set(.8,1.6,0);group.add(heatHalo);sensorPoints=[];
    for(var pos of [[1.39,1.45,-.35],[-1.3,2.65,.67],[1.2,.57,.9]]){var sensor=new T.Mesh(new T.SphereGeometry(.045,12,12),cyan);sensor.position.set(...pos);group.add(sensor);sensorPoints.push(sensor);}
    // A manufacturer plate, lifting eyes and copper ground line give the tank a finished silhouette.
    var plateCanvas=document.createElement('canvas');plateCanvas.width=512;plateCanvas.height=256;var ctx=plateCanvas.getContext('2d');ctx.fillStyle='#e9e9dc';ctx.fillRect(0,0,512,256);ctx.fillStyle='#384237';ctx.font='500 74px Arial';ctx.fillText('halo',35,100);ctx.font='25px monospace';ctx.fillText('NR-104 / NEURATWIN',35,158);ctx.fillRect(35,190,442,2);ctx.font='19px monospace';ctx.fillText('DISTRIBUTION TRANSFORMER',35,226);var plateTex=new T.CanvasTexture(plateCanvas);plateTex.encoding=T.sRGBEncoding;
    var plate=new T.Mesh(new T.PlaneGeometry(.65,.325),new T.MeshStandardMaterial({map:plateTex,metalness:.35,roughness:.5}));plate.rotation.y=Math.PI/2;plate.position.set(1.328,1.45,.28);group.add(plate);
    for(var x of [-1.12,1.12]){var eye=new T.Mesh(new T.TorusGeometry(.12,.035,10,24),trim);eye.position.set(x,2.99,-.5);group.add(eye);}
    var groundCurve=new T.CatmullRomCurve3([new T.Vector3(1.34,.67,-.55),new T.Vector3(1.47,.45,-.6),new T.Vector3(1.43,.15,-.65)]);group.add(new T.Mesh(new T.TubeGeometry(groundCurve,18,.025,8,false),copper));
    group.traverse(function(m){if(m.isMesh){m.castShadow=true;m.receiveShadow=true;}});heatHalo.visible=false;return group;
  }
  function addParticles(T) {
    var positions = [], i;
    for (i = 0; i < 95; i += 1) {
      positions.push((Math.random() - .5) * 9, Math.random() * 4.6, (Math.random() - .5) * 6);
    }
    var geometry = new T.BufferGeometry();
    geometry.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
    var points = new T.Points(geometry, new T.PointsMaterial({ color: 0x67b9d9, size: .025, transparent: true, opacity: .45, depthWrite: false }));
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
      if(document.body.classList.contains("halo-home")) camera.position.set(6.2,4.5,8.7);
      camera.lookAt(0, 1.9, 0);
      if(window.HaloStudio) window.HaloStudio(T,scene,renderer,.02);
      warmLight = new T.PointLight(0xffffff,.15,7);warmLight.position.set(1.4,2.1,1.7);scene.add(warmLight);
      rig = addTransformer(T);
      scene.add(rig);
      orbitA = new T.Mesh(new T.TorusGeometry(2.65, .009, 8, 100), new T.MeshBasicMaterial({ color: 0x70edff, transparent: true, opacity: .18 }));
      orbitA.rotation.x = Math.PI / 2; orbitA.rotation.z = -.28; orbitA.position.y = 1.7; scene.add(orbitA);
      orbitB = new T.Mesh(new T.TorusGeometry(2.1, .008, 8, 100), new T.MeshBasicMaterial({ color: 0x419fce, transparent: true, opacity: .12 }));
      orbitB.rotation.x = Math.PI / 2; orbitB.rotation.z = .42; orbitB.position.y = 1.7; scene.add(orbitB);
      orbitA.visible=false;orbitB.visible=false;
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
      rig.rotation.y += pointer.drag ? 0 : .0015;
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
    if (heatMaterial) heatMaterial.emissiveIntensity = .3 + ratio * .35;
    if (warmLight) warmLight.intensity = .12;
    if (heatHalo && heatHalo.material) heatHalo.material.opacity = .025 + ratio * .055;
  }

  function setMode(mode) {
    api.mode = mode || "thermal";
    if (!api.ready || !window.THREE || !heatMaterial || !warmLight) return;
    if (api.mode === "electrical") {
      heatMaterial.color.setHex(0x58aaff); heatMaterial.emissive.setHex(0x143e9d);
      warmLight.color.setHex(0x44a5ff);
      if (heatHalo && heatHalo.material) heatHalo.material.color.setHex(0x58aaff);
    } else {
      heatMaterial.color.setHex(0x38d8f5); heatMaterial.emissive.setHex(0x0c8dce);
      warmLight.color.setHex(0x36c9ff);
      if (heatHalo && heatHalo.material) heatHalo.material.color.setHex(0x27c7ff);
    }
  }

  window.NeuraTwin3D = api;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
}());