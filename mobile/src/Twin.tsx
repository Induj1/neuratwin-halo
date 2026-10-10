import React, { useCallback, useEffect, useRef } from 'react';
import { Platform, View } from 'react-native';
import { WebView } from 'react-native-webview';
import html from './generated/twin';
export function Twin({ source, temperature, severity, focus }: { source: string; temperature: number | null; severity: string; focus?: string | null }) {
  const native = useRef<WebView>(null), frame = useRef<HTMLIFrameElement>(null);
  const data = JSON.stringify({ kind: 'halo-state', source, temperature, focus, severity: severity === 'TRIP' || severity === 'CRITICAL' ? 'critical' : severity === 'WARNING' ? 'warning' : 'normal' });
  const sync = useCallback(() => { if (Platform.OS === 'web') frame.current?.contentWindow?.postMessage(data, '*'); else native.current?.injectJavaScript(`window.receive(${JSON.stringify(data)});true;`); }, [data]);
  useEffect(() => { sync(); }, [sync]);
  useEffect(() => { if (Platform.OS !== 'web') return; const receive = (event: MessageEvent) => { if (event.source === frame.current?.contentWindow && event.data === 'halo-model-ready') sync(); }; window.addEventListener('message', receive); return () => window.removeEventListener('message', receive); }, [sync]);
  return <View style={{ height: 245, marginHorizontal: -18, overflow: 'hidden' }}>{Platform.OS === 'web' ? React.createElement('iframe', { ref: frame, srcDoc: html, title: 'Interactive transformer', sandbox: 'allow-scripts', style: { width: '100%', height: '100%', border: 0 }, onLoad: sync }) : <WebView ref={native} source={{ html }} style={{ backgroundColor: 'transparent' }} scrollEnabled={false} onMessage={sync} onLoadEnd={sync} originWhitelist={['about:blank']} onShouldStartLoadWithRequest={r => r.url === 'about:blank'} javaScriptEnabled />}</View>;
}
