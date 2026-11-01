/** Native legacy demo is explicit; production phone reporting uses the web entry. */
import { Linking, Pressable, SafeAreaView, Text } from 'react-native';
import LegacyReporterDemo from './LegacyReporterDemo';
export default function App() {
  if (process.env.EXPO_PUBLIC_LEGACY_REPORTER_DEMO === 'true') return <LegacyReporterDemo />;
  const target = process.env.EXPO_PUBLIC_REPORTER_WEB_URL;
  const safeTarget = target && /^https:\/\/[^\s]+$/.test(target) ? target : null;
  return <SafeAreaView style={{ flex:1, padding:28, backgroundColor:'#0b132b', gap:20 }}>
    <Text style={{ color:'#48cae4', fontSize:28 }}>LifeJacket</Text>
    <Text style={{ color:'white', fontSize:18 }}>Phone-verified reporting is available through the configured browser app.</Text>
    <Text style={{ color:'#b1bdd1' }}>Native SMS verification requires a development build. This app does not submit through an unverified fallback.</Text>
    {safeTarget ? <Pressable onPress={() => Linking.openURL(safeTarget)}><Text style={{ color:'#48cae4' }}>Open reporter app in browser</Text></Pressable> : <Text style={{ color:'#b1bdd1' }}>The reporter web address is awaiting setup.</Text>}
  </SafeAreaView>;
}
