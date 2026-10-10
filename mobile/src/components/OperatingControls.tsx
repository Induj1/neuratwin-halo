import React, { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import Slider from '@react-native-community/slider';
import { useHalo } from '../store';
import { Snapshot } from '../types';
import { Button, Card, C, s } from '../ui';

export type ElectricalPreview = { load: number; imbalance: number };
export function previewElectrical(snapshot: Snapshot | null, preview: ElectricalPreview | null): Snapshot | null {
  if (!snapshot || !preview || snapshot.breaker === 'OPEN') return snapshot;
  const before = snapshot.inputs?.load_percent || 0;
  if (!before) return snapshot;
  const factor = preview.load / before, current = (snapshot.telemetry.secondary_current || 0) * factor;
  const d = preview.imbalance / 100;
  return { ...snapshot, telemetry: { ...snapshot.telemetry, loading_percent: preview.load,
    primary_current: snapshot.telemetry.primary_current == null ? null : snapshot.telemetry.primary_current * factor,
    secondary_current: current, phase_current_a: current * (1 + d), phase_current_b: current, phase_current_c: current * (1 - d), neutral_current: Math.sqrt(3) * current * d, phase_imbalance_percent: preview.imbalance } };
}
export function OperatingControls({ snapshot, onPreview }: { snapshot: Snapshot | null; onPreview: (value: ElectricalPreview | null) => void }) {
  const h = useHalo(), [draft, setDraft] = useState<ElectricalPreview | null>(null), [working, setWorking] = useState(false), [error, setError] = useState('');
  const alive = useRef(true); useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const values = draft || { load: snapshot?.inputs?.load_percent ?? 70, imbalance: snapshot?.inputs?.phase_imbalance_percent ?? 0 };
  const disabled = h.offline || h.busy || working || !snapshot?.inputs || snapshot.breaker === 'OPEN';
  function move(key: keyof ElectricalPreview, value: number) { const next = { ...values, [key]: value }; setDraft(next); onPreview(next); }
  async function commit(key: keyof ElectricalPreview, value: number) {
    if (!snapshot?.inputs || disabled) return;
    const next = { ...values, [key]: value }; setWorking(true); setError('');
    try { if (snapshot.running) await h.command('pause'); await h.command('inputs', { inputs: { ...snapshot.inputs, load_percent: next.load, phase_imbalance_percent: next.imbalance } }); }
    catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) { setWorking(false); setDraft(null); onPreview(null); } }
  }
  async function fault(kind: string) {
    if (disabled) return; setWorking(true); setError('');
    try { if (snapshot?.running) await h.command('pause'); if (kind === 'clear') await h.command('clear_fault'); else await h.command('inject', { fault: kind, severity: 2, duration_s: 1800 }); }
    catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setWorking(false); }
  }
  return <Card><View style={[s.rowBetween, { flexWrap: 'wrap' }]}><Text style={s.section}>Operating condition</Text><Text style={s.muted}>{draft ? 'Electrical preview' : working ? 'Applying…' : ''}</Text></View>
    <View style={s.rowBetween}><Text style={s.fieldLabel}>Load</Text><Text style={s.stat}>{Math.round(values.load)}%</Text></View>
    <Slider accessibilityLabel="Live load" disabled={disabled} minimumValue={0} maximumValue={180} step={1} value={values.load} onValueChange={v => move('load', v)} onSlidingComplete={v => void commit('load', v)} minimumTrackTintColor={C.green} maximumTrackTintColor={C.line} thumbTintColor={C.ink} />
    <View style={s.rowBetween}><Text style={s.fieldLabel}>Phase imbalance</Text><Text style={s.body}>{Math.round(values.imbalance)}%</Text></View>
    <Slider accessibilityLabel="Phase imbalance" disabled={disabled} minimumValue={0} maximumValue={60} step={1} value={values.imbalance} onValueChange={v => move('imbalance', v)} onSlidingComplete={v => void commit('imbalance', v)} minimumTrackTintColor={C.orange} maximumTrackTintColor={C.line} thumbTintColor={C.ink} />
    <View style={s.row}><Button title="Cooling fault" kind="quiet" disabled={disabled} onPress={() => void fault('cooling')} /><Button title="Thermal fault" kind="quiet" disabled={disabled} onPress={() => void fault('thermal')} />{snapshot?.fault && <Button title="Clear fault" kind="quiet" disabled={disabled} onPress={() => void fault('clear')} />}</View>
    {!!error && <Text accessibilityRole="alert" style={{ color: C.red, lineHeight: 22 }}>{error}</Text>}
  </Card>;
}
