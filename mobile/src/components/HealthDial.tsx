import React, { useEffect, useState } from 'react';
import { AccessibilityInfo, Animated, Pressable, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { Snapshot, Source } from '../types';
import { Card, C, fmt, s } from '../ui';

const factors = [
  ['thermal', 'Thermal', .22, 'transformer'], ['electrical', 'Electrical', .18, 'voltage'],
  ['loading', 'Loading', .20, 'current'], ['historical', 'Accumulated', .25, 'transformer'],
  ['environmental', 'Ambient', .05, 'surface'], ['oil', 'Oil condition', .10, 'transformer'],
] as const;
export function HealthDial({ snapshot, source, onFocus }: { snapshot: Snapshot | null; source: Source; onFocus?: (part: string) => void }) {
  const score = snapshot?.analysis.health_index ?? null;
  const [value] = useState(() => new Animated.Value(score ?? 0));
  const [shown, setShown] = useState(score ?? 0), [selected, setSelected] = useState('thermal');
  useEffect(() => { const listener = value.addListener(({ value: next }) => setShown(next)); return () => value.removeListener(listener); }, [value]);
  useEffect(() => {
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled().then(reduced => {
      if (!cancelled) Animated.timing(value, { toValue: score ?? 0, duration: reduced ? 0 : 450, useNativeDriver: false }).start();
    });
    return () => { cancelled = true; value.stopAnimation(); };
  }, [score, value]);
  const status = snapshot?.analysis.status;
  const colour = score == null ? C.muted : status === 'TRIP' || status === 'CRITICAL' || score < 50 ? C.red : status === 'WARNING' || score < 85 ? C.orange : C.green;
  const stress = snapshot?.analysis.stress;
  const available = factors.filter(([key]) => source === 'industrial' || ['thermal', 'electrical', 'loading'].includes(key) || (key === 'environmental' && snapshot?.telemetry.ambient_temperature != null));
  const active = available.find(([key]) => key === selected) || available[0];
  const reason = snapshot?.analysis.alerts[0]?.detail || snapshot?.analysis.maintenance[0] || 'Waiting for readings.';
  const path = 'M 38.9 141.1 A 68 68 0 1 1 135.1 141.1';
  const length = 2 * Math.PI * 68 * .75;
  return <Card>
    <View style={[s.rowBetween, { flexWrap: 'wrap' }]}><Text style={s.section}>Health index</Text><Text style={s.muted}>Screening score</Text></View>
    <View style={{ alignItems: 'center' }} accessibilityLabel={`Health index ${score == null ? 'unavailable' : fmt(score, 0) + ' out of 100'}`}>
      <Svg width={190} height={172} viewBox="0 0 174 158"><Path d={path} stroke="#e0ebe3" strokeWidth={11} fill="none" strokeLinecap="round" /><Path d={path} stroke={colour} strokeWidth={11} fill="none" strokeLinecap="round" strokeDasharray={`${length}`} strokeDashoffset={length * (1 - Math.max(0, Math.min(100, shown)) / 100)} /></Svg>
      <View style={{ position: 'absolute', top: 52, alignItems: 'center' }}><Text style={{ color: colour, fontSize: 51, fontWeight: '500', letterSpacing: -2 }}>{score == null ? '—' : Math.round(shown)}</Text><Text style={s.muted}>{score == null ? 'Unavailable' : 'out of 100'}</Text></View>
    </View>
    <View style={{ gap: 13 }}>{available.map(([key, name, weight, part]) => {
      const v = score == null ? null : stress?.[key] ?? null;
      return <Pressable key={key} accessibilityRole="button" accessibilityLabel={`${name} health contribution`} accessibilityState={{ selected: selected === key }} onPress={() => { setSelected(key); onFocus?.(part); }} style={{ gap: 6 }}>
        <View style={s.rowBetween}><Text style={[s.fieldLabel, selected === key && { color: C.green }]}>{name}</Text><Text style={s.muted}>{v == null ? '—' : `−${fmt(v * weight, 1)} pts`}</Text></View>
        <View style={{ height: 5, borderRadius: 4, backgroundColor: '#e5ede7', overflow: 'hidden' }}><View style={{ height: 5, width: `${Math.max(0, Math.min(100, v ?? 0))}%`, backgroundColor: selected === key ? C.orange : '#a6bbb0', borderRadius: 4 }} /></View>
      </Pressable>;
    })}</View>
    <Text style={s.muted}>{active[1]} · {active[0] === 'thermal' ? `${fmt(snapshot?.telemetry.transformer_temperature)} °C` : active[0] === 'electrical' ? `${fmt(snapshot?.telemetry.secondary_voltage)} V` : active[0] === 'loading' ? `${fmt(snapshot?.telemetry.loading_percent)}% load` : active[0] === 'environmental' ? `${fmt(snapshot?.telemetry.ambient_temperature)} °C` : active[0] === 'oil' ? `${fmt(snapshot?.telemetry.oil_condition)} /100` : 'Retained after recovery'}</Text>
    <Text style={[s.body, { fontSize: 14, lineHeight: 21 }]}>{reason}</Text>
  </Card>;
}
