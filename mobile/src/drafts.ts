import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import * as Crypto from 'expo-crypto';
import { Draft } from './types';

// Photos exceed Android AsyncStorage's per-row limit. Native drafts live in the
// app's private documents directory; the account/server hash scopes each file.
async function file(key: string) {
  return FileSystem.documentDirectory + 'inspections-' + await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, key) + '.json';
}
export async function readDrafts(key: string): Promise<Draft[]> {
  let raw: string | null = null;
  if (Platform.OS === 'web') raw = await AsyncStorage.getItem(key);
  else { const path = await file(key); if ((await FileSystem.getInfoAsync(path)).exists) raw = await FileSystem.readAsStringAsync(path); }
  return raw ? JSON.parse(raw) : [];
}
export async function writeDrafts(key: string, drafts: Draft[]) {
  const raw = JSON.stringify(drafts);
  try {
    if (Platform.OS === 'web') await AsyncStorage.setItem(key, raw);
    else await FileSystem.writeAsStringAsync(await file(key), raw);
  } catch { throw Error('Could not save this draft. Free device storage or use a smaller photo, then retry.'); }
}
