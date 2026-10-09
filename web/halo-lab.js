/* Acquisition-bound experiments. Emulator and physical controls never share a path. */
(()=>{'use strict';
const H=window.HaloWorkspace,$=id=>document.getElementById(id),esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(x,n=2)=>x==null?'—':Number(x).toLocaleString(undefined,{maximumFractionDigits:n});
let exp=null,diag=null,reference=null,busy=false,cursor=null,proofId=null,timer=null,started=false,ready=false,referenceLocked=false,referenceRow=null;
const active=()=>$('view-lab').classList.contains('active'),base=()=>'/lab/experiments/'+encodeURIComponent(exp.id);
const api=(path,body)=>H.api(path,body);
function error(text){$('lab-error').textContent=text||'';$('lab-error').hidden=!text;}
async function task(fn){if(busy||!ready)return;busy=true;buttons();error('');try{await fn();}catch(e){error(e.message);if(e.status===409&&exp){try{exp=await api(base());paint();}catch{}}}finally{busy=false;buttons();schedule();}}
function buttons(){const locked=busy||!ready,stopped=!exp||exp.state!=='recording',old=!!exp&&cursor!==null&&cursor<exp.rows.length-1;
 document.querySelectorAll('#view-lab button').forEach(b=>b.disabled=locked);
 ['lab-freeze','lab-sync','lab-stop'].forEach(id=>$(id).disabled=locked||stopped||old);
 $('lab-freeze').disabled=locked||stopped||old||!!exp?.forecast_hold;
 $('lab-advance').disabled=locked||stopped||old||exp?.source!=='software_emulator';
 $('lab-export').disabled=locked||!exp;$('lab-latest').disabled=locked||!old;
 $('lab-calibration-draft').disabled=locked||reference?.source!=='measured';
 $('lab-load').querySelector('button').disabled=locked||stopped||old||exp?.source!=='software_emulator';
 $('lab-marker').querySelector('button').disabled=locked||stopped||old;
 $('lab-reference').querySelectorAll('button').forEach(b=>b.disabled=locked||!currentDiagnostics()?.latest);
 $('lab-saved').disabled=locked;$('lab-cursor').disabled=locked||!exp;
}
function schedule(){clearTimeout(timer);if(!active()||document.hidden||!exp||exp.source!=='measured'||exp.state!=='recording')return;
 timer=setTimeout(()=>task(async()=>{const latest=cursor===null||cursor===exp.rows.length-1;exp=await api(base()+'/actions',{revision:exp.revision,action:'capture'});if(latest)cursor=null;await loadDiagnostics();paint();}),3500);
}
async function list(){const r=await api('/lab/experiments');$('lab-saved').innerHTML='<option value="">Select a recording…</option>'+r.experiments.map(e=>`<option value="${esc(e.id)}">${esc(e.name)} · ${e.source==='measured'?'physical recording':'emulator'} · ${esc(e.state)}</option>`).join('');$('lab-saved').value=exp?.id||'';}
async function loadDiagnostics(){diag=await api('/lab/commissioning');paintDiagnostics();}
function currentDiagnostics(){if(exp?.source==='software_emulator')return exp.diagnostics;return diag?.diagnostics;}
function paintDiagnostics(){const d=currentDiagnostics();if(!d)return;
 $('lab-diagnostics-context').textContent=exp?.source==='software_emulator'?'Software fixture channels below. Physical commissioning holds remain listed separately.':`Physical acquisition · ${d.connection} · ${d.age_s==null?'no sample':num(d.age_s,1)+' seconds since acquisition'}`;
 $('lab-channels').innerHTML=d.channels.map(c=>`<tr><td><strong>${esc(c.channel.replaceAll('_',' '))}</strong><small>${esc(c.unit)}</small></td><td>${num(c.raw,3)} ${esc(c.raw_unit)}${c.bias_mv==null?'':`<small>DC bias ${num(c.bias_mv)} mV</small>`}</td><td>${num(c.observed,3)} ${esc(c.unit)}</td><td>${c.min_mv==null?'No ADC range report':num(c.min_mv)+'–'+num(c.max_mv)+' mV'}<small>${esc(c.flags.join(', ')||'No channel flags reported')}</small></td></tr>`).join('');
 const link=diag?.device_link,age=link?(Date.now()-new Date(link.received_at).getTime())/1000:null;
 $('lab-link').textContent=`${d.frames} captured frames · ${d.sequence_gaps} sequence gaps · ${d.boot_changes} boot changes. `+(exp?.source==='software_emulator'?'Virtual readings never enter physical acquisition.':link?`Bridge last reported ${esc(link.chip)} · protocol ${link.protocol} · ${age>12?'historical status':link.compatible?'configuration agrees':'configuration unresolved'} · ${link.pending_frames} queued frames. Report age ${num(age,0)} s.`:'No bridge handshake report received.');
 // Pin the exact acquisition when a reference form is first focused.
 if(!referenceLocked)referenceRow=d.latest;
 $('lab-reference-frame').textContent=referenceRow?`Reference attaches to ${referenceRow.evidence_id} · ${new Date(referenceRow.timestamp).toLocaleTimeString()}${referenceLocked?' · pinned while editing':''}.`:'Await a captured sample before recording a reference.';
 $('lab-reference').dataset.evidence=referenceRow?.evidence_id||'';
 $('lab-hardware-holds').innerHTML=(diag?.holds||[]).map(x=>`<li>${esc(x)}</li>`).join('')||'<li>No software profile holds recorded. This is not electrical approval.</li>';
 $('lab-reference-history').innerHTML=(diag?.references||[]).map(r=>`<p><strong>${esc(r.channel)}</strong> · ${esc(r.source)} · error ${num(r.error,3)} ${esc(r.unit)} · ${r.within_tolerance===null?'no calibrated reading':r.within_tolerance?'within entered tolerance':'outside entered tolerance'} · ${esc(r.instrument)}</p>`).join('')||'<p>No recorded reference checks.</p>';
}
function chart(){if(!exp)return;const n=cursor??exp.rows.length-1,rows=exp.rows.slice(0,n+1),last=rows.at(-1),selected=exp.proofs.find(x=>x.proof.id===proofId)||exp.proofs.at(-1),p=selected?.proof;
 const start=new Date(exp.rows[0].timestamp).getTime(),end=Math.max(new Date(exp.rows.at(-1).timestamp).getTime(),p?new Date(p.origin).getTime()+p.horizon_min*60000:0),now=new Date(last.timestamp).getTime();
 const visibleProof=p&&new Date(p.origin).getTime()<=now;
 const values=exp.rows.map(r=>r.surface_c).filter(Number.isFinite).concat(visibleProof?p.points.map(x=>x.predicted_c):[]);if(!values.length){$('lab-chart').innerHTML='<text x="40" y="100" font-size="18">No qualified temperature readings.</text>';return;}
 const width=Math.max(280,$('lab-chart').clientWidth||1000),right=width-16,ticks=width<500?3:5;$('lab-chart').setAttribute('viewBox',`0 0 ${width} 300`);
 const lo=Math.min(...values)-1,hi=Math.max(...values)+1,x=t=>50+(t-start)/Math.max(1,end-start)*(right-50),y=v=>248-(v-lo)/(hi-lo)*220;
 let html='';for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4;html+=`<line x1="50" x2="${right}" y1="${y(v)}" y2="${y(v)}" stroke="#dbe3ea"/><text x="8" y="${y(v)+5}" fill="#4b5e6e" font-size="14">${num(v,1)}</text>`;}
 for(let i=0;i<ticks;i++){const t=start+(end-start)*i/(ticks-1);html+=`<text x="${x(t)}" y="283" text-anchor="${i===0?'start':i===ticks-1?'end':'middle'}" fill="#4b5e6e" font-size="14">${num((t-start)/60000,1)} min</text>`;}
 let d='',prev=null;for(const r of rows){const t=new Date(r.timestamp).getTime();if(!Number.isFinite(r.surface_c)||r.quality_flags?.length){prev=null;continue;}d+=(prev!==null&&t-prev<=15000?'L':'M')+x(t)+','+y(r.surface_c)+' ';prev=t;}
 html+=`<path d="${d}" fill="none" stroke="#245fa6" stroke-width="3"/>`;
 if(visibleProof){const origin=new Date(p.origin).getTime(),path=p.points.map((r,i)=>(i?'L':'M')+x(origin+r.minute*60000)+','+y(r.predicted_c)).join(' ');html+=`<path d="${path}" fill="none" stroke="#b45118" stroke-width="2.5" stroke-dasharray="7 5"/><line x1="${x(origin)}" x2="${x(origin+p.horizon_min*60000)}" y1="${y(p.initial_c)}" y2="${y(p.initial_c)}" stroke="#6c7c89" stroke-dasharray="3 5"/><line x1="${x(origin)}" x2="${x(origin)}" y1="20" y2="248" stroke="#b45118" opacity=".35"/>`;}
 $('lab-chart').innerHTML=html;$('lab-time').textContent=new Date(last.timestamp).toLocaleTimeString()+' · frame '+last.sequence;
 $('lab-replay-note').textContent=n<exp.rows.length-1?'Recorded replay position. Return to the latest acquisition to add evidence.':exp.source==='software_emulator'?'Software emulator · accelerated observation clock. No connected hardware.':exp.state==='stopped'?'Stopped recording · historical measurements.':`Latest captured physical acquisition · ${exp.diagnostics.connection}.`;
 const m=[['Surface temperature',num(last.surface_c)+' °C','Outer case · not winding'],['Secondary voltage',num(last.secondary_v)+' V','RMS measurement'],['Combined current',num(last.current_a,3)+' A','RMS measurement'],['Captured acquisitions',exp.rows.length,'Gaps remain visible']];
 $('lab-metrics').innerHTML=m.map(([a,b,c])=>`<div><span>${a}</span><strong>${esc(b)}</strong><small>${c}</small></div>`).join('');
 if(selected){const s=selected.score,q=s.assumptions_held;$('lab-score').innerHTML=`<div><span>Comparable model MAE</span><strong>${num(q.mae_c,3)} °C</strong></div><div><span>Persistence MAE</span><strong>${num(q.persistence_mae_c,3)} °C</strong></div><div><span>Comparable observations</span><strong>${q.count}</strong></div><div><span>Changed / missing</span><strong>${s.changed_input_samples} / ${s.missing_samples}</strong></div><p>${esc(s.status)} · ${esc(s.baseline_comparison)} ${n<exp.rows.length-1?'Scores cover the full capture, not the replay cursor.':''}</p>`;}else $('lab-score').innerHTML='<p>Freeze a forecast now. Its later error will appear here as observations arrive.</p>';
}
function paint(){if(!reference)$('lab-reference-result').innerHTML='<p>No reference check selected.</p>';if(!exp){$('lab-work').hidden=true;paintDiagnostics();buttons();return;}const e=exp,virtual=e.source==='software_emulator';$('lab-work').hidden=false;
 $('lab-source-label').textContent=virtual?'SOFTWARE EMULATOR · NO PHYSICAL HARDWARE':'PHYSICAL RECORDING · BENCH-001';$('lab-source-note').textContent=e.name+' · '+e.scope;$('lab-state').textContent=e.state;
 if(active())$('connection').textContent=virtual?'Bench lab · emulator':e.diagnostics.connection+' · physical recording';
 $('lab-load').hidden=!virtual;$('lab-advance').hidden=!virtual;$('lab-sync').hidden=virtual;
 $('lab-forecast-hold').textContent=(e.forecast_hold||'The model holds current and ambient constant. Changed-input samples are reported separately. No prediction interval has been calibrated.')+(e.uncaptured_samples_at_stop?` Recording cap: ${e.uncaptured_samples_at_stop} later samples were not captured.`:'');
 $('lab-cursor').max=e.rows.length-1;$('lab-cursor').value=cursor??e.rows.length-1;
 $('lab-proof').innerHTML=e.proofs.length?e.proofs.map(({proof:p},i)=>`<option value="${esc(p.id)}">Forecast ${i+1} · ${new Date(p.origin).toLocaleTimeString()}</option>`).join(''):'<option>No forecast yet</option>';
 if(!proofId||!e.proofs.some(x=>x.proof.id===proofId))proofId=e.proofs.at(-1)?.proof.id;if(proofId)$('lab-proof').value=proofId;
 const marks=new Set(e.markers.map(m=>m.kind));if(e.proofs.some(x=>x.score.samples.length))marks.add('observed');document.querySelectorAll('[data-stage]').forEach(li=>li.classList.toggle('complete',marks.has(li.dataset.stage)));
 $('lab-events').innerHTML=[...e.markers].reverse().map(m=>`<article><small>${new Date(m.timestamp).toLocaleTimeString()} · ${esc(m.kind.replaceAll('_',' '))}</small><p>${esc(m.note)}</p>${m.verification?`<small>${esc(m.verification)}</small>`:''}</article>`).join('');
 chart();paintDiagnostics();buttons();
}
async function act(action,extra={}){const latest=cursor===null||cursor===exp.rows.length-1;exp=await api(base()+'/actions',{revision:exp.revision,action,...extra});if(latest)cursor=null;paint();}
function bind(id,fn){$(id).onclick=()=>task(fn);}
$('lab-create').onsubmit=e=>{e.preventDefault();task(async()=>{const f=new FormData(e.target);exp=await api('/lab/experiments',{request_id:crypto.randomUUID(),source:f.get('source'),name:f.get('name')});cursor=null;proofId=null;reference=null;referenceLocked=false;referenceRow=null;sessionStorage.setItem('halo-lab-experiment',exp.id);await list();paint();});};
$('lab-saved').onchange=e=>{const id=e.target.value;if(!id)return;task(async()=>{exp=await api('/lab/experiments/'+encodeURIComponent(id));cursor=null;proofId=null;reference=null;referenceLocked=false;referenceRow=null;sessionStorage.setItem('halo-lab-experiment',id);paint();});};
bind('lab-freeze',()=>act('freeze'));bind('lab-advance',()=>act('advance'));bind('lab-sync',()=>act('capture'));bind('lab-stop',async()=>{await act('stop');await list();});
bind('lab-latest',async()=>{cursor=null;paint();});bind('lab-refresh',async()=>{await loadDiagnostics();if(exp)exp=await api(base());paint();});
bind('lab-export',async()=>{const r=await HaloAuth.fetch('/api/halo'+base()+'/export');if(!r.ok)throw Error('Experiment export unavailable.');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download=exp.id+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('lab-cursor').oninput=e=>{cursor=Number(e.target.value);chart();buttons();};$('lab-proof').onchange=e=>{proofId=e.target.value;chart();};
$('lab-load').onsubmit=e=>{e.preventDefault();task(()=>{const f=new FormData(e.target);return act('load',{branches:Number(f.get('branches')),note:f.get('note')});});};
$('lab-marker').onsubmit=e=>{e.preventDefault();task(async()=>{const f=new FormData(e.target);await act('mark',{kind:f.get('kind'),note:f.get('note')});e.target.elements.note.value='';});};
$('lab-reference').onsubmit=e=>{e.preventDefault();task(async()=>{const f=new FormData(e.target),d=currentDiagnostics();reference=await api('/lab/references',{request_id:crypto.randomUUID(),experiment_id:exp?.source==='software_emulator'?exp.id:null,evidence_id:e.target.dataset.evidence||d.latest.evidence_id,channel:f.get('channel'),reference:Number(f.get('reference')),tolerance_abs:Number(f.get('tolerance_abs')),zero_current_noise_mv:Number(f.get('zero_current_noise_mv')),instrument:f.get('instrument'),reviewer:f.get('reviewer')});
 $('lab-reference-result').innerHTML=`<div class="lab-result ${reference.within_tolerance===false?'fail':''}"><strong>${reference.within_tolerance===null?'Scale proposal ready':reference.within_tolerance?'Within entered tolerance':'Outside entered tolerance'}</strong><p>Error ${num(reference.error,3)} ${esc(reference.unit)} · permitted ±${num(reference.tolerance_abs,3)}</p><p>${esc(reference.source)} · ${esc(reference.evidence_id)}</p><code>${esc(JSON.stringify(reference.proposal))}</code><p>${esc(reference.note)}</p></div>`;await loadDiagnostics();});};
bind('lab-calibration-draft',async()=>{if(reference?.source!=='measured')return;const form=$('calibration-form'),cal=diag?.calibration||{};for(const [k,v] of Object.entries({...cal,...reference.proposal})){if(form.elements[k]&&v!=null)form.elements[k].value=v;}form.elements.id.value='CAL-'+Date.now();form.elements.reviewer.value=reference.reviewer;form.elements.reference.value=reference.instrument;form.elements.note.value='Reference check '+reference.id+' at '+reference.acquired_at+'. Review additional operating points before saving.';if(reference.channel==='surface_c')form.elements.surface_reference.value=reference.instrument;H.view('commissioning');form.scrollIntoView({block:'start'});});
$('lab-open-profile').onclick=e=>{e.preventDefault();H.view('commissioning');};
async function init(){if(!active())return;await task(async()=>{await loadDiagnostics();if(!started){const saved=sessionStorage.getItem('halo-lab-experiment');if(saved){try{exp=await api('/lab/experiments/'+encodeURIComponent(saved));}catch{sessionStorage.removeItem('halo-lab-experiment');}}started=true;}await list();paint();});}
const resetReference=document.createElement('button');resetReference.type='button';resetReference.textContent='Use latest acquisition for reference';resetReference.onclick=()=>{referenceLocked=false;paintDiagnostics();};$('lab-reference-frame').after(resetReference);
$('lab-reference').addEventListener('focusin',()=>{referenceLocked=true;paintDiagnostics();});
let resizeFrame;window.addEventListener('resize',()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{if(active())chart();});});
window.addEventListener('halo:view',init);window.addEventListener('halo:ready',()=>{ready=true;buttons();init();});document.addEventListener('visibilitychange',schedule);buttons();
})();
