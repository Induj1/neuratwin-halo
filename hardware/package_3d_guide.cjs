// Rebuild the portable hardware viewer and its tables from the same source data.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.resolve(__dirname, '../web');
const out = path.resolve(__dirname, '../../output/hardware-3d-rev1.5');
fs.mkdirSync(path.join(out, 'vendor'), {recursive:true});
for (const file of ['hardware-guide.css','hardware-guide.js','hardware-data.js','vendor/three-0.149.0.min.js','vendor/three-LICENSE.txt']) {
  fs.copyFileSync(path.join(web,file),path.join(out,file));
}
let html=fs.readFileSync(path.join(web,'hardware-guide.html'),'utf8');
html=html.replaceAll('href="../app"','href="http://127.0.0.1:8765/app"');
fs.writeFileSync(path.join(out,'index.html'),html);
const sandbox={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(web,'hardware-data.js'),'utf8'),sandbox);
const data=sandbox.window.HARDWARE;
const parts=new Map(data.parts.map(p=>[p.id,p]));
function csv(name,rows){fs.writeFileSync(path.join(out,name),'\ufeff'+rows.map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n'));}
csv('connections-rev1.5.csv',[
  ['From','To','Type','Connection','Check'],
  ...data.connections.map(c=>[parts.get(c[0]).name,parts.get(c[1]).name,c[2],c[3],c[4]])
]);
csv('components-rev1.5.csv',[
  ['ID','Component / assembly','Status','Location','Select / buy','Purpose','Assembly notes','Check','Reference'],
  ...data.parts.map(p=>[p.n,p.name,p.status||'PROPOSED',p.location,p.spec,p.purpose,p.notes.join(' | '),p.warning,p.source||''])
]);
csv('load-stages-rev1.5.csv',[
 ['Branches on','Nominal secondary V RMS','Resistance per branch ohms','Current A RMS (calculated)','Resistive load W (calculated)','Equivalent ohms'],
 ...[68,33].flatMap(r=>[1,2,3].map(n=>[n,data.load.voltage,r,(n*data.load.voltage/r).toFixed(3),(n*data.load.voltage**2/r).toFixed(3),(r/n).toFixed(3)]))
]);
fs.copyFileSync(path.join(__dirname,'HARDWARE_REV15_START_HERE.txt'),path.join(out,'START-HERE.txt'));
console.log(JSON.stringify({output:out,revision:data.revision,parts:data.parts.length,connections:data.connections.length,steps:data.steps.length}));
