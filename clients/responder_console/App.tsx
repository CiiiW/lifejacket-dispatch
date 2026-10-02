/**
 * Responder console root. Runs on iOS, Android, and the web from this file.
 *
 * A three-state view switch rather than a navigation library, matching the
 * reporter app: map -> detail -> log, and back. Swap in `expo-router` if the
 * console grows a sidebar or deep links.
 *
 * `RESPONDER_ID` is hardcoded until authentication exists. Every responder
 * action is attributed to it, so this must be replaced before the console is
 * used by more than one person -- see the repository README.
 */

import { useState } from 'react';
import { SafeAreaView, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import IncidentDetailScreen from './src/screens/IncidentDetailScreen';
import IncidentMapScreen from './src/screens/IncidentMapScreen';
import LogIncidentScreen from './src/screens/LogIncidentScreen';

// TODO: replace with the signed-in responder once auth is in place.
const RESPONDER_ID = 'org_the_marine_mammal_center_monterey_bay_operat';

type View =
  | { name: 'map' }
  | { name: 'detail'; incidentId: string }
  | { name: 'log'; incidentId: string };

export default function App() {
  const [view, setView] = useState<View>({ name: 'map' });

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="auto" />

      {view.name === 'map' && (
        <IncidentMapScreen
          onSelect={(incidentId) => setView({ name: 'detail', incidentId })}
        />
      )}

      {view.name === 'detail' && (
        <IncidentDetailScreen
          incidentId={view.incidentId}
          responderId={RESPONDER_ID}
          onLog={(incidentId) => setView({ name: 'log', incidentId })}
          onBack={() => setView({ name: 'map' })}
        />
      )}

      {view.name === 'log' && (
        <LogIncidentScreen
          incidentId={view.incidentId}
          responderId={RESPONDER_ID}
          onDone={() => setView({ name: 'map' })}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
});
