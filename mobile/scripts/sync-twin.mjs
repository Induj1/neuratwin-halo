import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const scripts = ['vendor/three-0.149.0.min.js','halo-studio.js','halo-bench-model.js','halo-twin.js'].map(file => readFileSync(root + 'web/' + file, 'utf8').replaceAll('</script', '<\\/script'));
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}canvas{width:100%;height:100%;display:block;touch-action:none}#part{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);font:12px system-ui;color:#476459;pointer-events:none}#unavailable{padding:50px 20px;text-align:center;font:15px system-ui;color:#476459;display:none}</style></head><body><canvas id="model"></canvas><span id="part"></span><div id="unavailable">3D view unavailable on this device</div>${scripts.map(s => '<script>'+s+'</script>').join('')}<script>
const twin=new HaloTwin(document.getElementById('model'),part=>document.getElementById('part').textContent=part.replaceAll('-',' '));
if(twin.failed){document.getElementById('model').style.display='none';document.getElementById('unavailable').style.display='block'}
window.receive=function(data){try{const v=typeof data==='string'?JSON.parse(data):data;if(v.kind!=='halo-state')return;twin.setDistribution(v.source==='industrial');twin.temperature(Number.isFinite(v.temperature)?v.temperature:null,v.severity||'normal');if(v.source==='industrial'&&!twin.failed&&twin.body){twin.body.material.color.setHex(v.severity==='critical'?0xba6845:v.severity==='warning'?0xbc935e:0x647b80)}if(v.focus&&v.focus!==window.lastFocus){twin.focus(v.focus);twin.select(v.focus);window.lastFocus=v.focus}twin.draw()}catch{}};
window.addEventListener('message',e=>window.receive(e.data));document.addEventListener('message',e=>window.receive(e.data));
window.addEventListener('resize',()=>twin.draw());
window.ReactNativeWebView?.postMessage('ready');window.parent?.postMessage('halo-model-ready','*');
</script></body></html>`;
mkdirSync(root+'mobile/src/generated',{recursive:true});
const envPath = root+'mobile/.env.local';
const configured = existsSync(envPath) ? readFileSync(envPath, 'utf8').match(/^EXPO_PUBLIC_API_URL=(.+)$/m)?.[1]?.trim() : '';
writeFileSync(root+'mobile/src/generated/connection.json', JSON.stringify({url: process.env.EXPO_PUBLIC_API_URL || configured || ''}));
writeFileSync(root+'mobile/src/generated/twin.ts','// Generated from the shared web model by npm run sync-twin.\nexport default '+JSON.stringify(html)+';\n');
