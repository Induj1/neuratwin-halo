/* Display-only annunciation. Never sends control commands. */
((root)=>{'use strict';
 const rank={normal:0,warning:1,critical:2};
 function surfaceLimits(settings={},override=null){
  if(Number.isFinite(override)&&override>=0&&override<=125)return {critical:override,warning:override-5,demo:false,operator:true};
  const configured=Number.isFinite(settings.temperature_critical);
  const critical=configured?settings.temperature_critical:55;
  return {critical,warning:configured&&Number.isFinite(settings.temperature_warning)?settings.temperature_warning:critical-5,demo:!configured};
 }
 function threshold(value,warning,critical,previous='normal',margin=2){
  if(![value,warning,critical].every(Number.isFinite))return 'unavailable';
  if(value>=critical||(previous==='critical'&&value>critical-margin))return 'critical';
  if(value>=warning||(rank[previous]>0&&value>warning-margin))return 'warning';
  return 'normal';
 }
 function createState(){return {key:null,levels:{},ack:{},hadAlarm:false,recovered:false,liveSeen:false};}
 function evaluate(previous,input){
  const s=previous.key===input.key?{...previous,levels:{...previous.levels},ack:{...previous.ack}}:{...createState(),key:input.key};
  const alerts=[],physical=input.mode==='prototype',d=input.display,r=input.result,p=input.settings||{};let incomplete=false;
  const scenarioKey=[input.fault,input.fault_at,p.tank].join(':');
  if(s.scenarioKey!==scenarioKey){delete s.ack['scenario-leak'];delete s.ack['scenario-gas'];s.scenarioKey=scenarioKey;}
  const demo=physical&&r?.available&&r.simulated_inputs;
  const available=!input.replay&&(physical?!!d?.live||demo||r?.electrical?.simulated:!!input.snapshot?.telemetry);
  const add=(id,label,value,warning,critical,unit,basis,low=false)=>{
   const level=Number.isFinite(value)?threshold(low?-value:value,low?-warning:warning,low?-critical:critical,s.levels[id]):'unavailable';
   if(level==='unavailable'){incomplete=true;return;}
   if(level!==s.levels[id]){if(rank[level]>rank[s.levels[id]||'normal']||level==='normal')delete s.ack[id];s.levels[id]=level;}
   if(rank[level]>0)alerts.push({id,label,level,value,unit,basis,acknowledged:!!s.ack[id]});
  };
  if(!available){return {...s,status:'unavailable',alerts:[],title:input.replay?'Replay · alarms paused':physical?(s.liveSeen?'Connection lost':'Waiting for ESP32'):'Waiting for simulation',detail:input.replay?'Return to current readings to resume alarms.':'Current conditions cannot be confirmed.',thermal:'unavailable'};}
  if(!physical||d?.live)s.liveSeen=true;
  let sensorMissing=false;
  if(physical&&d?.live){
   const value=d?.channels?.surface_temperature?.value,limits=surfaceLimits(input.snapshot?.settings,input.surface_limit_c);
   const thresholdKey=limits.warning+':'+limits.critical;
   if(s.surfaceThreshold!==thresholdKey){delete s.ack.surface;delete s.levels.surface;s.surfaceThreshold=thresholdKey;}
   sensorMissing=!Number.isFinite(value);
   if(!sensorMissing)add('surface','Surface temperature',value,limits.warning,limits.critical,'°C',limits.demo?'Measured · demo threshold':limits.operator?'Measured · alarm threshold':'Measured');
  }
  const modelReady=!!r?.available&&(!!r.live||demo);
  if(modelReady){
   add('oil','Oil temperature',r.oil_c,p.oil_limit_c-10,p.oil_limit_c,'°C','Modelled');
   if(p.tank==='sealed')add('pressure','Tank pressure',r.pressure_kpa,p.pressure_limit_kpa*.8,p.pressure_limit_kpa,'kPa','Modelled');
   if(p.tank==='sealed'||Number.isFinite(r.inventory_percent))add('level','Oil inventory',r.inventory_percent??r.level_percent,p.oil_warning_percent??95,p.oil_critical_percent??90,'%','Modelled',true);
   if(p.tank==='conservator')add('conservator','Conservator fill',r.level_percent,25,15,'%','Modelled',true);
   if(p.tank==='conservator')add('gas','Gas accumulation',r.gas_ml,100,200,'mL','Simulated');
   // A confirmed injection is visible immediately; measured/model thresholds still
   // determine escalation. A paused source cannot accumulate a leak or gas.
   if(r.fault===input.fault&&(input.fault==='leak'||input.fault==='gas'&&p.tank==='conservator')){
    const id='scenario-'+input.fault;
    alerts.push({id,label:input.fault==='leak'?'Oil leak scenario active':'Gas accumulation scenario active',level:'warning',basis:'Injected scenario',acknowledged:!!s.ack[id]});
   }
   if(r.stage==='trip'){
    if(s.levels.trip!=='critical')delete s.ack.trip;
    s.levels.trip='critical';alerts.push({id:'trip',label:'Model trip latched',level:'critical',basis:input.fault&&input.fault!=='none'?'Injected scenario':'Modelled',acknowledged:!!s.ack.trip});
   }else{s.levels.trip='normal';delete s.ack.trip;}
  }
  const electrical=r?.electrical;
  if(electrical?.available){
   const level=electrical.severity;
   if(level!==s.levels.electrical){delete s.ack.electrical;s.levels.electrical=level;}
   if(rank[level]>0)alerts.push({id:'electrical',label:electrical.label,level,basis:electrical.source,acknowledged:!!s.ack.electrical});
  }else{delete s.levels.electrical;delete s.ack.electrical;}
  alerts.sort((a,b)=>rank[b.level]-rank[a.level]);
  const missing=sensorMissing||!modelReady||incomplete;
  if(alerts.length){s.hadAlarm=true;s.recovered=false;}
  else if(s.hadAlarm&&!missing){s.recovered=true;s.hadAlarm=false;}
  const top=alerts[0],status=top?.level||(missing?'unavailable':s.recovered?'recovered':'normal');
  return {...s,alerts,status,thermal:sensorMissing||physical&&!d?.live?'unavailable':s.levels[physical?'surface':'oil']||'unavailable',
   title:top?`${top.level==='critical'?'Critical':'Warning'} · ${top.label}`:sensorMissing?'Surface temperature unavailable':!modelReady||incomplete?'Model unavailable':s.recovered?'Conditions recovered':demo?'Oil simulation running':'Within configured limits',
   detail:top?(top.id.startsWith('scenario-')?(!physical&&!input.snapshot?.running?'Advance source 1 min to progress the fault.':'Fault progressing. Critical limits trigger the siren.'):top.id==='trip'?'Review the cause before resetting the model trip.':top.id==='surface'?'Reduce load and inspect cooling.':top.id==='level'||top.id==='gas'?'Inspect the simulated fault; load reduction does not repair it.':'Review the recommended action below.'):
    sensorMissing?'Check the surface probe.':!modelReady||incomplete?'Waiting for current model output.':s.recovered?'Readings are below the alarm recovery thresholds.':'Monitoring temperature and virtual oil protection.',
   missing:demo?'Simulated oil system.':missing&&!!top?(sensorMissing?'Surface temperature unavailable.':'Model output unavailable.'):'',
  };
 }
 function acknowledge(state){const ack={...state.ack};for(const a of state.alerts||[])ack[a.id]=true;return {...state,ack,alerts:(state.alerts||[]).map(a=>({...a,acknowledged:true}))};}
 const api={threshold,surfaceLimits,createState,evaluate,acknowledge};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 root.HaloAlarms=api;
 if(typeof document==='undefined')return;
 const $=id=>document.getElementById(id),panel=$('px-alarm');if(!panel)return;
 let state=createState(),context=null,timer=null,signature='',lastInput=null,tones=[];
 const visible=()=>!document.hidden&&$('view-physics')?.classList.contains('active')&&document.body.dataset.twinSwitching!=='true';
 const pending=()=>state.alerts?.filter(a=>!a.acknowledged)||[];
 function stop(){clearInterval(timer);timer=null;for(const o of tones){try{o.stop();}catch{}}tones=[];}
 function beep(critical=false){
  if(!visible()||context?.state!=='running')return;
  const now=context.currentTime;
  // Harmonic-rich high/low siren, with brief ramps to avoid digital clicks.
  // Eight alternating blasts occupy 1.9 s of each 2 s critical cycle.
  for(let i=0;i<(critical?8:3);i++){
   const o=context.createOscillator(),g=context.createGain(),filter=context.createBiquadFilter();
   const spacing=critical?.24:.18,duration=critical?.22:.12,start=now+i*spacing,pitch=critical?(i%2?1440:960):1100;
   o.type='square';o.frequency.setValueAtTime(pitch,start);o.frequency.linearRampToValueAtTime(pitch*(critical?1.06:1),start+duration);
   filter.type='lowpass';filter.frequency.value=4200;filter.Q.value=.5;
   const volume=critical?.18:.12;g.gain.setValueAtTime(0,start);g.gain.linearRampToValueAtTime(volume,start+.006);g.gain.setValueAtTime(volume,start+duration-.012);g.gain.linearRampToValueAtTime(0,start+duration);
   o.connect(filter);filter.connect(g);g.connect(context.destination);tones.push(o);o.onended=()=>{tones=tones.filter(t=>t!==o);o.disconnect();filter.disconnect();g.disconnect();};o.start(start);o.stop(start+duration+.005);
  }
 }
 function syncSound(){
  const active=pending(),next=active.map(a=>a.id+':'+a.level).join('|'),critical=active.some(a=>a.level==='critical');
  if(context?.state!=='running'||!visible()||!active.length){stop();signature='';return;}
  if(next!==signature){stop();beep(critical);signature=next;}
  if(critical&&!timer)timer=setInterval(()=>beep(true),2000);
  if(!critical&&timer){clearInterval(timer);timer=null;}
 }
 function paint(){
  panel.dataset.state=state.status||'unavailable';panel.dataset.acknowledged=String(!!state.alerts?.length&&!pending().length);
  $('px-alarm-title').textContent=state.title||'Waiting for readings';
  $('px-alarm-detail').textContent=[state.detail,state.missing].filter(Boolean).join(' ');
  const list=$('px-alarm-signals');list.replaceChildren();
  for(const a of state.alerts||[]){const item=document.createElement('span');item.textContent=`${a.basis} · ${a.label}${Number.isFinite(a.value)?' '+a.value.toFixed(1)+' '+a.unit:''}`;list.append(item);}
  list.hidden=!state.alerts?.length;
  $('px-alarm-ack').disabled=!pending().length;$('px-alarm-ack').textContent=state.alerts?.length&&!pending().length?'Acknowledged':'Acknowledge';
  const temperature=$('px-readings')?.children[2];if(temperature)temperature.dataset.alarm=state.thermal;
  const scene=$('px-model')?.closest('.px-scene');if(scene)scene.dataset.alarm=state.thermal;
  syncSound();
 }
 api.update=input=>{lastInput=input;state=evaluate(state,input);paint();return state;};
 api.current=()=>structuredClone(state);
 $('px-alarm-ack').onclick=()=>{state=acknowledge(state);paint();};
 async function unlockAudio(event){
  // Normal interaction unlocks browser audio; acknowledgement must never start it.
  if(event?.target?.closest?.('#px-alarm-ack')||context?.state==='running')return;
  try{
   const Audio=root.AudioContext||root.webkitAudioContext;if(!Audio)return;
   if(!context||context.state==='closed'){context=new Audio();context.onstatechange=syncSound;}
   await context.resume();syncSound();
  }catch{/* Keep visual alarms available; retry audio on the next interaction. */}
 }
 document.addEventListener('click',unlockAudio);document.addEventListener('keydown',unlockAudio);
 if(navigator.userActivation?.hasBeenActive)unlockAudio();
 document.addEventListener('visibilitychange',syncSound);root.addEventListener('halo:view',syncSound);root.addEventListener('pagehide',stop);
 root.addEventListener('halo:session',()=>{stop();signature='';state=createState();});
 new MutationObserver(()=>{if(document.body.dataset.twinSwitching==='true')stop();else if(lastInput)syncSound();}).observe(document.body,{attributes:true,attributeFilter:['data-twin-switching']});
})(typeof window!=='undefined'?window:globalThis);
