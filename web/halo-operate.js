/* Two data sources, one view. Simulation commands cannot target physical relays. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), workspace=window.HaloWorkspace;
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,n=1)=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:n});
  const title=s=>String(s).replaceAll('_',' ');
  let mode='industrial', run=null, current=null, busy=false, catalog=null, timer=null, ready=false, dirty=false, selectedScenario=null;
  let twin=null,initializing=false,replaySource=null,replayIndex=0,sliderTimer=null,pendingInputs=null,sliding=false,reviewSource=null,observationSource=null,observationRequest=0,pollSerial=0;
  let requestedSource=null,switchingSource=false;
  let prototypeCache=null,prototypeFetching=null;
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
    // Keep review actions together; the study remains below the visual instruments.
    const decision=document.createElement('section');decision.id='op-decision-ribbon';
    decision.setAttribute('aria-label','Operating decision');
    decision.append(next.querySelector('.op-next-copy'));
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
    $('op-explore').append($('op-step'));$('op-start').hidden=true;
    const advanced=document.createElement('details');advanced.className='op-advanced';
    advanced.innerHTML='<summary>Scenarios, disturbances & model settings</summary>';
    $('op-industrial-controls').before(advanced);advanced.append($('op-industrial-controls'));
    // Keep the original model-led layout; place new instruments beneath it.
    grid.before(document.querySelector('.op-state-strip'));
    grid.after($('op-readings'));
    $('op-readings').after($('op-explore'));
    $('op-explore').after(decision);
    decision.after(document.querySelector('#op-workspace .op-replay'));
    document.querySelector('#op-workspace .op-replay').after(next);
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
    $('session-source').disabled=false;
    $('op-start').textContent=running?'Pause simulation':'Start simulation';
    $('op-start').disabled=busy||!run;$('op-step').disabled=busy||!run;
    $('op-report').disabled=busy||!run;$('op-trip').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-reconnect').disabled=busy||physical||!!current?.recovery_holds?.length;
    $('op-apply-scenario').disabled=busy||!run||current?.breaker==='OPEN';
    $('op-new').disabled=busy||!ready;$('op-create').disabled=busy||!ready;
    $('op-industrial').disabled=busy||!ready;$('op-prototype').disabled=busy||!ready;
    document.querySelectorAll('#view-operate form button, #op-industrial-controls form button, #op-prototype-controls form button, #op-maintenance button').forEach(b=>b.disabled=busy||!ready);
    $('op-clear').disabled=busy||!run;
    $('op-off').disabled=busy||!(current?.connection==='live'||(esp&&esp.packet().available&&esp.status()?.configured));
    $('op-running-note').textContent=running?(catalog?.server_clock?'Running - shared server clock.':'Running - pauses ticking when this view is hidden.'):'Paused - use Run or Step to advance.';
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
  let actionQueue=Promise.resolve();
  function act(action,extra={}){
    const target=mode==='industrial'&&!replaySource?run?.id:null;
    const pending=actionQueue.then(async()=>{
      if(replaySource)throw Error('Exit replay before changing the simulation.');
      if(!target||mode!=='industrial'||run?.id!==target)throw Error('The selected run changed. Review the current source before retrying.');
      const latest=window.HaloSession?.run();if(latest?.id===run.id&&latest.revision>run.revision)run=latest;
      if(action==='inputs')extra={...extra,inputs:{...run.inputs,...extra.inputs}};
      const r=await workspace.api(`/twin/runs/${encodeURIComponent(target)}/actions`,{action,revision:run.revision,request_id:crypto.randomUUID(),...extra});
      if(mode==='industrial'&&run?.id===target&&!replaySource){run=r;render(r);}
      return r;
    });
    // Multiple panels share this run. Serialize commands without rebasing a failed
    // server revision check or carrying queued actions into another asset.
    actionQueue=pending.catch(()=>{});return pending;
  }
  async function guarded(fn){
    if(busy)return;busy=true;buttons();error('');
    try{await fn();}catch(e){error(e.message);if(mode==='industrial'&&run&&e.status===409){try{run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}catch{}}}
    finally{busy=false;buttons();schedule();if(requestedSource&&!switchingSource)drainSource();else if(pendingInputs)flushSliders();}
  }
  function click(id,fn){$(id).addEventListener('click',()=>guarded(fn));}
  function schedule(){
    clearTimeout(timer);
    const ticket=++pollSerial;
    if(!ready||switchingSource||requestedSource||replaySource||document.hidden||!['view-operate','view-physics','view-maintenance'].some(id=>$(id)?.classList.contains('active')))return;
    timer=setTimeout(async()=>{
      if(busy){schedule();return;}
      const source=mode,id=run?.id;
      const applies=()=>ticket===pollSerial&&!busy&&!replaySource&&mode===source&&run?.id===id;
      try{
        // Reading telemetry must not lock navigation or simulate an operator action.
        if(source==='prototype'){
          const snapshot=await prototypeState();if(applies())render(snapshot);
        }else if(run&&catalog?.server_clock){
          const snapshot=await workspace.api('/twin/runs/'+encodeURIComponent(id));
          if(applies()&&snapshot.revision>=run.revision){run=snapshot;render(run);}
        }else if(run?.running)await guarded(()=>act('step',{seconds:run.inputs.speed}));
      }catch(e){if(applies())error(e.message);}
      finally{if(ticket===pollSerial)schedule();}
    },mode==='prototype'?2500:1500);
  }
  async function switchMode(next){
    if(busy||!ready)return;replaySource=null;pendingInputs=null;clearTimeout(sliderTimer);mode=next;dirty=false;error('');
    $('op-industrial').setAttribute('aria-pressed',String(mode==='industrial'));
    $('op-prototype').setAttribute('aria-pressed',String(mode==='prototype'));
    $('op-source').textContent=mode==='industrial'?'INDUSTRIAL SIMULATION':'PHYSICAL PROTOTYPE · ESP32';
    $('op-run-tools').hidden=mode==='prototype';$('op-prototype-refresh').hidden=mode!=='prototype';
    if(mode==='industrial'){
      if(!run&&catalog.runs.length){
        let saved;try{saved=sessionStorage.getItem('halo-industrial-run');}catch{}
        const chosen=catalog.runs.find(r=>r.id===saved)||catalog.runs[0];
        run=await workspace.api('/twin/runs/'+encodeURIComponent(chosen.id));settingsFields(run);$('op-run-select').value=run.id;
      }
      if(!requestedSource)render(run);
    }else{
      current=null;$('op-workspace').hidden=true;$('op-welcome').hidden=true;$('op-clock').textContent='Loading ESP32 measurements…';
      const snapshot=await prototypeState();if(!requestedSource)render(snapshot);
    }
    schedule();
  }
  /* Analysis from /twin/prototype and, in the same tick, the live board packet from /esp32/readings. */
  async function prototypeState(){
    // Cloud history can take longer than board acquisition. Refresh its summary
    // separately so it cannot hold up subsequent ESP32 instrument updates.
    if(!prototypeFetching){
      prototypeFetching=workspace.api('/twin/prototype').then(s=>{prototypeCache=s;return s;})
        .catch(e=>{if(!prototypeCache)throw e;return prototypeCache;}).finally(()=>{prototypeFetching=null;});
    }
    const pending=prototypeFetching;
    if(!prototypeCache){const [s]=await Promise.all([pending,esp?esp.poll():null]);return s;}
    if(esp)await esp.poll();
    return prototypeCache;
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
    loadsPanel?.update({packet:hw,status:st,latched:!!s.latched,busy,derived:window.HaloEsp32.math.deriveCurrents(hw,history)});
  }
  function populateInputs(s){
    const form=$('op-inputs');
    for(const [k,v] of Object.entries(s.inputs)){const field=form.elements[k];if(!field)continue;if(field.type==='checkbox')field.checked=v;else field.value=typeof v==='number'?Math.round(v*100)/100:v;}
    $('op-load-output').value=fmt(s.inputs.load_percent,0)+'%';
  }
  function settingsFields(s){
    $('op-settings-fields').innerHTML=Object.entries({...catalog?.settings,...s.settings}).map(([k,v])=>`<label>${esc(title(k))}<input type="number" step="any" name="${esc(k)}" value="${v}" required></label>`).join('');
  }
  function render(s){
    current=s;const physical=mode==='prototype';
    $('op-workspace').hidden=!s;$('op-welcome').hidden=!!s;
    if(!s){$('op-clock').textContent='Create or open a run';buttons();window.dispatchEvent(new CustomEvent('halo:operation-state',{detail:{snapshot:null,mode,replay:false}}));return;}
    if(!physical&&!replaySource){window.HaloSession?.bind(s);try{sessionStorage.setItem('halo-industrial-run',s.id);}catch{}}
    const t=s.telemetry,a=s.analysis;
    if($('view-operate').classList.contains('active')){$('connection').textContent=physical?title(s.connection)+' · ESP32':'Industrial · simulated';$('connection').className='pill';}
    $('op-industrial-controls').hidden=physical;$('op-prototype-controls').hidden=!physical;
    const wifiHardware=physical&&esp?.status()?.configured===true;
    $('op-waveform').hidden=wifiHardware;$('op-scope').hidden=!wifiHardware;
    document.querySelector('.op-hw-grid').hidden=!wifiHardware;
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
    if(!window.HaloControlCentre?.mounted){
    const changedModel=model().distribution!==!physical;
    model().setDistribution(!physical);if(changedModel)resetModelView();
    model().temperature(thermalValue,thermalSeverity,{warning:s.settings?.temperature_warning,critical:s.settings?.temperature_critical});model().draw();
    }
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
    const temp=HaloCommand.math.temperatureReading(s,mode,physical&&esp?esp.packet():null);
    // Measured channels and independent load-bank estimates never substitute for each other.
    const display=physical&&esp?esp.displaySnapshot():null;
    const derived=physical&&esp?window.HaloEsp32.math.deriveCurrents(esp.packet(),esp.history()):null;
    const loading=physical?prototypeLoading():null;
    // Voltages are always the board's own values; the live packet beats the stored frame copy.
    const secondaryV=display?display.channels.secondary_voltage.value:t.secondary_voltage;
    const primaryV=display?display.channels.primary_voltage.value:t.primary_voltage;
    const secondaryI=display?display.channels.secondary_current.value:t.secondary_current;
    const primaryI=display?display.channels.primary_current.value:t.primary_current;
    const rEff=derived&&derived.r_eff!=null?` · R_eff ${fmt(derived.r_eff,1)} Ω (${derived.loads_on} load${derived.loads_on===1?'':'s'} on)`:'';
    const secondaryNote=physical?`Measured ${fmt(secondaryI,3)} A · Estimated ${fmt(derived?.secondary_i,3)} A${derived?.disagreement?' · Readings disagree':''}`:`Current ${fmt(secondaryI,2)} A RMS`;
    const primaryNote=physical?`Measured ${fmt(primaryI,3)} A · Estimated ${fmt(derived?.primary_i,3)} A`:`Current ${fmt(primaryI,2)} A RMS${primaryVerified?'':' · unverified'}`;
    const readings=[['thermal',temp.label,temp.value,'°C',`${physical?(t.quality!=='qualified'?'Live probe · unverified':temp.critical===null?'Surface probe':`Critical ${fmt(temp.critical,0)} °C`):`${temp.critical===null?'Critical reference unavailable':`Critical ${fmt(temp.critical,0)} °C`} · oil ${fmt(t.oil_temperature)} °C`}`,temp.level],
      ['loading',physical?'Measured loading':'Mean-current loading',physical?loading.value:t.loading_percent,'%',physical?`Estimated ${fmt(display?.estimated_loading_percent)}% · 1 A rating`+rEff:`Highest phase ${fmt(t.max_phase_loading_percent)}%`,null],
      ['secondary','Secondary',secondaryV,'V',secondaryNote,null],
      ['primary','Primary',primaryV,'V',primaryNote,null]];
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
      if(wifiHardware){paintHardware(s);$('op-relays').hidden=true;}
      else{
        // USB-bridge fallback: the older relay command queue when Wi-Fi integration is not configured.
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
    HaloCommand.paint(s,{mode,replay:!!replaySource,model:model(),hardware:physical&&esp?esp.packet():null,loading});
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
    window.dispatchEvent(new CustomEvent('halo:operation-state',{detail:{snapshot:s,mode,replay:!!replaySource}}));
  }
  function prototypeLoading(){
    const packet=esp?.packet();
    const scope=!replaySource&&esp?window.HaloEsp32.math.scopePacket(packet,esp.history(),esp.status()):null;
    return HaloCommand.math.prototypeLoading(current,scope);
  }
  const trendChannels=[
    {key:'transformer_temperature',label:'Temperature',unit:'°C',color:'#ffad50'},
    {key:'loading_percent',label:'Loading',unit:'%',color:'#b5ce82'},
    {key:'secondary_current',label:'Secondary current',unit:'A',color:'#59d8c5'},
    {key:'secondary_voltage',label:'Secondary voltage',unit:'V',color:'#89bafa'}
  ];
  function trend(){
    if(!current)return;
    const history=mode==='prototype'&&!replaySource&&esp?esp.displayHistory().map(r=>({timestamp:r.timestamp,
      transformer_temperature:r.channels.surface_temperature.value,secondary_voltage:r.channels.secondary_voltage.value,
      secondary_current:r.channels.secondary_current.value,secondary_current_estimated:r.estimates?.secondary_current?.value,
      loading_percent:r.loading_percent,loading_percent_estimated:r.estimated_loading_percent})):current.history;
    if(!$('op-trend').children.length){
      $('op-trend').innerHTML=trendChannels.map(c=>`<section class="op-trend-card" data-channel="${c.key}"><div class="op-trend-heading"><h3>${c.label}</h3><span>${c.unit}</span></div><div class="op-trend-screen"><svg viewBox="0 0 480 200" role="img" aria-label="${c.label} over time"></svg></div></section>`).join('');
    }
    $('op-trend-note').textContent=`${history.length} samples · ${mode==='industrial'?'simulated time':'acquisition time'}`;
    const timeLabel=time=>new Date(time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    for(const channel of trendChannels){
      const {key,color}=channel,svg=$('op-trend').querySelector(`[data-channel="${key}"] svg`);
      const rows=history,estimatedKey=mode==='prototype'?key+'_estimated':null;
      const start=Date.parse(rows[0]?.timestamp),end=Date.parse(rows.at(-1)?.timestamp);
      if(key==='loading_percent'||key==='secondary_current')svg.closest('.op-trend-card').querySelector('h3').textContent=channel.label+(mode==='prototype'?' · measured / estimated':'');
      const valid=rows.filter(r=>Number.isFinite(r[key])&&Number.isFinite(Date.parse(r.timestamp)));
      const estimates=estimatedKey?rows.filter(r=>Number.isFinite(r[estimatedKey])&&Number.isFinite(Date.parse(r.timestamp))):[];
      if(!valid.length&&!estimates.length){svg.innerHTML='<text x="240" y="105" text-anchor="middle" class="op-trend-empty">No data yet</text>';continue;}
      const values=[...valid.map(r=>r[key]),...estimates.map(r=>r[estimatedKey])],low=Math.min(...values),high=Math.max(...values);
      const pad=Math.max(key==='secondary_current'?.05:1,(high-low)*.15),min=low-pad,max=high+pad;
      const x=r=>50+(Date.parse(r.timestamp)-start)/Math.max(1,end-start)*414,y=v=>170-(v-min)/(max-min)*150;
      let markup='';
      for(let i=0;i<=4;i++){
        const v=min+(max-min)*i/4,yy=y(v);
        markup+=`<path d="M50 ${yy}H464" class="op-trend-gridline"/><text x="42" y="${yy+4}" text-anchor="end">${fmt(v,key==='secondary_current'?2:1)}</text>`;
      }
      for(let i=0;i<=8;i++){const xx=50+414*i/8;markup+=`<path d="M${xx} 20V170" class="op-trend-gridline"/>`;}
      let path='',connected=false;
      for(const row of rows){
        if(!Number.isFinite(row[key])||!Number.isFinite(Date.parse(row.timestamp))){connected=false;continue;}
        path+=`${connected?'L':'M'}${x(row)},${y(row[key])} `;connected=true;
      }
      const last=valid.at(-1);
      markup+=`<path class="op-trend-line" data-basis="${mode==='prototype'?'measured':'simulated'}" d="${path}" stroke="${color}"/>${last?`<circle cx="${x(last)}" cy="${y(last[key])}" r="3" fill="${color}"/>`:''}<text x="50" y="191">${timeLabel(start)}</text><text x="464" y="191" text-anchor="end">${timeLabel(end)}</text>`;
      if(estimates.length){let expectedPath='',connected=false;for(const row of rows){if(!Number.isFinite(row[estimatedKey])||!Number.isFinite(Date.parse(row.timestamp))){connected=false;continue;}expectedPath+=`${connected?'L':'M'}${x(row)},${y(row[estimatedKey])} `;connected=true;}markup+=`<path class="op-trend-line" data-basis="estimated" d="${expectedPath}" stroke="#d9b8ff" stroke-dasharray="7 5"/><text x="460" y="14" text-anchor="end">Dashed: estimated</text>`;}
      svg.innerHTML=markup;
    }
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
  async function selectSource(next,{initial=false}={}){
    if(!['prototype','industrial','reference'].includes(next))return;
    if(next==='reference'&&!workspace.challenge){window.HaloSession?.paint();return;}
    requestedSource={next,initial:initial||!ready};window.HaloSession?.request(next);
    clearTimeout(timer);++pollSerial;
    if(!ready){init();return;}
    return drainSource();
  }
  async function drainSource(){
    if(!ready||busy||switchingSource||!requestedSource)return;
    switchingSource=true;
    try{
      while(requestedSource){
        const {next,initial}=requestedSource;requestedSource=null;
        document.body.dataset.twinInitialLoad=String(initial);document.body.dataset.twinSwitching='true';
        document.querySelectorAll('.view').forEach(v=>v.inert=true);
        try{
          if(next==='reference'){
            await workspace.useSource('replay');if(requestedSource)continue;
            window.HaloSession?.select(next);workspace.view('twin');
          }else{
            if(next==='prototype')await workspace.useSource('bench');
            if(requestedSource)continue;
            window.HaloSession?.select(next);await switchMode(next);
          }
        }catch(e){if(!requestedSource){if(next!=='reference'){mode=next;window.HaloSession?.select(next);render(null);}error(e.message);}}
      }
    }finally{
      switchingSource=false;document.body.dataset.twinSwitching='false';delete document.body.dataset.twinInitialLoad;window.HaloSession?.settled();
      document.querySelectorAll('.view').forEach(v=>v.inert=false);buttons();schedule();
    }
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
  $('op-model-reset').onclick=resetModelView;
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
  click('op-report',exportCurrent);window.HaloOperations={export:exportCurrent,selectSource,adopt,act,displaySnapshot:()=>esp?.displaySnapshot(),displayHistory:()=>esp?.displayHistory()||[],current:()=>({snapshot:current,mode,replay:!!replaySource}),refresh:async()=>{if(run){run=await workspace.api('/twin/runs/'+encodeURIComponent(run.id));render(run);}return run;}};
  async function init(){if(ready||initializing)return;initializing=true;try{await loadCatalog();ready=true;if(!requestedSource)requestedSource={next:window.HaloSession?.source()||'prototype',initial:true};await drainSource();}catch(e){error(e.message);}finally{initializing=false;buttons();}}
  window.addEventListener('halo:ready',init);
  window.addEventListener('halo:view',event=>{if(['operate','physics','maintenance'].includes(event.detail)){if(switchingSource||requestedSource)return;if(window.HaloSession?.source()==='reference'){workspace.view('twin');return;}if(ready){render(replaySource?HaloCommand.math.replaySnapshot(replaySource,replayIndex):mode==='industrial'?run:current);if(!window.HaloControlCentre?.mounted)model().draw();schedule();}else init();}else{clearTimeout(timer);if(replaySource){current=mode==='industrial'?run:replaySource;replaySource=null;window.HaloSession?.paint();}}});
  document.addEventListener('visibilitychange',schedule);
  buttons();
})();
