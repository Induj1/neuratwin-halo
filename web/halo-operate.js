/* Two data sources, one view. Simulation commands cannot target physical relays. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), workspace=window.HaloWorkspace;
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,n=1)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:n});
  const title=s=>String(s).replaceAll('_',' ');
  let mode='industrial', run=null, current=null, busy=false, catalog=null, timer=null, ready=false, dirty=false, selectedScenario=null;
  let twin=null,initializing=false,replaySource=null,replayIndex=0,sliderTimer=null,pendingInputs=null,sliding=false,reviewSource=null,observationSource=null,observationRequest=0;
  // Wi-Fi ESP32 instruments (prototype mode only). Absent when the module is not loaded.
  const esp=window.HaloEsp32&&workspace?window.HaloEsp32.create(workspace.api):null;
  let scope=null,thermo=null,loadsPanel=null;
  const grid=document.querySelector('#op-workspace .op-main-grid');
  const next=document.querySelector('#op-workspace .op-next');
  if(grid&&next){
    const stack=document.createElement('div');stack.className='op-visual-stack';
    grid.prepend(stack);stack.append(grid.querySelector('.op-model'));$('op-explore').before($('op-readings'));
    stack.after($('op-waveform'));$('op-waveform').after($('op-scope'));grid.after(next);
    grid.after(document.querySelector('#op-workspace .op-replay'));
    // Put the decision before the instruments; keep the detailed study below them.
    const decision=document.createElement('section');decision.id='op-decision-ribbon';
    decision.setAttribute('aria-label','Operating decision');
    decision.append(document.querySelector('.op-state-strip>div'),next.querySelector('.op-next-copy'));
    const review=document.createElement('button');review.id='op-review-action';review.textContent='Review this run →';
    review.onclick=()=>{
      reviewSource=HaloCommand.math.reviewContext(current,mode,!!replaySource);
      if(!reviewSource.available)return;
      paintGuide();$('op-guide').hidden=false;review.setAttribute('aria-expanded','true');
      $('op-guide').scrollIntoView({block:'nearest',behavior:'instant'});$('op-guide-signals').focus({preventScroll:true});
    };
    review.setAttribute('aria-controls','op-guide');review.setAttribute('aria-expanded','false');
    const assess=document.createElement('button');assess.id='op-observe-action';assess.textContent='Assess readings';
    assess.setAttribute('aria-controls','op-observation');assess.setAttribute('aria-expanded','false');assess.onclick=assessReadings;
    const actions=document.createElement('div');actions.className='op-decision-actions';actions.append(assess,review);
    decision.append(actions);grid.before(decision);
    $('op-compare').append($('op-prediction'));
    const heading=document.querySelector('#view-operate .op-heading');
    heading.firstElementChild.querySelector('p:not(.eyebrow)').replaceWith($('op-clock'));
    const menu=document.createElement('details');menu.className='op-run-menu';
    const summary=document.createElement('summary');summary.textContent='Run & export';menu.append(summary,$('op-run-tools'));
    heading.append(menu,$('op-prototype-refresh'));document.querySelector('#view-operate .op-toolbar').hidden=true;
    $('op-explore').append($('op-step'));$('op-start').hidden=true;
    const advanced=document.createElement('details');advanced.className='op-advanced';
    advanced.innerHTML='<summary>Scenarios, disturbances & model settings</summary>';
    $('op-industrial-controls').before(advanced);advanced.append($('op-industrial-controls'));
    const status=document.querySelector('.op-state-strip');$('op-readings').before(decision);decision.after(status);
    const basis=document.createElement('details');basis.className='op-health-explanation';basis.innerHTML='<summary>Assessment basis</summary>';
    const healthNote=document.querySelector('.op-decision>.op-health-note');healthNote.id='op-health-explanation-note';healthNote.before(basis);basis.append(healthNote);
  }

  function model(){if(!twin)twin=new HaloTwin($('op-twin'),part=>$('op-part').textContent=title(part));return twin;}
  function resetModelView(){
    const m=model();if(m.failed||!m.renderer)return;m.reset();
    if(mode==='industrial'){m.distance=8.8;m.pitch=.48;m.target.set(-.1,1.05,0);m.renderer.toneMappingExposure=.62;}
    else m.renderer.toneMappingExposure=.8;
    m.draw();
  }
  function paintGuide(){
    const context=HaloCommand.math.reviewContext(current,mode,!!replaySource);
    $('op-guide-source').textContent=`${context.label} · ${context.id||'unavailable'} · revision ${context.revision??'unavailable'}`;
    $('op-guide-note').textContent=context.note;
    const matches=HaloCommand.math.sameReviewSource(reviewSource,current,mode,!!replaySource);
    for(const id of ['op-guide-signals','op-guide-compare','op-guide-maintenance'])$(id).disabled=!matches||busy;
    if(!matches&&reviewSource){$('op-guide').hidden=true;$('op-review-action').setAttribute('aria-expanded','false');reviewSource=null;}
    if(observationSource&&!HaloCommand.math.sameObservationSource(observationSource,current,mode,!!replaySource))closeObservation();
    $('op-observe-action').hidden=!context.available;$('op-observe-action').disabled=busy;
  }
  function closeObservation(){observationRequest++;observationSource=null;$('op-observation').hidden=true;$('op-observe-action').setAttribute('aria-expanded','false');}
  async function assessReadings(){
    const context=HaloCommand.math.reviewContext(current,mode,!!replaySource);if(!context.available||busy)return;
    observationSource=context;const request=++observationRequest;
    $('op-observation').hidden=false;$('op-observe-action').setAttribute('aria-expanded','true');
    $('op-observation-body').textContent='Assessing the recorded channels…';
    $('op-observation').scrollIntoView({block:'nearest',behavior:'instant'});
    try{
      const result=await workspace.api(`/twin/runs/${encodeURIComponent(context.id)}/observation-review?revision=${context.revision}`);
      if(request!==observationRequest||!HaloCommand.math.sameObservationSource(context,current,mode,!!replaySource))return;
      const a=result.assessment,holds=a.validity?.holds||[],p=a.forecast?.points?.at(-1);
      $('op-observation-body').innerHTML=`<p class="op-observation-verdict"><strong>${esc(a.presentation_headline)}</strong></p><p>${esc(a.next_action)}</p>
        <div class="op-observation-facts"><div><span>Observed state</span><strong>${a.observed_status==='NORMAL'?'No threshold breach':esc(a.observed_status)}</strong></div><div><span>Conditional projection</span><strong>${a.available&&p?fmt(p.temperature_c)+' °C at 30 min':'Withheld'}</strong></div><div><span>Input records</span><strong>${fmt(result.observation_count,0)}</strong></div></div>
        ${holds.length?`<p><strong>Evidence holds:</strong> ${holds.map(x=>esc(title(x))).join(' · ')}</p>`:''}
        <p><strong>Signals to investigate:</strong> ${(a.hypotheses?.length?a.hypotheses:['no anomaly established']).map(x=>esc(title(x))).join(' · ')}. These are hypotheses, not confirmed causes.</p>
        <details><summary>Inspect the inputs and assumptions</summary><p>${esc(result.reference_basis)}</p><p>${esc(a.assumptions||a.reason)}</p><p><strong>Used:</strong> ${result.channels.map(esc).join(', ')}.</p><p><strong>Excluded:</strong> ${result.excluded.map(esc).join(', ')}.</p><p class="muted">Simulation observations · ${esc(result.run_id)} · revision ${result.revision} · model ${result.model_version}. No hardware action.</p><code>Input SHA-256: ${esc(result.input_sha256)}</code></details>`;
    }catch(e){if(request===observationRequest)$('op-observation-body').textContent='Assessment unavailable: '+e.message;}
  }
  $('op-observation-close').onclick=()=>{closeObservation();$('op-observe-action').focus();};
  function reviewAction(fn){
    if(!HaloCommand.math.sameReviewSource(reviewSource,current,mode,!!replaySource)||busy){error('Open a review for the currently selected simulation run.');return;}
    try{Promise.resolve(fn()).catch(e=>error(e.message));}catch(e){error(e.message);}
  }
  $('op-guide-close').onclick=()=>{$('op-guide').hidden=true;$('op-review-action').setAttribute('aria-expanded','false');$('op-review-action').focus();};
  $('op-guide-signals').onclick=()=>reviewAction(()=>{$('op-signals-title').scrollIntoView({block:'start',behavior:'instant'});$('op-signals-title').focus({preventScroll:true});});
  $('op-guide-compare').onclick=()=>reviewAction(()=>{next.scrollIntoView({block:'start',behavior:'instant'});$('op-compare-heading').setAttribute('tabindex','-1');$('op-compare-heading').focus({preventScroll:true});});
  $('op-guide-maintenance').onclick=()=>reviewAction(()=>{
    if(!window.HaloCase?.openRunMaintenance){error('Run-maintenance navigation is unavailable. The current source has not changed.');return;}
    window.HaloCase.openRunMaintenance(current.id);
  });
  function error(message){$('op-error').textContent=message||'';$('op-error').hidden=!message;}
  function list(id,items){$(id).innerHTML=items.map(x=>'<li>'+esc(x)+'</li>').join('');}
  function clock(seconds){const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=Math.floor(seconds%60);return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;}
  function buttons(){
    const physical=mode==='prototype',running=!!current?.running;
    $('session-source').disabled=!ready||busy||document.body.dataset.twinSwitching==='true';
    $('op-start').textContent=running?'Pause simulation':'Start simulation';
    $('op-start').disabled=busy||!run;$('op-step').disabled=busy||!run;
    $('op-report').disabled=busy||!run;$('op-trip').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-reconnect').disabled=busy||physical||!!current?.recovery_holds?.length;
    $('op-apply-scenario').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-new').disabled=busy||!ready;$('op-create').disabled=busy||!ready;
    $('op-industrial').disabled=busy||!ready;$('op-prototype').disabled=busy||!ready;
    document.querySelectorAll('#view-operate form button').forEach(b=>b.disabled=busy||!ready);
    $('op-clear').disabled=busy||!run;
    $('op-off').disabled=busy||!(current?.connection==='live'||(esp&&esp.packet().available&&esp.status()?.configured));
    $('op-running-note').textContent=running?'Running · accelerated clock; pauses ticking when this view is hidden.':'Paused · clock advances only when you run or step.';
    $('op-live-start').textContent=running?'Pause thermal response':'Start thermal response';
    $('op-live-start').disabled=busy||!run||!!replaySource;
    for(const id of ['op-live-load','op-live-imbalance'])$(id).disabled=!run||!!replaySource||(busy&&!sliding);
    $('op-replay-open').disabled=busy||!(current?.history?.length)||!!replaySource;
    if(replaySource){
      document.querySelectorAll('#op-industrial-controls input,#op-industrial-controls select,#op-industrial-controls button,#op-prototype-controls input,#op-prototype-controls button,#op-prototype-controls textarea,#op-maintenance input,#op-maintenance select,#op-maintenance textarea,#op-maintenance button').forEach(b=>b.disabled=true);
      ['op-new','op-start','op-step','op-trip','op-clear','op-reconnect','op-apply-scenario','op-run-select'].forEach(id=>$(id).disabled=true);
    }else{
      $('op-run-select').disabled=busy;
      document.querySelectorAll('#op-industrial-controls input,#op-industrial-controls select,#op-prototype-controls input,#op-prototype-controls textarea,#op-maintenance input,#op-maintenance select,#op-maintenance textarea').forEach(b=>b.disabled=busy);
    }
    if(busy)$('op-compare-apply').disabled=true;
    else {const p=HaloCommand.plan();$('op-compare-apply').disabled=!!replaySource||mode!=='industrial'||!p?.recommendation?.reduction_pct||p.origin_revision!==run?.revision;}
    if(current)paintGuide();
    if(mode==='prototype')loadsPanel?.setBusy(busy);
  }
  async function act(action,extra={}){
    if(replaySource)throw Error('Exit replay before changing the simulation.');
    if(mode!=='industrial'||!run)throw Error('Create or select an industrial run first.');
    const latest=window.HaloSession?.run();if(latest?.id===run.id&&latest.revision>run.revision)run=latest;
    if(action==='inputs')extra={...extra,inputs:{...run.inputs,...extra.inputs}};
    const r=await workspace.api(`/twin/runs/${encodeURIComponent(run.id)}/actions`,{action,revision:run.revision,request_id:crypto.randomUUID(),...extra});
    run=r;render(r);return r;
  }
  async function guarded(fn){
    if(busy)return;busy=true;buttons();error('');
    try{await fn();}catch(e){error(e.message);if(mode==='industrial'&&run&&e.status===409){try{run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}catch{}}}
    finally{busy=false;buttons();schedule();if(pendingInputs)flushSliders();}
  }
  function click(id,fn){$(id).addEventListener('click',()=>guarded(fn));}
  function schedule(){
    clearTimeout(timer);
    if(!ready||replaySource||document.hidden||!$('view-operate').classList.contains('active'))return;
    timer=setTimeout(()=>guarded(async()=>{
      if(mode==='prototype')render(await prototypeState());
      else if(run?.running)await act('step',{seconds:run.inputs.speed});
    }),mode==='prototype'?2500:1500);
  }
  async function switchMode(next){
    if(busy||!ready)return;replaySource=null;pendingInputs=null;clearTimeout(sliderTimer);mode=next;dirty=false;error('');
    $('op-industrial').setAttribute('aria-pressed',String(mode==='industrial'));
    $('op-prototype').setAttribute('aria-pressed',String(mode==='prototype'));
    $('op-source').textContent=mode==='industrial'?'INDUSTRIAL SIMULATION':'PHYSICAL PROTOTYPE · ESP32';
    $('op-run-tools').hidden=mode==='prototype';$('op-prototype-refresh').hidden=mode!=='prototype';
    if(mode==='industrial')render(run);else{
      current=null;$('op-workspace').hidden=true;$('op-welcome').hidden=true;$('op-clock').textContent='Loading ESP32 measurements…';
      await guarded(async()=>render(await prototypeState()));
    }
    schedule();
  }
  /* Analysis from /twin/prototype and, in the same tick, the live board packet from /esp32/readings. */
  async function prototypeState(){
    const [s]=await Promise.all([workspace.api('/twin/prototype'),esp?esp.poll():null]);
    return s;
  }
  function hardwareNote(s){
    const base=`${title(s.connection)} · ${s.control_enabled?'Automatic all-off requests armed':'Monitoring only; automatic cutoff is not enabled'}. Primary current needs its own calibrated sensor. Oil and winding temperature are unavailable.`;
    if(!esp)return base;
    const st=esp.status(),hw=esp.packet();
    if(!st||!st.configured)return 'Wi-Fi board integration is off (HALO_ESP32_URL unset on the server). '+base;
    if(!hw.available)return `Wi-Fi board unreachable${st.poller?.last_error?' · '+st.poller.last_error:hw.error?' · '+hw.error:''}. `+base;
    if(hw.stale)return `Wi-Fi board reading is STALE (${fmt(hw.age_s,0)} s old${hw.error?' · '+hw.error:''}). `+base;
    return `Wi-Fi board live · ${hw.device_id||'board'} · sequence ${hw.sequence} · ${fmt(hw.age_s,0)} s ago. `+base;
  }
  function requestLoads(body){
    if(!esp)return Promise.reject(Error('Wi-Fi board module is not loaded.'));
    if(busy)return Promise.reject(Error('Another request is in progress.'));
    return new Promise((resolve,reject)=>guarded(async()=>{
      try{const r=await esp.setLoads(body);esp.applyLoads(r.loads);if(current&&mode==='prototype')render(current);resolve(r);}
      catch(e){reject(e);throw e;}
    }));
  }
  function paintHardware(s){
    if(!esp)return;
    const hw=esp.packet(),st=esp.status(),history=esp.history();
    scope||=window.HaloScope?window.HaloScope.create($('op-scope'),window.HaloScope.presets.prototype()):null;
    scope?.update(window.HaloEsp32.math.scopePacket(hw,history,st));
    thermo||=window.HaloThermo?window.HaloThermo.create($('op-thermo'),{floor:0,ceiling:100,eyebrow:'SURFACE PROBE'}):null;
    thermo?.update(window.HaloEsp32.math.thermoPacket(hw,history,s.settings));
    loadsPanel||=window.HaloLoads?window.HaloLoads.create($('op-loads'),{setLoads:requestLoads}):null;
    loadsPanel?.update({packet:hw,status:st,latched:!!s.latched,busy});
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
    if(!physical&&!replaySource){window.HaloSession?.bind(s);try{sessionStorage.setItem('halo-industrial-run',s.id);}catch{}}
    const t=s.telemetry,a=s.analysis;
    if($('view-operate').classList.contains('active')){$('connection').textContent=physical?title(s.connection)+' · ESP32':'Industrial · simulated';$('connection').className='pill';}
    $('op-industrial-controls').hidden=physical;$('op-prototype-controls').hidden=!physical;
    $('op-waveform').hidden=physical&&!!esp;$('op-scope').hidden=!(physical&&esp);
    $('op-maintenance').hidden=physical;$('op-maintenance-physical').hidden=!physical;
    $('op-source').textContent=physical?'PHYSICAL PROTOTYPE · ESP32':'INDUSTRIAL SIMULATION';
    $('op-clock').textContent=physical?(s.connection==='disconnected'?'No acquisition received':new Date(t.timestamp).toLocaleString()):`${clock(s.elapsed_s)} simulated · ${s.running?'running':'paused'}`;
    $('op-condition').textContent=physical?(s.latched?'TRIP DECISION LATCHED':a.status):(s.breaker==='OPEN'?'TRIPPED':a.status);$('op-condition').dataset.level=(!physical&&s.breaker==='OPEN')||s.latched?'TRIP':a.status;
    $('op-protection').textContent=s.protection_state;$('op-breaker').textContent=s.breaker;
    $('op-breaker-label').textContent=physical?'Contact feedback':'Simulated breaker';
    $('op-quality').textContent=physical?(t.quality==='qualified'?'Core channels calibrated':title(t.quality)):'Model-generated';
    $('op-asset').textContent=physical?s.id:`INDUSTRIAL · ${s.id.slice(-8).toUpperCase()}`;
    $('op-model-title').textContent=physical?'Transformer demonstrator':`${fmt(s.settings.rated_kva,0)} kVA transformer`;
    $('op-model-note').textContent=physical?'Surface temperature · missing sensors remain unavailable':'Oil + winding thermal model · illustrative geometry';
    const thermalValue=t.quality==='qualified'&&s.settings?.temperature_warning!=null&&s.settings?.temperature_critical!=null?t.transformer_temperature:null;
    const thermalSeverity=thermalValue!=null&&s.settings?.temperature_critical!=null&&thermalValue>=s.settings.temperature_critical?'critical':thermalValue!=null&&s.settings?.temperature_warning!=null&&thermalValue>=s.settings.temperature_warning?'warning':'normal';
    const changedModel=model().distribution!==!physical;
    model().setDistribution(!physical);if(changedModel)resetModelView();
    model().temperature(thermalValue,thermalSeverity,{warning:s.settings?.temperature_warning,critical:s.settings?.temperature_critical});model().draw();
    $('op-flow-breaker').textContent=physical?'Contacts unverified':s.breaker==='OPEN'?'Breaker open':'Breaker closed';
    document.querySelector('#view-operate .op-flow').dataset.open=String(!physical&&s.breaker==='OPEN');
    $('op-health-band').dataset.level=a.status;
    $('op-health-explanation-note').textContent=a.health_evidence?.note||'Operating stress and recorded history. A screening index, not a failure probability.';
    $('op-next-step').textContent=!physical&&a.status==='WARNING'&&a.forward_risk?.requires_action?'Review loading and cooling before the projected thermal limit.':!physical&&a.status==='WARNING'&&a.maintenance[0]?.startsWith('Cooling remains declared impaired')?'Declared cooling impairment: keep load reduced and arrange inspection.':a.maintenance[0];next.dataset.level=a.status;$('op-decision-ribbon').dataset.level=a.status;$('op-review-action').hidden=physical||!!replaySource;document.querySelector('.op-advanced').hidden=physical;$('op-prediction').textContent=physical?'Surface trends are interpreted only with fresh calibrated measurements.':s.prediction.minutes_to_critical==null?s.prediction.note:`Thermal critical threshold in approximately ${s.prediction.minutes_to_critical} simulated min if present conditions persist without protection.`;
    $('op-trip-box').hidden=physical?!s.latched:s.breaker!=='OPEN';
    $('op-trip-reason').textContent=s.trip?.reason||'No trip.';
    list('op-recovery-holds',physical?['Inspect the physical rig. GPIO acknowledgments do not verify contact opening.']:s.recovery_holds||[]);
    $('op-reconnect').hidden=physical;
    const primaryVerified=!physical||['primary_v','primary_current_a'].every(k=>s.evidence.some(e=>e.channel===k&&e.available&&e.calibrated));
    const temp=HaloCommand.math.temperatureReading(s,mode);
    const readings=[['thermal',temp.label,temp.value,'°C',`${temp.critical===null?'Critical reference unavailable':`Critical ${fmt(temp.critical,0)} °C`} · ${physical?`ambient ${fmt(t.ambient_temperature)} °C`:`oil ${fmt(t.oil_temperature)} °C`}`,temp.level],
      ['loading',physical?'Measured loading':'Mean-current loading',t.loading_percent,'%',physical?'Relative to reviewed current limit':`Highest phase ${fmt(t.max_phase_loading_percent)}%`,null],
      ['secondary','Secondary',t.secondary_voltage,'V',`Current ${fmt(t.secondary_current,2)} A RMS`,null],
      ['primary','Primary',t.primary_voltage,'V',`Current ${fmt(t.primary_current,2)} A RMS${primaryVerified?'':' · unverified'}`,null]];
    $('op-readings').innerHTML=readings.map(([key,label,v,unit,note,level])=>`<div class="op-reading" data-reading="${key}" ${level?`data-level="${level}"`:''}><span>${esc(label)}</span><strong>${fmt(v)} <small>${unit}</small></strong><p>${esc(note)}</p></div>`).join('');
    if(!physical){
      const scenarioKey=s.id+':'+s.scenario;
      if(selectedScenario!==scenarioKey){$('op-scenario').value=s.scenario;selectedScenario=scenarioKey;}
      const saved=[...$('op-run-select').options].find(o=>o.value===s.id);
      if(saved)saved.textContent=`${s.id.slice(-8).toUpperCase()} · ${s.analysis.status} · ${s.breaker}`;
      if(!dirty)populateInputs(s);
      $('op-active-fault').textContent=s.fault?`${title(s.fault.kind)} active · ${fmt(Math.max(0,s.fault.until_s-s.elapsed_s),0)} simulated seconds remaining`:'No injected disturbance.';
      $('op-ageing').textContent=fmt(s.condition.equivalent_age_hours,2)+' equivalent hours';
      $('op-life').textContent=`${fmt(s.condition.insulation_consumed_percent,3)}% of illustrative thermal-ageing budget used. Actual remaining life unavailable.`;
    }else{
      $('op-prototype-note').textContent=hardwareNote(s);
      if(esp){paintHardware(s);$('op-relays').hidden=true;}
      else{
        // USB-bridge fallback: the older relay command queue when the Wi-Fi module is absent.
        $('op-relays').hidden=false;
        $('op-relays').innerHTML=[0,1,2,3].map(i=>`<div><strong>K${i+1}${i===3?' · locked':''}</strong><span>39 Ω / 10 W</span><p>${s.relay_states?(s.relay_states[i]?'GPIO reports ON':'GPIO reports OFF'):'State unavailable'}</p><button data-op-relay="${i}" ${i===3||!s.load_control_available||busy?'disabled':''}>${s.relay_states?.[i]?'Request OFF':'Request ON'}</button></div>`).join('');
        $('op-relays').querySelectorAll('button').forEach(b=>b.onclick=()=>guarded(async()=>{const states=[...current.relay_states];states[Number(b.dataset.opRelay)]=!states[Number(b.dataset.opRelay)];await physicalRelays(states);}));
      }
      $('op-command-status').textContent=s.command?.status?`Last cutoff command: ${s.command.status}. Electrical contact state is not measured.`:'No cutoff command recorded.';
      list('op-holds',s.holds);$('op-reset-latch').hidden=!s.latched;
    }
    $('op-alerts').innerHTML=a.alerts.length?a.alerts.map(x=>`<article class="op-signal" data-level="${x.severity}"><strong>${x.severity} · ${esc(title(x.parameter))}</strong>${esc(x.detail)}<small>Observed: ${esc(typeof x.value==='number'?fmt(x.value,3):x.value)} · reference: ${esc(x.threshold)} · ${esc(title(x.category))}</small></article>`).join(''):'<p class="muted">No active signal in the available evidence.</p>';
    const events=physical?s.events.map(e=>({...e.content,timestamp:e.content.timestamp||e.created_at,kind:e.kind,detail:e.content.detail||e.content.reason||e.content.note||e.content.status||title(e.kind)})):s.events;
    $('op-events').innerHTML=[...events].reverse().slice(0,60).map(e=>`<article class="op-event"><time>${new Date(e.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time><div><strong>${esc(title(e.kind))}</strong><p>${esc(e.detail)}</p></div></article>`).join('')||'<p class="muted">Events appear after telemetry or operator actions.</p>';
    list('op-maintenance-list',a.maintenance);list('op-assumptions',s.assumptions);trend();
    HaloCommand.paint(s,{mode,replay:!!replaySource,model:model()});
    $('op-explore').hidden=physical||!!replaySource;
    if(!pendingInputs&&!sliderTimer){$('op-live-load').value=s.inputs?.load_percent??0;$('op-live-imbalance').value=s.inputs?.phase_imbalance_percent??0;}
    const displayedInputs=pendingInputs?.inputs||(sliderTimer?{load_percent:Number($('op-live-load').value),phase_imbalance_percent:Number($('op-live-imbalance').value)}:s.inputs);
    $('op-live-load-output').textContent=fmt(displayedInputs?.load_percent,0)+'%';$('op-live-imbalance-output').textContent=fmt(displayedInputs?.phase_imbalance_percent??0,0)+'%';
    $('op-replay-exit').hidden=!replaySource;$('op-replay-range').disabled=!replaySource;
    if(replaySource){const position=physical?new Date(t.timestamp).toLocaleString():clock(s.elapsed_s);$('op-clock').textContent='REPLAY · '+new Date(t.timestamp).toLocaleString();$('session-context').textContent=`REPLAY · ${s.id} · ${position} · ${physical?'acquisition continues':'simulation paused'}`;$('connection').textContent='Replay · recorded state';$('op-replay-count').textContent=`${replayIndex+1} / ${replaySource.history.length} · ${position}`;}
    else $('op-replay-count').textContent=`${s.history.length} recorded observations`;
    $('op-alerts').querySelectorAll('.op-signal').forEach((el,i)=>{const b=document.createElement('button');b.textContent='Replay this signal';b.disabled=!!replaySource;b.onclick=()=>enterReplay(a.alerts[i].timestamp);el.append(b);});
    if(!replaySource)$('op-events').querySelectorAll('.op-event').forEach((el,i)=>{const event=[...events].reverse().slice(0,60)[i];const b=document.createElement('button');b.textContent='Inspect recorded state';b.onclick=()=>enterReplay(event.timestamp,event.id);el.lastElementChild.append(b);});
    buttons();
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
    $('op-run-select').innerHTML='<option value="">Select a saved run</option>'+catalog.runs.map(r=>`<option value="${esc(r.id)}">${esc(r.id.slice(-8).toUpperCase())} · ${new Date(r.started_at).toLocaleString()} · ${esc(r.breaker)}</option>`).join('');
    if(run)$('op-run-select').value=run.id;
  }
  async function create(){run=await workspace.api('/twin/runs',{request_id:crypto.randomUUID()});dirty=false;await loadCatalog();settingsFields(run);render(run);}
  async function enterReplay(timestamp,eventId){
    if(busy||replaySource)return;
    pendingInputs=null;clearTimeout(sliderTimer);sliderTimer=null;
    await guarded(async()=>{
      if(mode==='industrial'&&run?.running)await act('pause');
      const source=mode==='industrial'?run:current;if(!source?.history?.length)return;
      replaySource=structuredClone(source);clearTimeout(timer);HaloCommand.invalidate();
      const target=timestamp?Date.parse(timestamp):Infinity;
      replayIndex=replaySource.history.findLastIndex(r=>Date.parse(r.timestamp)<=target);
      if(Number.isFinite(eventId)){const matched=replaySource.history.findIndex(r=>r.event_cursor>=eventId);if(matched>=0)replayIndex=matched;}
      if(replayIndex<0)replayIndex=0;
      $('op-replay-range').max=replaySource.history.length-1;$('op-replay-range').value=replayIndex;
      render(HaloCommand.math.replaySnapshot(replaySource,replayIndex));
      $('op-replay-banner').scrollIntoView({block:'nearest'});
    });
  }
  function exitReplay(){if(!replaySource)return;const source=replaySource;replaySource=null;dirty=false;render(mode==='industrial'?run:source);schedule();}
  $('op-replay-open').onclick=()=>enterReplay();$('op-replay-exit').onclick=exitReplay;
  $('op-replay-range').oninput=()=>{if(!replaySource)return;replayIndex=Number($('op-replay-range').value);render(HaloCommand.math.replaySnapshot(replaySource,replayIndex));};
  function flushSliders(){
    if(busy||!pendingInputs||replaySource||mode!=='industrial')return;
    const queued=pendingInputs;pendingInputs=null;
    if(queued.run_id!==run?.id){$('op-input-status').textContent='Run changed. Set the sliders for the selected run.';return;}
    const inputs=queued.inputs;sliding=true;
    guarded(async()=>{
      try{dirty=false;await act('inputs',{inputs});$('op-input-status').textContent=pendingInputs?'Applying the latest simulation input…':'Applied · electrical state updated; temperature follows the simulation clock.';}
      catch(e){$('op-input-status').textContent='Change not applied. '+e.message;throw e;}
      finally{sliding=false;}
    });
  }
  for(const id of ['op-live-load','op-live-imbalance'])$(id).oninput=()=>{
    if(mode!=='industrial'||replaySource||!run)return;
    const inputs={load_percent:Number($('op-live-load').value),phase_imbalance_percent:Number($('op-live-imbalance').value)};
    pendingInputs={run_id:run.id,inputs};
    HaloCommand.invalidate();$('op-compare-status').textContent='Input pending · comparison will follow the applied state.';
    $('op-live-load-output').textContent=inputs.load_percent+'%';$('op-live-imbalance-output').textContent=inputs.phase_imbalance_percent+'%';
    $('op-input-status').textContent='Applying simulation input…';clearTimeout(sliderTimer);
    sliderTimer=setTimeout(()=>{sliderTimer=null;flushSliders();},100);
  };
  click('op-live-start',()=>act(run.running?'pause':'start'));
  click('op-compare-apply',async()=>{
    const preview=HaloCommand.plan();
    if(replaySource||mode!=='industrial'||!preview?.recommendation?.reduction_pct)return;
    if(preview.origin_revision!==run.revision)throw Error('The state changed. Review the refreshed comparison before applying.');
    const p=await workspace.api(`/twin/runs/${encodeURIComponent(run.id)}/plans`,{request_id:crypto.randomUUID(),revision:run.revision,horizon_min:60,max_delay_min:0});
    run=await workspace.api(`/twin/runs/${encodeURIComponent(run.id)}/apply-plan`,{plan_id:p.id,revision:run.revision});
    dirty=false;render(run);$('op-input-status').textContent='Demand reduction applied. Run the clock to observe thermal recovery.';
  });
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
  click('op-prototype-refresh',async()=>{await esp?.refreshStatus(true);render(await prototypeState());});
  $('op-run-select').onchange=()=>guarded(async()=>{if(!$('op-run-select').value)return;run=await workspace.api('/twin/runs/'+encodeURIComponent($('op-run-select').value));dirty=false;settingsFields(run);render(run);});
  click('op-start',()=>act(run.running?'pause':'start'));click('op-step',async()=>{const paused=!run.running;if(paused)await act('start');try{await act('step',{seconds:300});}finally{if(paused&&run.running)await act('pause');}});
  click('op-trip',()=>act('trip'));click('op-reconnect',()=>act('reconnect'));click('op-clear',()=>act('clear_fault'));
  click('op-apply-scenario',async()=>{dirty=false;await act('scenario',{scenario:$('op-scenario').value});});
  $('op-inputs').oninput=()=>{dirty=true;$('op-load-output').value=$('op-load').value+'%';};
  $('op-inputs').onsubmit=e=>{e.preventDefault();guarded(async()=>{const form=e.target.elements;const inputs={};for(const k of Object.keys(catalog.inputs))inputs[k]=k==='protection_enabled'?form[k].checked:k==='cooling'?form[k].value:Number(form[k].value);dirty=false;await act('inputs',{inputs});});};
  $('op-fault').onsubmit=e=>{e.preventDefault();guarded(()=>act('inject',{fault:e.target.elements.fault.value,severity:Number(e.target.elements.severity.value),duration_s:Number(e.target.elements.duration_s.value)}));};
  $('op-maintenance').onsubmit=e=>{e.preventDefault();guarded(async()=>{await act('maintenance',{maintenance:e.target.elements.maintenance.value,note:e.target.elements.note.value});e.target.elements.note.value='';dirty=false;populateInputs(run);});};
  $('op-settings-form').onsubmit=e=>{e.preventDefault();guarded(()=>act('settings',{settings:Object.fromEntries([...new FormData(e.target)].map(([k,v])=>[k,Number(v)]))}));};
  $('op-trend-channel').onchange=trend;$('op-model-reset').onclick=resetModelView;
  $('op-commissioning').onclick=e=>{e.preventDefault();workspace.view('commissioning');};
  async function physicalRelays(states){
    if(mode!=='prototype')return;
    if(esp&&esp.status()?.configured){
      // Wi-Fi board: proxy to the board's load API. Only the all-off form is used here; branch switching lives in the load panel.
      const r=await esp.setLoads({load1:!!states[0],load2:!!states[1],load4:!!states[3]});esp.applyLoads(r.loads);
      $('op-command-status').textContent=`Board acknowledged drive states · ${r.loads?.loads_on??'?'} branch(es) on. Contact state is not measured.`;
      if(current)render(current);return;
    }
    const r=await workspace.api('/relays',{states,request_id:crypto.randomUUID()});$('op-command-status').textContent=`Request ${r.status}. Await firmware acknowledgment; contacts remain unverified.`;
  }
  click('op-off',()=>physicalRelays([false,false,false,false]));
  $('op-reset-latch').onsubmit=e=>{e.preventDefault();guarded(async()=>{await workspace.api('/twin/prototype/reset-latch',{note:e.target.elements.note.value});render(await prototypeState());e.target.reset();});};
  function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  async function exportCurrent(){
    if(mode==='prototype'){await window.HaloEvidenceWorkflow.downloadRaw('/twin/prototype','prototype-twin-evidence.json');return;}
    if(!run)throw Error('Create or select an industrial run first.');const id=run.id,response=await HaloAuth.fetch('/api/halo/twin/runs/'+encodeURIComponent(id)+'/report');if(!response.ok)throw Error('Report could not be generated.');download(await response.blob(),id+'-report.zip');}
  async function adopt(s){replaySource=null;pendingInputs=null;clearTimeout(sliderTimer);sliderTimer=null;run=s;mode='industrial';window.HaloSession?.select('industrial');await loadCatalog();settingsFields(s);render(s);}
  click('op-report',exportCurrent);window.HaloOperations={export:exportCurrent,selectSource,adopt,act,refresh:async()=>{if(run){run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}return run;}};
  async function init(){if(ready||initializing)return;initializing=true;try{await loadCatalog();if(catalog.runs.length){let saved;try{saved=sessionStorage.getItem('halo-industrial-run');}catch{}const chosen=catalog.runs.find(r=>r.id===saved)||catalog.runs[0];run=await workspace.api('/twin/runs/'+encodeURIComponent(chosen.id));settingsFields(run);$('op-run-select').value=run.id;}ready=true;render(run);if(window.HaloSession?.source()==='prototype')await selectSource('prototype');schedule();}catch(e){error(e.message);}finally{initializing=false;buttons();}}
  window.addEventListener('halo:ready',init);
  window.addEventListener('halo:view',event=>{if(event.detail==='operate'){if(window.HaloSession?.source()==='reference'){workspace.view('twin');return;}if(ready){render(replaySource?HaloCommand.math.replaySnapshot(replaySource,replayIndex):mode==='industrial'?run:current);model().draw();schedule();}else init();}else{clearTimeout(timer);if(replaySource){current=mode==='industrial'?run:replaySource;replaySource=null;window.HaloSession?.paint();}}});
  document.addEventListener('visibilitychange',schedule);
  buttons();
})();
