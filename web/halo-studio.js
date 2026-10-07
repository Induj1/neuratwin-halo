/* Neutral studio lighting shared by the two interactive models. */
window.HaloStudio = function (T, scene, renderer, floorY) {
 renderer.outputEncoding=T.sRGBEncoding;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;
 const faces=[];
 for(let i=0;i<6;i++){const c=document.createElement('canvas');c.width=c.height=128;const x=c.getContext('2d');const g=x.createLinearGradient(0,0,0,128);g.addColorStop(0,'#d8dacf');g.addColorStop(.5,i===2?'#ffffff':'#b1b5aa');g.addColorStop(1,'#838d80');x.fillStyle=g;x.fillRect(0,0,128,128);x.fillStyle='#ffffff';x.fillRect(i%2?10:76,12,24,100);faces.push(c);}
 const env=new T.CubeTexture(faces);env.needsUpdate=true;env.encoding=T.sRGBEncoding;const pmrem=new T.PMREMGenerator(renderer);scene.environment=pmrem.fromCubemap(env).texture;env.dispose();pmrem.dispose();
 scene.add(new T.HemisphereLight(0xffffff,0x929686,.7));
 const key=new T.DirectionalLight(0xfff8ed,2.3);key.position.set(-3,8,5);key.castShadow=true;key.shadow.mapSize.set(2048,2048);key.shadow.camera.left=-7;key.shadow.camera.right=7;key.shadow.camera.top=7;key.shadow.camera.bottom=-7;key.shadow.normalBias=.025;key.shadow.bias=-.0002;key.shadow.radius=4;scene.add(key);
 const fill=new T.DirectionalLight(0xdfe8ee,.9);fill.position.set(4,4,-4);scene.add(fill);
 const ground=new T.Mesh(new T.PlaneGeometry(60,60),new T.ShadowMaterial({color:0x59634f,opacity:.16}));ground.rotation.x=-Math.PI/2;ground.position.y=floorY;ground.receiveShadow=true;scene.add(ground);
 const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d');const gradient=ctx.createRadialGradient(64,64,8,64,64,64);gradient.addColorStop(0,'rgba(48,55,39,0.22)');gradient.addColorStop(.45,'rgba(48,55,39,0.10)');gradient.addColorStop(1,'rgba(48,55,39,0)');ctx.fillStyle=gradient;ctx.fillRect(0,0,128,128);const shadow=new T.Mesh(new T.PlaneGeometry(7,6),new T.MeshBasicMaterial({map:new T.CanvasTexture(c),transparent:true,depthWrite:false}));shadow.rotation.x=-Math.PI/2;shadow.position.y=floorY+.004;scene.add(shadow);
};
