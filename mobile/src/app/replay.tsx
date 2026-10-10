import React, { useEffect, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import Slider from '@react-native-community/slider';
import { useLocalSearchParams } from 'expo-router';
import { useHalo } from '../store';
import { HistoryRow, Snapshot } from '../types';
import { Button, Card, C, Empty, Screen, s } from '../ui';
import { TwinVisuals } from '../components/TwinVisuals';

function nearest(rows: HistoryRow[], timestamp: string) { const time = new Date(timestamp).getTime(); return rows.reduce((best, row, index) => Math.abs(new Date(row.timestamp).getTime() - time) <= Math.abs(new Date(rows[best].timestamp).getTime() - time) ? index : best, 0); }
function frame(origin: Snapshot, row: HistoryRow): Snapshot {
  return { ...origin, running: false, elapsed_s: row.elapsed_s,
    telemetry: { timestamp: row.timestamp, quality: row.quality || 'unverified', transformer_temperature: row.transformer_temperature,
      primary_voltage: row.primary_voltage ?? null, secondary_voltage: row.secondary_voltage ?? null, primary_current: row.primary_current ?? null,
      secondary_current: row.secondary_current ?? null, loading_percent: row.loading_percent ?? null, ambient_temperature: row.ambient_temperature ?? null,
      phase_current_a: row.phase_current_a ?? null, phase_current_b: row.phase_current_b ?? null, phase_current_c: row.phase_current_c ?? null, neutral_current: row.neutral_current ?? null, phase_imbalance_percent: row.phase_imbalance_percent ?? null,
      oil_condition: row.oil_condition ?? null },
    breaker: row.breaker || 'UNKNOWN', protection_state: row.breaker === 'OPEN' ? 'ISOLATED' : 'Recorded state',
    analysis: row.analysis || { health_index: row.health_index ?? null, status: row.status || 'UNKNOWN', stress: {}, alerts: [], maintenance: ['Recorded observation.'] },
    trip: null };
}
export default function Replay() {
  const h = useHalo(), { at } = useLocalSearchParams<{ at?: string }>();
  if (!h.snapshot?.history.length) return <Screen back title="Event replay"><Empty title="No history yet" text="Run the simulation or connect the prototype to record readings." /></Screen>;
  return <ReplayTimeline key={h.source + ':' + h.runId} initial={h.snapshot} at={at} />;
}
function ReplayTimeline({ initial, at }: { initial: Snapshot; at?: string }) {
  // Freeze the entry-time history: background polling must not move this timeline.
  const [origin] = useState(initial), rows = origin.history;
  const [index, setIndex] = useState(at ? nearest(rows, at) : 0), [playing, setPlaying] = useState(false);
  useEffect(() => { if (!playing) return; const timer = setInterval(() => setIndex(i => { if (i >= rows.length - 1) { clearInterval(timer); return i; } return i + 1; }), 125); return () => clearInterval(timer); }, [playing, rows.length]);
  const ended = index >= rows.length - 1;
  const events = origin.events.filter(e => e.timestamp && new Date(e.timestamp).getTime() >= new Date(rows[0].timestamp).getTime() && new Date(e.timestamp).getTime() <= new Date(rows.at(-1)!.timestamp).getTime() && !['created','start','pause'].includes(e.kind)).slice(-10);
  const snap = frame(origin, rows[index]);
  return <Screen back title="Event replay"><Card><View style={s.rowBetween}><Text style={s.section}>{new Date(rows[index].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</Text><Text style={s.muted}>{index + 1} / {rows.length}</Text></View>
    <Slider accessibilityLabel="Replay position" minimumValue={0} maximumValue={Math.max(1, rows.length - 1)} step={1} value={index} disabled={rows.length < 2} onValueChange={v => { setPlaying(false); setIndex(Math.min(rows.length - 1, v)); }} minimumTrackTintColor={C.green} maximumTrackTintColor={C.line} thumbTintColor={C.ink} />
    <View style={s.row}><Button title={playing && !ended ? 'Pause replay' : ended ? 'Replay again' : 'Play replay'} kind="quiet" icon={playing && !ended ? 'pause' : 'play'} disabled={rows.length < 2} onPress={() => { if (ended) setIndex(0); setPlaying(ended ? true : !playing); }} /></View>
  </Card><TwinVisuals snapshot={snap} source={origin.source} replay />
    {events.length > 0 && <View style={{ gap: 8 }}>{events.map((event, i) => <Pressable key={`${event.timestamp}-${i}`} accessibilityRole="button" accessibilityLabel={`Replay ${event.kind}`} onPress={() => { setPlaying(false); setIndex(nearest(rows, event.timestamp!)); }} style={{ paddingVertical: 9, borderTopWidth: 1, borderTopColor: C.line }}><Text style={s.body}>{event.detail || event.kind.replaceAll('_', ' ')}</Text></Pressable>)}</View>}
  </Screen>;
}
