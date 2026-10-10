import React, { useState } from 'react';
import { Text, View, Pressable } from 'react-native';
import { router, usePathname } from 'expo-router';
import { useHalo } from '../../store';
import { Screen, SourceSwitch, Card, Button, Section, Trend, Icon, fmt, label, s } from '../../ui';
import { TwinVisuals } from '../../components/TwinVisuals';
import { Intervention } from '../../components/Intervention';
import { OperatingControls, previewElectrical, ElectricalPreview } from '../../components/OperatingControls';
export default function TwinScreen() { const h = useHalo(); return <TwinDashboard key={h.source + ':' + h.runId} />; }
function TwinDashboard() {
  const h = useHalo(), [choose, setChoose] = useState(false), focused = usePathname() === '/'; const snap = h.snapshot, t = snap?.telemetry;
  const [preview, setPreview] = useState<ElectricalPreview | null>(null);
  const act = (action: string, extra = {}) => { void h.command(action, extra).catch(() => {}); };
  return <Screen title="Digital twin"><SourceSwitch />
    {h.source === 'industrial' && <View style={s.rowBetween}><Pressable accessibilityRole="button" onPress={() => setChoose(!choose)} style={{ flex: 1, flexDirection: 'row', gap: 8, alignItems: 'center' }}><Text numberOfLines={1} style={[s.body, { flexShrink: 1 }]}>{snap?.profile?.name || 'Choose a run'}</Text><Icon name="arrow" size={15} /></Pressable><Pressable accessibilityRole="button" accessibilityLabel="New run" onPress={() => void h.createRun().catch(() => {})} disabled={h.busy || h.offline} style={s.round}><Icon name="plus" /></Pressable></View>}
    {choose && h.source === 'industrial' && <Card>{h.catalog?.runs.map(r => <Pressable accessibilityRole="button" key={r.id} onPress={() => { h.select('industrial', r.id); setChoose(false); }} style={{ paddingVertical: 10 }}><Text style={s.body}>{label(r.scenario)} · {Math.round(r.elapsed_s / 60)} min</Text><Text style={s.muted}>{new Date(r.started_at).toLocaleString()}</Text></Pressable>)}</Card>}
      {h.source === 'industrial' && <View style={s.row}><Button style={{ flex: 1 }} title={snap?.running ? 'Pause' : 'Run'} icon={snap?.running ? 'pause' : 'play'} disabled={h.busy || h.offline || !h.serverClock || !snap || !!preview} onPress={() => act(snap?.running ? 'pause' : 'start')} /><Button style={{ flex: 1 }} title="Controls" kind="quiet" onPress={() => router.push('/controls')} /></View>}
      <TwinVisuals snapshot={previewElectrical(snap, preview)} source={h.source} active={focused} offline={h.offline}>{h.source === 'industrial' && <OperatingControls snapshot={snap} onPreview={setPreview} />}</TwinVisuals>
      {h.source === 'industrial' && !snap && h.session && !h.offline && <Button title="Create run" icon="plus" disabled={h.busy} onPress={() => void h.createRun().catch(() => {})} />}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>{[['Primary voltage', t?.primary_voltage, 'V'], ['Secondary voltage', t?.secondary_voltage, 'V'], ['Primary current', t?.primary_current, 'A'], ['Secondary current', t?.secondary_current, 'A']].map(([name, value, unit]) => <Card key={String(name)} style={{ width: '48%', flexGrow: 1, padding: 17, gap: 8 }}><Text style={s.muted}>{name}</Text><Text style={s.stat}>{fmt(value as number | null, 2)}<Text style={{ fontSize: 14 }}> {unit}</Text></Text></Card>)}</View>
      {h.source === 'industrial' && <Intervention snapshot={snap} />}
      <Button title="Replay events" kind="quiet" icon="play" disabled={!snap?.history.length} onPress={() => router.push('/replay')} />
      <Section title="Temperature"><Card><Trend rows={snap?.history || []} /></Card></Section>
      {!!snap?.trip && <Card style={{ backgroundColor: '#fff0e7' }}><Text style={s.section}>Trip record</Text><Text style={s.body}>{snap.trip.reason}</Text><Button title="Review alerts" kind="quiet" icon="arrow" onPress={() => router.push('/alerts')} /></Card>}
  </Screen>;
}
