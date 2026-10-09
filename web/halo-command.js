/* One observed packet paints every instrument. No hardware commands or invented samples. */
(() => {
  'use strict';
  const finite=v=>typeof v==='number'&&Number.isFinite(v), clamp=v=>Math.max(0,Math.min(100,v));
  const names={thermal:'Thermal',electrical:'Electrical',loading:'Loading',historical:'Accumulated',environmental:'Ambient',oil:'Oil input'};
  function components(s,mode){
    const a=s.analysis||{},t=s.telemetry||{},qualified=t.quality==='qualified';
    const available={thermal:qualified&&finite(t.transformer_temperature),electrical:qualified&&finite(mode==='prototype'?t.secondary_voltage:t.primary_voltage),loading:qualified&&finite(t.loading_percent),historical:mode==='industrial',environmental:qualified&&finite(t.ambient_temperature),oil:mode==='industrial'&&finite(t.oil_condition)};
    return Object.keys(names).map(key=>({key,label:names[key],value:available[key]&&finite(a.stress?.[key])?a.stress[key]:null}));
  }
  function changeNote(s){
    const a=s.analysis||{},t=s.telemetry||{},past=(s.history||[]).filter(r=>r.timestamp<t.timestamp||(r.timestamp===t.timestamp&&finite(r.input_context?.revision)&&finite(s.revision)&&r.input_context.revision<s.revision&&['loading_percent','transformer_temperature','phase_imbalance_percent'].some(k=>r[k]!==t[k]))).at(-1);
    if(t.quality&&t.quality!=='qualified')return 'Waiting for qualified readings before interpreting a change.';
    if(!past)return 'First observation · build a history to see what changes.';
    const dt=finite(t.transformer_temperature)&&finite(past.transformer_temperature)?t.transformer_temperature-past.transformer_temperature:null;
    const dl=finite(t.loading_percent)&&finite(past.loading_percent)?t.loading_percent-past.loading_percent:null;
    if(dt!==null&&dt>.1&&dl!==null&&Math.abs(dl)<3)return 'Temperature rising at nearly constant load.';
    if(dt!==null&&dt<-.1&&dl!==null&&Math.abs(dl)<3)return 'Temperature falling; thermal recovery is in progress.';
    if(dl!==null&&dl>3)return 'Load increased; current changes before temperature.';
    if(dl!==null&&dl< -3)return 'Load reduced; thermal recovery takes time.';
    if((t.phase_imbalance_percent||0)>0)return 'Phase currents differ; inspect phase allocation.';
    return a.status==='UNKNOWN'?'Channel evidence is insufficient for a condition score.':'No large change since the preceding observation.';
  }
  function dialState(assessment){
    const a=assessment||{},held=!finite(a.health_index);
    return {held,score:held?null:a.health_index,stress:finite(a.operating_stress_index)?a.operating_stress_index:null,
      status:a.status||'UNKNOWN',title:held?'Health unavailable':'Health screening'};
  }
  function planPresentation(p){
    const r=p?.recommendation,available=p?.available===true&&!!r;
    const reduction=available&&finite(r.reduction_pct)&&r.reduction_pct>0;
    const series=available?[{label:'Continue unchanged',points:p.baseline?.points||[],color:'#a15b28'}]:[];
    if(reduction)series.push({label:`Reduce demand ${r.reduction_pct}%`,points:r.points||[],color:'#246eaa'});
    return {available,reduction,series,title:reduction?'Compare the next hour':'If present inputs continue',
      status:!p?.available?(p?.holds||[]).join(' ')||'A qualified comparison is unavailable.':!r?'No demand reduction meets the declared constraints. Inspect the active condition.':reduction?`${r.reduction_pct}% demand reduction · immediate simulated action.`:'No intervention proposed. One unchanged-input trajectory is shown; this is not a safety clearance.'};
  }
  function temperatureReading(s,mode){
    const t=s?.telemetry||{},settings=s?.settings||{},qualified=t.quality==='qualified';
    const value=qualified&&finite(t.transformer_temperature)?t.transformer_temperature:null;
    const critical=finite(settings.temperature_critical)?settings.temperature_critical:null;
    const warning=finite(settings.temperature_warning)?settings.temperature_warning:null;
    return {value,critical,warning,label:mode==='prototype'?'Measured surface':'Modelled hot-spot',
      level:value===null?'UNKNOWN':critical!==null&&value>=critical?'CRITICAL':warning!==null&&value>=warning?'WARNING':'NORMAL'};
  }
  function reviewContext(s,mode,replay=false){
    const id=s?.id||null;
    return {id,revision:s?.revision??null,mode,replay,available:!!id&&mode==='industrial'&&!replay,
      label:mode==='prototype'?'Physical ESP32 measurements':replay?'Recorded simulation state':'Selected industrial simulation',
      note:mode==='prototype'?'Review measured channels and commissioning. Simulation actions do not apply to this source.':replay?'Exit replay to investigate the current run. Recorded evidence remains unchanged.':'Inspect the signals, compare a simulated action, then document the follow-up on this run.'};
  }
  function sameReviewSource(context,s,mode,replay=false){
    return !!context?.available&&mode==='industrial'&&!replay&&context.id===s?.id;
  }
  function sameObservationSource(context,s,mode,replay=false){
    return sameReviewSource(context,s,mode,replay)&&Number.isInteger(context.revision)&&context.revision===s.revision;
  }
  function replaySnapshot(source,index){
    const rows=source.history||[],row=rows[index];if(!row)return null;
    const context=row.input_context||{},retained=row.component_data_available===true&&row.analysis;
    const analysis=retained?row.analysis:{status:row.status||'UNKNOWN',health_index:null,stress:{},alerts:[],maintenance:['Component assessment was not retained for this observation.'],health_evidence:{note:'Recorded readings only. Historical component scores are unavailable; current settings are not used to recreate them.'}};
    return {...source,...context,telemetry:{...row,source:source.source||'industrial'},analysis,
      inputs:row.inputs||context.inputs||{},settings:row.settings||context.settings||{},
      fault:context.fault??null,trip:context.trip??null,scenario:context.scenario??'UNKNOWN',revision:context.revision??null,
      relay_states:row.relay_states??null,command:null,latched:context.latched??false,connection:'recorded',
      control_enabled:false,load_control_available:false,evidence:[],holds:['Historical commissioning and physical contact state are unavailable.'],
      elapsed_s:row.elapsed_s||0,breaker:row.breaker||'UNKNOWN',running:false,
      health_band:analysis.health_index==null?'Unavailable':'Recorded screening estimate',
      protection_state:'RECORDED SNAPSHOT',recovery_holds:['Exit replay to operate the live simulation.'],
      prediction:row.prediction||{minutes_to_critical:null,note:'A forecast was not retained for this observation.'},
      condition:{equivalent_age_hours:row.equivalent_age_hours??null,insulation_consumed_percent:null},
      history:rows.slice(0,index+1),events:(source.events||[]).filter(e=>(e.timestamp||e.created_at)<row.timestamp||((e.timestamp||e.created_at)===row.timestamp&&finite(row.event_cursor)&&finite(e.id)&&e.id<=row.event_cursor)),
      replay:true,component_data_available:!!retained};
  }
  const math={components,changeNote,replaySnapshot,dialState,planPresentation,temperatureReading,reviewContext,sameReviewSource,sameObservationSource};
  if(typeof module!=='undefined'&&module.exports)module.exports=math;
  if(typeof window==='undefined')return;
  const $=id=>document.getElementById(id),esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,n=1)=>finite(v)?v.toLocaleString(undefined,{maximumFractionDigits:n}):'—';
  let wave=null,selection=null,lastContext=null,planToken=0,planTimer=null,plan=null,lastPlanKey=null;
  const detail={thermal:['surface',2,'Temperature and thermal response'],electrical:['voltage',0,'Voltage and phase-current evidence'],loading:['current',3,'Demand and load current'],historical:['transformer',-1,'Recorded stress history'],environmental:['transformer',2,'Ambient context for the transformer'],oil:['transformer',3,'Simulated oil condition']};
  function highlight(){
    if(!lastContext)return;
    const {model,mode}=lastContext;
    document.querySelectorAll('#op-stress button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.component===selection)));
    const reading=selection==='thermal'||selection==='environmental'?'thermal':selection==='electrical'?(mode==='prototype'?'secondary':'primary'):selection==='loading'?'loading':null;
    document.querySelectorAll('#op-readings .op-reading').forEach(el=>el.dataset.highlight=String(el.dataset.reading===reading));
    if(!selection)return;
    const [part,,label]=detail[selection];const industrialPart={thermal:'radiator',electrical:'bushings',loading:'bushings',historical:'transformer',environmental:'transformer',oil:'transformer'}[selection];model.select(mode==='industrial'?industrialPart:part);
    $('op-part').textContent=label+(mode==='industrial'?' · explanatory geometry; no fault localization':' · illustrative component');
    $('op-component-note').textContent=selection==='historical'?'Accumulated stress is modelled history, not a sensor reading.':selection==='oil'?'Oil condition is a simulation input; the physical prototype does not measure oil.':label+' highlighted in the readings and model.';
  }
  function paint(s,context){
    lastContext=context;const {mode,replay}=context,a=s.analysis,t=s.telemetry;
    wave ||= window.HaloWaveform?.create($('op-waveform'));
    const plot=$('op-waveform').querySelector('.hw-plot'),disclosure=$('op-waveform').querySelector('.hw-disclosure');
    if(plot&&disclosure&&disclosure.nextElementSibling!==plot){disclosure.after(plot);plot.after($('op-waveform').querySelector('.hw-scale-note'));}
    const waveDetails=$('op-waveform').querySelector('.hw-details');
    if(waveDetails&&!waveDetails.dataset.compact){
      waveDetails.dataset.compact='true';waveDetails.querySelector('summary').textContent='Waveform controls · pause & inspect';
      for(const selector of ['.hw-toolbar','.hw-inspection','.hw-footnote'])waveDetails.append($('op-waveform').querySelector(selector));
    }
    const referenceCurrent=finite(s.settings?.rated_kva)&&finite(s.settings?.secondary_v)&&s.settings.secondary_v>0?s.settings.rated_kva*1000/(Math.sqrt(3)*s.settings.secondary_v):null;
    wave?.update({mode,telemetry:t,quality:t.quality,replay,referenceCurrent,sourceLabel:replay?'Recorded incident':mode==='industrial'?'Industrial simulation':'Physical prototype'});
    const d=dialState(a),{held,score}=d;
    // A health hold is the headline. A separate stress metric cannot replace it.
    $('op-dial-title').textContent=d.title;
    $('op-health').textContent=held?(d.status==='UNKNOWN'?'—':d.status==='NORMAL'?'Held':d.status==='TRIP'?'Tripped':'Review'):num(score,0);$('op-dial-scale').hidden=held;
    $('op-dial').dataset.held=String(held);
    $('op-score-direction').hidden=held;
    $('op-score-direction').textContent=held?'':'Combined screening · 100 = less modelled stress';
    $('op-health-ring').style.strokeDashoffset=String(553*(1-(finite(score)?clamp(score):0)/100));
    $('op-dial').dataset.level=d.status;
    $('op-dial').setAttribute('aria-label',`${$('op-dial-title').textContent}: ${num(score,0)}${finite(score)?' out of 100':''}. ${held?'Health assessment unavailable. ':''}${a.status}`);
    $('op-health-band').textContent=held?(d.status==='UNKNOWN'?'Evidence unavailable':d.status+' · health assessment withheld'):a.status==='NORMAL'?'Screening estimate':a.status+' · review signals';
    $('op-change').textContent=changeNote(s);
    const focusedContribution=$('op-stress').contains(document.activeElement)?document.activeElement.dataset.component:null;
    const extraOpen=$('op-stress').querySelector('details')?.open,contributions=components(s,mode).map(c=>`<button type="button" class="op-contribution" data-component="${c.key}" ${c.value===null?'disabled':''} aria-pressed="${c.key===selection}"><span>${c.label}</span><i><b style="transform:scaleX(${c.value===null?0:clamp(c.value)/100})"></b></i><strong>${c.value===null?'N/A':num(c.value,0)}</strong></button>`);
    $('op-stress').innerHTML=contributions.slice(0,4).join('')+`<details ${extraOpen?'open':''}><summary>Ambient & simulated oil input</summary>${contributions.slice(4).join('')}${mode==='industrial'?`<p class="op-oil-input">Simulated oil condition: <strong>${num(t.oil_condition,0)}/100</strong>. A scenario input, separate from the combined health screening above; no oil measurement is implied.</p>`:''}</details>`;
    $('op-stress').querySelectorAll('button').forEach(b=>b.onclick=()=>{selection=b.dataset.component;highlight();});
    if(focusedContribution)$('op-stress').querySelector(`[data-component="${focusedContribution}"]:not(:disabled)`)?.focus({preventScroll:true});
    $('op-component-note').textContent=mode==='prototype'?'Oil and accumulated insulation stress are unavailable on this prototype.':'Stress factors · 0 = none indicated, 100 = high. Select a factor to inspect.';
    highlight();
    $('op-phase-readout').hidden=mode!=='industrial';
    $('op-phase-readout').textContent=`A ${num(t.phase_current_a)} A · B ${num(t.phase_current_b)} A · C ${num(t.phase_current_c)} A · neutral ${num(t.neutral_current)} A RMS`;
    $('op-compare').hidden=mode!=='industrial'||replay;
    $('op-replay-banner').hidden=!replay;$('op-explore').hidden=!!replay;
    if(replay||mode!=='industrial'){invalidate();return;}
    const key=s.id+':'+s.revision;
    if(lastPlanKey!==key){
      lastPlanKey=key;plan=null;$('op-compare-apply').disabled=true;
      $('op-compare-status').textContent='Comparing this recorded state…';
      $('op-compare-chart').innerHTML='';$('op-compare-metrics').textContent='';$('op-compare-legend').innerHTML='';
      clearTimeout(planTimer);const token=++planToken;
      planTimer=setTimeout(async()=>{
        try{const p=await HaloWorkspace.api(`/twin/runs/${encodeURIComponent(s.id)}/intervention-preview?revision=${s.revision}&horizon_min=60&max_delay_min=0`);if(token!==planToken)return;plan=p;drawPlan(p);}
        catch(e){if(token===planToken){$('op-compare-status').textContent=e.status===409?'State changed; the next comparison will use the latest readings.':'Comparison unavailable: '+e.message;$('op-compare-apply').disabled=true;}}
      },220);
    }
  }
  function invalidate(){clearTimeout(planTimer);planToken++;lastPlanKey=null;plan=null;$('op-compare-apply').disabled=true;}
  function drawPlan(p){
    const r=p.recommendation,view=planPresentation(p);
    $('op-compare-heading').textContent=view.title;
    $('op-compare-status').textContent=view.status;
    $('op-compare-apply').disabled=!view.reduction;$('op-compare-apply').hidden=!view.reduction;
    $('op-compare-apply').textContent=view.reduction?`Apply ${r.reduction_pct}% reduction`:'No reduction to apply';
    $('op-compare-legend').innerHTML=view.series.map((series,i)=>`<span data-curve="${i}">${esc(series.label)}</span>`).join('');
    $('op-compare-chart').setAttribute('aria-label',view.reduction?'Conditional modelled hot-spot temperature: unchanged input and reduced demand':'Conditional modelled hot-spot temperature with unchanged inputs; no intervention proposed');
    if(!view.available){$('op-compare-chart').innerHTML='<text x="24" y="105" fill="#566678" font-size="15">Comparison held until the operating condition is reviewed.</text>';$('op-compare-metrics').innerHTML='';return;}
    const rows=view.series.map(series=>series.points),values=rows.flat().map(x=>x.temperature_c).filter(finite);
    if(!values.length){$('op-compare-chart').innerHTML='';$('op-compare-metrics').textContent='Trajectory samples unavailable.';return;}
    const low=Math.min(...values)-3,high=Math.max(...values)+3;
    const x=v=>46+v/p.horizon_min*630,y=v=>160-(v-low)/(high-low)*130;
    let svg='';for(let i=0;i<3;i++){const v=low+(high-low)*i/2;svg+=`<path d="M46 ${y(v)}H676" stroke="#d5dfe7"/><text x="4" y="${y(v)+4}" fill="#536476" font-size="12">${num(v,0)}°</text>`;}
    rows.forEach((row,i)=>svg+=`<path data-trajectory="${i}" d="${row.map((v,n)=>(n?'L':'M')+x(v.minute)+','+y(v.temperature_c)).join(' ')}" fill="none" stroke="${view.series[i].color}" stroke-width="3" ${i||!view.reduction?'':'stroke-dasharray="6 4"'}/>`);
    svg+=`<text x="46" y="187" fill="#536476" font-size="12">Now</text><text x="614" y="187" fill="#536476" font-size="12">+${num(p.horizon_min,0)} min</text>`;$('op-compare-chart').innerHTML=svg;
    $('op-compare-legend').dataset.single=String(!view.reduction);
    $('op-compare-metrics').innerHTML=`<div><span>Unchanged input · peak</span><strong>${num(p.baseline.peak_c)} °C</strong></div>${view.reduction?`<div><span>Reduced demand · peak</span><strong>${num(r.peak_c)} °C</strong></div><div><span>Energy curtailed · ${num(p.horizon_min,0)} min</span><strong>${num(r.curtailed_kwh,2)} kWh</strong></div>`:''}<div><span>240 min sensitivity peak</span><strong>${num(r.sensitivity_peak_c)} °C</strong></div>`;
  }
  window.HaloCommand={paint,invalidate,plan:()=>plan,math};
})();
