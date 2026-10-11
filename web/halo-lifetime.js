/* Read-only scenario layer. Never changes source readings or sends hardware commands. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const num=(v,n=1)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:n}):'—';
 const anchor=$('op-readings');if(!anchor)return;
 const panel=document.createElement('section');panel.id='op-lifetime';panel.className='panel lifetime-panel';panel.hidden=true;
 panel.innerHTML=`<div class="lifetime-heading"><h2>Ageing sensitivity study</h2><span id="life-source">Scenario estimates</span></div><p>Assumption-driven exploration, not a measured remaining lifespan or validated probability of failure. Use the maintenance model for operational follow-up.</p>
 <div class="lifetime-metrics"><div><span>Condition score</span><strong id="life-condition">—</strong><small>Inspectable screening</small></div><div><span>Time to temperature limit</span><strong id="life-limit">—</strong><small id="life-limit-note">Conditional forecast</small></div><div><span>Modelled remaining life</span><strong id="life-remaining">—</strong><small>Conditional median</small></div><div><span>Simulated failure risk</span><strong id="life-risk">—</strong><small id="life-risk-note">Next 365 days</small></div></div>
 <p id="life-status" role="status"></p><div id="life-charts" class="lifetime-charts"></div>
 <details id="life-assumptions"><summary>Model assumptions</summary><p>Lifetime and risk use an assumed thermal-ageing model. They are not measured lifespan or calibrated failure probabilities. Future loading is held constant without protective interruption.</p><form id="life-form"><div id="life-fields" class="lifetime-fields"></div><div class="case-actions"><button type="submit">Update model</button><button type="button" id="life-reset">Reset assumptions</button></div></form><p id="life-basis"></p><div id="life-components"></div></details>`;
 anchor.after(panel);
 const fields=[['reference_life_years','Reference life scale (years)',1,100],['initial_equivalent_age_years','Assumed equivalent age (years)',0,200],['risk_horizon_days','Risk horizon (days)',1,3650],['weibull_shape','Lifetime distribution shape',1.01,8],['reference_temperature_c','Reference ageing temperature (°C)',20,150],['temperature_offset_c','Temperature offset (°C)',0,80],['doubling_c','Ageing doubles every (°C)',3,30],['ambient_c','Assumed ambient (°C)',-20,60],['rated_rise_c','Rise at rated current (°C)',.1,150],['thermal_tau_min','Thermal time constant (min)',1,1440],['limit_temperature_c','Temperature limit (°C)',0,200]];
 let state=null,key=null,parameters=null,result=null,inflight=false,queued=false,version=0,lastSignature=null,timer=null;
 function fill(){if(!parameters)return;$('life-fields').innerHTML=fields.map(([name,label,min,max])=>`<label>${label}<input name="${name}" type="number" value="${parameters[name]}" min="${min}" max="${max}" step="${name==='risk_horizon_days'?'1':'any'}" required></label>`).join('');}
 function persist(){try{if(parameters)localStorage.setItem('halo-life:'+key,JSON.stringify(parameters));else localStorage.removeItem('halo-life:'+key);}catch{}}
 function clear(){result=null;for(const id of ['life-condition','life-limit','life-remaining','life-risk'])$(id).textContent='—';$('life-charts').replaceChildren();$('life-basis').textContent='';$('life-components').replaceChildren();$('life-status').textContent='Preparing scenario…';}
 function graph(points,yKey,title,unit,xEnd,color,threshold){
   if(!points.length)return '';
   const vals=points.map(p=>p[yKey]);if(Number.isFinite(threshold))vals.push(threshold);
   let lo=Math.min(...vals),hi=Math.max(...vals);const pad=Math.max(unit==='%'?.02:2,(hi-lo)*.1);lo-=pad;hi+=pad;
   if(unit==='%')lo=0;
   const x=v=>48+v/points.at(-1).x*485,y=v=>132-(v-lo)/(hi-lo)*104;
   const grid=Array.from({length:3},(_,i)=>{const v=lo+(hi-lo)*i/2;return `<line x1="48" x2="533" y1="${y(v)}" y2="${y(v)}"/><text x="4" y="${y(v)+4}">${num(v,unit==='%'?2:0)}</text>`;}).join('');
   const path=points.map((p,i)=>(i?'L':'M')+x(p.x)+','+y(p[yKey])).join(' ');
   return `<figure><figcaption>${esc(title)} <span>${esc(unit)}</span></figcaption><svg viewBox="0 0 560 167" role="img" aria-label="${esc(title)}">${grid}${Number.isFinite(threshold)?`<path d="M48 ${y(threshold)}H533" stroke="#efa94f" stroke-dasharray="5 5" fill="none"/>`:''}<path d="${path}" fill="none" stroke="${color}" stroke-width="2.5"/><text x="48" y="158">Now</text><text x="533" y="158" text-anchor="end">${esc(xEnd)}</text></svg></figure>`;
 }
 function paint(r){
   result=r;
   $('life-source').textContent=(r.source_status==='cached'?'Last readings':r.mode==='prototype'?'Prototype inputs':'Industrial inputs')+' · scenario estimates';
   $('life-assumptions').querySelector('summary').textContent=r.assumption_origin?.startsWith('Explicit')?'Independent scenario overrides':'Model assumptions · inherited thermal defaults';
   $('life-condition').textContent=r.condition_score==null?'—':num(r.condition_score,0)+'/100';
   $('life-limit').textContent=r.limit_state==='already_reached'?'Reached':r.limit_state==='crossing'?num(r.minutes_to_limit)+' min':r.limit_state==='no_crossing'?'No crossing':r.limit_state==='beyond_horizon'?'>4 h':'—';
   $('life-limit-note').textContent=num(r.assumptions.limit_temperature_c)+' °C · 4-hour horizon';
   $('life-remaining').textContent=r.life_state==='beyond_horizon'?'>50 yr':r.remaining_life_years==null?'—':r.remaining_life_years<1?num(r.remaining_life_years*12)+' mo':num(r.remaining_life_years)+' yr';
   $('life-risk').textContent=r.failure_probability==null?'—':r.failure_probability>0&&r.failure_probability<.0001?'<0.01%':num(r.failure_probability*100,2)+'%';
   $('life-risk-note').textContent='Next '+r.risk_horizon_days+' days · thermal ageing';
   $('life-status').textContent=r.reasons.join(' ')||(r.source_status==='cached'?'Based on cached readings from '+new Date(r.basis_timestamp).toLocaleString()+'.':r.observations?.skipped_gap_seconds?'Data gaps excluded from accumulated ageing.':'');
   const risk=r.risk_curve.map(p=>({x:p.days,value:100*p.probability})),thermal=r.temperature_curve.map(p=>({x:p.minute,value:p.temperature_c}));
   $('life-charts').innerHTML=graph(thermal,'value','Temperature forecast','°C','4 hours','#59d8c5',r.assumptions.limit_temperature_c)+graph(risk,'value','Simulated cumulative risk','%',risk.length?num(risk.at(-1).x/365.25)+' years':'','#a9bfef');
   const o=r.observations;
   $('life-basis').textContent=(o?`${o.samples} samples · ${num(o.integrated_seconds/60)} min integrated · ${num(o.observed_equivalent_age_hours,4)} equivalent hours accumulated. `:'')+`Current reference ${num(r.assumptions.rated_current_a,3)} A; voltage reference ${num(r.assumptions.nominal_voltage_v)} V. `+r.temperature_basis+'. '+(r.current_sources?.join(', ')||'')+'. '+`Ageing rate floor ${r.assumptions.minimum_ageing_rate}×; cap 1024×. `+r.coverage_note+' '+r.life_definition;
   $('life-components').innerHTML=Object.entries(r.condition_components).map(([k,v])=>`<div><span>${esc(k)} · ${num(v.weight*100,0)}% weight</span><strong>${num(v.stress,0)} / 100 stress</strong></div>`).join('');
 }
 async function update(force=false){
   if(!state?.snapshot||state.replay)return;
   if(inflight){queued=true;return;}
   const physical=state.mode==='prototype',s=state.snapshot;
   const body={revision:physical?null:s.revision,assumptions:parameters};
   if(physical){body.display_current=HaloOperations.displaySnapshot();body.display_history=HaloOperations.displayHistory();}
   const signature=JSON.stringify([key,s.revision,body.display_current?.boot_id,body.display_current?.sequence,body.display_current?.live,parameters]);
   if(!force&&signature===lastSignature)return;
   const request=version;inflight=true;
   try{
     const r=await HaloWorkspace.api('/twin/lifetime/'+encodeURIComponent(physical?'BENCH-001':s.id),body);
     if(request!==version)return;
     lastSignature=signature;if(!parameters){parameters=r.assumptions;fill();}
     paint(r);
   }catch(error){if(request===version){clear();$('life-status').textContent=error.message;}}
   finally{inflight=false;if(queued){queued=false;update(true);}}
 }
 window.addEventListener('halo:operation-state',e=>{
   state=e.detail;panel.hidden=!state.snapshot||state.replay;if(panel.hidden)return;
   const next=state.mode+':'+state.snapshot.id;
   if(next!==key){key=next;version++;lastSignature=null;parameters=null;clear();$('life-fields').replaceChildren();
     try{parameters=JSON.parse(localStorage.getItem('halo-life:'+key)||'null');}catch{}fill();
   }
   clearTimeout(timer);timer=setTimeout(()=>update(),250);
 });
 $('life-form').onsubmit=e=>{e.preventDefault();if(!parameters)return;parameters={...parameters,...Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)]))};version++;lastSignature=null;persist();clear();update(true);};
 $('life-reset').onclick=()=>{parameters=null;version++;lastSignature=null;persist();$('life-fields').replaceChildren();clear();update(true);};
 window.HaloLifetime={parameters:()=>parameters?structuredClone(parameters):null,result:()=>result?structuredClone(result):null};
})();
