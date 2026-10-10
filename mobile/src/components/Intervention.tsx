import React, { useEffect, useRef, useState } from 'react';
import { Text, View } from 'react-native';
import Svg, { Path, Line } from 'react-native-svg';
import { api } from '../api';
import { useHalo, uuid } from '../store';
import { Plan, ProjectionPoint, Snapshot } from '../types';
import { Button, Card, C, fmt, s } from '../ui';

function Comparison({ plan }: { plan: Plan }) {
  const before = plan.baseline.points, after = plan.recommendation?.points || [];
  const temperatures = [...before, ...after].map(p => p.temperature_c);
  const lo = Math.min(...temperatures) - 4, hi = Math.max(...temperatures) + 4;
  const draw = (points: ProjectionPoint[]) => points.map((p, i) => `${i ? 'L' : 'M'}${8 + 284 * p.minute / Math.max(1, plan.horizon_min)},${145 - (p.temperature_c - lo) / (hi - lo) * 120}`).join(' ');
  return <View accessibilityLabel="Projected temperature comparison"><View style={s.rowBetween}><Text style={s.muted}>{fmt(hi, 0)} °C</Text><Text style={s.muted}>{plan.horizon_min} min projection</Text></View><Svg width="100%" height={162} viewBox="0 0 300 162">{[25,85,145].map(y => <Line key={y} x1={0} x2={300} y1={y} y2={y} stroke={C.line} strokeDasharray="3 5" />)}<Path d={draw(before)} stroke={C.orange} strokeWidth={2.5} fill="none" /><Path d={draw(after)} stroke={C.green} strokeWidth={2.5} fill="none" /></Svg><View style={s.rowBetween}><Text style={{ color: C.orange, fontSize: 13 }}>Do nothing</Text><Text style={{ color: C.green, fontSize: 13 }}>Reduce load</Text></View></View>;
}
export function Intervention({ snapshot }: { snapshot: Snapshot | null }) {
  const h = useHalo(), [plan, setPlan] = useState<Plan | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const unavailable = h.offline || h.busy || !snapshot || snapshot.breaker === 'OPEN';
  const stale = !!plan && !plan.applied && plan.origin_revision !== snapshot?.revision;
  async function compare() {
    if (!snapshot || busy || unavailable) return;
    setBusy(true); setError('');
    try {
      if (snapshot.running) await h.command('pause');
      const latest = await api<Snapshot>('/twin/runs/' + snapshot.id);
      const result = await api<Plan>('/twin/runs/' + snapshot.id + '/plans', { request_id: uuid(), revision: latest.revision, horizon_min: 60, max_delay_min: 0 });
      if (mounted.current) setPlan(result);
    } catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function apply() {
    if (!snapshot || !plan || stale || unavailable || busy) return;
    setBusy(true); setError('');
    try { await api('/twin/runs/' + snapshot.id + '/apply-plan', { plan_id: plan.id, revision: plan.origin_revision }); if (mounted.current) { setPlan({ ...plan, applied: true }); await h.refresh(); } }
    catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <Card><Text style={s.section}>Prevent the next trip</Text><Text style={s.muted}>Compare one hour with and without load reduction.</Text>
    {plan && <><Comparison plan={plan} />{plan.recommendation ? <><View style={s.rowBetween}><View><Text style={s.muted}>Peak temperature</Text><Text style={[s.stat, { fontSize: 23 }]}>{fmt(plan.baseline.peak_c)} → {fmt(plan.recommendation.peak_c)}°</Text></View><View style={{ alignItems: 'flex-end' }}><Text style={s.muted}>Load reduction</Text><Text style={s.stat}>{fmt(plan.recommendation.reduction_pct, 0)}%</Text></View></View><Text style={s.muted}>{fmt(plan.recommendation.curtailed_kwh)} kWh curtailed · simulated</Text><Button title={plan.applied ? 'Recommendation applied' : 'Apply recommendation'} disabled={unavailable || busy || stale || plan.applied || !plan.recommendation.reduction_pct} onPress={() => void apply()} /></> : <Text style={s.body}>No load reduction meets the model limits.</Text>}</>}
    {stale && <Text style={s.muted}>Conditions changed. Compare again.</Text>}
    {!!error && <Text accessibilityRole="alert" style={{ color: C.red, lineHeight: 22 }}>{error}</Text>}
    <Button title={busy ? 'Calculating…' : plan ? 'Compare again' : 'Compare outcomes'} kind={plan ? 'quiet' : 'primary'} icon="arrow" disabled={unavailable || busy} onPress={() => void compare()} />
  </Card>;
}
