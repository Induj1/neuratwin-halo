/* One operator surface. Existing data adapters and command handlers keep ownership. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),root=$('view-physics');if(!root)return;
 const make=(tag,cls,id)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(id)el.id=id;return el;};
 const append=(host,...nodes)=>nodes.filter(Boolean).forEach(node=>host.append(node));
 const detail=(title,...nodes)=>{const box=make('details','cc-detail'),summary=make('summary');summary.textContent=title;box.append(summary);append(box,...nodes);return box;};
 const panel=make('div','cc-panels'),overview=make('section','cc-overview','cc-overview'),analysis=make('section','cc-analysis','cc-analysis');
 const nav=make('div','cc-tabs');nav.setAttribute('role','tablist');nav.setAttribute('aria-label','Control centre');
 for(const [key,label] of [['overview','Overview'],['analysis','Analysis']]){
  const button=make('button',null,'cc-tab-'+key);button.textContent=label;button.type='button';button.dataset.panel=key;button.setAttribute('role','tab');button.setAttribute('aria-controls','cc-'+key);nav.append(button);
 }
 for(const [key,node] of [['overview',overview],['analysis',analysis]]){node.setAttribute('role','tabpanel');node.setAttribute('aria-labelledby','cc-tab-'+key);}
 const cabinet=root.querySelector('.px-cabinet'),alarm=$('px-alarm'),heading=root.querySelector('.px-heading');
 heading.after($('op-error'),root.querySelector('.px-source-line'),nav,alarm,panel);panel.append(overview,analysis);
 overview.append(cabinet,root.querySelector('.px-live-graphs'));
 const desk=cabinet.querySelector('.px-desk'),control=desk.querySelector('.px-control-bay');
 const analysisGrid=make('div','cc-analysis-grid');analysisGrid.append(desk.querySelector('.px-forecast'),$('px-decision'));analysis.append(analysisGrid);
 desk.replaceChildren(control);desk.classList.add('cc-load-desk');
 // Keep the fluid load/imbalance controls and the existing ESP32 relay panel once.
 const physicalLoads=make('div',null,'cc-physical-loads');append(physicalLoads,$('op-loads'));
 append(control,physicalLoads,$('op-explore'));$('px-simulation').hidden=true;
 const response=root.querySelector('.px-live-graphs');
 const signals=$('op-alerts').closest('section'),timeline=$('op-events').closest('section');
 const history=detail('Signals & recorded history',document.querySelector('.op-replay'),$('op-replay-banner'),signals,timeline);
 overview.append(history);
 // The load bank has one location; commissioning and latch records stay inspectable.
 $('op-thermo').hidden=true;
 const hardware=detail('Hardware status & commissioning',$('op-prototype-controls'));
 overview.append(hardware);
 const faultPanel=make('section','cc-fault-panel');const faultHeading=make('div','cc-section-heading'),faultTitle=make('h2');faultTitle.textContent='Fault scenarios';faultHeading.append(faultTitle,$('px-tank'));faultPanel.append(faultHeading,root.querySelector('.px-faults'),$('px-simulation'));
 analysis.prepend(faultPanel);
 root.querySelector('.px-bottom summary').textContent='Oil model assumptions';
 append(analysis,root.querySelector('.px-bottom'),$('tf-panel'),$('op-lifetime'),$('op-engineering'));
 const review=make('div','cc-review-actions');append(review,$('op-observe-action'),$('op-review-action'));analysis.append(review,$('op-observation'),$('op-guide'));
 const screening=detail('Screening basis',document.querySelector('.op-decision'));
 const comparison=detail('Industrial intervention study',$('op-compare'));
 append(analysis,screening,comparison,document.querySelector('.op-advanced'));
 root.append($('px-error'));
 // Keep one source selector (the shared session bar) and one report action.
 const runPicker=make('label','cc-run-picker');const runLabel=make('span');runLabel.textContent='Saved run';runPicker.append(runLabel,$('op-run-select'));heading.querySelector('.px-toolbar').prepend(runPicker);
 const toMaintenance=make('button');toMaintenance.textContent='Maintenance';toMaintenance.onclick=()=>HaloWorkspace.view('maintenance');$('px-decision').append(toMaintenance);
 const maintenance=$('view-maintenance'),workflow=$('mt-workflow');
 const legacy=detail('Earlier records & simulation service');legacy.id='cc-maintenance-history';
 for(const node of [...maintenance.children])if(node.id!=='mt-maintenance-entry')legacy.append(node);
 const service=$('op-maintenance').closest('section');legacy.append(service);
 const maintenanceHeading=make('div','cc-maintenance-heading');maintenanceHeading.id='cc-maintenance-heading';
 const title=make('h1');title.textContent='Maintenance';const back=make('button');back.textContent='Control centre';back.onclick=()=>HaloWorkspace.view('control');maintenanceHeading.append(title,back);
 maintenance.prepend(maintenanceHeading,workflow);maintenance.append(legacy);
 $('mt-maintenance-entry').hidden=true;
 function select(name,focus=false){
  const selected=name==='analysis'?'analysis':'overview';root.dataset.panel=selected;
  overview.hidden=selected!=='overview';analysis.hidden=selected!=='analysis';
  for(const button of nav.children){const on=button.dataset.panel===selected;button.setAttribute('aria-selected',String(on));button.tabIndex=on?0:-1;if(on&&focus)button.focus();}
  window.dispatchEvent(new Event('resize'));
 }
 nav.onclick=e=>{const button=e.target.closest('[data-panel]');if(button)select(button.dataset.panel);};
 nav.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();select(e.key==='Home'?'overview':e.key==='End'?'analysis':root.dataset.panel==='overview'?'analysis':'overview',true);};
 function sync(state){
  const physical=state.mode==='prototype',has=!!state.snapshot;
  physicalLoads.hidden=!physical;hardware.hidden=!physical;runPicker.hidden=physical;
  comparison.hidden=physical||!has;screening.hidden=!has;review.hidden=!has;
  control.hidden=!has;$('op-explore').hidden=physical||!has||state.replay;
  $('px-control-context').hidden=true;
  response.hidden=!has;
  $('px-new').disabled=$('op-new').disabled;
 }
 window.addEventListener('halo:operation-state',e=>sync(e.detail));
 window.addEventListener('halo:view',e=>{if(e.detail==='physics'){select(root.dataset.panel);sync(HaloOperations.current());}});
 // A historical signal/review shortcut should reveal its target instead of scrolling a hidden panel.
 $('op-guide-signals').addEventListener('click',()=>{select('overview');history.open=true;signals.scrollIntoView({block:'start',behavior:'smooth'});});
 $('op-guide-compare').addEventListener('click',()=>{select('analysis');comparison.open=true;comparison.scrollIntoView({block:'start',behavior:'smooth'});});
 window.HaloControlCentre={mounted:true,select};select('overview');sync(HaloOperations.current());
})();
