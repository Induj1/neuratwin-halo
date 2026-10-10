import React, { useState } from 'react';
import { Platform, Text } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { useHalo } from '../store';
import { request } from '../api';
import { enableNotifications, disableNotifications } from '../notifications';
import { Screen, Card, Section, Button, s, C } from '../ui';
export default function Account() {
  const h = useHalo(), [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  async function perform(fn: () => Promise<string | void>) { setBusy(true); setMessage(''); try { const result = await fn(); if (result) setMessage(result); } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); } }
  async function share() {
    const industrial = h.source === 'industrial'; if (!h.snapshot) throw Error('Select a twin first.');
    const response = await request(industrial ? '/twin/runs/' + h.snapshot.id + '/report' : '/twin/prototype');
    const filename = industrial ? h.snapshot.id + '-report.zip' : 'prototype-evidence.json';
    if (Platform.OS === 'web') { const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000); }
    else { const bytes = new Uint8Array(await response.arrayBuffer()); let text = ''; for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192)); const path = FileSystem.cacheDirectory + filename; await FileSystem.writeAsStringAsync(path, btoa(text), { encoding: FileSystem.EncodingType.Base64 }); if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(path); else throw Error('Sharing is unavailable on this device.'); }
  }
  return <Screen back title="Settings">
    <Section title="Notifications"><Card><Text style={s.body}>Receive critical alerts for the selected transformer.</Text><Button title="Enable notifications" icon="alerts" disabled={busy || !h.snapshot || h.offline} onPress={() => void perform(() => enableNotifications(h.source, h.runId))} /><Button title="Disable on this device" kind="quiet" disabled={busy} onPress={() => void perform(() => disableNotifications(h.source, h.runId))} /></Card></Section>
    <Section title="Evidence"><Card><Button title="Share current report" kind="quiet" icon="download" disabled={busy || !h.snapshot || h.offline} onPress={() => void perform(share)} /><Text style={s.muted}>{h.drafts.length} inspection drafts on this device.</Text></Card></Section>
    {!!message && <Text accessibilityRole="alert" style={{ color: C.ink, lineHeight: 23 }}>{message}</Text>}
  </Screen>;
}
