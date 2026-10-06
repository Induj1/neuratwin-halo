/* Self-contained offline assembly explorer. All geometry is illustrative. */
(() => {
  'use strict';
  const D = window.HARDWARE;
  const $ = id => document.getElementById(id);
  const partById = new Map(D.parts.map(p => [p.id,p]));
  let selected = 'transformer', mode = 'assembly', stepIndex = 0;
  let renderer, scene, camera, root, wireRoot, enclosureLid, shellWalls, loadGuard, transformerGuard, selectionRing;
  const loadSwitches=[], loadBodies=[];
  const branchState=[true,false,false];
  let loadResistance=D.load.resistance;
  let explosion = 0, wantedExplosion = 0, queued = false;
  let cam = {theta:0.28,phi:0.70,zoom:1,target:[-10,50,35]};
  let wantCam = {...cam,target:[...cam.target]};
  const models = new Map(), labels = new Map(), picking = [];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stage = $('stage'), canvas = $('hardware-canvas');
  let stageW = 1000, stageH = 580;
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // Instructions and tables work even if the browser has no WebGL support.
  D.parts.forEach(p => {
    const b = document.createElement('button'); b.className='part-button'; b.dataset.part=p.id;
    b.setAttribute('aria-pressed','false'); b.innerHTML=`<b>${p.n}</b><span>${p.short}<small>${p.category.toLowerCase()}</small></span>`;
    b.addEventListener('click',()=>{selectPart(p.id);document.querySelector('.assembly-workspace').scrollIntoView({behavior:'instant',block:'start'});}); $('part-list').append(b);
    const label=document.createElement('button'); label.className='part-label'; label.dataset.part=p.id;
    label.innerHTML=`<i>${p.n}</i>${p.short}`; label.setAttribute('aria-label',`Select ${p.name}`);
    label.addEventListener('click',()=>selectPart(p.id)); $('part-labels').append(label); labels.set(p.id,label);
  });
  D.steps.forEach((s,i)=>{const b=document.createElement('button'); b.innerHTML=`<b>${String(i+1).padStart(2,'0')}</b>${s.name}`; b.addEventListener('click',()=>setStep(i)); $('step-track').append(b);});

  function selectPart(id) {
    selected=id; const p=partById.get(id);
    $('component-number').textContent=p.n; $('component-category').textContent=p.category;
    $('component-status').textContent=p.status||'PROPOSED';
    $('component-title').textContent=p.name; $('component-purpose').textContent=p.purpose;
    $('component-location').textContent=p.location; $('component-spec').textContent=p.spec;
    $('component-steps').replaceChildren(...p.notes.map(t=>{const li=document.createElement('li');li.textContent=t;return li;}));
    $('component-warning').textContent=p.warning;
    $('source-link').hidden=!p.source; if(p.source){$('source-link').href=p.source;$('source-link').textContent=p.sourceLabel||'Component reference ↗';}
    document.querySelectorAll('.part-button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.part===id)));
    labels.forEach((b,key)=>b.classList.toggle('selected',key===id));
    renderConnections(); refreshWireStyles(); requestRender();
  }
  function renderConnections(){
    const filter=$('wire-filter').value;
    const rows=D.connections.filter(c=>filter==='all'||(filter==='selected'?(c[0]===selected||c[1]===selected):c[2]===filter));
    $('wire-table').innerHTML=rows.map(c=>`<tr${c[2]==='pending'?' class="pending-row"':''}><td><i class="connection-kind" style="--swatch:${D.colors[c[2]]}"></i>${escape(partById.get(c[0]).short)}</td><td>${escape(partById.get(c[1]).short)}</td><td>${c[2]==='pending'?'<b class="pending-label">PENDING</b> ':''}${escape(c[3])}</td><td>${escape(c[4])}</td></tr>`).join('') || '<tr><td colspan="4">This is a mechanical part with no direct electrical connection.</td></tr>';
  }
  function setMode(next){
    mode=next; document.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===next)));
    $('build-panel').hidden=next!=='steps';
    $('show-wires').checked=next!=='assembly';
    updateWiring(); if(next==='steps')setStep(stepIndex); else requestRender();
  }
  function setStep(i){
    stepIndex=Math.max(0,Math.min(D.steps.length-1,i)); const s=D.steps[stepIndex];
    $('step-count').textContent=`${String(stepIndex+1).padStart(2,'0')} / ${String(D.steps.length).padStart(2,'0')}`;
    $('step-title').textContent=s.title; $('step-body').textContent=s.body; $('step-check').textContent=s.check;
    [...$('step-track').children].forEach((b,j)=>{b.setAttribute('aria-current',j===stepIndex?'step':'false');});
    $('prev-step').disabled=stepIndex===0; $('next-step').disabled=stepIndex===D.steps.length-1;
    $('explode').value=s.explode; setExplosion(s.explode); selectPart(s.ids[0]); setCamera(s.camera);
  }
  function setExplosion(value){wantedExplosion=Number(value)/100;$('explode-value').textContent=`${value}%`;requestRender();}
  function updateWiring(){if(wireRoot)wireRoot.visible=$('show-wires').checked;$('wire-legend').hidden=!$('show-wires').checked;requestRender();}
  function setCamera(preset){
    wantCam={theta:preset==='top'?0:preset==='front'?0:0.28,phi:preset==='top'?0.025:preset==='front'?1.36:0.70,zoom:1,target:[-10,50,35]};
    document.querySelectorAll('[data-camera]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.camera===preset))); requestRender();
  }
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
  document.querySelectorAll('[data-camera]').forEach(b=>b.addEventListener('click',()=>setCamera(b.dataset.camera)));
  $('reset-camera').addEventListener('click',()=>setCamera('iso'));
  $('explode').addEventListener('input',e=>setExplosion(e.target.value));
  $('show-wires').addEventListener('change',updateWiring);
  $('show-labels').addEventListener('change',requestRender); $('show-lid').addEventListener('change',requestRender);
  $('wire-filter').addEventListener('change',()=>{renderConnections();refreshWireStyles();requestRender();});
  $('prev-step').addEventListener('click',()=>setStep(stepIndex-1));$('next-step').addEventListener('click',()=>setStep(stepIndex+1));
  $('focus-part').addEventListener('click',()=>{if(!models.has(selected))return;const v=models.get(selected).position;wantCam={theta:.18,phi:.62,zoom:2.2,target:[v.x,v.y+10,v.z]};requestRender();});

  function updateLoadPlanner(){
    const count=branchState.filter(Boolean).length;
    const voltage=D.load.voltage, resistance=loadResistance;
    $('load-current').textContent=`${(count*voltage/resistance).toFixed(2)} A RMS`;
    $('load-power').textContent=`${(count*voltage*voltage/resistance).toFixed(1)} W`;
    $('load-resistance').textContent=count?`${(resistance/count).toFixed(1)} Ω`:'Open circuit';
    document.querySelectorAll('.branch-rating').forEach(el=>el.textContent=`${resistance} Ω · 50 W rated`);
    $('load-stage-note').textContent=`Each ${resistance} Ω branch dissipates ${(voltage**2/resistance).toFixed(2)} W at ${voltage} V RMS.`;
    $('load-total-note').textContent=`Three branches: ${(3*voltage/resistance).toFixed(3)} A / ${(3*voltage**2/resistance).toFixed(2)} W.`;
    $('circuit-branches').innerHTML=branchState.map((on,i)=>{const x=220+i*150;return `<g class="circuit-branch ${on?'on':''}"><path d="M${x} 24V48M${x} 75V91M${x} 132V170"/><path d="M${x} 48L${on?x:x+23} 75"/><circle cx="${x}" cy="48" r="3"/><circle cx="${x}" cy="75" r="3"/><rect x="${x-10}" y="91" width="20" height="41"/><text x="${x+18}" y="66">K${i+1} ${on?'ON':'OFF'}</text><text x="${x+18}" y="117">${resistance} Ω</text></g>`;}).join('');
    loadSwitches.forEach((m,i)=>{m.rotation.x=branchState[i]?-.32:.32;m.material.color.set(branchState[i]?'#c75424':'#536259');});
    loadBodies.forEach((m,i)=>m.material.color.set(branchState[i]?'#b97622':'#96866c'));
    requestRender();
  }
  branchState.forEach((_,i)=>$('branch-'+(i+1)).addEventListener('change',e=>{branchState[i]=e.target.checked;updateLoadPlanner();}));
  $('load-choice').addEventListener('change',e=>{loadResistance=Number(e.target.value);updateLoadPlanner();});
  $('source-mode').addEventListener('change',e=>{
    const assembled=e.target.value==='assembled';
    document.querySelector('.hv-node b').textContent=assembled?'230 V → 12-0-12 V transformer':'Lab trainer · 12 V AC output';
    $('source-note').textContent=assembled?'The lab technician prepares the proposed transformer in a protected enclosure on the existing college AC supply. Confirm the actual winding rating, fuses, disconnect, earthing/isolation and venue permission. This is not a mains wiring schematic.':'Borrow an enclosed 230 V to 12 V AC transformer trainer. Confirm its output rating, protection and venue permission with the lab technician. This diagram is a functional overview, not a mains wiring schematic.';
    selectPart('power');
  });
  $('inspect-load').addEventListener('click',()=>{selectPart('loadbank');document.querySelector('.assembly-workspace').scrollIntoView({behavior:'instant',block:'start'});});
  updateLoadPlanner();

  function material(color, metal=0, rough=.65){return new THREE.MeshStandardMaterial({color,metalness:metal,roughness:rough});}
  function box(parent,w,h,d,x,y,z,color,metal=0){
    const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material(color,metal)); m.position.set(x,y,z); m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;
  }
  function cyl(parent,r,h,x,y,z,color,metal=0){
    const m=new THREE.Mesh(new THREE.CylinderGeometry(r,r,h,32),material(color,metal));m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;
  }
  function line(parent,points,color,width=1){
    const m=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(...p))),new THREE.LineBasicMaterial({color,linewidth:width}));parent.add(m);return m;
  }
  function cable(parent,points,color,r=1.4){
    const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)),false,'catmullrom',.15);
    const m=new THREE.Mesh(new THREE.TubeGeometry(curve,32,r,6,false),material(color)); parent.add(m);return m;
  }
  function surfaceText(parent,text,w,d,x,y,z,bg='#edf0df',fg='#324333',font=26){
    const texCanvas=document.createElement('canvas'); texCanvas.width=512;texCanvas.height=Math.max(80,Math.round(512*d/w));
    const ctx=texCanvas.getContext('2d');ctx.fillStyle=bg;ctx.fillRect(0,0,texCanvas.width,texCanvas.height);ctx.fillStyle=fg;ctx.font=`600 ${font}px Arial`;ctx.textAlign='center';ctx.textBaseline='middle';
    const ls=text.split('\n');ls.forEach((l,i)=>ctx.fillText(l,256,texCanvas.height/2+(i-(ls.length-1)/2)*font*1.4));
    const texture=new THREE.CanvasTexture(texCanvas);texture.encoding=THREE.sRGBEncoding;
    const m=new THREE.Mesh(new THREE.PlaneGeometry(w,d),new THREE.MeshBasicMaterial({map:texture,side:THREE.DoubleSide}));m.rotation.x=-Math.PI/2;m.position.set(x,y,z);parent.add(m);return m;
  }
  function pcb(parent,w,d,color='#25665a'){
    box(parent,w,2,d,0,0,0,color);
    for(const x of [-w/2+3,w/2-3])for(const z of [-d/2+3,d/2-3]){
      cyl(parent,2.3,2.3,x,.4,z,'#c4af6c',.55);cyl(parent,1.25,2.5,x,.55,z,'#354235');
    }
    for(let i=0;i<Math.floor((d-13)/5);i++)for(const x of [-w/2+3,w/2-3]){
      box(parent,3,3,3,x,2.5,-d/2+8+i*5,'#1f2b25');box(parent,1,5,1,x,5,-d/2+8+i*5,'#d2b264',.65);
    }
    for(const x of [-w/2+4,w/2-4])for(const z of [-d/2+4,d/2-4])cyl(parent,2.2,8,x,-5,z,'#b9bcc0',.65);
  }
  function groupFor(p){const g=new THREE.Group();g.position.fromArray(p.pos);g.userData.part=p.id;root.add(g);models.set(p.id,g);return g;}
  function buildGeometry(){
    root=new THREE.Group();scene.add(root);
    box(root,820,10,450,5,-7,40,'#e0dfd1');
    for(const x of [-385,395])for(const z of [-162,245])cyl(root,5,3,x,0,z,'#acafa4',.6);
    surfaceText(root,'USB / CONTROLLER',135,13,-250,.3,118,'#e0dfd1','#3264aa',30);
    surfaceText(root,'ENCLOSED AC / PRIMARY',175,13,72,.3,-105,'#e0dfd1','#a43e34',28);
    surfaceText(root,'3 PARALLEL LOAD BRANCHES',190,13,120,.3,226,'#e0dfd1','#9d522b',26);
    surfaceText(root,'USB POWER + DATA',112,13,315,.3,-32,'#e0dfd1','#3264aa',30);
    // Enclosure floor and intentionally transparent shell.
    const enc=groupFor(partById.get('enclosure')); box(enc,254,7,178,0,0,0,'#ccd3c7');
    box(enc,237,3,161,0,5,0,'#f2f0e3');
    shellWalls=new THREE.Group();enc.add(shellWalls);
    for(const dims of [[254,85,3,0,40,-88],[254,85,3,0,40,88],[3,85,178,-126,40,0],[3,85,178,126,40,0]]){
      const m=box(shellWalls,...dims,'#bcc9b9');m.material.transparent=true;m.material.opacity=.20;m.material.depthWrite=false;m.castShadow=false;
      const edge=new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry),new THREE.LineBasicMaterial({color:'#a5b4a0',transparent:true,opacity:.5}));edge.position.copy(m.position);shellWalls.add(edge);
    }
    for(const x of [-115,115])for(const z of [-78,78])cyl(enc,3,80,x,40,z,'#b5bdb0',.15);
    for(const z of [-35,25,63]){const gland=cyl(enc,7,9,129,20,z,'#424d43');gland.rotation.z=Math.PI/2;}
    enclosureLid=new THREE.Group();enclosureLid.position.set(-195,99,5);root.add(enclosureLid);
    const lm=box(enclosureLid,256,4,180,0,0,0,'#dce4d2');lm.material.transparent=true;lm.material.opacity=.13;lm.material.depthWrite=false;lm.castShadow=false;
    const le=new THREE.LineSegments(new THREE.EdgesGeometry(lm.geometry),new THREE.LineBasicMaterial({color:'#9cac93',transparent:true,opacity:.7}));enclosureLid.add(le);
    // Enclosed AC source requirement, never the rejected inverter board.
    let g=groupFor(partById.get('power'));box(g,125,42,63,0,0,0,'#8b9285');
    surfaceText(g,'COLLEGE AC\nPROTECTED FEED',112,40,0,21.2,0,'#e7e6d9','#943b30',31);
    box(g,42,5,15,0,23,21,'#465149');surfaceText(g,'COVERED INLET',38,9,0,26,21,'#465149','#f4edda',35);
    box(g,32,10,17,87,-10,0,'#b04727');box(g,22,3,10,87,-3,0,'#e3ccae');
    cyl(g,8,10,86,-9,30,'#394e43');cyl(g,7,6,86,-1,30,'#bd4c2c');
    surfaceText(g,'FUSE / OFF',49,8,88,-20,50,'#e0dfd1','#854126',36);
    // ESP32 and recognizable RF shield/USB connectors.
    g=groupFor(partById.get('mcu'));pcb(g,31,67,'#253c37');box(g,19,4,24,0,4,-12,'#bec6c1',.7);surfaceText(g,'ESP32\nS3',16,21,0,6.2,-12,'#cad0cb','#48554e',58);
    box(g,20,2,11,0,3,-29,'#222e28');for(let i=0;i<4;i++)line(g,[[-8,4.1,-33+i*2],[8,4.1,-33+i*2]],'#c4a867');
    box(g,8,5,6,-6,4,34,'#acb7b1',.8);box(g,8,5,6,6,4,34,'#acb7b1',.8);box(g,6,2,5,-5,3,19,'#555e53');box(g,5,2,5,5,3,19,'#555e53');
    ['rtd1','rtd2'].forEach((id,i)=>{const r=groupFor(partById.get(id));pcb(r,43,34,'#74509a');box(r,11,3,11,0,3,-2,'#232b28');box(r,34,8,10,0,5,17,'#2b956f');for(let n=0;n<4;n++)cyl(r,2,1,-12+n*8,9.5,17,'#c9cdba',.7);surfaceText(r,`RTD ${i?'B':'A'}`,24,6,0,1.3,-12,'#74509a','#f8f1f7',54);});
    // Laminated core / insulated winding illustration, enclosed terminal zones.
    g=groupFor(partById.get('transformer'));box(g,98,5,76,0,-12,0,'#87918a',.65);
    for(let i=0;i<13;i++)box(g,78,53,3,0,15,-23+i*4,'#6c7772',.65);
    box(g,44,48,59,0,16,0,'#ab7336',.2);
    for(let i=0;i<12;i++)box(g,46,2.3,60,0,-4+i*3.6,0,'#d0a45e',.5);
    box(g,52,4,64,0,43,0,'#594f3e');surfaceText(g,'230 V / 12-0-12 V',49,14,0,45.2,0,'#efe0b9','#5b4a31',36);
    for(const x of [-40,40]){box(g,8,8,66,x,-5,0,'#a9ada1',.6);for(const z of [-30,30])cyl(g,2.5,3,x,0,z,'#c7c9bb',.7);}
    for(const x of [-64,64]){box(g,19,18,48,x,0,0,x<0?'#b5614a':'#b79a56');surfaceText(g,x<0?'PRIMARY\nGUARDED':'SECONDARY\n12 V',18,37,x,10,0,'#eee2c7','#604937',52);}
    transformerGuard=new THREE.Group();g.add(transformerGuard);
    const hvGuard=box(transformerGuard,156,78,96,0,23,0,'#dda661');hvGuard.material.transparent=true;hvGuard.material.opacity=.10;hvGuard.material.depthWrite=false;hvGuard.castShadow=false;
    const hvEdge=new THREE.LineSegments(new THREE.EdgesGeometry(hvGuard.geometry),new THREE.LineBasicMaterial({color:'#b17439',transparent:true,opacity:.65}));hvEdge.position.copy(hvGuard.position);transformerGuard.add(hvEdge);
    // Dedicated load-bank heatsink, three parallel resistor branches and switches.
    g=groupFor(partById.get('loadbank'));box(g,162,7,85,0,0,0,'#8b9690',.65);
    for(let i=0;i<16;i++)box(g,3,15,85,-75+i*10,-11,0,'#82918a',.65);
    [-50,0,50].forEach((x,i)=>{const body=box(g,29,14,52,x,10,0,'#b97622',.55);loadBodies.push(body);for(const z of [-31,31]){box(g,12,2,12,x,4,z,'#aa8345',.6);cyl(g,2,2,x,6,z,'#d7d8c7',.7);box(g,3,3,7,x,10,z,'#c5b487',.7);}for(let n=0;n<5;n++)box(g,2,2,44,x-10+n*5,18,0,'#d1a358',.5);surfaceText(g,`R${i+1} / LOAD`,25,8,x,19.5,0,'#c5974f','#4c3c23',43);});
    // Physical switching lives in the separate relay bank, not on manual rockers.
    loadGuard=new THREE.Group();loadGuard.position.y=50;g.add(loadGuard);
    for(const x of [-84,84])box(loadGuard,2,62,91,x,-22,0,'#758a76',.25);
    for(let i=0;i<12;i++)box(loadGuard,165,2,2,0,10,-44+i*8,'#7d927d',.4);
    // Sensor footprints are placeholders until exact V/I modules are selected.
    for(const id of ['senseout']){const sensor=groupFor(partById.get(id));box(sensor,52,3,36,0,0,0,'#b0b5a8');box(sensor,30,7,18,0,5,0,'#879184');surfaceText(sensor,'AC V / I\nREVIEW',43,27,0,9,0,'#e7e8dc','#5f6e60',46);}
    g=groupFor(partById.get('relays'));
    [-32,0,32].forEach((x,i)=>{box(g,27,2,47,x,0,0,'#376c67');box(g,22,17,22,x,10,0,'#326eaa');box(g,23,10,10,x,6,22,'#518079');const led=cyl(g,2,3,x,3,-16,'#b6743c');loadSwitches.push(led);surfaceText(g,`K${i+1}`,17,10,x,19,0,'#326eaa','#eff4dc',50);});
    g=groupFor(partById.get('conditioning'));pcb(g,45,30,'#676b8c');box(g,28,6,17,0,5,0,'#4e566f');surfaceText(g,'ADC / DRIVER\nPENDING',37,23,0,9,0,'#ede9df','#585773',40);
    g=groupFor(partById.get('aux'));box(g,65,28,41,0,6,0,'#536575');surfaceText(g,'REGULATED DC\n5 V MODULE SUPPLY',59,32,0,20.2,0,'#e8eadf','#435b6a',32);box(g,14,8,12,37,5,0,'#324c54');
    // Probes and brackets.
    g=groupFor(partById.get('probe'));let pr=cyl(g,3,52,0,0,0,'#d0d6d0',.9);pr.rotation.z=Math.PI/2;box(g,9,12,11,0,-2,0,'#b66135',.5);
    g=groupFor(partById.get('ambient'));pr=cyl(g,3,38,0,0,0,'#c8d3c8',.85);pr.rotation.z=Math.PI/2;box(g,8,8,10,-14,-5,0,'#d8d4bc');surfaceText(g,'ROOM AIR',48,9,0,-15,18,'#e0dfd1','#52664f',36);
    // Laptop prop / no fake live readings.
    g=groupFor(partById.get('laptop'));box(g,105,4,72,0,-24,12,'#81958e',.6);surfaceText(g,'USB POWER + DATA',83,21,0,-21.8,24,'#8e9c91','#30443a',35);
    const screen=new THREE.Group();screen.position.set(0,8,-20);screen.rotation.x=-.16;g.add(screen);box(screen,105,68,4,0,0,0,'#2d4840');
    const sc=surfaceText(screen,'NEURATWIN\nBENCH-001\nADAPTER PLANNED',95,57,0,0,2.3,'#eceddc','#375449',34);sc.rotation.x=0;
    D.parts.forEach(p=>{const group=models.get(p.id);group.traverse(o=>{o.userData.part=p.id;if(o.isMesh)picking.push(o);});});
    wireRoot=new THREE.Group();root.add(wireRoot);buildWires();wireRoot.visible=false;
    selectionRing=new THREE.Mesh(new THREE.RingGeometry(25,27,64),new THREE.MeshBasicMaterial({color:'#c35f2f',side:THREE.DoubleSide,transparent:true,opacity:.8,depthWrite:false}));selectionRing.rotation.x=-Math.PI/2;root.add(selectionRing);
    updateLoadPlanner();
  }
  function anchor(id){return models.get(id).position.clone().add(new THREE.Vector3(0,8,0));}
  function buildWires(){
    while(wireRoot.children.length){const c=wireRoot.children[0];c.geometry.dispose();c.material.dispose();wireRoot.remove(c);}
    const drawn=new Set();
    D.connections.forEach((c,i)=>{
      const key=`${c[0]}-${c[1]}-${c[2]}`;if(drawn.has(key))return;drawn.add(key);
      const a=anchor(c[0]),b=anchor(c[1]); const offset=(i%4)*4;
      let mid=[(a.x+b.x)/2,Math.max(a.y,b.y)+13+offset,(a.z+b.z)/2+15];
      const points=[[a.x,a.y,a.z],[a.x,a.y+12,a.z+8],mid,[b.x,b.y+12,b.z+8],[b.x,b.y,b.z]];
      let w;
      if(c[2]==='pending'||c[2]==='ac'){
        const curve=new THREE.CatmullRomCurve3(points.map(p=>new THREE.Vector3(...p)));
        w=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(50)),new THREE.LineDashedMaterial({color:D.colors[c[2]],dashSize:6,gapSize:5}));w.computeLineDistances();wireRoot.add(w);
      }else w=cable(wireRoot,points,D.colors[c[2]],c[2]==='power'||c[2]==='usb'?1.7:1.15);
      w.userData={from:c[0],to:c[1],kind:c[2]};
    });refreshWireStyles();
  }
  function refreshWireStyles(){
    if(!wireRoot)return;const filter=$('wire-filter').value;
    wireRoot.children.forEach(w=>{const relates=w.userData.from===selected||w.userData.to===selected;const match=filter==='all'||(filter==='selected'?relates:w.userData.kind===filter);w.visible=match;w.material.transparent=true;w.material.opacity=relates?.98:.42;});
  }
  function applyPositions(){
    D.parts.forEach(p=>{const m=models.get(p.id);m.position.set(p.pos[0]+p.lift[0]*explosion,p.pos[1]+p.lift[1]*explosion,p.pos[2]+p.lift[2]*explosion);});
    enclosureLid.position.y=99+145*explosion;
    loadGuard.position.y=50+65*explosion;
    transformerGuard.position.y=80*explosion;
    buildWires();
  }
  function updateLabels(){
    const occupied=[];
    const priority=[selected,'transformer','relays','loadbank','mcu','power','laptop'];
    const ordered=[...new Set([...priority,...D.parts.map(p=>p.id)])].map(id=>partById.get(id));
    const heights={enclosure:100,transformer:78,loadbank:66,mcu:16,rtd1:16,rtd2:16,probe:16,ambient:20,laptop:50,power:35,senseout:20,relays:25,conditioning:22,aux:24};
    ordered.forEach(p=>{
      const e=labels.get(p.id);if(!$('show-labels').checked){e.hidden=true;return;}
      const v=models.get(p.id).position.clone();v.y+=heights[p.id];v.project(camera);
      const x=(v.x*.5+.5)*stageW,y=(-v.y*.5+.5)*stageH-12;
      const w=e.offsetWidth||115,h=27;const rect={left:x-w/2-4,right:x+w/2+4,top:y-h-5,bottom:y+12};
      const overlap=occupied.some(r=>rect.left<r.right&&rect.right>r.left&&rect.top<r.bottom&&rect.bottom>r.top);
      const inside=rect.left>4&&rect.right<stageW-4&&rect.top>55&&rect.bottom<stageH-50&&v.z>-1&&v.z<1;
      e.hidden=!inside||(overlap&&p.id!==selected);if(!e.hidden){occupied.push(rect);e.style.left=`${x}px`;e.style.top=`${y}px`;}
    });
  }
  function updateCamera(){
    const aspect=stageW/stageH;const height=Math.max(555+85*explosion,1010/aspect)/cam.zoom;
    camera.left=-height*aspect/2;camera.right=height*aspect/2;camera.top=height/2;camera.bottom=-height/2;camera.updateProjectionMatrix();
    const t=new THREE.Vector3(...cam.target); if(cam.zoom<1.1)t.y+=30*explosion; const r=1150;
    camera.position.set(t.x+r*Math.sin(cam.phi)*Math.sin(cam.theta),t.y+r*Math.cos(cam.phi),t.z+r*Math.sin(cam.phi)*Math.cos(cam.theta));camera.lookAt(t);camera.updateMatrixWorld();
  }
  function requestRender(){if(!renderer||queued)return;queued=true;requestAnimationFrame(renderFrame);}
  function renderFrame(){
    queued=false;if(!renderer)return;
    let unsettled=false;const k=reducedMotion?1:.25;
    if(Math.abs(explosion-wantedExplosion)>.002){explosion+= (wantedExplosion-explosion)*k;unsettled=true;applyPositions();}
    else if(explosion!==wantedExplosion){explosion=wantedExplosion;applyPositions();}
    for(const key of ['theta','phi','zoom']){if(Math.abs(cam[key]-wantCam[key])>.0005){cam[key]+=(wantCam[key]-cam[key])*k;unsettled=true;}else cam[key]=wantCam[key];}
    for(let i=0;i<3;i++){if(Math.abs(cam.target[i]-wantCam.target[i])>.03){cam.target[i]+=(wantCam.target[i]-cam.target[i])*k;unsettled=true;}else cam.target[i]=wantCam.target[i];}
    updateCamera();
    const showLid=$('show-lid').checked;enclosureLid.visible=showLid;
    shellWalls.visible=showLid; loadGuard.visible=showLid;transformerGuard.visible=showLid;
    // Inspect the low-voltage controller boards with the enclosure guard hidden.
    const p=models.get(selected).position;selectionRing.position.set(p.x,p.y+1,p.z);
    selectionRing.scale.setScalar(selected==='enclosure'?4.7:selected==='loadbank'?2.9:selected==='power'?2.2:1);
    renderer.render(scene,camera);updateLabels();if(unsettled)requestRender();
  }
  function initScene(){
    if(!window.THREE)throw new Error('Local Three.js library was not loaded.');
    renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,preserveDrawingBuffer:true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));renderer.outputEncoding=THREE.sRGBEncoding;
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.setClearColor('#e8ece2');
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.85;
    scene=new THREE.Scene();camera=new THREE.OrthographicCamera(-600,600,400,-400,1,4000);
    scene.add(new THREE.HemisphereLight('#fffdeb','#bacab2',.8));
    const sun=new THREE.DirectionalLight('#fff7e4',1.1);sun.position.set(-260,800,380);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-650;sun.shadow.camera.right=650;sun.shadow.camera.top=550;sun.shadow.camera.bottom=-550;sun.shadow.camera.far=1700;sun.shadow.bias=-.0004;sun.shadow.normalBias=1.5;scene.add(sun);
    const fill=new THREE.DirectionalLight('#d3e4f2',.35);fill.position.set(400,200,-200);scene.add(fill);
    const ground=new THREE.Mesh(new THREE.PlaneGeometry(6000,6000),material('#e8ece2'));ground.rotation.x=-Math.PI/2;ground.position.y=-15;ground.receiveShadow=true;scene.add(ground);
    const grid=new THREE.GridHelper(1800,45,'#c3cbbb','#d5dbcc');grid.position.y=-14.8;grid.material.transparent=true;grid.material.opacity=.45;scene.add(grid);
    buildGeometry();
    new ResizeObserver(()=>{const r=stage.getBoundingClientRect();stageW=r.width;stageH=r.height;renderer.setSize(stageW,stageH,false);requestRender();}).observe(stage);
    const raycaster=new THREE.Raycaster();const pointer=new THREE.Vector2();let down=null;
    canvas.addEventListener('pointerdown',e=>{if(down)return;canvas.setPointerCapture(e.pointerId);down={id:e.pointerId,x:e.clientX,y:e.clientY,sx:e.clientX,sy:e.clientY,theta:wantCam.theta,phi:wantCam.phi};});
    canvas.addEventListener('pointermove',e=>{if(!down||e.pointerId!==down.id)return;wantCam.theta=down.theta-(e.clientX-down.x)*.007;wantCam.phi=Math.max(.03,Math.min(1.5,down.phi-(e.clientY-down.y)*.005));requestRender();});
    canvas.addEventListener('pointerup',e=>{if(!down||e.pointerId!==down.id)return;const isClick=Math.hypot(e.clientX-down.sx,e.clientY-down.sy)<5;down=null;if(isClick){const r=canvas.getBoundingClientRect();pointer.set(((e.clientX-r.left)/r.width)*2-1,-((e.clientY-r.top)/r.height)*2+1);raycaster.setFromCamera(pointer,camera);const hits=raycaster.intersectObjects(picking).filter(h=>{let o=h.object;while(o){if(!o.visible)return false;o=o.parent;}return true;});if(hits.length)selectPart(hits[0].object.userData.part);}});
    canvas.addEventListener('pointercancel',()=>{down=null;});
    canvas.addEventListener('wheel',e=>{e.preventDefault();wantCam.zoom=Math.max(.65,Math.min(3.4,wantCam.zoom*Math.exp(-e.deltaY*.001)));requestRender();},{passive:false});
    canvas.addEventListener('keydown',e=>{let used=true;if(e.key==='ArrowLeft')wantCam.theta-=.15;else if(e.key==='ArrowRight')wantCam.theta+=.15;else if(e.key==='ArrowUp')wantCam.phi=Math.max(.03,wantCam.phi-.12);else if(e.key==='ArrowDown')wantCam.phi=Math.min(1.5,wantCam.phi+.12);else if(e.key==='+'||e.key==='=')wantCam.zoom=Math.min(3.4,wantCam.zoom*1.1);else if(e.key==='-')wantCam.zoom=Math.max(.65,wantCam.zoom/1.1);else if(e.key==='0')setCamera('iso');else used=false;if(used){e.preventDefault();requestRender();}});
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();$('stage-error').hidden=false;});
    requestRender();
  }
  function annotatedSnapshot(){
    if(!renderer)return null;renderer.render(scene,camera);
    const out=document.createElement('canvas');out.width=canvas.width;out.height=canvas.height+100;const ctx=out.getContext('2d');
    ctx.fillStyle='#f4f1e9';ctx.fillRect(0,0,out.width,out.height);ctx.drawImage(canvas,0,65);
    ctx.fillStyle='#202a28';ctx.font='bold 23px Arial';ctx.fillText('NEURATWIN / HARDWARE ASSEMBLY ATLAS',24,36);
    const ratio=canvas.width/stageW;labels.forEach((e,id)=>{if(e.hidden)return;const x=parseFloat(e.style.left)*ratio,y=parseFloat(e.style.top)*ratio+65;const p=partById.get(id);ctx.font=`${Math.max(14,11*ratio)}px Arial`;const text=`${p.n}  ${p.short}`;const w=ctx.measureText(text).width+16;ctx.fillStyle=id===selected?'#f6e5d7':'#fffef6';ctx.fillRect(x-w/2,y-22*ratio,w,20*ratio);ctx.fillStyle='#263a2d';ctx.fillText(text,x-w/2+8,y-8*ratio);});
    ctx.fillStyle='#616961';ctx.font='14px Arial';ctx.fillText('Rev 1.5 • Core demo • Secondary V / I • Surface + room temperature • USB ESP32',24,out.height-12);return out.toDataURL('image/png');
  }
  $('snapshot').addEventListener('click',()=>{const url=annotatedSnapshot();if(!url)return;$('snapshot-image').src=url;$('snapshot-download').href=url;$('snapshot-dialog').showModal();});
  $('close-snapshot').addEventListener('click',()=>$('snapshot-dialog').close());
  function makePrintSheets(){
    const image=annotatedSnapshot();
    $('print-sheets').innerHTML=`<article class="print-page"><div class="print-label">NEURATWIN / ASSEMBLY ATLAS / REV 1.5</div><h1>AC transformer bench</h1><p><b>SELECTED PLAN:</b> Use the existing college AC supply through an enclosed, protected transformer. Borrow a lab trainer first or have the lab technician prepare the proposed transformer assembly. No inverter, battery or primary hobby-sensor modules are needed. Physical verification is still required.</p><p>Laptop USB powers the ESP32. The protected college AC connection powers the enclosed transformer; use one verified nominal 12 V AC section. Three secondary-side relays switch parallel resistors across one nominal 12 V section.</p><p><b>Source option shown:</b> ${escape($('source-mode').selectedOptions[0].textContent)}. This viewer does not electrically verify either physical assembly. Keep the mains section inaccessible.</p>${image?`<img src="${image}" alt="Current labelled assembly view">`:''}<p><b>Core demonstration:</b> change the secondary load, observe measured voltage/current and temperatures, then explain the dashboard alert or recommended action. Room temperature is retained because the problem statement includes ambient conditions; surface minus ambient is the temperature rise.</p><h2>Proposed build sequence</h2><ol>${D.steps.map(s=>`<li><b>${s.title.slice(4)}</b> ${s.check}</li>`).join('')}</ol></article>`;
    $('print-sheets').innerHTML+=`<article class="print-page"><div class="print-label">LOAD PLANNER / NOMINAL 12 V AC RMS</div><h2>Three repeatable load steps</h2><p>Illustrated choice: ${loadResistance} Ω per branch, 50 W chassis rating subject to correct mounting. Each branch has a series relay contact and resistor, returning to the other terminal of the same secondary section. All branches are parallel.</p><table><thead><tr><th>Branches on</th><th>Current RMS</th><th>Resistive load power</th></tr></thead><tbody>${[1,2,3].map(n=>`<tr><td>${n}</td><td>${(n*D.load.voltage/loadResistance).toFixed(3)} A</td><td>${(n*D.load.voltage**2/loadResistance).toFixed(2)} W</td></tr>`).join('')}</tbody></table><p>Calculated at exactly 12 V RMS, not measurements. Check actual secondary voltage, winding current/VA rating, resistor mounting, fuses and thermal cutoff. A 50 W resistor does not automatically consume 50 W.</p><p>Separate regulated DC powers compatible relay / sensor modules. Never feed 12 V AC into the ESP32, relay power inputs or an ordinary DC buck. Keep USB as the ESP32 power source.</p><h2>Open engineering decisions</h2><p>Protected transformer assembly; ZMPT101B accuracy at 12 V AC; two secondary analog channels and conditioning; relay driver compatibility/pins; auxiliary power and grounding/isolation; fuse/wire/cutoff ratings; live firmware and adapter.</p><p>Voltage sensing is across the measured circuit; current sensing is in series. No raw mains divider connects to the MCU. Compute RMS from waveforms; real power needs valid time-aligned voltage/current processing.</p><p>PT100 A measures transformer exterior; PT100 B measures ambient. Surface temperature does not directly establish winding hot-spot, oil temperature or remaining life. Primary sensing is deferred. Do not report measured transformer efficiency or input losses from secondary measurements alone.</p></article>`;
    for(let i=0;i<D.parts.length;i+=3){$('print-sheets').innerHTML+=`<article class="print-page"><div class="print-label">NEURATWIN / PARTS ${D.parts[i].n}–${D.parts[Math.min(i+2,D.parts.length-1)].n}</div>${D.parts.slice(i,i+3).map(p=>`<h2>${p.n} / ${escape(p.name)}</h2><p><b>Location:</b> ${escape(p.location)}<br><b>Select:</b> ${escape(p.spec)}</p><ol>${p.notes.map(n=>`<li>${escape(n)}</li>`).join('')}</ol><p><b>Check:</b> ${escape(p.warning)}</p>`).join('')}</article>`;}
    for(let i=0;i<D.connections.length;i+=7){$('print-sheets').innerHTML+=`<article class="print-page"><div class="print-label">NEURATWIN / CONNECTION REVIEW / REV 1.5</div><h2>Connection concepts & retained GPIOs</h2><p>GPIO signal names, not header numbers. Primary AC is conceptual only; PENDING interfaces are not ready to wire. Confirm the technician-reviewed schematic first.</p><table><thead><tr><th>From / to</th><th>Connection</th><th>Assembly check</th></tr></thead><tbody>${D.connections.slice(i,i+7).map(c=>`<tr><td>${partById.get(c[0]).short} → ${partById.get(c[1]).short}</td><td>${c[2]==='pending'?'PENDING: ':''}${escape(c[3])}</td><td>${escape(c[4])}</td></tr>`).join('')}</tbody></table></article>`;}
  }
  $('print-guide').addEventListener('click',()=>{makePrintSheets();window.print();});
  // Text has no dependency on the 3D renderer.
  selectPart('transformer');
  try{initScene();}catch(error){$('stage-error').hidden=false;$('snapshot').disabled=true;$('part-labels').hidden=true;console.error('Hardware guide:',error);}
})();
