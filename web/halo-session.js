/* One visible source selection for every workspace destination. */
(() => {
  'use strict';
  const params=new URLSearchParams(location.search);
  let source=params.has('challenge')?'reference':params.get('asset')==='BENCH-001'?'prototype':'industrial';
  let run=null;
  function paint(){
    document.body.dataset.twinSource=source;
    const label=document.getElementById('session-context');
    if(label)label.textContent=source==='industrial'?(run?`${run.profile?.name||'Distribution transformer'} · ${run.id.slice(-8).toUpperCase()} · ${Math.round(run.elapsed_s/60)} simulated min`:'Industrial simulation · select or create a run'):
      source==='prototype'?'BENCH-001 · physical ESP32 · measurements only':'Independent reference studies · replay source selected below';
    const select=document.getElementById('session-source');if(select)select.value=source;
    if(source==='industrial'){
      const status=document.getElementById('connection');if(status)status.textContent='Industrial · simulated';
      const count=document.getElementById('incident-count');if(count)count.textContent='';
    }
    if(document.body.dataset.twinSwitching==='true'){const status=document.getElementById('connection');if(status)status.textContent='Switching source…';}
  }
  function select(next){if(!['industrial','prototype','reference'].includes(next))return;source=next;paint();window.dispatchEvent(new CustomEvent('halo:session',{detail:{source,run}}));}
  window.HaloSession={source:()=>source,industrial:()=>source==='industrial',run:()=>run,
    select,bind:s=>{run=s;paint();window.dispatchEvent(new CustomEvent('halo:run',{detail:s}));},paint};
  paint();window.addEventListener('halo:snapshot',paint);window.addEventListener('halo:view',paint);
})();
