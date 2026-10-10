import React, { useState } from 'react';
import { Text, View } from 'react-native';
import { router } from 'expo-router';
import { useHalo } from '../../store';
import { api } from '../../api';
import { Screen, Card, Empty, Section, Button, label, s, C } from '../../ui';
export default function Alerts() {
  const h = useHalo(), [acked, setAcked] = useState<string[]>([]), [error, setError] = useState(''); const snap = h.snapshot;
  async function acknowledge(fingerprint: string) { try { await api('/mobile/acknowledgments', { source: h.source, run_id: h.source === 'industrial' ? h.runId : null, fingerprint }); setAcked(v => [...v, fingerprint]); } catch (e) { setError((e as Error).message); } }
  return <Screen title="Alerts" detail={h.source === 'industrial' ? 'Selected industrial run' : 'Physical prototype'}>{!!error && <Text style={{ color: C.red }}>{error}</Text>}
    {!snap ? <Empty title="Signals unavailable" text="Alerts and protection events appear when readings arrive." /> : <>
      {!snap.analysis.alerts.length && <Empty title={snap.trip ? 'Trip remains latched' : 'No active signals'} text={snap.trip ? snap.trip.reason : 'The available readings have no active alerts.'} />}
      {snap.analysis.alerts.map(a => { const fingerprint = snap.id + ':' + a.code + ':' + (a.timestamp || a.severity); return <Card key={a.code} style={{ borderLeftWidth: 3, borderLeftColor: a.severity === 'WARNING' ? C.orange : C.red }}><Text style={{ color: a.severity === 'WARNING' ? C.orange : C.red, fontSize: 12, fontWeight: '700', letterSpacing: 1 }}>{a.severity}</Text><Text style={s.section}>{label(a.parameter)}</Text><Text style={s.body}>{a.detail}</Text><View style={s.rowBetween}><Text style={s.muted}>Reading {String(a.value ?? '—')}</Text><Text style={s.muted}>Threshold {String(a.threshold ?? '—')}</Text></View><Button title={acked.includes(fingerprint) ? 'Acknowledged' : 'Acknowledge'} kind="quiet" disabled={h.offline || acked.includes(fingerprint)} onPress={() => void acknowledge(fingerprint)} /><Button title="Replay signal" kind="quiet" disabled={!snap.history.length} onPress={() => router.push({ pathname: '/replay', params: { at: a.timestamp || snap.telemetry.timestamp } })} /><Button title="Record an inspection" kind="quiet" icon="inspect" onPress={() => router.push('/inspect')} /></Card>; })}
      {!!snap.recovery_holds?.length && snap.breaker === 'OPEN' && <Section title="Before reconnection"><Card>{snap.recovery_holds.map(hold => <Text key={hold} style={s.body}>{hold}</Text>)}</Card></Section>}
      <Section title="Timeline"><Card>{snap.events.length ? [...snap.events].reverse().slice(0, 20).map((event, i) => <View key={event.id || i} style={{ gap: 5, paddingBottom: 14, borderBottomColor: C.line, borderBottomWidth: i === snap.events.length - 1 ? 0 : 1 }}><View style={s.rowBetween}><Text style={[s.body, { fontWeight: '600' }]}>{label(event.kind)}</Text><Text style={s.muted}>{new Date(event.timestamp || event.created_at || '').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</Text></View><Text style={s.muted}>{event.detail || event.content?.note || event.content?.detail || event.content?.reason}</Text></View>) : <Text style={s.muted}>Events appear as conditions change.</Text>}</Card></Section>
    </>}
  </Screen>;
}
