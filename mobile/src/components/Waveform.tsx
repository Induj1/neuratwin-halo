import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AppState, Platform, Pressable, Text, View } from 'react-native';
import { WebView } from 'react-native-webview';
import { Snapshot, Source } from '../types';
import { Button, Card, fmt, s } from '../ui';

const colours = ['#ba753a', '#3f8a9a', '#477963', '#b64c3b'];
const html = `<!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><style>html,body{margin:0;background:transparent;font:11px system-ui;color:#6c8078}canvas{display:block;width:100%;height:175px;touch-action:pan-y}#read{height:20px;text-align:center}</style><canvas></canvas><div id="read">Touch to inspect</div><script>
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d'),read=document.getElementById('read');
let state={values:[],phases:[],names:[],visible:[],unit:'A',active:false},values=[],theta=0,last=0,probe=null;
const colors=['#ba753a','#3f8a9a','#477963','#b64c3b'];
window.receive=data=>{try{const next=typeof data==='string'?JSON.parse(data):data;if(next.kind==='halo-wave'){if(next.key!==state.key){values=[];theta=0;probe=null}state=next;}}catch{}};
window.addEventListener('message',e=>receive(e.data));document.addEventListener('message',e=>receive(e.data));
function inspect(e){const r=canvas.getBoundingClientRect();probe=Math.max(0,Math.min(1,(e.clientX-r.left-30)/(r.width-40)))}
canvas.addEventListener('pointerdown',inspect);canvas.addEventListener('pointermove',e=>{if(e.buttons||e.pointerType==='mouse')inspect(e)});canvas.addEventListener('pointerleave',()=>{probe=null;read.textContent='Touch to inspect'});
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
function render(time){requestAnimationFrame(render);if(time-last<30)return;const dt=Math.min(.08,(time-last)/1000);last=time;
const rect=canvas.getBoundingClientRect(),w=rect.width,h=175,dpr=Math.min(devicePixelRatio||1,2);if(canvas.width!==Math.round(w*dpr)){canvas.width=Math.round(w*dpr);canvas.height=h*dpr}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
if(state.active&&!state.paused&&!document.hidden&&!reduced.matches)theta+=dt*3;
state.values.forEach((target,i)=>{values[i]=target==null?null:values[i]==null?target:values[i]+(target-values[i])*Math.min(1,dt*10)});
const max=Math.max(1,state.range||0,...values.filter(v=>v!=null).map(v=>Math.abs(v)*1.6)),left=30,right=w-10,mid=85,amp=62/max;
ctx.strokeStyle='#dce7df';ctx.lineWidth=1;ctx.setLineDash([3,5]);for(const y of [23,85,147]){ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke()}ctx.setLineDash([]);ctx.fillStyle='#6c8078';ctx.font='10px system-ui';ctx.fillText(Math.round(max).toString(),1,26);ctx.fillText('0',13,88);ctx.fillText('-'+Math.round(max),1,150);ctx.fillText('0',left,170);ctx.fillText('20',left+(right-left)/2-5,170);ctx.fillText('40 ms',right-28,170);
state.values.forEach((v,i)=>{if(v==null||!state.visible[i])return;ctx.beginPath();ctx.strokeStyle=colors[i];ctx.lineWidth=2;for(let p=0;p<=180;p++){const x=left+(right-left)*p/180;const y=mid-Math.sin(p/180*Math.PI*4+theta+(state.phases[i]||0))*values[i]*Math.SQRT2*amp;p?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()});
if(probe!=null){const x=left+probe*(right-left);ctx.strokeStyle='#8fa69a';ctx.beginPath();ctx.moveTo(x,10);ctx.lineTo(x,152);ctx.stroke();read.textContent=(probe*40).toFixed(1)+' ms · '+state.values.map((v,i)=>v!=null&&state.visible[i]?state.names[i]+' '+(Math.sin(probe*Math.PI*4+theta+(state.phases[i]||0))*values[i]*Math.SQRT2).toFixed(1)+' '+state.unit:null).filter(Boolean).join(' · ')}
}requestAnimationFrame(render);window.ReactNativeWebView?.postMessage('ready');window.parent?.postMessage('halo-wave-ready','*');</script></html>`;

export function Waveform({ snapshot, source, active = true, replay = false }: { snapshot: Snapshot | null; source: Source; active?: boolean; replay?: boolean }) {
  const [paused, setPaused] = useState(false), [quantity, setQuantity] = useState<'current' | 'voltage'>('current'), [hidden, setHidden] = useState<number[]>([]), [foreground, setForeground] = useState(AppState.currentState === 'active');
  const native = useRef<WebView>(null), frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => { const sub = AppState.addEventListener('change', value => setForeground(value === 'active')); return () => sub.remove(); }, []);
  const t = snapshot?.telemetry, industrial = source === 'industrial';
  const phases = [t?.phase_current_a, t?.phase_current_b, t?.phase_current_c];
  const names = industrial ? ['L1', 'L2', 'L3', 'N'] : ['Primary', 'Secondary'];
  const values: (number | null)[] = industrial ? [phases?.[0] ?? null, phases?.[1] ?? null, phases?.[2] ?? null, t?.neutral_current ?? null] : quantity === 'current' ? [t?.primary_current ?? null, t?.secondary_current ?? null] : [t?.primary_voltage ?? null, t?.secondary_voltage ?? null];
  const real = (phases?.[0] ?? 0) - ((phases?.[1] ?? 0) + (phases?.[2] ?? 0)) / 2;
  const imaginary = Math.sqrt(3) / 2 * ((phases?.[2] ?? 0) - (phases?.[1] ?? 0));
  const unit = industrial || quantity === 'current' ? 'A' : 'V';
  const payload = JSON.stringify({ kind: 'halo-wave', key: source + quantity, names, values, phases: industrial ? [0, -Math.PI * 2 / 3, -Math.PI * 4 / 3, Math.atan2(imaginary, real)] : [0, 0], visible: names.map((_, i) => !hidden.includes(i)), unit, active: active && foreground, paused: paused || replay, range: industrial && t?.loading_percent ? (t.secondary_current || 0) / (t.loading_percent / 100) * 2 : 0 });
  const message = useRef(payload);
  const sync = useCallback(() => { const data = message.current; if (Platform.OS === 'web') frame.current?.contentWindow?.postMessage(data, '*'); else native.current?.injectJavaScript(`window.receive(${JSON.stringify(data)});true;`); }, []);
  useLayoutEffect(() => { message.current = payload; sync(); }, [payload, sync]);
  useEffect(() => { if (Platform.OS !== 'web') return; const ready = (e: MessageEvent) => { if (e.source === frame.current?.contentWindow && e.data === 'halo-wave-ready') sync(); }; window.addEventListener('message', ready); return () => window.removeEventListener('message', ready); }, [sync]);
  return <Card><View style={[s.rowBetween, { flexWrap: 'wrap' }]}><Text style={s.section}>{industrial ? 'Three-phase current' : 'Electrical waveform'}</Text><Text style={s.muted}>{industrial ? 'Simulated' : 'RMS illustration'}</Text></View>
    {!industrial && <View style={s.row}>{(['current', 'voltage'] as const).map(q => <Button key={q} title={q === 'current' ? 'Current' : 'Voltage'} kind="quiet" onPress={() => { setQuantity(q); setHidden([]); }} />)}</View>}
    <View style={{ height: 198, marginHorizontal: -8 }}>{Platform.OS === 'web' ? React.createElement('iframe', { ref: frame, srcDoc: html, title: 'Electrical waveform', sandbox: 'allow-scripts', style: { width: '100%', height: '100%', border: 0 }, onLoad: sync }) : <WebView ref={native} source={{ html }} style={{ backgroundColor: 'transparent' }} scrollEnabled={false} onMessage={sync} onLoadEnd={sync} originWhitelist={['about:blank']} onShouldStartLoadWithRequest={r => r.url === 'about:blank'} />}</View>
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>{names.map((name, i) => <Pressable key={name} accessibilityRole="button" accessibilityLabel={`${name} waveform`} accessibilityState={{ selected: !hidden.includes(i) }} onPress={() => setHidden(v => v.includes(i) ? v.filter(n => n !== i) : [...v, i])} style={{ minWidth: industrial ? '40%' : '43%', flexGrow: 1, opacity: hidden.includes(i) ? .4 : 1, gap: 4, paddingVertical: 6 }}><Text style={{ color: colours[i], fontWeight: '600', fontSize: 13 }}>{name}</Text><Text style={s.body}>{fmt(values[i], 1)} {unit} <Text style={s.muted}>RMS</Text></Text></Pressable>)}</View>
    {industrial && <View style={s.rowBetween}><Text style={s.muted}>Phase imbalance</Text><Text style={s.fieldLabel}>{fmt(t?.phase_imbalance_percent, 0)}%</Text></View>}
    {!replay && <Button title={paused ? 'Play waveform' : 'Pause waveform'} kind="quiet" icon={paused ? 'play' : 'pause'} disabled={values.every(v => v == null)} onPress={() => setPaused(v => !v)} />}
  </Card>;
}
