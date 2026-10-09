/* Imported records keep their own asset, assessment and maintenance evidence. */
(()=>{'use strict';
const H=window.HaloWorkspace,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const input=(label,name,value='',type='text',attrs='')=>`<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${attrs}></label>`;
const note=(label='Evidence / review note')=>`<label>${label}<textarea name="note" minlength="10" maxlength="1500" required></textarea></label>`;
const iso=value=>{const d=new Date(value);if(!value||!Number.isFinite(d.getTime()))throw Error('Enter the actual date and time for this recording or action.');return d.toISOString();};
const endpoint=id=>'/twin/challenges/'+encodeURIComponent(id);
const label=s=>String(s||'unknown').replaceAll('_',' ');
let epoch=0;
// Keep the last intent for each form across retries and panel remounts. A lost
// response must not turn the same submitted evidence into a second write.
const attempts=new Map();
function panel(){return '<section class="case-panel evidence-workflow" id="case-reference-workflow" aria-label="Imported recording maintenance"><p role="status">Loading recording-linked maintenance…</p></section>';}
async function downloadRaw(path,filename,stillCurrent=()=>true){
 // Paths are relative to /api/halo. Preserve the server's bytes: JavaScript
 // turns 10.0 into 10 on re-serialization, breaking recorded Python hashes.
 if(!stillCurrent())return;
 const response=await window.HaloAuth.fetch('/api/halo'+path,{method:'GET',cache:'no-store'});
 if(!stillCurrent())return;
 if(!response.ok){const data=await response.json().catch(()=>({}));throw Error(response.status>=500?'The workspace service is temporarily unavailable. Please try again.':typeof data.detail==='string'?data.detail:'Evidence export is unavailable. Check your access and the recording state.');}
 const blob=await response.blob();if(!stillCurrent())return;
 const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
async function mount({record,onCase}){
 const host=document.getElementById('case-reference-workflow');if(!host)return;
 const token=++epoch;let workflow=null,cases=[],busy=false;
 const disabledBefore=new Map();
 const alive=()=>epoch===token&&host.isConnected;
 const request=async(path,body)=>{if(!alive())throw Error('This recording view has changed.');const result=await H.api(path,body);if(!alive())throw Error('This recording view has changed.');return result;};
 function lockControls(){host.querySelectorAll('button,input,select,textarea').forEach(el=>{if(!disabledBefore.has(el))disabledBefore.set(el,el.disabled);el.disabled=true;});}
 function unlockControls(){for(const [el,disabled] of disabledBefore)if(el.isConnected)el.disabled=disabled;disabledBefore.clear();}
 function intent(el,stage,payload){
  const formKey=el.id||['referenceObservation','referenceFollowup','referenceClose','referenceImport'].map(k=>el.dataset[k]?k+':'+el.dataset[k]:'').find(Boolean);
  const key=[record.id,formKey,stage].join('/'),fingerprint=JSON.stringify(payload);let state=attempts.get(key);
  if(!state||state.fingerprint!==fingerprint){state={fingerprint,id:crypto.randomUUID()};attempts.set(key,state);}return state;
 }
 const submit=(el,stage,path,payload)=>request(path,{request_id:intent(el,stage,payload).id,...payload});
 async function refresh(){
  const results=await Promise.all([request('/twin/challenges'),record?.source==='imported reference'?request(endpoint(record.id)+'/workflow'):Promise.resolve(null)]);
  if(!alive())return;cases=results[0].cases;workflow=results[1];paint();
 }
 async function task(fn){if(busy||!alive())return;busy=true;lockControls();const status=host.querySelector('[data-reference-status]');if(status)status.textContent='Saving reviewed evidence…';
  try{await fn();if(alive())await refresh();}catch(e){if(alive()){const currentStatus=host.querySelector('[data-reference-status]');if(currentStatus)currentStatus.textContent=e.message||'Evidence could not be saved. Retry the same form or refresh and review the record.';}}finally{busy=false;if(alive())unlockControls();else disabledBefore.clear();}
 }
 const button=(text,action,blocked=false)=>`<button type="button" data-reference-action="${action}" ${blocked?'disabled data-blocked="true"':''}>${text}</button>`;
 function rules(w){const a=w.acceptance_rules;return `${a.stable_minutes} stable min · oil ≤ ${a.max_oil_c} °C · load ≤ ${a.max_load_percent}% · oil decrease ≥ ${a.min_oil_drop_c} °C. Comparison: load within ${a.max_load_difference_pct} percentage points, ambient within ${a.max_ambient_difference_c} °C, voltage within ${a.max_voltage_difference_pu} pu.`;}
 function workCard(w){
  const closed=w.status==='closed_reference_review',inspected=w.trail.some(t=>t.kind==='inspection'),acted=w.trail.some(t=>t.kind==='action');
  const linked=new Set(w.followups.map(f=>f.case_id));
  const eligible=cases.filter(c=>c.source==='imported reference'&&c.id!==record.id&&!linked.has(c.id)&&c.assessed&&c.asset_id===w.asset_id&&c.source_class===w.source_class);
  return `<article class="case-record" data-reference-work="${esc(w.id)}"><span class="case-state">${esc(label(w.status))} · ${esc(w.priority)}</span><h3>${esc(w.title)}</h3><p>Owner: ${esc(w.owner)} · ${esc(w.asset_id)} · ${esc(label(w.source_class))}</p><p>${esc(w.acceptance_note)}</p><details><summary>Recorded acceptance criteria</summary><p>${esc(rules(w))}</p><p>Operator-declared review criteria, not manufacturer limits.</p></details>
   ${w.trail.map(t=>`<p class="evidence-trail"><strong>${esc(label(t.kind))}</strong> · ${esc(new Date(t.observed_at).toLocaleString())}<br>${esc(t.note)}</p>`).join('')}
   ${w.followups.map(f=>`<p class="evidence-trail"><strong>Follow-up recording</strong> · ${esc(cases.find(c=>c.id===f.case_id)?.name||f.case_id)}<br>${esc(f.note)}</p>`).join('')}
   ${Number.isFinite(w.verification.metrics?.origin_mean_oil_c)?`<div class="case-kpis"><div><span>Origin mean oil</span><strong>${Number(w.verification.metrics.origin_mean_oil_c).toFixed(1)} °C</strong></div><div><span>Follow-up mean oil</span><strong>${Number(w.verification.metrics.followup_mean_oil_c).toFixed(1)} °C</strong></div><div><span>Oil change</span><strong>${Number(w.verification.metrics.oil_drop_c).toFixed(1)} °C decrease</strong></div></div>`:''}
   ${closed?'<p class="case-alert">Reference review closed. This record does not certify a physical repair.</p>':`${w.verification.holds.length?`<div class="case-alert"><strong>Acceptance still requires</strong><ul>${w.verification.holds.map(h=>`<li>${esc(h)}</li>`).join('')}</ul></div>`:'<p class="case-state">The later recording meets the declared reference-review criteria.</p>'}
   ${!acted?`<form class="case-form" data-reference-observation="${esc(w.id)}"><h4>${inspected?'Record the action':'Record the inspection'}</h4>${input('Actual observation time · your local timezone','observed_at','','datetime-local','required step="1"')}${note(inspected?'Action taken and supporting evidence':'Inspection findings and supporting evidence')}<button>${inspected?'Record action':'Record inspection'}</button></form>`:`<details><summary>Attach later evidence</summary><form class="case-form" data-reference-followup="${esc(w.id)}"><label>Frozen recording for the same asset<select name="case_id" required><option value="">Select a follow-up recording</option>${eligible.map(c=>`<option value="${esc(c.id)}">${esc(c.name)} · ${c.revealed?'revealed':'frozen'}</option>`).join('')}</select></label>${note('Why this recording is comparable')}<button ${eligible.length?'':'disabled data-blocked="true"'}>Link follow-up</button></form>
   <form class="case-form evidence-followup-import" data-reference-import="${esc(w.id)}"><h4>Or import a follow-up CSV</h4><p>Same oil-channel format and temperature capability as the origin. The first 70 rows must be a reviewed healthy reference.</p><label>Follow-up CSV<input name="recording" type="file" accept=".csv,text/csv" required></label>${input('Recording name','name','','text','required minlength="3" maxlength="120"')}${input('Recording start · your local timezone','recording_started_at','','datetime-local','required step="1"')}${input('Assessment origin · zero-based row','origin',90,'number','required min="70" max="4998"')}${note('Follow-up source and observations')}<label><input type="checkbox" name="reviewed" required> I reviewed the healthy prefix and confirm the same asset, units, calibration and configuration references.</label><button>Import, freeze assessment & link</button></form></details>`}
   <form class="case-form" data-reference-close="${esc(w.id)}">${note('Final review conclusion')}<button ${w.verification.eligible?'':'disabled data-blocked="true"'}>Close reference review</button><small>This closes the evidence review only. Physical repair verification remains unavailable.</small></form>`}</article>`;
 }
 function paint(){
  if(!alive())return;
  const binding=workflow?.binding,meta=binding?.provenance;
  host.innerHTML=`<p class="eyebrow">RECORDING → FINDING → ACTION → LATER EVIDENCE</p><h2>Follow this finding through maintenance.</h2><p>This record has its own asset and source. It is separate from the selected industrial simulation.</p><div class="case-actions"><label>Imported recording<select data-reference-select><option value="">Choose a saved recording</option>${cases.filter(c=>c.source==='imported reference').map(c=>`<option value="${esc(c.id)}" ${c.id===record?.id?'selected':''}>${esc(c.name)} · ${esc(c.asset_id||'unbound')}</option>`).join('')}</select></label>${button('Refresh records','refresh')}${workflow?button('Reveal recordings for export','reveal')+button('Download evidence chain','export'):''}</div><p data-reference-status role="status" class="case-muted"></p>`+
  (!workflow?'<p>Import an oil-temperature CSV in Evidence, or choose a previously imported recording. Concealed synthetic challenges retain their separate assessment workflow.</p>':
   `<p class="evidence-source"><strong>${esc(record.name)}</strong> · ${esc(meta?.asset_id||'Asset not bound')} · ${esc(label(meta?.source_class))} reference</p>`+
   (!binding?`<form class="case-form" id="reference-bind"><h3>Bind the source once</h3><p>Keep unknown details unverified. This metadata cannot be silently changed after binding.</p><div class="case-columns">${input('Asset ID','asset_id','','text','required pattern="[A-Za-z0-9_-]{1,80}"')}<label>Declared source<select name="source_class"><option value="unknown">Unknown / not verified</option><option value="synthetic">Synthetic reference</option><option value="recorded_oil_reference">Recorded oil reference</option></select></label>${input('Reviewer','reviewer','','text','required minlength="2"')}${input('Recording start · local time, if known','recording_started_at','','datetime-local','step="1"')}${input('Calibration / source-scale reference','calibration_reference')}${input('Transformer configuration reference','configuration_reference')}</div><label><input name="units_verified" type="checkbox"> Units reviewed: seconds, °C, load %, voltage pu</label><label><input name="calibration_reviewed" type="checkbox"> Calibration/source-scale reference reviewed</label><label><input name="configuration_reviewed" type="checkbox"> Configuration reference reviewed</label>${note('Source description and review note')}<button>Bind recording provenance</button></form>`:
    `<details><summary>Immutable source binding</summary><p>Reviewer: ${esc(meta.reviewer)} · start ${esc(meta.recording_started_at||'unknown')}</p><p>Calibration: ${esc(meta.calibration_reference||'unknown')} (${meta.calibration_reviewed?'reviewed':'unverified'}) · configuration: ${esc(meta.configuration_reference||'unknown')} (${meta.configuration_reviewed?'reviewed':'unverified'}).</p><p>${esc(meta.note)}</p><code>${esc(binding.sha256)}</code><p>${esc(binding.review_scope)}</p></details>`)+
   (!record.assessment?`<p>Freeze this recording’s observation assessment before creating a work order.</p>${button('Freeze this recording assessment','assess')}`:binding?`<details class="evidence-new-work"><summary>Create a recording-linked work order</summary><form class="case-form" id="reference-create"><div class="case-columns">${input('Action / investigation','title','','text','required minlength="5" maxlength="180"')}${input('Owner / reviewer','owner','','text','required minlength="2"')}<label>Priority<select name="priority"><option value="soon">Soon</option><option value="urgent">Urgent</option><option value="routine">Routine</option></select></label></div><label>Acceptance note<textarea name="acceptance_note" required minlength="15" maxlength="1500"></textarea></label><details open><summary>Declare acceptance before follow-up</summary><div class="case-columns">${input('Stable window · min','stable_minutes',10,'number','required min="5" max="30"')}${input('Maximum gap · seconds','max_gap_seconds',120,'number','required min="30" max="180"')}${input('Maximum load · %','max_load_percent',99,'number','required min="0" max="99.9" step=".1"')}${input('Maximum oil · °C','max_oil_c',90,'number','required min="20" max="120" step=".1"')}${input('Minimum oil decrease · °C','min_oil_drop_c',0,'number','required min="0" max="30" step=".1"')}${input('Load comparability · percentage points','max_load_difference_pct',5,'number','required min="0" max="10" step=".1"')}${input('Ambient comparability · °C','max_ambient_difference_c',3,'number','required min="0" max="5" step=".1"')}${input('Voltage comparability · pu','max_voltage_difference_pu',.02,'number','required min="0" max=".05" step=".001"')}</div><p>These are operator-declared review criteria. Confirm them for your experiment.</p></details><button>Create work order for this recording</button></form></details>`:'')+
   workflow.work_orders.map(workCard).join('')+`<p class="case-muted">${esc(workflow.limitations.join(' '))}</p>`);
  host.querySelector('[data-reference-select]').onchange=e=>{const id=e.target.value;if(id)task(async()=>{const selected=await request(endpoint(id));if(alive())onCase(selected);});};
  host.querySelectorAll('[data-reference-action]').forEach(b=>b.onclick=()=>task(async()=>{
   if(b.dataset.referenceAction==='assess'){const assessed=await request(endpoint(record.id)+'/assess',{});if(alive())onCase(assessed);return;}
   if(b.dataset.referenceAction==='reveal'){const ids=[record.id,...new Set(workflow.work_orders.flatMap(w=>w.followups.map(f=>f.case_id)))];for(const id of ids)await request(endpoint(id)+'/reveal',{});const revealed=await request(endpoint(record.id));if(alive())onCase(revealed);return;}
   if(b.dataset.referenceAction==='export')await downloadRaw(endpoint(record.id)+'/workflow/export','halo-recording-maintenance-evidence.json',alive);
  }));
  // Capture successful controls before task() disables them; disabled fields
  // are deliberately omitted by FormData in browsers.
  const form=(selector,fn)=>host.querySelectorAll(selector).forEach(f=>f.onsubmit=e=>{e.preventDefault();if(busy||!alive())return;const values=new FormData(f);task(()=>fn(values,f));});
  form('#reference-bind',async(f,el)=>{const provenance=Object.fromEntries(['asset_id','source_class','reviewer','note'].map(k=>[k,f.get(k)]));for(const k of ['units_verified','calibration_reviewed','configuration_reviewed'])provenance[k]=f.has(k);for(const k of ['calibration_reference','configuration_reference'])provenance[k]=f.get(k)||null;provenance.recording_started_at=f.get('recording_started_at')?iso(f.get('recording_started_at')):null;await submit(el,'bind',endpoint(record.id)+'/binding',{provenance});});
  form('#reference-create',async(f,el)=>{const acceptance_rules=Object.fromEntries(['stable_minutes','max_gap_seconds','max_load_percent','max_oil_c','min_oil_drop_c','max_load_difference_pct','max_ambient_difference_c','max_voltage_difference_pu'].map(k=>[k,Number(f.get(k))]));await submit(el,'create',endpoint(record.id)+'/work',{title:f.get('title'),owner:f.get('owner'),priority:f.get('priority'),acceptance_note:f.get('acceptance_note'),acceptance_rules});});
  const work=id=>workflow.work_orders.find(w=>w.id===id),body=(w,f)=>({revision:w.revision,note:f.get('note')}),route=w=>endpoint(record.id)+'/work/'+encodeURIComponent(w.id);
  form('[data-reference-observation]',async(f,el)=>{const w=work(el.dataset.referenceObservation);await submit(el,'observation',route(w)+'/observations',{...body(w,f),kind:w.trail.some(t=>t.kind==='inspection')?'action':'inspection',observed_at:iso(f.get('observed_at'))});});
  form('[data-reference-followup]',async(f,el)=>{const w=work(el.dataset.referenceFollowup);await submit(el,'followup',route(w)+'/followup',{...body(w,f),case_id:f.get('case_id')});});
  form('[data-reference-close]',async(f,el)=>{const w=work(el.dataset.referenceClose);await submit(el,'close',route(w)+'/close',body(w,f));});
  form('[data-reference-import]',async(f,el)=>{
   const w=work(el.dataset.referenceImport),file=f.get('recording');if(!file?.size||file.size>1000000)throw Error('Choose a CSV up to 1 MB.');
   const payload={temperature_mode:record.temperature_mode,csv_text:await file.text(),name:f.get('name'),origin_index:Number(f.get('origin')),healthy_reference_reviewed:f.has('reviewed'),provenance:{...meta,recording_started_at:iso(f.get('recording_started_at')),note:f.get('note')}};
   if(!alive())return;const state=intent(el,'import',payload);
   if(!state.created)state.created=await request('/twin/challenges/import',{request_id:state.id,...payload});
   if(!state.assessed){await request(endpoint(state.created.id)+'/assess',{});state.assessed=true;}
   await submit(el,'import-link',route(w)+'/followup',{...body(w,f),case_id:state.created.id});
  });
  if(busy)lockControls();
 }
 try{await refresh();}catch(e){if(alive())host.innerHTML=`<h2>Recording-linked maintenance unavailable</h2><p role="alert">${esc(e.message)}</p><p>The selected simulation and physical maintenance records are unchanged.</p>`;}
}
window.HaloEvidenceWorkflow={panel,mount,downloadRaw};
})();
