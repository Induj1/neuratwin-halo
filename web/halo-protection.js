/* Read-only studies and recorded maintenance. Never calls a hardware command route. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),analysis=$('cc-analysis');if(!analysis)return;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=(v,n=1)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:n}):'—';
 const make=(id,html)=>{const e=document.createElement('section');e.id=id;e.className='pr-panel';e.innerHTML=html;return e;};
 const electric=make('pr-electrical',`<div class="pr-heading"><h2>Electrical protection study</h2><button id="pr-job-create">Create job card</button></div>
 <div id="pr-event-state" class="pr-event-state" role="status"><strong>Waiting for source</strong></div>
 <div class="pr-metrics" id="pr-electrical-values"></div><div class="pr-traces" id="pr-traces"></div>
 <div class="pr-actions"><button data-pr-exercise="overload">Simulate overload</button><button data-pr-exercise="short">Simulate short circuit</button><button data-pr-exercise="recovery">Simulate restored supply</button><button data-pr-exercise="none">Clear exercise</button></div>
 <p id="pr-electrical-basis"></p><details class="pr-detail"><summary>Detection & calculation settings</summary>
 <form id="pr-settings"><div class="pr-fields">
 <label>Overload pickup · × rated<input name="overload_pickup_pu" type="number" min="1.01" max="3" step=".01" value="1.1" required></label>
 <label>Overload persistence · s<input name="overload_delay_s" type="number" min="0" max="300" step=".1" value="5" required></label>
 <label>Fault pickup · × rated<input name="fault_pickup_pu" type="number" min="2" max="20" step=".1" value="5" required></label>
 <label>Voltage dip · per unit<input name="voltage_dip_pu" type="number" min=".01" max=".99" step=".01" value=".7" required></label>
 <label>Fault persistence · s<input name="fault_delay_s" type="number" min=".01" max="10" step=".01" value=".1" required></label>
 <label>Startup guard · s<input name="startup_guard_s" type="number" min="0" max="30" step=".1" value="3" required></label>
 <label>Declared impedance · %<input name="impedance_percent" type="number" min=".1" max="100" step=".1" placeholder="Not established"></label>
 <label>Winding resistance · Ω<input name="winding_resistance_ohm" type="number" min=".001" max="10000" step="any" placeholder="Not established"></label>
 </div><button type="submit">Apply study settings</button></form></details>`);
 analysis.querySelector('.cc-fault-panel').after(electric);
 const oil=make('pr-oil',`<div class="pr-heading"><h2>Oil inventory</h2><span>Simulated · litres at 25 °C</span></div>
 <div class="pr-metrics" id="pr-oil-values"></div><div id="pr-oil-trend" class="pr-traces"></div>
 <div class="pr-actions"><button id="pr-leak-slow">Slow loss · 0.12 L/min</button><button id="pr-leak-fast">Rapid leak · 2 L/min</button><button id="pr-leak-stop">Stop leak</button></div>
 <form id="pr-refill" class="pr-inline"><label>Refill · L<input name="litres" type="number" min=".1" max="5000" step=".1" value="30" required></label><button>Record simulated refill</button></form>
 <details class="pr-detail"><summary>Inventory & thermal assumptions</summary><form id="pr-oil-settings"><div class="pr-fields">
 <label>Warning inventory · %<input name="oil_warning_percent" type="number" min="1" max="100" value="95" required></label>
 <label>Critical inventory · %<input name="oil_critical_percent" type="number" min="1" max="99" value="90" required></label>
 <label>Oil density · kg/L<input name="oil_density_kg_l" type="number" min=".5" max="1.5" step=".01" value=".87" required></label>
 <label>Oil specific heat · kJ/kg K<input name="oil_cp_kj_kg_k" type="number" min=".5" max="5" step=".1" value="1.9" required></label>
 <label>Solid thermal capacity · kJ/K<input name="solid_capacity_kj_k" type="number" min="1" max="100000" value="80" required></label>
 </div><button>Apply assumptions</button></form></details><p id="pr-oil-note"></p></section>`);
 electric.after(oil);
 const calculations=make('pr-calculations','<h2>Calculations</h2><div id="pr-formulas"></div>');oil.after(calculations);
 const overview=document.createElement('div');overview.id='pr-inventory';overview.className='pr-inventory';$('px-level-fill').closest('.px-level').after(overview);
 const jobs=make('pr-jobs',`<div class="pr-heading"><h2>Protection job cards</h2><button id="pr-jobs-refresh">Refresh</button></div><div id="pr-job-list" class="pr-job-list"></div>
 <div id="pr-job-detail" hidden><h3 id="pr-job-title"></h3><p id="pr-job-source"></p><div id="pr-job-evidence" class="pr-metrics"></div>
 <form id="pr-job-form"><label>Technician finding / corrective action<textarea name="note" minlength="3" maxlength="2000" required></textarea></label><div class="pr-actions"><button name="operation" value="finding">Save finding</button><button name="operation" value="action">Record corrective action</button><button name="operation" value="verify">Compare follow-up</button><button type="button" id="pr-job-pdf">Export job PDF</button></div></form><div id="pr-job-trail"></div><p id="pr-job-verification"></p></div><p id="pr-job-message" role="status"></p>`);
 $('cc-maintenance-heading').after(jobs);
 const message=document.createElement('p');message.id='pr-message';message.setAttribute('role','status');electric.append(message);
 let latest=null,state=null,asset=null,records=[],selected=null,epoch=0,working=false,lastHash='';
 const metrics=entries=>entries.map(([name,value])=>`<div><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`).join('');
 function trace(rows,key,label,unit,xkey='seconds',limit=null){
  const points=rows.filter(v=>Number.isFinite(v[key])&&(v.valid!==false||xkey==='minute')),values=points.map(v=>v[key]);
  if(!points.length)return `<div class="pr-trace"><h3>${esc(label)}</h3><p>No qualified samples</p></div>`;
  const low=Math.min(0,...values),high=Math.max(1,...values,limit??0)*1.1,end=Math.max(1,...rows.map(r=>r[xkey]??0));
  const x=v=>60+v/end*470,y=v=>157-(v-low)/(high-low)*117;
  let pen=false;const path=rows.map(v=>{if(!Number.isFinite(v[key])||v.valid===false&&xkey!=='minute'){pen=false;return '';}if(v.gap_before)pen=false;const part=(pen?'L':'M')+x(v[xkey])+','+y(v[key]);pen=true;return part;}).join(' ');
  return `<div class="pr-trace"><h3>${esc(label)} <span>${esc(unit)}</span></h3><svg viewBox="0 0 550 205" role="img" aria-label="${esc(label)}"><path class="pr-grid" d="M60 40H530M60 98H530M60 157H530"/><text x="5" y="45">${fmt(high,0)}</text><text x="5" y="160">${fmt(low,0)}</text>${Number.isFinite(limit)?`<path class="pr-limit" d="M60 ${y(limit)}H530"/>`:''}<path class="pr-line" d="${path}"/><text x="60" y="190">0</text><text x="530" y="190" text-anchor="end">${fmt(end)} ${xkey==='minute'?'model min':'s'}</text></svg></div>`;
 }
 function draw(){const r=latest,e=r?.electrical,p=r?.settings||{};
  $('pr-event-state').dataset.level=e?.severity||'unavailable';$('pr-event-state').innerHTML=`<strong>${esc(e?.label||'Waiting for source')}</strong><span>${esc(e?.source||'')}</span>`;
  $('pr-electrical-values').innerHTML=metrics([['Study current',fmt(e?.current_a,3)+' A'],['Rated current',fmt(e?.rated_current_a,2)+' A'],['Event peak',fmt(e?.peak_a,2)+' A'],['Current² exposure',fmt(e?.i2t_a2s,2)+' A²s']]);
  $('pr-electrical-basis').textContent=(e?.reason||'Waiting for source')+(e?.simulated?' Simulated isolation sends no board command.':'');
  $('pr-job-create').disabled=working||!r||!!state?.replay||!(e?.severity==='critical'||e?.severity==='warning'||r.stage==='trip'||r.stage==='warning'||r.missing_l>0||r.loss_rate_l_min>0);
  for(const button of electric.querySelectorAll('[data-pr-exercise]')){button.disabled=!!state?.replay||!state?.snapshot;button.setAttribute('aria-pressed',String((HaloPhysics.options().electrical?.kind||'none')===button.dataset.prExercise));}
  const hash=r?.input_sha256;if(hash!==lastHash){lastHash=hash;
   $('pr-traces').innerHTML=trace(e?.trace||[],'current_a','Current','A','seconds',e?.rated_current_a)+trace(e?.trace||[],'voltage_v','Voltage','V')+trace(e?.trace||[],'i2t_a2s','Exposure','A²s');
   $('pr-oil-trend').innerHTML=trace(r?.curves||[],'inventory_l','Remaining oil forecast','L','minute',r?.oil_limit_l);
   const open=new Set([...$('pr-formulas').querySelectorAll('details[open]')].map(d=>d.dataset.formula));
   $('pr-formulas').innerHTML=(r?.calculations||[]).map((c,i)=>`<details class="pr-detail" data-formula="${i}" ${open.has(String(i))?'open':''}><summary>${esc(c.title)}</summary><div class="pr-equation">${esc(c.equation)}</div><p class="pr-substitution">${esc(c.substitution)}</p><p>${esc(c.basis)}</p></details>`).join('');
  }
  $('pr-oil-values').innerHTML=metrics([['Remaining',fmt(r?.inventory_l)+' / '+fmt(p.oil_litres,0)+' L'],['Oil lost',fmt(r?.oil_balance?.lost_total_l)+' L'],['Loss rate',fmt(r?.loss_rate_l_min,2)+' L/min'],['Time to critical',!r?.available?'—':r.oil_time_to_limit_min===0?'Limit reached':r.oil_time_to_limit_min==null?'No ongoing loss':fmt(r.oil_time_to_limit_min)+' model min'],['Expanded volume',fmt(r?.expanded_volume_l)+' L'],['Thermal capacity',fmt(r?.effective_capacity_kj_k)+' kJ/K']]);
  overview.innerHTML=`<strong>${fmt(r?.inventory_l)} / ${fmt(p.oil_litres,0)} L</strong><span>${fmt(r?.inventory_percent)}% remaining · ${fmt(r?.missing_l)} L missing</span><button id="pr-oil-open">Inventory & calculations</button>`;
  $('pr-oil-open').onclick=()=>{HaloControlCentre.select('analysis');oil.scrollIntoView({block:'start',behavior:'smooth'});};
  $('pr-oil-note').textContent='Model inventory at 25 °C. Stop leak preserves lost oil; refill adds only the recorded amount. Demo limits: '+fmt(p.oil_warning_percent,0)+'% warning / '+fmt(p.oil_critical_percent,0)+'% critical.';
  const available=r?.available&&!state?.replay;for(const id of ['pr-leak-slow','pr-leak-fast'])$(id).disabled=!available;
  $('pr-leak-stop').disabled=!available||!(r?.loss_rate_l_min>0);$('pr-refill').querySelector('button').disabled=!available||!(r?.missing_l>0);
 }
 async function run(fn){if(working)return;working=true;draw();$('pr-message').textContent='';$('pr-job-message').textContent='';try{await fn();}catch(e){$('pr-message').textContent=e.message;$('pr-job-message').textContent=e.message;}finally{working=false;draw();}}
 const path=()=>'/twin/protection-jobs/'+encodeURIComponent(asset);
 async function loadJobs(){if(!asset)return;const token=epoch;try{const data=await HaloWorkspace.api(path());if(token!==epoch)return;records=data;if(selected)selected=records.find(j=>j.id===selected.id)||null;renderJobs();}catch(e){if(token===epoch)$('pr-job-message').textContent=e.message;}}
 function renderJobs(){
  $('pr-job-list').innerHTML=records.length?records.map(j=>`<button data-job="${esc(j.id)}" aria-pressed="${j.id===selected?.id}"><strong>${esc(j.title)}</strong><span>${esc(j.status.replaceAll('_',' '))} · ${esc(new Date(j.created_at).toLocaleString())}</span></button>`).join(''):'<p>No protection jobs for this asset.</p>';
  $('pr-job-list').querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>{selected=records.find(j=>j.id===b.dataset.job);$('pr-job-form').reset();renderJobs();});
  $('pr-job-detail').hidden=!selected;if(!selected)return;
  const r=selected.study;$('pr-job-title').textContent=selected.title;$('pr-job-source').textContent=(r.simulated_inputs?'Simulated oil inputs':r.mode==='industrial'?'Industrial simulation':'Prototype-driven model')+' · '+r.electrical.source+' · frozen '+new Date(selected.created_at).toLocaleString();
  $('pr-job-evidence').innerHTML=metrics([['Oil at event',fmt(r.inventory_l)+' L'],['Current basis',r.current_source||'Unavailable'],['Electrical event',r.electrical.label],['Event peak',fmt(r.electrical.peak_a)+' A']]);
  $('pr-job-trail').innerHTML=selected.trail.map(t=>`<div class="pr-trail"><strong>${esc(t.operation.replaceAll('_',' '))}</strong><span>${esc(new Date(t.at).toLocaleString())}</span><p>${esc(t.note)}</p></div>`).join('');
  const v=selected.verification;$('pr-job-verification').textContent=v?`${v.outcome.replaceAll('_',' ')} · oil ${fmt(v.before_oil_l)} → ${fmt(v.after_oil_l)} L. ${v.note}`:'Record findings, then the corrective action, then compare a newer follow-up.';
 }
 electric.querySelectorAll('[data-pr-exercise]').forEach(b=>b.onclick=()=>HaloPhysics.exercise(b.dataset.prExercise));
 $('pr-leak-slow').onclick=()=>run(()=>HaloPhysics.oilAction('leak',.12));$('pr-leak-fast').onclick=()=>run(()=>HaloPhysics.oilAction('leak',2));$('pr-leak-stop').onclick=()=>run(()=>HaloPhysics.oilAction('stop'));
 $('pr-refill').onsubmit=e=>{e.preventDefault();run(()=>HaloPhysics.oilAction('refill',Number(e.target.elements.litres.value)));};
 for(const id of ['pr-settings','pr-oil-settings'])$(id).onsubmit=e=>{e.preventDefault();const fields=Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,v===''?null:Number(v)]));const p={...HaloPhysics.options().settings,...fields};if(p.oil_critical_percent>=p.oil_warning_percent||p.fault_pickup_pu<=p.overload_pickup_pu){$('pr-message').textContent='Critical oil inventory must be lower than warning; fault pickup must exceed overload pickup.';return;}HaloPhysics.configure({settings:p});};
 $('pr-job-create').onclick=()=>run(async()=>{const token=epoch;const j=await HaloWorkspace.api(path(),{...HaloPhysics.context(),request_id:crypto.randomUUID()});if(token!==epoch)return;records=[j,...records.filter(v=>v.id!==j.id)];selected=j;renderJobs();HaloWorkspace.view('maintenance');jobs.scrollIntoView({block:'start'});});
 $('pr-jobs-refresh').onclick=()=>run(loadJobs);
 $('pr-job-form').onsubmit=e=>{e.preventDefault();const operation=e.submitter?.value;if(!operation||!selected)return;run(async()=>{const token=epoch,j=await HaloWorkspace.api(path()+'/'+encodeURIComponent(selected.id),{...HaloPhysics.context(),job_revision:selected.revision,operation,note:$('pr-job-form').elements.note.value});if(token!==epoch)return;selected=j;records=records.map(v=>v.id===j.id?j:v);renderJobs();$('pr-job-form').reset();});};
 $('pr-job-pdf').onclick=()=>run(async()=>{if(!selected)return;const response=await HaloAuth.fetch('/api/halo'+path()+'/'+encodeURIComponent(selected.id)+'/report.pdf');if(!response.ok)throw Error('Job report unavailable');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='neuratwin-protection-job.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 function sync(next){state=next;const id=state?.snapshot?(state.mode==='prototype'?'BENCH-001':state.snapshot.id):null;if(id!==asset){asset=id;epoch++;records=[];selected=null;renderJobs();loadJobs();}}
 window.addEventListener('halo:operation-state',e=>sync(e.detail));window.addEventListener('halo:physics',e=>{sync(e.detail.state);latest=e.detail.result;draw();});
 window.addEventListener('halo:view',e=>{if(e.detail==='maintenance')loadJobs();});
 sync(HaloOperations.current());latest=HaloPhysics.result();draw();
})();
