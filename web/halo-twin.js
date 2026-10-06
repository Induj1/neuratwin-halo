/* Local procedural geometry. Illustrative assembly, never a wiring reference. */
class HaloTwin {
 constructor(canvas, onSelect=()=>{}) {
  this.canvas=canvas; this.onSelect=onSelect; this.parts=[]; this.angle=.62; this.pitch=.55; this.distance=11;
  try {
   const T=window.THREE; if(!T) throw Error('Three unavailable');
   this.renderer=new T.WebGLRenderer({canvas,antialias:true,alpha:true});
   this.renderer.setPixelRatio(Math.min(devicePixelRatio,2)); this.renderer.outputEncoding=T.sRGBEncoding;this.renderer.toneMapping=T.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1;
   this.scene=new T.Scene(); this.camera=new T.PerspectiveCamera(38,1,.1,80);
   this.scene.add(new T.HemisphereLight(0xffffff,0x8d9989,.8));
   const sun=new T.DirectionalLight(0xffffff,1.1);sun.position.set(3,8,5);this.scene.add(sun);
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
  const T=THREE, mesh=new T.Mesh(new T.BoxGeometry(w,h,d),new T.MeshStandardMaterial({color,roughness:.5,metalness:metal}));mesh.position.set(x,y,z);mesh.userData.part=part;this.root.add(mesh);if(part)this.parts.push(mesh);return mesh;
 }
 cylinder(x,y,z,r,h,color,part,rotation=0) {
  const T=THREE,m=new T.Mesh(new T.CylinderGeometry(r,r,h,28),new T.MeshStandardMaterial({color,roughness:.42,metalness:.2}));m.position.set(x,y,z);m.rotation.z=rotation;m.userData.part=part;this.root.add(m);if(part)this.parts.push(m);return m;
 }
 wire(points,color) {const T=THREE,curve=new T.CatmullRomCurve3(points.map(p=>new T.Vector3(...p)));this.root.add(new T.Mesh(new T.TubeGeometry(curve,24,.026,7,false),new T.MeshStandardMaterial({color})));}
 build(distribution) {
  this.distribution=distribution;while(this.root.children.length){const m=this.root.children[0];m.geometry?.dispose();m.material?.dispose();this.root.remove(m);}this.parts=[];this.cutawayParts=[];
  this.box(0,-.13,0,7,.24,4.6,0xd8d5c9);
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
   this.box(1.42,.16,-1,2.25,.12,.8,0x254f66,'relay');
   for(let i=0;i<4;i++){const x=.62+i*.53;this.box(x,.39,-1,.43,.36,.53,0x4594af,'relay');this.cylinder(x,.42,.57,.14,.7,i===3?0xada492:0x74906d,'relay',Math.PI/2);this.wire([[x,.3,-.65],[x,.12,-.2],[x-.28,.16,.57]],0x9e694a);}
   this.box(1.4,.18,1.48,1.4,.13,.62,0x283f42,'controller');this.box(1.35,.3,1.48,.65,.14,.49,0xa4afad,'controller',.8);
   for(let x=.8;x<2.1;x+=.13){this.box(x,.22,1.1,.04,.17,.1,0xbeab77,'controller');this.box(x,.22,1.85,.04,.17,.1,0xbeab77,'controller');}
   this.box(-.22,.23,-1.57,.66,.12,.5,0x367988,'current');this.box(-.24,.36,-1.57,.3,.15,.25,0x93b4a2,'current');
   for(const z of [-1.4,1.4]){this.box(-2.9,.2,z,.45,.1,.85,0x31677e,'voltage');this.box(-2.9,.39,z,.35,.3,.4,0x487fa5,'voltage');}
   this.wire([[-1.8,1.58,0],[-1.8,1.95,-.5],[-.25,.4,-1.5]],0x476b8a);
   this.wire([[-.8,1.58,0],[-.6,1.88,-.65],[.6,.55,-1]],0xb3634c);
  }
  this.draw();
 }
 setDistribution(value){if(!this.failed&&value!==this.distribution)this.build(value);}
 setCutaway(value){if(this.failed)return;this.cover.visible=!value;this.cutawayParts.forEach(m=>m.visible=!value);this.draw();}
 select(part){if(this.failed)return;this.parts.forEach(m=>m.material.emissive.setHex(m.userData.part===part?0x192d29:0));this.onSelect(part);this.draw();}
 temperature(value){if(this.failed)return;this.body.material.color.setHex(value==null?0xa4aaa4:value>55?0xba6845:value>40?0xbc935e:this.distribution?0x647b80:0xb3a56b);this.draw();}
 reset(){this.angle=.62;this.pitch=.55;this.distance=11;this.draw();}
 pick(e){const r=this.canvas.getBoundingClientRect(),p=new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),ray=new THREE.Raycaster();ray.setFromCamera(p,this.camera);const hit=ray.intersectObjects(this.parts)[0];if(hit)this.select(hit.object.userData.part);}
 draw(){if(!this.renderer||this.failed)return;const w=this.canvas.clientWidth,h=this.canvas.clientHeight;if(!w||!h)return;this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.camera.position.set(Math.sin(this.angle)*Math.cos(this.pitch)*this.distance,Math.sin(this.pitch)*this.distance,Math.cos(this.angle)*Math.cos(this.pitch)*this.distance);this.camera.lookAt(0,.45,0);this.renderer.render(this.scene,this.camera);}
}
window.HaloTwin=HaloTwin;
