import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const D=createRequire(import.meta.url)('../web/halo-physics.js');

test('demo clock and load changes are independent of measured snapshots',()=>{
 const measured={live:false,channels:{secondary_current:{value:null,raw:.8}}};
 const before=structuredClone(measured);assert(D.needsDemo(measured));
 const d=D.create(1000);D.advance(d,60,3000);D.setLoad(d,110,4000);
 assert.equal(d.elapsed_seconds,63);assert.equal(d.steps[0].load_percent,65);
 assert.equal(d.steps[1].seconds,63);assert.equal(d.steps[1].load_percent,110);
 assert.equal(D.timestamp(d),new Date(64000).toISOString());
 assert.deepEqual(measured,before);assert(!('tick' in D.request(d)));
});

test('gauges and oil inputs use the same estimate despite a measured-current disagreement',()=>{
 const d={live:true,channels:{secondary_current:{value:.8},secondary_voltage:{value:12},surface_temperature:{value:35}}};
 assert(!D.needsDemo(d));d.disagreement=true;d.estimates={secondary_current:{value:12/19.5}};
 assert(!D.needsDemo(d));assert.equal(D.inputCurrent(d),12/19.5);assert.equal(d.channels.secondary_current.value,.8);
 d.channels.surface_temperature.value=null;assert(D.needsDemo(d));
});

test('high current stays in the source study instead of silently becoming demo input',()=>{
 const d={live:true,channels:{secondary_current:{value:10},secondary_voltage:{value:2},surface_temperature:{value:35}}};
 assert.equal(D.needsDemo(d),false);assert.equal(D.inputCurrent(d),10);
});
