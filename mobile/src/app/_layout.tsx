import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { HaloProvider } from '../store';
import { NotificationListener } from '../notifications';
function Navigation() {
  return <><StatusBar style="dark" /><NotificationListener /><Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#edf3ef' } }}><Stack.Screen name="(tabs)" /><Stack.Screen name="login" /><Stack.Screen name="account" options={{ presentation: 'modal' }} /><Stack.Screen name="replay" /><Stack.Screen name="controls" options={{ presentation: 'modal' }} /></Stack></>;
}
export default function Layout() { return <SafeAreaProvider><HaloProvider><Navigation /></HaloProvider></SafeAreaProvider>; }
