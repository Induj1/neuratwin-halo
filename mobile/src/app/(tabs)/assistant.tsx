import React, { useLayoutEffect, useState } from 'react';
import { Text } from 'react-native';
import { useHalo, uuid } from '../../store';
import { api } from '../../api';
import { Screen, Card, Button, Field, s, C } from '../../ui';
type Message = { id: string; who: 'user' | 'assistant'; text: string; evidence?: { source: string; timestamp: string }; provider?: string };
export default function AssistantScreen() { const h = useHalo(); return <Assistant key={h.source + ':' + h.runId} />; }
function Assistant() {
  const h = useHalo(), [messages, setMessages] = useState<Message[]>([]), [question, setQuestion] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const context = `${h.source}:${h.runId}`, active = React.useRef(context);
  useLayoutEffect(() => { active.current = context; }, [context]);
  async function ask(text: string) { if (busy || !text.trim()) return; const origin = context; setBusy(true); setError(''); setQuestion(''); setMessages(v => [...v, { id: uuid(), who: 'user', text }]); try { const answer = await api('/mobile/assistant', { source: h.source, run_id: h.source === 'industrial' ? h.runId : null, question: text }); if (origin === active.current) setMessages(v => [...v, { id: uuid(), who: 'assistant', ...answer }]); } catch (e) { if (origin === active.current) setError((e as Error).message); } finally { setBusy(false); } }
  return <Screen title="Ask Halo" detail={h.source === 'industrial' ? 'Answers from this simulation’s evidence.' : 'Answers from this prototype’s readings.'}>{messages.length === 0 && <Card><Text style={[s.section, { lineHeight: 28 }]}>What would you like to understand?</Text>{['What needs attention?', 'Why did it trip?', 'What are the recovery checks?'].map(q => <Button key={q} title={q} kind="quiet" icon="arrow" disabled={!h.snapshot || h.offline || busy} onPress={() => void ask(q)} />)}</Card>}{messages.map(m => <Card key={m.id} style={{ backgroundColor: m.who === 'user' ? '#d7e7dd' : '#ffffffcf', marginLeft: m.who === 'user' ? 24 : 0, marginRight: m.who === 'assistant' ? 12 : 0 }}><Text style={s.body}>{m.text}</Text>{m.evidence && <Text style={s.muted}>{m.provider === 'openai' ? 'AI explanation' : 'Evidence summary'} · {new Date(m.evidence.timestamp).toLocaleTimeString()}</Text>}</Card>)}{busy && <Text style={s.muted}>Reading the current evidence…</Text>}{!!error && <Text style={{ color: C.red }}>{error}</Text>}<Field title="Your question" value={question} onChangeText={setQuestion} placeholder="What changed?" multiline /><Button title="Ask Halo" icon="arrow" disabled={!question.trim() || busy || h.offline || !h.snapshot} onPress={() => void ask(question)} /></Screen>;
}
