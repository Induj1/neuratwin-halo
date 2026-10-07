/* Local procedural geometry. Illustrative assembly, never a wiring reference. */
class HaloTwin {
 constructor(canvas, onSelect=()=>{}) {
  this.canvas=canvas; this.onSelect=onSelect; this.parts=[]; this.angle=.48; this.pitch=.7; this.distance=11.5;
  try {
   const T=window.THREE; if(!T) throw Error('Three unavailable');
   this.renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:true});
   this.renderer.setPixelRatio(Math.min(devicePixelRatio,2)); this.renderer.outputEncoding=T.sRGBEncoding;this.renderer.toneMapping=T.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1;
   this.scene=new T.Scene(); this.camera=new T.PerspectiveCamera(38,1,.1,80);
   if(window.HaloStudio)window.HaloStudio(T,this.scene,this.renderer,-.38);
   this.root=new T.Group();this.scene.add(this.root); this.build(false);
   this.resize=new ResizeObserver(()=>this.draw());this.resize.observe(canvas);
   let drag=null;
   canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,moved:0};canvas.setPointerCapture(e.pointerId);});
   canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.moved+=Math.abs(dx)+Math.abs(dy);this.angle-=dx*.009;this.pitch=Math.max(.12,Math.min(1.3,this.pitch+dy*.005));drag.x=e.clientX;drag.y=e.clientY;this.draw();});
   canvas.addEventListener('pointerup',e=>{if(drag?.moved<5)this.pick(e);drag=null;});
   canvas.addEventListener('wheel',e=>{e.preventDefault();this.distance=Math.max(6,Math.min(18,this.distance+e.deltaY*.005));this.draw();},{passive:false});
   canvas.style.touchAction='none';this.draw();
  } catch(e) { this.failed=true;const fallback=canvas.parentElement.querySelector('.model-fallback');if(fallback)fallback.hidden=false; }
 }
 box(x,y,z,w,h,d,color,part,metal=.15) {
  const T=THREE,r=Math.min(.045,w*.12,h*.12,d*.12),s=new T.Shape(),a=w/2-r,b=h/2-r;s.moveTo(-a,-b);s.lineTo(a,-b);s.lineTo(a,b);s.lineTo(-a,b);s.closePath();const geo=new T.ExtrudeGeometry(s,{depth:d-2*r,bevelEnabled:true,bevelSize:r,bevelThickness:r,bevelSegments:2,steps:1});geo.translate(0,0,-d/2+r);const mesh=new T.Mesh(geo,new T.MeshStandardMaterial({color,roughness:.36,metalness:metal}));mesh.castShadow=true;mesh.receiveShadow=true;mesh.position.set(x,y,z);mesh.userData.part=part;this.root.add(mesh);if(part)this.parts.push(mesh);return mesh;
 }
 cylinder(x,y,z,r,h,color,part,rotation=0) {
  const T=THREE,m=new T.Mesh(new T.CylinderGeometry(r,r,h,28),new T.MeshStandardMaterial({color,roughness:.42,metalness:.2}));m.castShadow=true;m.receiveShadow=true;m.position.set(x,y,z);m.rotation.z=rotation;m.userData.part=part;this.root.add(m);if(part)this.parts.push(m);return m;
 }
 wire(points,color) {const T=THREE,curve=new T.CatmullRomCurve3(points.map(p=>new T.Vector3(...p)));this.root.add(new T.Mesh(new T.TubeGeometry(curve,24,.026,7,false),new T.MeshStandardMaterial({color})));}
 label(text,x,y,z,part){const c=document.createElement('canvas');c.width=384;c.height=96;const ctx=c.getContext('2d');ctx.fillStyle='#e6e9dc';ctx.fillRect(0,0,384,96);ctx.strokeStyle='#bac3ab';ctx.lineWidth=3;ctx.strokeRect(2,2,380,92);ctx.font='500 35px monospace';ctx.fillStyle='#46523b';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,192,48);const texture=new THREE.CanvasTexture(c);texture.encoding=THREE.sRGBEncoding;const m=new THREE.Mesh(new THREE.PlaneGeometry(1,.25),new THREE.MeshStandardMaterial({map:texture,side:THREE.DoubleSide,roughness:.8,metalness:.05}));m.rotation.x=-Math.PI/2;m.position.set(x,y,z);m.userData.part=part;this.root.add(m);if(part)this.parts.push(m);}
 details(distribution){
 for(const x of [-3.22,3.22])for(const z of [-2.02,2.02])this.cylinder(x,.02,z,.08,.09,0xbfc4b5);
 this.box(0,-.27,0,7.2,.07,4.8,0xa6af98,undefined,.55);
 if(!distribution){for(const x of [-2.28,-.33])for(const z of [-.67,.67])this.cylinder(x,1.66,z,.04,.13,0x89a2ae,'transformer');for(const x of [-1.82,-.78]){this.cylinder(x,1.6,0,.06,.2,0xd6ae73,'transformer');this.box(x,.08,0,.65,.06,1.5,0x616c5e,'transformer');}for(let i=0;i<4;i++){const x=.62+i*.53;this.box(x,.58,-1,.31,.025,.36,0x364536,'relay');this.box(x,.59,-1,.18,.02,.05,0xadbd95,'relay');for(const z of [-1.32,-.69])this.cylinder(x,.27,z,.045,.06,0xb6a57d,'relay');}this.box(.85,.3,1.5,.23,.15,.19,0xb9c5c7,'controller',.7);this.wire([[-2.5,.94,.3],[-2.65,.75,.4],[-2.7,.13,.75],[-1.9,.12,1.5]],0x8d9c7d);this.label('TRANSFORMER',-1.3,.015,1.25,'transformer');this.label('LOAD BANK',1.35,.015,.93,'relay');this.label('ESP32',1.35,.015,2.02,'controller');this.label('CURRENT',-.2,.015,-2.03,'current');}
 else{for(const x of [-1.18,.38])this.box(x,.05,0,.22,.18,2.05,0x616c5e,'transformer');this.label('TRANSFORMER',-.4,.015,1.74,'transformer');this.label('CONTROLLER',2,.015,1.4,'controller');}}
 build(distribution) {
  this.distribution=distribution;while(this.root.children.length){const m=this.root.children[0];m.geometry?.dispose();m.material?.map?.dispose();m.material?.dispose();this.root.remove(m);}this.parts=[];this.cutawayParts=[];
  this.box(0,-.13,0,7,.24,4.6,0xc5cbb8);
  if(distribution){
   this.body=this.box(-.4,1.1,0,2.2,2.2,1.65,0x647b80,'transformer',.5);
   for(let i=0;i<12;i++){this.box(-1.55+i*.22,1.05,1, .08,1.8,.35,0x83968f,'transformer',.45);}
   this.cover=this.box(-.4,2.27,0,2.4,.16,1.85,0x324c50,'transformer',.4);
   for(let x=-1.1;x<.8;x+=.7){this.cylinder(x,2.7,0,.13,.75,0xae7451,'transformer');for(let y=2.4;y<3;y+=.14)this.cylinder(x,y,0,.21,.07,0xc4946c,'transformer');}
   this.cylinder(.8,2.3,0,.23,.9,0xb85b2f,'surface');this.box(2,.6,0,1.4,1.2,1.5,0xe6dfc8,'controller');
  } else {
   for(let i=0;i<20;i++){const plate=this.box(-1.3,.75,-.76+i*.08,2.2,1.4,.055, i%2?0x536565:0x798985,'transformer',.65);if(i>8)this.cutawayParts.push(plate);}
   for(let x of [-1.82,-.78]){this.cylinder(x,.85,0,.42,1.35,0xab5c31,'transformer');for(let y=.25;y<1.48;y+=.07)this.cylinder(x,y,0,.44,.035,0xc5824e,'transformer');}
   this.cover=this.box(-1.3,1.55,0,2.38,.13,1.8,0xb3a56b,'transformer',.7);this.body=this.cover;
   this.box(-1.3,.06,0,2.5,.14,1.95,0xb3a56b,'transformer',.7);
   this.box(-2.51,.9,.3,.12,.46,.3,0xe7e0ce,'surface');
   this.box(1.42,.16,-1,2.25,.12,.8,0x657a60,'relay');
   for(let i=0;i<4;i++){const x=.62+i*.53;this.box(x,.39,-1,.43,.36,.53,0x819874,'relay');this.cylinder(x,.42,.57,.14,.7,i===3?0xada492:0x74906d,'relay',Math.PI/2);this.wire([[x,.3,-.65],[x,.12,-.2],[x-.28,.16,.57]],0x9e694a);}
   this.box(1.4,.18,1.48,1.4,.13,.62,0x40543f,'controller');this.box(1.35,.3,1.48,.65,.14,.49,0xa4afad,'controller',.8);
   for(let x=.8;x<2.1;x+=.13){this.box(x,.22,1.1,.04,.17,.1,0xbeab77,'controller');this.box(x,.22,1.85,.04,.17,.1,0xbeab77,'controller');}
   this.box(-.22,.23,-1.57,.66,.12,.5,0x788f69,'current');this.box(-.24,.36,-1.57,.3,.15,.25,0x93b4a2,'current');
   for(const z of [-1.4,1.4]){this.box(-2.9,.2,z,.45,.1,.85,0x708766,'voltage');this.box(-2.9,.39,z,.35,.3,.4,0x93a788,'voltage');}
   this.wire([[-1.8,1.58,0],[-1.8,1.95,-.5],[-.25,.4,-1.5]],0x476b8a);
   this.wire([[-.8,1.58,0],[-.6,1.88,-.65],[.6,.55,-1]],0xb3634c);
  }
  for(const x of [-2.85,2.85])for(const z of [-1.75,1.75])this.cylinder(x,-.32,z,.18,.13,0x59674f);
  for(const z of [-2.25,2.25])this.box(0,.006,z,6.8,.02,.025,0x96a487);
  for(const x of [-3.35,3.35])this.box(x,.006,0,.025,.02,4.5,0x96a487);
  this.details(distribution);
  this.draw();
 }
 setDistribution(value){if(!this.failed&&value!==this.distribution)this.build(value);}
 setCutaway(value){if(this.failed)return;this.cover.visible=!value;this.cutawayParts.forEach(m=>m.visible=!value);this.draw();}
 select(part){if(this.failed)return;this.parts.forEach(m=>m.material.emissive.setHex(m.userData.part===part?0x192d29:0));this.onSelect(part);this.draw();}
 temperature(value){if(this.failed)return;this.body.material.color.setHex(value==null?0xa4aaa4:value>55?0xba6845:value>40?0xbc935e:this.distribution?0x647b80:0xb3a56b);this.draw();}
 reset(){this.angle=.48;this.pitch=.7;this.distance=11.5;this.draw();}
 pick(e){const r=this.canvas.getBoundingClientRect(),p=new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),ray=new THREE.Raycaster();ray.setFromCamera(p,this.camera);const hit=ray.intersectObjects(this.parts)[0];if(hit)this.select(hit.object.userData.part);}
 draw(){if(!this.renderer||this.failed)return;const w=this.canvas.clientWidth,h=this.canvas.clientHeight;if(!w||!h)return;this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();const distance=this.distance*Math.max(1,1.38/this.camera.aspect);this.camera.position.set(Math.sin(this.angle)*Math.cos(this.pitch)*distance,Math.sin(this.pitch)*distance,Math.cos(this.angle)*Math.cos(this.pitch)*distance);this.camera.lookAt(0,.45,0);this.renderer.render(this.scene,this.camera);}
}
window.HaloTwin=HaloTwin;
