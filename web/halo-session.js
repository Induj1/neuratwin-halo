/* One visible source selection for every workspace destination. */
(() => {
  'use strict';
  const params=new URLSearchParams(location.search);
  let source=params.has('challenge')?'reference':params.get('asset')==='DT-SIM'?'industrial':'prototype';
  let run=null,pending=null;
  // Blind challenges have their own context; recordings are not live working sources.
  if(params.has('challenge')){
    const select=document.getElementById('session-source');
    if(select){const option=new Option('Blind challenge','reference');option.disabled=true;select.add(option);}
  }
  function paint(){
    if(window.HaloFleet?.active()){HaloFleet.paintContext();return;}
    document.body.dataset.twinSource=source;
    if(document.getElementById('view-portfolio')?.classList.contains('active')){
      const status=document.getElementById('connection');if(status)status.textContent='Fleet · frozen recordings';return;
    }
    if(document.getElementById('view-lab')?.classList.contains('active')){
      const status=document.getElementById('connection');if(status)status.textContent='Bench lab · source shown below';return;
    }
    if(window.HaloOperations?.current().replay&&document.body.dataset.twinSwitching!=='true'){
      const status=document.getElementById('connection');if(status)status.textContent='Replay · recorded state';return;
    }
    const label=document.getElementById('session-context');
    if(label)label.textContent=source==='industrial'?(run?`${run.profile?.name||'Distribution transformer'} · ${run.id.slice(-8).toUpperCase()} · ${Math.round(run.elapsed_s/60)} simulated min`:'Industrial simulation · select or create a run'):
      source==='prototype'?'BENCH-001 · physical ESP32 · measurements only':'Independent reference studies · replay source selected below';
    const select=document.getElementById('session-source');if(select)select.value=pending||source;
    if(source==='industrial'){
      const status=document.getElementById('connection');if(status)status.textContent='Industrial · simulated';
      const count=document.getElementById('incident-count');if(count)count.textContent='';
    }
    if(source==='prototype'){
      const status=document.getElementById('connection'),snapshot=window.HaloOperations?.current().snapshot,display=window.HaloOperations?.displaySnapshot();
      const connection=display?.live?'live':display?.quality==='stale'?'stale':snapshot?.connection;
      if(status)status.textContent=connection==='live'?'Physical · live':connection==='stale'?'Physical · stale':snapshot?'Physical · offline':'Waiting for readings';
    }
    if(document.body.dataset.twinSwitching==='true'){const status=document.getElementById('connection');if(status)status.textContent='Switching source…';}
  }
  function select(next){if(!['industrial','prototype','reference'].includes(next))return;source=next;paint();window.dispatchEvent(new CustomEvent('halo:session',{detail:{source,run}}));}
  window.HaloSession={source:()=>source,industrial:()=>source==='industrial',run:()=>run,
    request:next=>{pending=next;paint();},requested:()=>pending,settled:()=>{pending=null;paint();},
    select,bind:s=>{run=s;paint();window.dispatchEvent(new CustomEvent('halo:run',{detail:s}));},paint};
  paint();window.addEventListener('halo:snapshot',paint);window.addEventListener('halo:view',paint);window.addEventListener('halo:operation-state',paint);
})();
