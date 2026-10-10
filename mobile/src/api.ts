import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import demoConnectionConfig from './generated/connection.json';

export type Session = { url: string; access_token: string; refresh_token?: string; user_id?: string; role?: string; expires_at?: number };
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
let session: Session | null = null;
let renewal: Promise<void> | null = null;
let generation = 0;
const key = 'halo-mobile-session';
export const defaultUrl = Platform.OS === 'web' && typeof location !== 'undefined' ? location.origin : process.env.EXPO_PUBLIC_API_URL || demoConnectionConfig.url;
let demoConnection: Promise<Session> | null = null;
export function normalizeUrl(value: string) {
  const u = new URL(value.trim());
  if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password || u.search || u.hash) throw Error('Enter the server URL, for example https://your-server.example.');
  if (u.protocol === 'http:' && !/^(localhost$|127\.0\.0\.1$|10\.\d+\.\d+\.\d+$|192\.168\.\d+\.\d+$|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$)/.test(u.hostname)) throw Error('Use HTTPS for a public server.');
  return u.origin;
}
export async function saveSession(value: Session | null, renewed = false) {
  if (!renewed) generation++;
  session = value;
  if (Platform.OS === 'web') { if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key); }
  else if (value) await SecureStore.setItemAsync(key, JSON.stringify(value)); else await SecureStore.deleteItemAsync(key);
}
export async function loadSession() {
  const raw = Platform.OS === 'web' ? sessionStorage.getItem(key) : await SecureStore.getItemAsync(key);
  let cached: Session | null = null;
  try { cached = raw ? JSON.parse(raw) : null; } catch {}
  if (cached?.url === defaultUrl && cached.role === 'demo') session = cached;
  try { return await connectDemo(); } catch (error) { if (session) return session; throw error; }
}
export async function connectDemo(): Promise<Session> {
  if (!demoConnection) demoConnection = (async () => {
    if (!defaultUrl) throw Error('Connection unavailable.');
    const url = normalizeUrl(defaultUrl);
    const data = await (await raw(url, '/api/halo/mobile/demo-session')).json();
    const value: Session = { url, ...data };
    await saveSession(value, true);
    return value;
  })().finally(() => { demoConnection = null; });
  return demoConnection;
}
export function getSession() { return session; }
export async function raw(url: string, path: string, body?: unknown, token?: string) {
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), path.endsWith('/assistant') ? 35000 : 18000);
  try {
    const response = await fetch(url + path, { method: body === undefined ? 'GET' : 'POST', signal: controller.signal, headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new ApiError(typeof data.detail === 'string' ? data.detail : response.status === 422 ? 'Check the values and try again.' : 'Request could not be completed.', response.status); }
    return response;
  } finally { clearTimeout(timer); }
}
async function renew() {
  if (!session?.refresh_token) return;
  if (!renewal) renewal = (async () => { const before = session!; const data = await (await raw(before.url, '/api/halo/mobile/refresh', { refresh_token: before.refresh_token })).json(); if (session === before) await saveSession({ ...before, ...data, expires_at: Date.now() + data.expires_in * 1000 }, true); })().finally(() => { renewal = null; });
  await renewal;
}
export async function request(path: string, body?: unknown, retry = true): Promise<Response> {
  const expected = generation;
  if (!session) await connectDemo();
  if (session?.expires_at && session.expires_at < Date.now() + 30000) await renew();
  if (!session || expected !== generation) throw new ApiError('Session changed. Retry from the current account.', 401);
  try { return await raw(session.url, '/api/halo' + path, body, session.access_token); }
  catch (e) { if (e instanceof ApiError && e.status === 401 && retry && session?.role === 'demo' && expected === generation) { await connectDemo(); return request(path, body, false); } if (e instanceof ApiError && e.status === 401 && retry && session?.refresh_token && expected === generation) { await renew(); if (expected !== generation) throw e; return request(path, body, false); } throw e; }
}
export async function api<T = any>(path: string, body?: unknown): Promise<T> { return (await request(path, body)).json(); }
