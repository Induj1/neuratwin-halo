import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

test('offline shell includes every local stylesheet and script required by the app',()=>{
  const root=new URL('../web/',import.meta.url);
  const source=readFileSync(new URL('halo-sw.js',root),'utf8');
  const shell=runInNewContext(source+'\nSHELL;',{self:{addEventListener(){}}});
  const html=readFileSync(new URL('halo.html',root),'utf8');
  for(const match of html.matchAll(/(?:src|href)="(\/static\/[^"?]+)(?:\?[^" ]*)?"/g)){
    const path=match[1];
    assert(shell.includes(path),`${path} is required but not available offline`);
    assert(existsSync(new URL(path.slice('/static/'.length),root)),`${path} does not exist`);
  }
});
