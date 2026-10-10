import React, { useState } from 'react';
import { Text, View } from 'react-native';
import { Snapshot, Source } from '../types';
import { Twin } from '../Twin';
import { Card, C, fmt, label, s } from '../ui';
import { HealthDial } from './HealthDial';
import { Waveform } from './Waveform';

export function TwinVisuals({ snapshot: snap, source, active = true, replay = false, offline = false, children }: React.PropsWithChildren<{ snapshot: Snapshot | null; source: Source; active?: boolean; replay?: boolean; offline?: boolean }>) {
  const [focus, setFocus] = useState<string | null>(null), t = snap?.telemetry;
  const unavailable = !snap || (source === 'prototype' && t?.quality !== 'qualified');
  return <>
    <Card style={{ paddingBottom: 18 }}><View style={s.rowBetween}><View style={s.row}><View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: unavailable || offline ? C.muted : snap.analysis.status === 'NORMAL' ? C.green : C.orange }} /><Text style={{ color: C.ink, fontSize: 14, fontWeight: '600' }}>{unavailable ? 'Unavailable' : snap.breaker === 'OPEN' ? 'Tripped' : label(snap.analysis.status)}</Text></View><Text style={s.muted}>{replay ? 'Replay' : source === 'industrial' ? 'Simulation' : label(snap?.connection || 'Disconnected')}</Text></View>
      <View style={[s.rowBetween, { alignItems: 'flex-end' }]}><View><Text style={{ fontSize: 48, letterSpacing: -2, color: C.ink, fontWeight: '500' }}>{fmt(t?.transformer_temperature)}<Text style={{ fontSize: 23, letterSpacing: 0 }}>°C</Text></Text><Text style={s.muted}>{source === 'prototype' ? 'Surface temperature' : 'Modelled hot-spot'}</Text></View><View style={{ alignItems: 'flex-end' }}><Text style={{ fontSize: 27, color: C.ink }}>{fmt(t?.loading_percent, 0)}<Text style={{ fontSize: 15 }}>%</Text></Text><Text style={s.muted}>Loading</Text></View></View>
      {active && <Twin source={source} temperature={t?.transformer_temperature ?? null} severity={snap?.analysis.status || 'unavailable'} focus={focus} />}
      <View style={s.divider} /><View style={s.rowBetween}><Text style={s.muted}>Protection</Text><Text style={{ fontSize: 13, color: C.ink, fontWeight: '600', flexShrink: 1, textAlign: 'right' }}>{snap?.protection_state || 'Unavailable'}</Text></View>
    </Card>
    <Waveform snapshot={snap} source={source} active={active && !offline} replay={replay} />
    {children}
    <HealthDial snapshot={snap} source={source} onFocus={setFocus} />
  </>;
}
