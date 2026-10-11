// Destructive synthetic fixtures only in an explicitly isolated local server.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.HALO_PLAYWRIGHT_MODULE||'playwright');
const base=process.env.HALO_AUDIT_URL;
if(process.env.HALO_AUDIT_WRITE_FIXTURES!=='1'||!base||!/^http:\/\/(127\.0\.0\.1|localhost):/.test(base))throw Error('Isolated localhost fixture server required');
(async()=>{
 const status=await(await fetch(base+'/api/halo/status')).json();assert.equal(status.storage_backend,'sqlite');assert.equal(status.esp32_configured,false);assert.equal(status.hardware_control_enabled,false);
 const browser=await chromium.launch({headless:true,args:['--disable-webgl']});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});let page=await context.newPage();const errors=[],commands=[];
 const monitor=p=>{p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.method()==='POST'&&/\/esp32\//.test(r.url()))commands.push(r.url());});};monitor(page);
 const ready=()=>page.waitForFunction(()=>window.HaloFleet?.current().run&&!document.getElementById('view-fleet').hasAttribute('aria-busy'));
 const pane=async name=>{await page.locator(`.fl-subnav [data-fl-panel=${name}]`).click();await ready();};
 try{
 await page.goto(base+'/app');await page.waitForFunction(()=>window.HaloFleet);await page.locator('nav [data-view=fleet]').click();await ready();
 await page.click('#fl-new');await ready();assert.equal(await page.evaluate(()=>HaloFleet.current().run.assets.length),12);
 await page.locator('.fl-map [data-asset="DEMO-U02"]').click();await ready();await pane('actions');await page.locator('#fl-forecast-form button').click();await ready();await page.click('#fl-tick');await ready();await page.click('#fl-score');await ready();assert.match(await page.locator('#fl-score-result').innerText(),/5 scored/);
 console.log('PASS frozen forecast and later-reference scoring');
 await pane('map');await page.selectOption('#fl-area','rural');assert.equal(await page.locator('.fl-map [data-asset]').count(),6);await page.locator('.fl-map [data-asset="DEMO-R02"]').click();await ready();await pane('twin');
 await page.click('[data-scenario=disconnect]');await ready();await page.click('#fl-tick30');await ready();await page.click('#fl-tick30');await ready();assert.equal(await page.evaluate(()=>HaloFleet.current().run.assets.find(a=>a.id==='DEMO-R02').freshness),'expired');
 await pane('evidence');const downloadPromise=page.waitForEvent('download');await page.click('#fl-harvest');const download=await downloadPromise;await ready();const path=await download.path();await page.setInputFiles('#fl-import',path);await ready();await page.waitForFunction(()=>document.getElementById('fl-message').textContent.includes('historical readings imported'));
 assert.equal(await page.evaluate(()=>HaloFleet.current().run.assets.find(a=>a.id==='DEMO-R02').freshness),'expired');console.log('PASS rural expiry and historical harvest without false live status');
 await pane('map');await page.locator('.fl-map [data-asset="DEMO-R06"]').click();await ready();await pane('maintenance');await page.locator('#fl-job-create button').click();await ready();await page.click('#fl-accept');await ready();
 await context.setOffline(true);await page.locator('#fl-visit [name=note]').fill('Technician inspected synthetic cooling and recorded the finding offline.');await page.click('#fl-visit button[value=visit]');await ready();assert.match(await page.locator('#fl-queue').innerText(),/1 saved visit/);
 const url=page.url();await page.close();await context.setOffline(false);page=await context.newPage();monitor(page);await page.goto(url);await ready();await page.waitForFunction(()=>!document.getElementById('fl-queue').hidden);await page.click('#fl-sync');await ready();assert.equal(await page.evaluate(()=>HaloFleet.current().job.visits.length),1);
 await page.locator('#fl-visit [name=note]').fill('Recorded corrective action in the synthetic exercise.');await page.click('#fl-visit button[value=action]');await ready();await page.click('#fl-tick30');await ready();await page.click('#fl-review');await ready();assert.equal(await page.evaluate(()=>HaloFleet.current().job.outcome.classification),'mitigated');console.log('PASS durable offline visit across tab closure, action and reviewed synthetic mitigation');
 await pane('costs');await page.locator('#fl-cost [name=source]').fill('Assumed rehearsal costs, 11 October 2026');await page.locator('#fl-cost button').click();await ready();assert.match(await page.locator('.fl-cost-list').innerText(),/—/);
 await pane('evidence');await page.waitForSelector('#fl-passport img');const pdfWait=page.waitForEvent('download');await page.click('[data-export=pdf]');const pdf=await pdfWait;await pdf.saveAs('../.fix-work/fleet-report.pdf');await ready();
 await pane('map');await page.selectOption('#fl-area','all');await page.screenshot({path:'../.fix-work/fleet-map-reviewed.png',fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:'../.fix-work/fleet-mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert.equal(overflow,false,'Mobile horizontal overflow');
 await page.selectOption('#session-source','prototype');await page.waitForFunction(()=>!HaloFleet.active()&&document.getElementById('view-physics').classList.contains('active'));
 assert.equal(commands.length,0);assert.deepEqual(errors,[]);console.log('PASS exports, QR passport, mobile layout and return to physical prototype without hardware commands');
 }catch(e){console.log('UI ERROR',await page.locator('#fl-message').innerText());console.log('STATE',await page.evaluate(()=>({panel:HaloFleet.current().panel,selected:HaloFleet.current().selected,busy:document.getElementById('view-fleet').getAttribute('aria-busy')})));throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
