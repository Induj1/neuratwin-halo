import { useEffect, useLayoutEffect, useRef } from 'react';
import type { NotificationResponse } from 'expo-notifications';
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import { router } from 'expo-router';
import { api, getSession } from './api';
import { useHalo } from './store';
async function tokenKey() { const s = getSession(); return 'halo-push-' + await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, (s?.url || '') + ':' + (s?.user_id || 'local')); }
export async function enableNotifications(source: string, runId: string | null) {
  if (Platform.OS === 'web') throw Error('Open the installed phone app to enable push notifications.');
  const projectId = Constants.expoConfig?.extra?.eas?.projectId || Constants.easConfig?.projectId;
  if (!projectId) throw Error('Link this development build to an EAS project before enabling notifications.');
  const N = await import('expo-notifications');
  if (Platform.OS === 'android') await N.setNotificationChannelAsync('transformer-alerts', { name: 'Transformer alerts', importance: N.AndroidImportance.HIGH });
  const permission = await N.requestPermissionsAsync();
  if (!permission.granted) throw Error('Notifications are disabled in your device settings.');
  const token = (await N.getExpoPushTokenAsync({ projectId })).data;
  const result = await api('/mobile/notifications', { source, run_id: source === 'industrial' ? runId : null, token, enabled: true });
  await SecureStore.setItemAsync(await tokenKey(), token);
  return result.delivery_enabled ? 'Notifications enabled for this asset.' : 'Device registered. Start the server notification worker to deliver alerts.';
}
export async function disableNotifications(source: string, runId: string | null) { if (Platform.OS === 'web') return; const key = await tokenKey(), token = await SecureStore.getItemAsync(key); if (token) { await api('/mobile/notifications', { source, run_id: source === 'industrial' ? runId : null, token, enabled: false }); await SecureStore.deleteItemAsync(key); } }
export function NotificationListener() {
  const h = useHalo();
  const { session } = h;
  const haloRef = useRef(h);
  useLayoutEffect(() => { haloRef.current = h; }, [h]);
  useEffect(() => {
    if (Platform.OS === 'web' || !session) return;
    let remove: (() => void) | undefined, cancelled = false;
    import('expo-notifications').then(N => {
      if (cancelled) return;
      N.setNotificationHandler({ handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }) });
      const handle = (response: NotificationResponse | null) => { if(cancelled)return; const data = response?.notification.request.content.data; if (data?.source === 'industrial' && typeof data.run_id === 'string') haloRef.current.select('industrial', data.run_id); else if (data?.source === 'prototype') haloRef.current.select('prototype'); else return; router.push('/alerts'); void N.clearLastNotificationResponseAsync(); };
      const sub = N.addNotificationResponseReceivedListener(handle); remove = () => sub.remove();
      N.getLastNotificationResponseAsync().then(handle);
    }).catch(() => {});
    return () => { cancelled = true; remove?.(); };
  }, [session]);
  return null;
}
