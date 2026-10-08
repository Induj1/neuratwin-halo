/* Two data sources, one view. Simulation commands cannot target physical relays. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), workspace=window.HaloWorkspace;
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,n=1)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:n});
  const title=s=>String(s).replaceAll('_',' ');
  let mode='industrial', run=null, current=null, busy=false, catalog=null, timer=null, ready=false, dirty=false, selectedScenario=null;
  let twin=null;
  function model(){if(!twin)twin=new HaloTwin($('op-twin'),part=>$('op-part').textContent=title(part));return twin;}
  function error(message){$('op-error').textContent=message||'';$('op-error').hidden=!message;}
  function list(id,items){$(id).innerHTML=items.map(x=>'<li>'+esc(x)+'</li>').join('');}
  function clock(seconds){const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=Math.floor(seconds%60);return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;}
  function buttons(){
    const physical=mode==='prototype',running=!!current?.running;
    $('op-start').textContent=running?'Pause simulation':'Start simulation';
    $('op-start').disabled=busy||!run;$('op-step').disabled=busy||!run||!running;
    $('op-report').disabled=busy||!run;$('op-trip').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-reconnect').disabled=busy||physical||!!current?.recovery_holds?.length;
    $('op-apply-scenario').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-new').disabled=busy||!ready;$('op-create').disabled=busy||!ready;
    $('op-industrial').disabled=busy||!ready;$('op-prototype').disabled=busy||!ready;
    document.querySelectorAll('#view-operate form button').forEach(b=>b.disabled=busy||!ready);
    $('op-clear').disabled=busy||!run;
    $('op-off').disabled=busy||current?.connection!=='live';
    $('op-running-note').textContent=running?'Running · accelerated clock; pauses ticking when this view is hidden.':'Paused · clock advances only when you run or step.';
  }
  async function act(action,extra={}){
    if(mode!=='industrial'||!run)throw Error('Create or select an industrial run first.');
    const latest=window.HaloSession?.run();if(latest?.id===run.id&&latest.revision>run.revision)run=latest;
    const r=await workspace.api(`/twin/runs/${encodeURIComponent(run.id)}/actions`,{action,revision:run.revision,request_id:crypto.randomUUID(),...extra});
    run=r;render(r);return r;
  }
  async function guarded(fn){
    if(busy)return;busy=true;buttons();error('');
    try{await fn();}catch(e){error(e.message);if(mode==='industrial'&&run&&e.status===409){try{run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}catch{}}}
    finally{busy=false;buttons();schedule();}
  }
  function click(id,fn){$(id).addEventListener('click',()=>guarded(fn));}
  function schedule(){
    clearTimeout(timer);
    if(!ready||document.hidden||!$('view-operate').classList.contains('active'))return;
    timer=setTimeout(()=>guarded(async()=>{
      if(mode==='prototype')render(await workspace.api('/twin/prototype'));
      else if(run?.running)await act('step',{seconds:run.inputs.speed});
    }),mode==='prototype'?2500:1500);
  }
  async function switchMode(next){
    if(busy||!ready)return;mode=next;dirty=false;error('');
    $('op-industrial').setAttribute('aria-pressed',String(mode==='industrial'));
    $('op-prototype').setAttribute('aria-pressed',String(mode==='prototype'));
    $('op-source').textContent=mode==='industrial'?'INDUSTRIAL SIMULATION':'PHYSICAL PROTOTYPE · ESP32';
    $('op-run-tools').hidden=mode==='prototype';$('op-prototype-refresh').hidden=mode!=='prototype';
    if(mode==='industrial')render(run);else{
      current=null;$('op-workspace').hidden=true;$('op-welcome').hidden=true;$('op-clock').textContent='Loading ESP32 measurements…';
      await guarded(async()=>render(await workspace.api('/twin/prototype')));
    }
    schedule();
  }
  function populateInputs(s){
    const form=$('op-inputs');
    for(const [k,v] of Object.entries(s.inputs)){const field=form.elements[k];if(!field)continue;if(field.type==='checkbox')field.checked=v;else field.value=typeof v==='number'?Math.round(v*100)/100:v;}
    $('op-load-output').value=fmt(s.inputs.load_percent,0)+'%';
  }
  function settingsFields(s){
    $('op-settings-fields').innerHTML=Object.entries(s.settings).map(([k,v])=>`<label>${esc(title(k))}<input type="number" step="any" name="${esc(k)}" value="${v}" required></label>`).join('');
  }
  function render(s){
    current=s;const physical=mode==='prototype';
    $('op-workspace').hidden=!s;$('op-welcome').hidden=!!s;
    if(!s){$('op-clock').textContent='Create or open a run';buttons();return;}
    if(!physical)window.HaloSession?.bind(s);
    const t=s.telemetry,a=s.analysis;
    if($('view-operate').classList.contains('active')){$('connection').textContent=physical?title(s.connection)+' · ESP32':'Industrial · simulated';$('connection').className='pill';}
    $('op-industrial-controls').hidden=physical;$('op-prototype-controls').hidden=!physical;
    $('op-maintenance').hidden=physical;$('op-maintenance-physical').hidden=!physical;
    $('op-source').textContent=physical?'PHYSICAL PROTOTYPE · ESP32':'INDUSTRIAL SIMULATION';
    $('op-clock').textContent=physical?(s.connection==='disconnected'?'No acquisition received':new Date(t.timestamp).toLocaleString()):`${clock(s.elapsed_s)} simulated · ${s.running?'running':'paused'}`;
    $('op-condition').textContent=physical?(s.latched?'TRIP DECISION LATCHED':a.status):(s.breaker==='OPEN'?'TRIPPED':a.status);$('op-condition').dataset.level=(!physical&&s.breaker==='OPEN')||s.latched?'TRIP':a.status;
    $('op-protection').textContent=s.protection_state;$('op-breaker').textContent=s.breaker;
    $('op-breaker-label').textContent=physical?'Contact feedback':'Simulated breaker';
    $('op-quality').textContent=physical?(t.quality==='qualified'?'Core channels calibrated':title(t.quality)):'Model-generated';
    $('op-asset').textContent=physical?s.id:`INDUSTRIAL · ${s.id.slice(-8).toUpperCase()}`;
    $('op-model-title').textContent=physical?'Physical transformer demonstrator':`${fmt(s.settings.rated_kva,0)} kVA distribution transformer`;
    $('op-model-note').textContent=physical?'Surface temperature · missing sensors remain unavailable':'Oil + winding thermal model · illustrative geometry';
    model().setDistribution(!physical);model().temperature(t.transformer_temperature,a.status==='NORMAL'?'normal':'critical');model().draw();
    $('op-flow-breaker').textContent=physical?'Contacts unverified':s.breaker==='OPEN'?'Breaker open':'Breaker closed';
    document.querySelector('#view-operate .op-flow').dataset.open=String(!physical&&s.breaker==='OPEN');
    $('op-health').textContent=fmt(a.health_index,1);$('op-health-band').textContent=physical?(a.health_index==null?'Insufficient evidence':a.status==='NORMAL'?'Screening estimate':a.status+' · review signals'):s.health_band;
    $('op-health-band').dataset.level=a.status;
    $('op-stress').innerHTML=Object.entries(a.stress).map(([k,v])=>`<div class="op-stress-row"><span>${esc(title(k))}</span><i><b style="width:${Math.max(0,Math.min(100,v))}%"></b></i><span>${fmt(v,0)}</span></div>`).join('');
    $('op-next-step').textContent=a.maintenance[0];$('op-prediction').textContent=physical?'Surface trends are interpreted only with fresh calibrated measurements.':s.prediction.minutes_to_critical==null?s.prediction.note:`Thermal critical threshold in approximately ${s.prediction.minutes_to_critical} simulated min if present conditions persist without protection.`;
    $('op-trip-box').hidden=physical?!s.latched:s.breaker!=='OPEN';
    $('op-trip-reason').textContent=s.trip?.reason||'No trip.';
    list('op-recovery-holds',physical?['Inspect the physical rig. GPIO acknowledgments do not verify contact opening.']:s.recovery_holds||[]);
    $('op-reconnect').hidden=physical;
    const primaryVerified=!physical||['primary_v','primary_current_a'].every(k=>s.evidence.some(e=>e.channel===k&&e.available&&e.calibrated));
    const readings=[['Primary',t.primary_voltage,'V',`Current ${fmt(t.primary_current,3)} A RMS${primaryVerified?'':' · incomplete / unverified'}`],
      ['Secondary',t.secondary_voltage,'V',`Current ${fmt(t.secondary_current,3)} A RMS`],
      [physical?'Surface temperature':'Modelled hot-spot',t.transformer_temperature,'°C',physical?`Ambient ${fmt(t.ambient_temperature)} °C`:`Top oil ${fmt(t.oil_temperature)} °C · ambient ${fmt(t.ambient_temperature)} °C`],
      ['Loading',t.loading_percent,'%',physical?'Relative to reviewed current limit':`Oil level ${fmt(t.oil_level_percent,0)}% · condition ${fmt(t.oil_condition,0)}/100`]];
    $('op-readings').innerHTML=readings.map(([label,v,unit,note])=>`<div class="op-reading"><span>${esc(label)}</span><strong>${fmt(v)} <small>${unit}</small></strong><p>${esc(note)}</p></div>`).join('');
    if(!physical){
      const scenarioKey=s.id+':'+s.scenario;
      if(selectedScenario!==scenarioKey){$('op-scenario').value=s.scenario;selectedScenario=scenarioKey;}
      const saved=[...$('op-run-select').options].find(o=>o.value===s.id);
      if(saved)saved.textContent=`${title(s.scenario)} · ${new Date(s.started_at).toLocaleString()} · ${s.breaker}`;
      if(!dirty)populateInputs(s);
      $('op-active-fault').textContent=s.fault?`${title(s.fault.kind)} active · ${fmt(Math.max(0,s.fault.until_s-s.elapsed_s),0)} simulated seconds remaining`:'No injected disturbance.';
      $('op-ageing').textContent=fmt(s.condition.equivalent_age_hours,2)+' equivalent hours';
      $('op-life').textContent=`${fmt(s.condition.insulation_consumed_percent,3)}% thermal budget used · ${s.condition.conditional_life_years>50?'>50 years · outside planning horizon':fmt(s.condition.conditional_life_years,1)+' conditional years'}`;
    }else{
      $('op-prototype-note').textContent=`${title(s.connection)} · ${s.control_enabled?'Automatic all-off requests armed':'Monitoring only; automatic cutoff is not enabled'}. Primary current needs its own calibrated sensor. Oil and winding temperature are unavailable.`;
      $('op-relays').innerHTML=[0,1,2,3].map(i=>`<div><strong>K${i+1}${i===3?' · locked':''}</strong><span>39 Ω / 10 W</span><p>${s.relay_states?(s.relay_states[i]?'GPIO reports ON':'GPIO reports OFF'):'State unavailable'}</p><button data-op-relay="${i}" ${i===3||!s.load_control_available||busy?'disabled':''}>${s.relay_states?.[i]?'Request OFF':'Request ON'}</button></div>`).join('');
      $('op-relays').querySelectorAll('button').forEach(b=>b.onclick=()=>guarded(async()=>{const states=[...current.relay_states];states[Number(b.dataset.opRelay)]=!states[Number(b.dataset.opRelay)];await physicalRelays(states);}));
      $('op-command-status').textContent=s.command?.status?`Last cutoff command: ${s.command.status}. Electrical contact state is not measured.`:'No cutoff command recorded.';
      list('op-holds',s.holds);$('op-reset-latch').hidden=!s.latched;
    }
    $('op-alerts').innerHTML=a.alerts.length?a.alerts.map(x=>`<article class="op-signal" data-level="${x.severity}"><strong>${x.severity} · ${esc(title(x.parameter))}</strong>${esc(x.detail)}<small>Observed: ${esc(typeof x.value==='number'?fmt(x.value,3):x.value)} · reference: ${esc(x.threshold)} · ${esc(title(x.category))}</small></article>`).join(''):'<p class="muted">No active signal in the available evidence.</p>';
    const events=physical?s.events.map(e=>({...e.content,timestamp:e.content.timestamp||e.created_at,kind:e.kind,detail:e.content.detail||e.content.reason||e.content.note||e.content.status||title(e.kind)})):s.events;
    $('op-events').innerHTML=[...events].reverse().slice(0,60).map(e=>`<article class="op-event"><time>${new Date(e.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time><div><strong>${esc(title(e.kind))}</strong><p>${esc(e.detail)}</p></div></article>`).join('')||'<p class="muted">Events appear after telemetry or operator actions.</p>';
    list('op-maintenance-list',a.maintenance);list('op-assumptions',s.assumptions);trend();buttons();
  }
  function trend(){
    if(!current)return;const key=$('op-trend-channel').value, rows=current.history,valid=rows.filter(r=>r[key]!=null&&Number.isFinite(r[key]));
    $('op-trend-note').textContent=`${rows.length} recent samples · ${mode==='industrial'?'simulated clock':'acquisition timestamps'} · gaps remain gaps`;
    if(!valid.length){$('op-trend').innerHTML='<text x="24" y="115" fill="#66796c" font-size="18">No qualified observations for this channel.</text>';return;}
    const values=valid.map(r=>r[key]),low=Math.min(...values),high=Math.max(...values),pad=Math.max(1,(high-low)*.15),min=low-pad,max=high+pad;
    const start=Date.parse(rows[0].timestamp),end=Date.parse(rows.at(-1).timestamp),x=r=>55+(Date.parse(r.timestamp)-start)/Math.max(1,end-start)*820,y=v=>215-(v-min)/(max-min)*180;
    let markup='';for(let i=0;i<4;i++){const v=min+(max-min)*i/3;markup+=`<line x1="55" y1="${y(v)}" x2="875" y2="${y(v)}" stroke="#dbe4de"/><text x="3" y="${y(v)+5}" fill="#66796c" font-size="14">${fmt(v)}</text>`;}
    let path='',connected=false;for(const r of rows){if(r[key]==null){connected=false;continue;}path+=`${connected?'L':'M'}${x(r)},${y(r[key])} `;connected=true;}
    markup+=`<path d="${path}" stroke="#367964" stroke-width="3" fill="none"/>`;const last=valid.at(-1);markup+=`<circle cx="${x(last)}" cy="${y(last[key])}" r="4" fill="#367964"/>`;$('op-trend').innerHTML=markup;
  }
  async function loadCatalog(){
    catalog=await workspace.api('/twin/catalog');
    $('op-scenario').innerHTML=Object.entries(catalog.scenarios).map(([k,v])=>`<option value="${k}">${esc(v.name)}</option>`).join('');
    $('op-fault-kind').innerHTML=catalog.faults.map(k=>`<option value="${k}">${esc(title(k))}</option>`).join('');
    $('op-maintenance-kind').innerHTML=catalog.maintenance.map(k=>`<option value="${k}">${esc(title(k))}</option>`).join('');
    $('op-run-select').innerHTML='<option value="">Select a saved run</option>'+catalog.runs.map(r=>`<option value="${esc(r.id)}">${esc(title(r.scenario))} · ${new Date(r.started_at).toLocaleString()} · ${esc(r.breaker)}</option>`).join('');
    if(run)$('op-run-select').value=run.id;
  }
  async function create(){run=await workspace.api('/twin/runs',{request_id:crypto.randomUUID()});dirty=false;await loadCatalog();settingsFields(run);render(run);}
  click('op-new',create);click('op-create',create);
  async function selectSource(next){
    if(busy||!ready||document.body.dataset.twinSwitching==='true'){window.HaloSession?.paint();return;}
    const previous=window.HaloSession?.source();clearTimeout(timer);document.body.dataset.twinSwitching='true';$('session-source').disabled=true;
    try{
      if(next==='reference'){await workspace.useSource('replay');workspace.view('twin');return;}
      if(next==='prototype')await workspace.useSource('bench');
      window.HaloSession?.select(next);await switchMode(next);
    }catch(e){window.HaloSession?.select(previous);error(e.message);throw e;}
    finally{document.body.dataset.twinSwitching='false';$('session-source').disabled=false;schedule();}
  }
  $('op-industrial').onclick=()=>selectSource('industrial');$('op-prototype').onclick=()=>selectSource('prototype');
  click('op-prototype-refresh',async()=>render(await workspace.api('/twin/prototype')));
  $('op-run-select').onchange=()=>guarded(async()=>{if(!$('op-run-select').value)return;run=await workspace.api('/twin/runs/'+encodeURIComponent($('op-run-select').value));dirty=false;settingsFields(run);render(run);});
  click('op-start',()=>act(run.running?'pause':'start'));click('op-step',()=>act('step',{seconds:300}));
  click('op-trip',()=>act('trip'));click('op-reconnect',()=>act('reconnect'));click('op-clear',()=>act('clear_fault'));
  click('op-apply-scenario',async()=>{dirty=false;await act('scenario',{scenario:$('op-scenario').value});});
  $('op-inputs').oninput=()=>{dirty=true;$('op-load-output').value=$('op-load').value+'%';};
  $('op-inputs').onsubmit=e=>{e.preventDefault();guarded(async()=>{const form=e.target.elements;const inputs={};for(const k of Object.keys(catalog.inputs))inputs[k]=k==='protection_enabled'?form[k].checked:k==='cooling'?form[k].value:Number(form[k].value);dirty=false;await act('inputs',{inputs});});};
  $('op-fault').onsubmit=e=>{e.preventDefault();guarded(()=>act('inject',{fault:e.target.elements.fault.value,severity:Number(e.target.elements.severity.value),duration_s:Number(e.target.elements.duration_s.value)}));};
  $('op-maintenance').onsubmit=e=>{e.preventDefault();guarded(async()=>{await act('maintenance',{maintenance:e.target.elements.maintenance.value,note:e.target.elements.note.value});e.target.elements.note.value='';dirty=false;populateInputs(run);});};
  $('op-settings-form').onsubmit=e=>{e.preventDefault();guarded(()=>act('settings',{settings:Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)]))}));};
  $('op-trend-channel').onchange=trend;$('op-model-reset').onclick=()=>model().reset();
  $('op-commissioning').onclick=e=>{e.preventDefault();workspace.view('commissioning');};
  async function physicalRelays(states){if(mode!=='prototype')return;const r=await workspace.api('/relays',{states,request_id:crypto.randomUUID()});$('op-command-status').textContent=`Request ${r.status}. Await firmware acknowledgment; contacts remain unverified.`;}
  click('op-off',()=>physicalRelays([false,false,false,false]));
  $('op-reset-latch').onsubmit=e=>{e.preventDefault();guarded(async()=>{await workspace.api('/twin/prototype/reset-latch',{note:e.target.elements.note.value});render(await workspace.api('/twin/prototype'));e.target.reset();});};
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  async function exportCurrent(){
    if(mode==='prototype'){const data=await workspace.api('/twin/prototype');download(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),'prototype-twin-evidence.json');return;}
    if(!run)throw Error('Create or select an industrial run first.');const id=run.id,response=await HaloAuth.fetch('/api/halo/twin/runs/'+encodeURIComponent(id)+'/report');if(!response.ok)throw Error('Report could not be generated.');download(await response.blob(),id+'-report.zip');}
  async function adopt(s){run=s;mode='industrial';window.HaloSession?.select('industrial');await loadCatalog();settingsFields(s);render(s);}
  click('op-report',exportCurrent);window.HaloOperations={export:exportCurrent,selectSource,adopt,act,refresh:async()=>{if(run){run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}return run;}};
  async function init(){if(ready)return;try{await loadCatalog();ready=true;render(null);if(catalog.runs.length){run=await workspace.api('/twin/runs/'+encodeURIComponent(catalog.runs[0].id));settingsFields(run);$('op-run-select').value=run.id;render(run);}if(window.HaloSession?.source()==='prototype')await selectSource('prototype');schedule();}catch(e){error(e.message);}}
  window.addEventListener('halo:ready',init);
  window.addEventListener('halo:view',event=>{if(event.detail==='operate'){if(window.HaloSession?.source()==='reference'){workspace.view('twin');return;}if(ready){render(mode==='industrial'?run:current);model().draw();schedule();}else init();}else clearTimeout(timer);});
  document.addEventListener('visibilitychange',schedule);
  buttons();
})();
