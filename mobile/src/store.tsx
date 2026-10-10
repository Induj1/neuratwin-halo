import React, { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Crypto from 'expo-crypto';
import { api, ApiError, defaultUrl, loadSession, Session } from './api';
import { Catalog, Draft, Inspection, Snapshot, Source } from './types';
import { readDrafts, writeDrafts } from './drafts';

type Store = { session: Session | null; booting: boolean; source: Source; runId: string | null; snapshot: Snapshot | null; catalog: Catalog | null; offline: boolean; busy: boolean; error: string; drafts: Draft[]; inspections: Inspection[]; serverClock: boolean;
  reconnect: () => Promise<void>; select: (source: Source, runId?: string | null) => void; refresh: () => Promise<void>; command: (action: string, extra?: object) => Promise<void>; createRun: () => Promise<void>; saveDraft: (draft: Draft) => Promise<void>; discardDraft: (id: string) => Promise<void>; submitDraft: (draft: Draft) => Promise<void>; clearError: () => void };
const Context = createContext<Store>(null!);
export const useHalo = () => useContext(Context);
export const uuid = () => Crypto.randomUUID();

export function HaloProvider({ children }: React.PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null), [booting, setBooting] = useState(true);
  const [source, setSource] = useState<Source>('industrial'), [runId, setRunId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null), [catalog, setCatalog] = useState<Catalog | null>(null);
  const [offline, setOffline] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [drafts, setDrafts] = useState<Draft[]>([]), [inspections, setInspections] = useState<Inspection[]>([]);
  const current = useRef({ session, source, runId });
  useLayoutEffect(() => { current.current = { session, source, runId }; }, [session, source, runId]);
  const refreshing = useRef(false), mutating = useRef(false), draftRef = useRef<Draft[]>([]), syncing = useRef(false);
  const hydrated = useRef(false);
  const refreshRef = useRef<() => Promise<void>>(async () => {});
  const draftWrites = useRef<Promise<void>>(Promise.resolve());
  const namespace = (_session?: Session | null) => 'halo-' + encodeURIComponent(defaultUrl + ':local');
  const connecting = useRef(false);
  function reconnect(): Promise<void> {
    if (connecting.current) return Promise.resolve();
    connecting.current = true;
    return loadSession().then(value => { setSession(value); setError(''); })
      .catch(() => { setOffline(true); })
      .finally(() => { connecting.current = false; setBooting(false); });
  }
  useEffect(() => {
    void reconnect();
    const timer = setInterval(() => { if (!current.current.session) void reconnect(); }, 8000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const key = namespace(); let cancelled = false;
    Promise.all([AsyncStorage.getItem(key + '-selection'), readDrafts(key + '-drafts')]).then(([selection, saved]) => {
      if (cancelled) return;
      try { if (selection) { const v = JSON.parse(selection); if (['industrial','prototype'].includes(v.source)) { current.current.source = v.source; current.current.runId = v.runId; setSource(v.source); setRunId(v.runId); } } draftRef.current = saved; setDrafts(saved); } catch { setError('Saved device data could not be read.'); }
    }).catch(() => { if(!cancelled)setError('Saved device data could not be read.'); }).finally(() => { if(!cancelled){ hydrated.current = true; void refreshRef.current(); } }); return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    const key = namespace() + '-snapshot-' + source + '-' + (runId || 'none');
    AsyncStorage.getItem(key).then(saved => {
      if (!saved || cancelled) return;
      try { const value = JSON.parse(saved); setSnapshot(previous => previous || value); } catch {}
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [source, runId]);
  function select(next: Source, id?: string | null) {
    current.current.source = next; if(id !== undefined)current.current.runId = id;
    setSource(next); if (id !== undefined) setRunId(id); setSnapshot(null); setInspections([]); setError('');
    void AsyncStorage.setItem(namespace() + '-selection', JSON.stringify({ source: next, runId: id === undefined ? runId : id }));
  }
  async function persistDrafts(change: (previous: Draft[]) => Draft[]) {
    const write = draftWrites.current.catch(() => {}).then(async () => {
      if (!hydrated.current) throw Error('Device storage is still loading. Try again.');
      const next = change(draftRef.current);
      await writeDrafts(namespace(session) + '-drafts', next);
      draftRef.current = next; setDrafts(next);
    });
    draftWrites.current = write;
    await write;
  }
  async function saveDraft(draft: Draft) { await persistDrafts(previous => [draft, ...previous.filter(d => d.request_id !== draft.request_id)]); }
  async function discardDraft(id: string) { await persistDrafts(previous => previous.filter(d => d.request_id !== id)); }
  async function upload(draft: Draft) { if (current.current.session !== session) return; const { queued, error: ignored, ...payload } = draft; await api('/mobile/inspections', payload); if (current.current.session === session) await discardDraft(draft.request_id); }
  async function refresh() {
    if (!current.current.session) { void reconnect(); return; }
    if (!hydrated.current || refreshing.current) return;
    refreshing.current = true;
    const ctx = { ...current.current }, stillCurrent = () => current.current.session === ctx.session && current.current.source === ctx.source && current.current.runId === ctx.runId;
    const cache = namespace(ctx.session!) + '-snapshot-' + ctx.source + '-' + (ctx.runId || 'none');
    try {
      const list = await api<Catalog>('/twin/catalog'); if (!stillCurrent()) return; setCatalog(list);
      if (ctx.source === 'industrial' && !ctx.runId && list.runs.length) { select('industrial', list.runs[0].id); return; }
      let snap: Snapshot | null;
      try { snap = ctx.source === 'prototype' ? await api<Snapshot>('/twin/prototype') : ctx.runId ? await api<Snapshot>('/twin/runs/' + encodeURIComponent(ctx.runId)) : null; }
      catch (error) {
        if (error instanceof ApiError && error.status === 404 && ctx.source === 'industrial' && stillCurrent()) {
          await AsyncStorage.removeItem(cache);
          select('industrial', list.runs[0]?.id || null); setOffline(false); return;
        }
        throw error;
      }
      if (!stillCurrent()) return;
      setSnapshot(previous => previous?.id === snap?.id && previous?.source === 'industrial' && (previous?.revision || 0) > (snap?.revision || 0) ? previous : snap); setOffline(false);
      if (snap) await AsyncStorage.setItem(cache, JSON.stringify(snap));
      if (snap) {
        const notes = await api<Inspection[]>('/mobile/inspections?' + new URLSearchParams({ source: ctx.source, ...(ctx.runId ? { run_id: ctx.runId } : {}) }));
        if (stillCurrent()) setInspections(notes);
      }
      if (!syncing.current && draftRef.current.some(d => d.queued)) {
        syncing.current = true;
        try { for (const d of [...draftRef.current].filter(d => d.queued)) { if (current.current.session !== ctx.session) break; try { await upload(d); } catch (e) { if (e instanceof ApiError && e.status < 500) await saveDraft({ ...d, queued: false, error: e.message }); else break; } } } finally { syncing.current = false; }
      }
    } catch (e) {
      if (!stillCurrent()) return;
      if (e instanceof ApiError && [401,403].includes(e.status)) { setOffline(true); setSnapshot(null); setInspections([]); setError('Live connection unavailable'); }
      else { setOffline(true); const saved = await AsyncStorage.getItem(cache); if (saved && stillCurrent()) { try { setSnapshot(JSON.parse(saved)); } catch {} } }
    } finally { refreshing.current = false; }
  }
  useLayoutEffect(() => { refreshRef.current = refresh; });
  useEffect(() => { void refreshRef.current(); const timer = setInterval(() => { if (AppState.currentState === 'active') void refreshRef.current(); }, 1500); const event = AppState.addEventListener('change', state => { if (state === 'active') void refreshRef.current(); }); return () => { clearInterval(timer); event.remove(); }; }, [session, source, runId]);
  async function perform(fn: () => Promise<void>) {
    if (mutating.current) throw Error('Wait for the current action to finish.');
    mutating.current = true; setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'Could not complete the action.'); throw e; } finally { mutating.current = false; setBusy(false); void refresh(); }
  }
  async function command(action: string, extra = {}) {
    if (offline || !snapshot || source !== 'industrial') throw Error('Reconnect and select an industrial run.');
    const id = snapshot.id;
    await perform(async () => {
      for(let attempt=0;attempt<3;attempt++) {
        const latest = await api<Snapshot>('/twin/runs/' + id);
        if (current.current.session !== session) throw Error('Session changed.');
        try { const result = await api<Snapshot>('/twin/runs/' + id + '/actions', { action, revision: latest.revision, request_id: uuid(), ...extra }); if (current.current.session === session && current.current.source === 'industrial' && current.current.runId === id) setSnapshot(result); return; }
        catch(e) { if (!(e instanceof ApiError && e.status === 409 && ['start','pause'].includes(action) && attempt < 2)) throw e; }
      }
    });
  }
  async function createRun() { const origin = current.current.source; await perform(async () => { const result = await api<Snapshot>('/twin/runs', { request_id: uuid() }); if (current.current.session === session && current.current.source === origin) { select('industrial', result.id); setSnapshot(result); } }); }
  async function submitDraft(draft: Draft) { await saveDraft({ ...draft, queued: true, error: undefined }); if (!offline) { try { await upload(draft); } catch (e) { if (e instanceof ApiError && e.status < 500) { await saveDraft({ ...draft, queued: false, error: e.message }); throw e; } } } void refresh(); }
  return <Context.Provider value={{ session, booting, source, runId, snapshot, catalog, offline, busy, error, drafts, inspections, serverClock: !!catalog?.server_clock, reconnect, select, refresh, command, createRun, saveDraft, discardDraft, submitDraft, clearError: () => setError('') }}>{children}</Context.Provider>;
}
