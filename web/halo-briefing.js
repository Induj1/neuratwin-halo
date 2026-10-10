/* Industrial extensions and PDF export. Prototype instruments retain their data path. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id),esc=v=>String(v??'Unavailable').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,n=1)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:n}):'—';
  let state=null,token=0,source=null;
  const toolbar=document.querySelector('#view-operate .op-toolbar');if(!toolbar)return;
  const exportButton=document.createElement('button');exportButton.id='op-export-pdf';exportButton.textContent='Export PDF';exportButton.disabled=true;toolbar.append(exportButton);
  const dialog=document.createElement('dialog');dialog.className='briefing-export';dialog.innerHTML=`<form><h2>Export report</h2><p>All retained readings, charts and decisions.</p><label>From <input name="start" type="datetime-local"></label><label>To <input name="end" type="datetime-local"></label><small>Leave dates empty for all retained records. Times use this device’s timezone.</small><p class="briefing-export-status" role="status"></p><div class="case-actions"><button type="button" data-close>Cancel</button><button type="submit" class="primary">Download PDF</button></div></form>`;document.body.append(dialog);
  exportButton.onclick=()=>{dialog.querySelector('[role=status]').textContent='';dialog.showModal();};dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.querySelector('form').onsubmit=async event=>{
    event.preventDefault();const current=window.HaloOperations.current();if(!current.snapshot)return;
    const form=event.currentTarget,button=form.querySelector('[type=submit]'),status=form.querySelector('[role=status]');button.disabled=true;status.textContent='Preparing report…';
    try{
      const physical=current.mode==='prototype',id=physical?'BENCH-001':current.snapshot.id;
      const body={revision:physical?null:current.snapshot.revision,
        lifetime_assumptions:window.HaloLifetime?.parameters()||null,
        physics_options:window.HaloPhysics?.options()||null,
        start:form.elements.start.value?new Date(form.elements.start.value).toISOString():null,
        end:form.elements.end.value?new Date(form.elements.end.value).toISOString():null};
      if(physical&&!current.replay){body.display_current=HaloOperations.displaySnapshot();body.display_history=HaloOperations.displayHistory();}
      const response=await HaloAuth.fetch('/api/halo/twin/reports/'+encodeURIComponent(id)+'/pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(!response.ok){const error=await response.json();throw Error(typeof error.detail==='string'?error.detail:'Report inputs could not be accepted.');}
      const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='neuratwin-'+current.mode+'-report.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);dialog.close();
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
  };
  const panel=document.createElement('section');panel.id='op-engineering';panel.className='panel briefing-panel';panel.hidden=true;
  panel.innerHTML=`<div class="briefing-heading"><h2>Electrical & thermal studies</h2><button id="briefing-blind">Blind fault challenge</button></div><div class="briefing-metrics"><div><span>Impedance</span><strong id="briefing-z">—</strong></div><div><span>Prospective fault current</span><strong id="briefing-fault">—</strong></div><div><span>Tank pressure · simulated</span><strong id="briefing-pressure">—</strong></div><div><span>Pressure rise</span><strong id="briefing-rise">—</strong></div></div><p id="briefing-basis" class="case-muted"></p><div class="case-actions"><button id="briefing-electrical">Review electrical readings</button><button id="briefing-thermal">Compare cold / hot</button><button id="briefing-maintenance">Open maintenance</button><button id="briefing-evaluation">Evaluation results</button></div><div id="briefing-result" role="status"></div>`;
  document.querySelector('#op-workspace .op-bottom-grid').before(panel);
  function paint(detail){
    state=detail;const s=detail.snapshot,physical=detail.mode==='prototype';exportButton.disabled=!s||!!detail.replay;
    panel.hidden=physical||!s||!!detail.replay;
    const key=detail.mode+':'+s?.id;if(key!==source){source=key;++token;$('briefing-result').replaceChildren();}
    if(panel.hidden)return;
    const e=s.electrical_model,t=s.telemetry;
    $('briefing-z').textContent=num(e?.transformer_impedance_percent,2)+'%';$('briefing-fault').textContent=num(e?.prospective_rms_a,0)+' A RMS';
    $('briefing-pressure').textContent=num(t.pressure_kpa)+' kPa gauge';$('briefing-rise').textContent=num(t.pressure_rate_kpa_s)+' kPa/s';
    $('briefing-basis').textContent='Three-phase terminal fault estimate · '+(s.profile?.impedance_basis||'illustrative').replaceAll('_',' ')+' parameters · '+num(e?.frequency_hz,0)+' Hz';
    $('briefing-thermal').disabled=s.breaker!=='CLOSED'||!!s.fault;
  }
  window.addEventListener('halo:operation-state',e=>paint(e.detail));
  async function study(button,path,render){
    if(!state?.snapshot||state.mode!=='industrial')return;
    const origin={id:state.snapshot.id,revision:state.snapshot.revision},request=++token;button.disabled=true;
    $('briefing-result').textContent='Preparing study…';
    try{const result=await HaloWorkspace.api('/twin/runs/'+encodeURIComponent(origin.id)+path,{revision:origin.revision});if(request!==token)return;
      $('briefing-result').innerHTML=`<p class="case-muted">Recorded study · revision ${origin.revision}</p>`+render(result);
    }catch(error){if(request===token)$('briefing-result').textContent=error.message;}finally{button.disabled=false;}
  }
  $('briefing-electrical').onclick=e=>study(e.currentTarget,'/electrical-review',r=>`<h3>${esc(r.assessment.classification.replaceAll('_',' '))}</h3><p>${esc(r.assessment.action)}</p><ul>${[...r.assessment.evidence,...r.assessment.missing].map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p class="case-muted">${esc(r.note)}</p>`);
  $('briefing-thermal').onclick=e=>study(e.currentTarget,'/thermal-pair',r=>{
    const lines=r.cases.map(c=>c.forecast.points),values=lines.flat().map(p=>p.temperature_c),low=Math.min(...values)-3,high=Math.max(...values)+3;
    const x=m=>45+m/60*615,y=v=>180-(v-low)/(high-low)*155;
    const grid=Array.from({length:4},(_,i)=>{const v=low+(high-low)*i/3;return `<line x1="45" x2="660" y1="${y(v)}" y2="${y(v)}" stroke="#b9d4c522"/><text x="3" y="${y(v)+4}">${num(v,0)}°</text>`;}).join('');
    const graph=grid+lines.map((line,i)=>`<path d="${line.map((p,n)=>(n?'L':'M')+x(p.minute)+','+y(p.temperature_c)).join(' ')}" stroke="${i?'#efa94f':'#59d8c5'}" fill="none" stroke-width="2.5"/>`).join('');
    return `<h3>Same demand. Different starting temperature.</h3><svg class="briefing-thermal-chart" viewBox="0 0 700 220" role="img" aria-label="Cool and already-hot transformer thermal comparison">${graph}<text x="45" y="207">Now</text><text x="606" y="207">60 min</text></svg><div class="briefing-metrics">${r.cases.map(c=>`<div><span>${esc(c.label)}</span><strong>${num(c.forecast.peak_c)} °C peak</strong><small>${c.time_to_limit.minutes_to_critical==null?'No crossing in forecast horizon':num(c.time_to_limit.minutes_to_critical)+' min to critical'}</small></div>`).join('')}</div><p class="case-muted">${esc(r.note)}</p>`;
  });
  $('briefing-maintenance').onclick=()=>HaloCase.openRunMaintenance(state.snapshot.id);
  $('briefing-blind').onclick=()=>HaloWorkspace.view('evidence');
  $('briefing-evaluation').onclick=async e=>{
    const button=e.currentTarget,request=++token;button.disabled=true;$('briefing-result').textContent='Evaluating held-out synthetic events…';
    try{const r=await HaloWorkspace.api('/twin/electrical-evaluation');if(request!==token)return;
      $('briefing-result').innerHTML=`<h3>Electrical diagnosis · synthetic evaluation</h3><div class="briefing-metrics"><div><span>Exact class match</span><strong>${num(100*r.accuracy)}%</strong></div><div><span>Threshold baseline</span><strong>${num(100*r.baseline_accuracy)}%</strong></div><div><span>Non-abstained coverage</span><strong>${num(100*r.coverage)}%</strong></div><div><span>False alarms / normal events</span><strong>${r.false_alarm_events} / ${r.normal_event_denominator}</strong></div></div><table><thead><tr><th>Class</th><th>Cases</th><th>Precision</th><th>Recall</th></tr></thead><tbody>${Object.entries(r.classes).map(([k,v])=>`<tr><td>${esc(k.replaceAll('_',' '))}</td><td>${v.count}</td><td>${v.precision===null?'—':num(100*v.precision)+'%'}</td><td>${num(100*v.recall)}%</td></tr>`).join('')}</tbody></table><p>${esc(r.source)}</p><p class="case-muted">${esc(r.limitations.join(' '))}</p>`;
    }catch(error){if(request===token)$('briefing-result').textContent=error.message;}finally{button.disabled=false;}
  };
})();
