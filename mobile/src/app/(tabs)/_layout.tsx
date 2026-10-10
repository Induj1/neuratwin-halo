import React from 'react';
import { Tabs } from 'expo-router';
import { Icon, C } from '../../ui';
export default function Layout() { return <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: C.ink, tabBarInactiveTintColor: '#82938a', tabBarStyle: { backgroundColor: '#f8fbf8', borderTopColor: '#e0e9e2', paddingTop: 10, minHeight: 76 }, tabBarLabelStyle: { fontSize: 11, fontWeight: '600', marginTop: 4 } }}>{[['index', 'Twin', 'twin'], ['alerts', 'Alerts', 'alerts'], ['inspect', 'Inspect', 'inspect'], ['assistant', 'Assistant', 'assistant']].map(([name, title, icon]) => <Tabs.Screen key={name} name={name} options={{ title, tabBarIcon: ({ color }) => <Icon name={icon} color={String(color)} /> }} />)}</Tabs>; }
