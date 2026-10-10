import React from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View, ViewStyle } from 'react-native';
import Svg, { Path, Line } from 'react-native-svg';
import { LinearGradient } from 'expo-linear-gradient';
import { router } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useHalo } from './store';

export const C = { ink: '#193e36', muted: '#6c8078', green: '#287862', pale: '#eef5f0', line: '#dce7df', orange: '#a75b30', red: '#b64c3b' };
export const fmt = (v: number | null | undefined, digits = 1) => v == null || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: digits });
export const label = (v: string) => v.replaceAll('_', ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
export function Icon({ name, color = C.ink, size = 22 }: { name: string; color?: string; size?: number }) {
  const paths: Record<string, string> = { twin: 'M12 3 3 8v9l9 5 9-5V8L12 3Zm0 10L3 8m9 5 9-5m-9 5v9m-5-17 9 5', alerts: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9 21h6', inspect: 'M8 5H5v16h14V5h-3M8 3h8v4H8V3Zm0 9h8m-8 4h5', assistant: 'M21 11a9 9 0 0 1-9 9H5l-4 2 2-6a9 9 0 1 1 18-5ZM8 10h8m-8 4h5', account: 'M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z', arrow: 'm9 5 7 7-7 7', plus: 'M12 4v16M4 12h16', camera: 'M3 7h4l2-3h6l2 3h4v14H3V7Zm9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z', play: 'm7 4 14 8-14 8V4Z', pause: 'M8 4v16M16 4v16', bolt: 'm13 2-9 12h7l-1 8 10-13h-8l1-7Z', back: 'm15 5-7 7 7 7', check: 'm5 12 4 4L19 6', download: 'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4', close: 'm6 6 12 12M6 18 18 6' };
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none"><Path d={paths[name] || paths.twin} stroke={color} strokeWidth={1.65} strokeLinecap="round" strokeLinejoin="round" /></Svg>;
}
export function Button({ title, onPress, kind = 'primary', disabled, icon, style }: { title: string; onPress: () => void; kind?: 'primary' | 'quiet' | 'danger'; disabled?: boolean; icon?: string; style?: ViewStyle }) {
  const color = kind === 'primary' ? '#fff' : kind === 'danger' ? C.red : C.ink;
  return <Pressable accessibilityRole="button" accessibilityLabel={title} disabled={disabled} onPress={onPress} style={({ pressed }) => [s.button, { backgroundColor: kind === 'primary' ? C.ink : kind === 'danger' ? '#f9e9e2' : '#ffffffbd', opacity: disabled ? .4 : pressed ? .75 : 1 }, style]}>{icon && <Icon name={icon} color={color} size={18} />}<Text style={[s.buttonText, { color }]}>{title}</Text></Pressable>;
}
export function Card({ children, style }: React.PropsWithChildren<{ style?: ViewStyle }>) { return <View style={[s.card, style]}>{children}</View>; }
export function Heading({ title, detail }: { title: string; detail?: string }) { return <View style={{ marginBottom: 20 }}><Text style={s.title}>{title}</Text>{detail && <Text style={[s.muted, { marginTop: 8 }]}>{detail}</Text>}</View>; }
export function Field({ title, ...props }: React.ComponentProps<typeof TextInput> & { title: string }) { return <View style={{ gap: 9 }}><Text style={s.fieldLabel}>{title}</Text><TextInput placeholderTextColor="#87998f" accessibilityLabel={title} {...props} style={[s.input, props.multiline && { minHeight: 112, textAlignVertical: 'top' }, props.style]} /></View>; }
export function Section({ title, children, aside }: React.PropsWithChildren<{ title: string; aside?: React.ReactNode }>) { return <View style={{ gap: 15, marginTop: 6 }}><View style={s.rowBetween}><Text style={s.section}>{title}</Text>{aside}</View>{children}</View>; }
export function Screen({ children, title, detail, back = false }: React.PropsWithChildren<{ title: string; detail?: string; back?: boolean }>) {
  const h = useHalo(), insets = useSafeAreaInsets();
  return <LinearGradient colors={['#e1ede5', '#edf3ef', '#f5f6f0']} style={{ flex: 1 }}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingTop: Math.max(insets.top, 16), paddingBottom: 32 + insets.bottom, paddingHorizontal: 22, width: '100%', maxWidth: 580, alignSelf: 'center', gap: 22 }} refreshControl={<RefreshControl refreshing={false} onRefresh={() => void h.refresh()} tintColor={C.green} />}>
    <View style={[s.rowBetween, { marginBottom: 4 }]}>{back ? <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() => router.back()} style={s.round}><Icon name="back" /></Pressable> : <Text style={s.logo}>halo<Text style={{ color: '#4d8d73' }}>.</Text></Text>}<Pressable accessibilityRole="button" accessibilityLabel="Settings" onPress={() => router.push('/account')} style={s.round}><Icon name="account" size={20} /></Pressable></View>
    <Heading title={title} detail={detail} />
    {h.offline && <View style={s.notice}><Text style={s.noticeText}>{h.booting ? 'Connecting…' : h.snapshot ? 'Offline · saved readings' : 'Live connection unavailable'}</Text></View>}
    {!!h.error && <Pressable onPress={h.clearError} style={s.notice}><Text style={s.noticeText}>{h.error}</Text></Pressable>}
    {children}
  </ScrollView></LinearGradient>;
}
export function SourceSwitch() { const h = useHalo(); return <View style={s.segment}>{(['industrial', 'prototype'] as const).map(source => <Pressable accessibilityRole="button" accessibilityState={{ selected: h.source === source }} key={source} onPress={() => h.select(source)} style={[s.segmentItem, h.source === source && { backgroundColor: '#fff' }]}><Text style={{ color: h.source === source ? C.ink : C.muted, fontSize: 15, fontWeight: '600' }}>{label(source)}</Text></Pressable>)}</View>; }
export function Empty({ title, text, children }: React.PropsWithChildren<{ title: string; text: string }>) { return <Card style={{ gap: 16, paddingVertical: 32 }}><Icon name="twin" size={36} /><Text style={s.section}>{title}</Text><Text style={s.body}>{text}</Text>{children}</Card>; }
export function Loading() { return <ActivityIndicator color={C.green} style={{ padding: 35 }} />; }
export function Trend({ rows }: { rows: { transformer_temperature: number | null }[] }) {
  const vals = rows.map(r => r.transformer_temperature).filter((v): v is number => v != null && Number.isFinite(v));
  if (!vals.length) return <Text style={s.muted}>No temperature readings yet.</Text>;
  const lo = Math.min(...vals) - 2, hi = Math.max(...vals) + 2, x = (i: number) => 8 + i / Math.max(1, rows.length - 1) * 284, y = (v: number) => 125 - (v - lo) / (hi - lo) * 106;
  let d = '', linked = false; rows.forEach((r, i) => { const v = r.transformer_temperature; if (v == null || !Number.isFinite(v)) { linked = false; return; } d += `${linked ? 'L' : 'M'}${x(i)},${y(v)} `; linked = true; });
  return <View accessibilityLabel={`Temperature trend, ${rows.length} samples. ${fmt(vals.at(-1))} degrees Celsius.`}><View style={s.rowBetween}><Text style={s.muted}>{fmt(hi)}°</Text><Text style={s.muted}>°C</Text></View><Svg width="100%" height={140} viewBox="0 0 300 140">{[30, 75, 120].map(y => <Line key={y} x1="0" x2="300" y1={y} y2={y} stroke={C.line} strokeDasharray="3 5" />)}<Path d={d} stroke={C.green} strokeWidth={2.4} fill="none" strokeLinecap="round" strokeLinejoin="round" /></Svg><View style={s.rowBetween}><Text style={s.muted}>Earlier</Text><Text style={s.muted}>Latest</Text></View></View>;
}
export const s = StyleSheet.create({
  logo: { fontSize: 33, fontWeight: '700', letterSpacing: -1.8, color: C.ink }, title: { fontSize: 34, fontWeight: '600', letterSpacing: -1.1, color: C.ink, lineHeight: 41 }, section: { fontSize: 20, fontWeight: '600', letterSpacing: -.4, color: C.ink }, body: { fontSize: 15, lineHeight: 24, color: C.ink }, muted: { fontSize: 13, lineHeight: 20, color: C.muted }, fieldLabel: { color: C.ink, fontSize: 14, fontWeight: '500' },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }, row: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 10 },
  card: { backgroundColor: '#ffffffc9', borderColor: '#fff', borderWidth: 1, borderRadius: 25, padding: 22, gap: 16 }, button: { minHeight: 48, borderRadius: 16, paddingVertical: 13, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9 }, buttonText: { fontSize: 14, fontWeight: '600' }, round: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#ffffffb3', alignItems: 'center', justifyContent: 'center' }, input: { borderRadius: 15, borderWidth: 1, borderColor: C.line, backgroundColor: '#fff', padding: 15, color: C.ink, fontSize: 16, minHeight: 50 },
  segment: { flexDirection: 'row', borderRadius: 19, backgroundColor: '#d9e5dd', padding: 5, gap: 4 }, segmentItem: { flex: 1, minHeight: 43, alignItems: 'center', justifyContent: 'center', borderRadius: 14 }, notice: { backgroundColor: '#fff0df', borderRadius: 15, padding: 15 }, noticeText: { color: '#895328', fontSize: 14, lineHeight: 21 }, divider: { height: 1, backgroundColor: C.line }, chip: { paddingVertical: 9, paddingHorizontal: 13, borderRadius: 13, backgroundColor: '#ffffffbc', borderWidth: 1, borderColor: C.line }, stat: { fontSize: 28, fontWeight: '500', letterSpacing: -.8, color: C.ink },
});
