/* Shared source, separate virtual oil model. No automatic physical commands. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),root=$('view-physics');if(!root)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=(v,n=1)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:n}):'—';
 const lit={0:'abcdef',1:'bc',2:'abdeg',3:'abcdg',4:'bcfg',5:'acdfg',6:'acdefg',7:'abc',8:'abcdefg',9:'abcdfg','-':'g'};
 const seg={a:'5,1 23,1 26,4 23,7 5,7 2,4',b:'24,8 27,5 27,24 24,27 21,24 21,11',c:'24,29 27,32 27,51 24,54 21,51 21,32',d:'5,53 23,53 26,56 23,59 5,59 2,56',e:'2,29 5,32 5,51 2,54 0,51 0,32',f:'2,5 5,8 5,24 2,27 0,24 0,8',g:'5,27 23,27 26,30 23,33 5,33 2,30'};
 function digits(value,decimals=1){const text=Number.isFinite(value)?value.toFixed(decimals):'---';let x=0;const pieces=[];for(const c of text){if(c==='.'){pieces.push(`<circle class="px-seg-on" cx="${x+2}" cy="56" r="2.5"/>`);x+=9;continue;}pieces.push(`<g transform="translate(${x},0)">${Object.entries(seg).map(([k,p])=>`<polygon points="${p}" class="px-seg-${lit[c]?.includes(k)?'on':'off'}"/>`).join('')}</g>`);x+=35;}return `<svg viewBox="0 0 ${x} 61" role="img" aria-label="${text==='---'?'Unavailable':text}">${pieces.join('')}</svg>`;}
 function meter(name,value,unit,source,decimals=1,max=100,limit=null){
  const point=(v,r)=>{const a=(210-240*v/max)*Math.PI/180;return [70+r*Math.cos(a),68-r*Math.sin(a)]};
  const ticks=Array.from({length:21},(_,i)=>{const a=point(i*max/20,51),b=point(i*max/20,i%5===0?42:47);return `<path d="M${a}L${b}"/>`}).join('');
  const labels=[0,.5,1].map(v=>{const pos=point(v*max,34);return `<text x="${pos[0]}" y="${pos[1]+3}">${fmt(v*max,max<5?1:0)}</text>`}).join('');
  const needle=point(Math.max(0,Math.min(max,value??0)),43),mark=Number.isFinite(limit)&&limit<=max?point(limit,53):null;
  return `<div class="px-instrument"><div class="px-meter-label"><span>${esc(name)}</span></div><div class="px-gauge-face"><svg viewBox="0 0 140 104" aria-hidden="true"><g class="px-scale-ticks">${ticks}</g>${labels}<text class="px-dial-unit" x="70" y="56">${esc(unit)}</text>${mark?`<circle cx="${mark[0]}" cy="${mark[1]}" r="2.8" fill="#981818"/>`:''}${Number.isFinite(value)?`<path class="px-needle" d="M70 68L${needle}"/><circle cx="70" cy="68" r="4" fill="#1d252b"/>`:'<text x="70" y="82">NO SIGNAL</text>'}</svg></div><div class="px-number">${digits(value,decimals)}<span>${esc(unit)}</span></div><small>${esc(source)}</small></div>`;
 }
 function panelIndicators(r,physical,display){
  const ready=!!r?.available,settings=options.settings;
  const cells=[['SOURCE',physical?(display?.live?'LIVE':display?.timestamp?'CACHED':'OFFLINE'):'SIMULATED',physical?(display?.live?'signal':'off'):'signal'],
   ['OIL TEMP',ready?(r.oil_c>=settings.oil_limit_c?'HIGH':r.oil_c>=settings.oil_limit_c-10?'WARNING':'NORMAL'):'NO DATA',ready?(r.oil_c>=settings.oil_limit_c?'trip':r.oil_c>=settings.oil_limit_c-10?'warning':'normal'):'off'],
   ['PRESSURE',settings.tank==='conservator'?'VENTED':!ready||r.pressure_kpa==null?'NO DATA':r.pressure_kpa>=settings.pressure_limit_kpa?'HIGH':r.pressure_kpa>=settings.pressure_limit_kpa*.8?'WARNING':'NORMAL',settings.tank==='conservator'||!ready||r.pressure_kpa==null?'off':r.pressure_kpa>=settings.pressure_limit_kpa?'trip':r.pressure_kpa>=settings.pressure_limit_kpa*.8?'warning':'normal'],
   ['OIL LEVEL',ready?(r.level_percent<(settings.tank==='sealed'?95:25)?'LOW':'NORMAL'):'NO DATA',!ready?'off':r.level_percent<(settings.tank==='sealed'?95:25)?'warning':'normal'],
   ['SCENARIO',options.fault==='none'?'NONE':options.fault.toUpperCase(),options.fault==='none'?'off':'warning'],
   ['MODEL TRIP',ready?(r.stage==='trip'?'LATCHED':'CLEAR'):'NO DATA',!ready?'off':r.stage==='trip'?'trip':'normal']];
  $('px-annunciators').innerHTML=cells.map(([name,value,status])=>`<div class="px-annunciator" data-state="${status}"><span>${name}</span><strong>${value}</strong></div>`).join('');
 }
 function mimic(physical,display,t){
  const voltage=physical?display?.channels.secondary_voltage?.value:t?.secondary_voltage,live=physical?display?.live:!!t;
  const powered=live&&Number.isFinite(voltage)&&voltage>1;
  const branches=physical?['load1','load2','load4']:['Demand'];
  $('px-mimic').innerHTML=`<svg viewBox="0 0 480 164" role="img" aria-label="${physical?'Bench relay command states, not contact feedback':'Simulated transformer demand'}"><g class="px-bus" data-on="${powered}"><path d="M30 77H127M179 77H246V36H447"/><circle cx="146" cy="77" r="20"/><circle cx="165" cy="77" r="20"/></g><text x="30" y="58">SUPPLY</text><text x="132" y="119">TRANSFORMER</text>${branches.map((k,i)=>{const x=physical?272+i*78:365,on=physical?live&&display?.loads?.[k]:powered;return `<g class="px-bus" data-on="${!!on}"><path d="M${x} 36V67M${x} 88V120"/><path d="M${x} 88L${on?x:x+12} 67"/><circle cx="${x}" cy="67" r="3"/><rect x="${x-9}" y="120" width="18" height="9"/></g><text x="${x}" y="148" text-anchor="middle">${physical?k.replace('load','LOAD '):'DEMAND'}</text>`}).join('')}<circle cx="30" cy="77" r="4" fill="${powered?'#981818':'#626a64'}"/></svg><span>${physical?'RELAY COMMAND STATES':'SIMULATED CIRCUIT'}</span>`;
 }
 let state=null,result=null,key=null,serial=0,inflight=false,queued=false,last='',model=null,field=false,sensorNodes=[],busy=false;
 let options={settings:{tank:'sealed',clock_scale:60},fault:'none',fault_at:null,reset_at:null};
 const active=()=>root.classList.contains('active');
 // Share the existing instruments, including their histories and interaction state.
 // Anchors restore them to Digital twin when this view closes.
 const graphSlots=['op-scope','op-waveform','op-trend','op-trend-note'].map(id=>{const node=$(id),anchor=document.createComment(id+' home');node.before(anchor);return {node,anchor,host:$(id==='op-scope'||id==='op-waveform'?'px-electrical-graphs':'px-response-graphs')};});
 function syncGraphs(){for(const {node,anchor,host} of graphSlots){if(active()){if(node.parentNode!==host)host.append(node);}else if(node.previousSibling!==anchor)anchor.after(node);}}
 function sourceKey(s){return s?.mode+':'+s?.snapshot?.id;}
 function clear(){result=null;sensorNodes=[];last='';serial++;toggle(false);paint();}
 function origin(){return state?.mode==='industrial'?'Industrial simulation':'Physical prototype';}
 function currentTime(){return state?.mode==='prototype'?HaloOperations.displaySnapshot()?.timestamp:state?.snapshot?.telemetry?.timestamp;}
 function optionsCopy(){return JSON.parse(JSON.stringify(options));}
 function showModel(){
  if(!active())return;
  const physical=state?.mode!=='industrial';
  if(!model)model=new HaloTwin($('px-model'),p=>$('px-part').textContent=p.replaceAll('_',' '));
  const changed=model.distribution!==!physical;
  model.setDistribution(!physical);
  if(!model.failed&&changed){model.reset();if(!physical){model.distance=8.4;model.pitch=.48;model.target.set(-.1,1.05,0);}model.renderer.toneMappingExposure=physical?.8:.68;}
  const display=physical?window.HaloOperations?.displaySnapshot():null;
  const value=physical?(display?.live?display.channels.surface_temperature.value:null):result?.oil_c??null;
  const limits=physical?{warning:state?.snapshot?.settings?.temperature_warning,critical:state?.snapshot?.settings?.temperature_critical}:{warning:options.settings.oil_limit_c-10,critical:options.settings.oil_limit_c};
  const alarm=window.HaloAlarms?.current(),severity=value==null?'normal':['warning','critical'].includes(alarm?.thermal)?alarm.thermal:'normal';
  model.temperature(value,severity,limits);model.draw();
  if($('px-model').dataset.source!==(physical?'prototype':'industrial'))$('px-part').textContent=physical?'Surface probe':'Virtual oil model';
  $('px-model').dataset.source=physical?'prototype':'industrial';
  $('px-model').setAttribute('aria-label',physical?'Interactive physical transformer bench assembly':'Interactive industrial transformer model');
  if(!field)$('px-scene-label').textContent=physical?'Physical prototype':'Industrial transformer';
 }
 function thermalField(){const f=result?.fem;if(!f){$('px-fem').innerHTML='<p>Thermal field waits for source readings.</p>';return;}const low=options.settings.ambient_c??25,high=Math.max(low+1,f.peak_c);const colour=t=>{const v=Math.max(0,Math.min(1,(t-low)/(high-low)));return `hsl(${195-v*190} ${28+v*48}% ${76-v*27}%)`;};
  $('px-fem').innerHTML=`<svg viewBox="-0.04 -0.04 .38 .49" role="img" aria-label="Solved finite element temperature field">${f.triangles.map(tri=>`<polygon points="${tri.map(i=>f.nodes[i].join(',')).join(' ')}" fill="${colour(tri.reduce((s,i)=>s+f.temperature_c[i],0)/3)}" stroke="#1d252b18" stroke-width=".0006"/>`).join('')}${sensorNodes.map(i=>`<circle cx="${f.nodes[i][0]}" cy="${f.nodes[i][1]}" r=".008" fill="#f8f888" stroke="#1d252b" stroke-width=".002"/>`).join('')}</svg><div class="px-fem-scale"><span>${fmt(high)} °C</span><i style="background:linear-gradient(to bottom,${colour(high)},${colour((low+high)/2)},${colour(low)})"></i><span>${fmt(low)} °C</span></div>`;
 }
 function chart(key,title,unit,limit){const r=result;const empty=`<div class="px-chart"><div>${title}<span>${unit}</span></div><p>${r?.available&&key==='pressure_kpa'?'Vented conservator · no gas-cushion pressure':'Waiting for source readings'}</p></div>`;if(!r?.available||r.curves[0]?.[key]==null)return empty;
  const all=[...r.curves,...r.mitigated].map(v=>v[key]).filter(Number.isFinite);if(Number.isFinite(limit))all.push(limit);let lo=Math.min(...all),hi=Math.max(...all),pad=Math.max(2,(hi-lo)*.1);lo-=pad;hi+=pad;
  const x=t=>90+t/120*442,y=v=>174-(v-lo)/(hi-lo)*130;
  const grid=Array.from({length:3},(_,i)=>{const v=lo+(hi-lo)*i/2;return `<line x1="90" x2="532" y1="${y(v)}" y2="${y(v)}"/><text x="78" y="${y(v)+6}" text-anchor="end">${fmt(v,0)}</text>`;}).join('');
  return `<div class="px-chart"><div>${title}<span>${unit}</span></div><svg viewBox="0 0 560 224" role="img" aria-label="${title} under continued and reduced load">${grid}${Number.isFinite(limit)?`<path d="M90 ${y(limit)}H532" fill="none" stroke="#f8a808" stroke-dasharray="4 5"/>`:''}${[r.curves,r.mitigated].map((rows,i)=>`<path d="${rows.filter(v=>Number.isFinite(v[key])).map((v,j)=>(j?'L':'M')+x(v.minute)+','+y(v[key])).join(' ')}" fill="none" stroke="${i?'#c8d8e8':'#e85848'}" stroke-width="2" ${i?'stroke-dasharray="6 3"':''}/>`).join('')}<text x="90" y="211">Now</text><text x="532" y="211" text-anchor="end">120 model min</text></svg></div>`;
 }
 function paint(){const s=state?.snapshot,r=result,physical=state?.mode!=='industrial',display=physical?window.HaloOperations?.displaySnapshot():null,t=s?.telemetry;
  syncGraphs();
  const v=physical?display?.channels.secondary_voltage:t?{value:t.secondary_voltage,source:'simulated'}:null;
  const a=physical?display?.channels.secondary_current:t?{value:t.secondary_current,source:'simulated'}:null;
  const temp=physical?display?.channels.surface_temperature:t?{value:t.oil_temperature,source:'simulated'}:null;
  const channel=c=>c?.source?.replaceAll('_',' ')||'unavailable';
  $('px-readings').innerHTML=meter('Secondary voltage',v?.value,'V',channel(v),1,physical?30:600)+meter('Secondary current',a?.value,'A',channel(a),physical?3:1,physical?1.5:Math.ceil((t?.secondary_current/(t?.loading_percent/100)||1000)*1.8/100)*100,physical?1:null)+meter(physical?'Surface temperature':'Source top-oil',temp?.value,'°C',channel(temp),1,150)+meter('Source loading',physical?display?.loading_percent:t?.loading_percent,'%',physical?'1 A reference':'Rated current',1,180,100);
  window.HaloAlarms?.update({key:sourceKey(state),mode:physical?'prototype':'industrial',snapshot:s,display,result:r,settings:options.settings,fault:options.fault,fault_at:options.fault_at,replay:state?.replay});
  panelIndicators(r,physical,display);mimic(physical,display,t);
  $('px-control-context').textContent=physical?'Physical load switching is in Operator action.':s?'Changes simulated demand.':'Create an industrial run to set demand.';
  $('px-origin').textContent=origin()+' · '+(physical?(display?.live?'live readings':display?.timestamp?'cached readings':'offline'):'modelled readings');
  $('px-simulation').hidden=physical||!s;if(!physical&&s){if(document.activeElement!==$('px-load'))$('px-load').value=s.inputs.load_percent;$('px-load-value').textContent=fmt(s.inputs.load_percent,0)+'%';}
  $('px-clock-label').textContent=`MODEL CLOCK · ${options.settings.clock_scale}×`;
  $('px-oil-meters').innerHTML=meter('Top-oil estimate',r?.oil_c,'°C','Virtual model',1,150,options.settings.oil_limit_c)+meter(options.settings.tank==='sealed'?'Tank pressure':'Gas accumulation',options.settings.tank==='sealed'?r?.pressure_kpa:r?.gas_ml,options.settings.tank==='sealed'?'kPa g':'mL',options.settings.tank==='sealed'?'Virtual model':options.fault==='gas'?'Injected scenario':'No gas measurement',1,options.settings.tank==='sealed'?Math.max(100,options.settings.pressure_limit_kpa*1.5):300,options.settings.tank==='sealed'?options.settings.pressure_limit_kpa:200);
  const faultLive=!!r?.available&&!!r.live&&(!physical||!!display?.live);
  $('px-level-label').textContent=(r?.level_basis||(options.settings.tank==='sealed'?'Oil inventory':'Conservator fill'))+(r?.available&&!faultLive?' · paused':'');$('px-level-value').textContent=Number.isFinite(r?.level_percent)?fmt(r.level_percent)+'%':'—';$('px-level-fill').style.width=Math.max(0,Math.min(100,r?.level_percent??0))+'%';
  const rec=r?.recommendation;$('px-state').textContent=(r?.stage||'waiting').toUpperCase();$('px-decision').dataset.state=r?.stage||'waiting';
  $('px-action').textContent=rec?.action||'Waiting for current and temperature';
  $('px-action-detail').textContent=!r?.available?(r?.reason||'Open Industrial simulation to explore without the board.'):r.stage==='trip'?'Model trip latched. Review the scenario before restoring loads.':rec.load_reduction_percent>0?`Reduce demand by ${fmt(rec.load_reduction_percent,0)}%. Projected peak ${fmt(rec.peak_before_c)} → ${fmt(rec.peak_after_c)} °C.`:'Within configured limits over the next two model hours.';
  if(r?.available&&!r.live)$('px-action-detail').textContent+=' Cached inputs; physical commands paused.';
  $('px-limit').textContent=r?.available?(r.time_to_limit_min==null?'>120 min':fmt(r.time_to_limit_min,0)+' min'):'—';$('px-retained').textContent=rec?fmt(100-rec.load_reduction_percent,0)+'%':'—';
  $('px-apply').disabled=busy||state?.replay||!r?.available||!r.live||r.stage==='trip'||!rec?.sufficient||rec.load_reduction_percent<=0;
  $('px-apply').textContent=physical?'Shed '+(rec?.branches_to_shed||'')+' bench load'+(rec?.branches_to_shed===1?'':'s'):'Apply simulated load reduction';
  $('px-trip').hidden=!physical;$('px-trip').disabled=busy||state?.replay||!display?.live;$('px-export').disabled=!s||state?.replay;$('px-new').hidden=physical;
  const loads=display?.loads;$('px-branches').innerHTML=physical?['load1','load2','load4'].map((k,i)=>`<span class="px-branch" data-on="${!!loads?.[k]}"><i></i>M${i+1}</span>`).join(''):'Distribution load';
  $('px-charts').innerHTML=chart('oil_c','Top-oil forecast','°C',options.settings.oil_limit_c)+chart('pressure_kpa','Pressure forecast','kPa gauge',options.settings.pressure_limit_kpa);
  $('px-projection-note').textContent=options.fault==='none'?'Forecasts hold loading and ambient constant. Dashed line: recommended load. Amber: configured limit.':'Fault injected. Forecasts show thermal loading only; shedding does not repair a leak or gas fault.';
  $('px-model-status').textContent=r?.available?(r.live?'Source connected':'Cached source'):'Awaiting source';
  $('px-basis').textContent=r?.available?`${r.matrix.length} source samples · ${fmt(r.integrated_seconds)} s integrated · ${fmt(r.skipped_seconds)} s gaps excluded. ${r.scope} ${r.pressure_basis} ${r.temperature_basis} Current: ${r.current_source}. Oil expansion uses bulk temperature; defaults and volume geometry are assumptions.`:'The current source must supply current and temperature. No additional sensor is required to run the virtual model.';
  $('px-events').innerHTML=r?.events.map(e=>`<div>${esc(new Date(e.timestamp).toLocaleTimeString())} · ${esc(e.state)} · ${esc(e.origin)}</div>`).join('')||'';
  const f=r?.fem;$('px-fem-facts').innerHTML=f?`<table><tbody><tr><td>Linear triangular elements</td><td>${f.elements}</td></tr><tr><td>Heat input / rejected</td><td>${fmt(f.heat_input_w,2)} / ${fmt(f.heat_rejected_w,2)} W</td></tr><tr><td>Energy balance residual</td><td>${f.balance_error_w.toExponential(1)} W</td></tr><tr><td>Model peak</td><td>${fmt(f.peak_c)} °C</td></tr><tr><td>Cross-section / depth</td><td>0.30 × 0.40 / 0.20 m</td></tr></tbody></table><p>${esc(f.scope)} Fixed illustrative losses: 2 W core + 10 K² W copper. This field is a separate declared geometry study, not the oil forecast's measured temperature field.</p>`:'<p>FEM study waits for source readings.</p>';
  document.querySelectorAll('[data-px-fault]').forEach(b=>{b.disabled=busy||!faultLive||(b.dataset.pxFault==='gas'&&options.settings.tank!=='conservator')||(b.dataset.pxFault==='surge'&&options.settings.tank!=='sealed');b.setAttribute('aria-pressed',String(b.dataset.pxFault===options.fault));b.title=physical&&!display?.live?'Reconnect ESP32 or use Industrial simulation.':'';});
  $('px-json').disabled=!r?.available;$('px-sensors').disabled=!r?.fem;showModel();if(field)thermalField();
 }
 async function update(force=false){if(!active()||!state?.snapshot||state.replay)return;if(inflight){queued=true;return;}const physical=state.mode==='prototype',s=state.snapshot;
  const body={revision:physical?null:s.revision,options:optionsCopy()};if(physical){body.display_current=HaloOperations.displaySnapshot();body.display_history=HaloOperations.displayHistory();}
  const signature=JSON.stringify([key,s.revision,body.display_current?.sequence,body.display_current?.live,body.options]);if(!force&&signature===last)return;
  const token=serial;inflight=true;try{const r=await HaloWorkspace.api('/twin/physics/'+encodeURIComponent(physical?'BENCH-001':s.id),body);if(token!==serial)return;result=r;last=signature;options.settings=r.settings;$('px-error').textContent='';paint();}catch(e){if(token===serial){result=null;paint();$('px-error').textContent=e.message;}}finally{inflight=false;if(queued){queued=false;update();}}}
 window.addEventListener('halo:operation-state',e=>{state=e.detail;const next=sourceKey(state);if(next!==key){key=next;options.fault='none';options.fault_at=null;options.reset_at=null;clear();$('px-command').textContent='';$('px-sensor-result').replaceChildren();}if(state.replay)clear();if(active()){paint();update();}});
 window.addEventListener('halo:view',e=>{syncGraphs();if(e.detail==='physics'){state=HaloOperations.current();paint();update(true);}else serial++;});
 function changed(){serial++;last='';result=null;paint();update(true);}
 $('px-tank').onchange=e=>{options.settings.tank=e.target.value;options.fault='none';options.fault_at=null;changed();};
 $('px-settings').onsubmit=e=>{e.preventDefault();Object.assign(options.settings,Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)])));changed();};
 document.querySelectorAll('[data-px-fault]').forEach(b=>b.onclick=async()=>{
  if(busy||!result?.available||!result.live||state?.replay||state?.mode==='prototype'&&!HaloOperations.displaySnapshot()?.live)return;const source=key;busy=true;paint();
  try{
   // Fault progression uses source time. Starting a scenario must also start a
   // paused industrial clock; physical readings and relay commands are untouched.
   if(state.mode==='industrial'&&!state.snapshot.running)await HaloOperations.act('start');
   if(key!==source)return;
   options.fault=b.dataset.pxFault;options.fault_at=currentTime();changed();
  }catch(e){$('px-error').textContent=e.message;}finally{busy=false;paint();}
 });
 $('px-reset').onclick=()=>{options.fault='none';options.fault_at=null;options.reset_at=currentTime();$('px-command').textContent='';changed();};
 $('px-assembly').onclick=()=>toggle(false);$('px-field').onclick=()=>toggle(true);
 function toggle(value){field=value;$('px-fem').hidden=!value;$('px-model').hidden=value;$('px-assembly').setAttribute('aria-pressed',String(!value));$('px-field').setAttribute('aria-pressed',String(value));$('px-scene-label').textContent=value?'Declared FEM cross-section':state?.mode==='industrial'?'Industrial transformer':'Physical prototype';$('px-field-value').textContent=value?'Illustrative geometry · °C':'Drag to inspect';if(value)thermalField();else showModel();}
 $('px-export').onclick=()=>document.getElementById('op-export-pdf').click();
 $('px-new').onclick=()=>document.getElementById('op-new').click();
 $('px-load').oninput=e=>$('px-load-value').textContent=e.target.value+'%';
 $('px-load').onchange=async e=>{try{await HaloOperations.act('inputs',{inputs:{load_percent:Number(e.target.value)}});}catch(e){$('px-error').textContent=e.message;}};
 $('px-advance').onclick=async()=>{const b=$('px-advance');b.disabled=true;try{await HaloOperations.act('advance_paused',{seconds:60});}catch(e){$('px-error').textContent=e.message;}finally{b.disabled=false;}};
 async function command(trip=false){if(busy||state?.replay||!state?.snapshot||(!trip&&(!result?.available||!result.live||result.stage==='trip'||!result.recommendation.sufficient)))return;const r=result,startKey=key,startSerial=serial,revision=state.snapshot.revision,startLoads=JSON.stringify(HaloOperations.displaySnapshot()?.loads);busy=true;paint();$('px-command').textContent='Sending command…';try{
   if(state.mode==='prototype'){
    const status=await HaloWorkspace.api('/esp32/status');if(!status.control_enabled)throw Error('Bench switching is locked on the server.');
    const d=HaloOperations.displaySnapshot();if(key!==startKey||state?.replay||!d?.live||(!trip&&(serial!==startSerial||result?.input_sha256!==r.input_sha256||JSON.stringify(d.loads)!==startLoads||d.channels.secondary_current.value!==r.input_current_a)))throw Error('Source changed. Recompute before switching.');
    const active=['load4','load2','load1'].filter(k=>d.loads?.[k]);const count=trip?active.length:r.recommendation.branches_to_shed;
    if(!trip&&(!count||count>active.length))throw Error('Load state changed; refresh the recommendation.');
    const body=trip?{load1:false,load2:false,load4:false}:Object.fromEntries(active.slice(0,count).map(k=>[k,false]));
    await HaloWorkspace.api('/esp32/loads',body);$('px-command').textContent='Board acknowledged. Awaiting fresh current; contact position is not measured.';
   }else{if(state.snapshot.revision!==revision)throw Error('Run changed; refresh the recommendation.');await HaloOperations.act('inputs',{inputs:{load_percent:state.snapshot.inputs.load_percent*(1-r.recommendation.load_reduction_percent/100)}});$('px-command').textContent='Simulated demand reduced. Advance the run to inspect recovery.';}
  }catch(e){$('px-command').textContent=e.message;}finally{busy=false;paint();}}
 $('px-apply').onclick=()=>command();$('px-trip').onclick=()=>command(true);
 $('px-sensors').onclick=async()=>{const token=serial;$('px-sensors').disabled=true;try{const r=await HaloWorkspace.api('/twin/physics-sensor-study');if(token!==serial)return;sensorNodes=r.results[0].node_ids;toggle(true);$('px-sensor-result').innerHTML=`<table><thead><tr><th>Surface sensors</th><th>Held-out RMSE</th></tr></thead><tbody>${r.results.map(v=>`<tr><td>${v.sensors}</td><td>${fmt(v.rmse_c,2)} °C</td></tr>`).join('')}</tbody></table><p>${esc(r.scope)} Yellow point: selected single-sensor position. Sensor count is a cost proxy; no price saving is assumed.</p>`;}catch(e){$('px-sensor-result').textContent=e.message;}finally{$('px-sensors').disabled=false;}};
 $('px-json').onclick=()=>{if(!result)return;const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='neuratwin-physics-study.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 window.HaloPhysics={options:()=>optionsCopy(),result:()=>result?structuredClone(result):null};state=HaloOperations.current();key=sourceKey(state);paint();if(active())update();
})();
