/**
 * Reporter app root.
 *
 * Two screens and a hand-rolled switch between them rather than a navigation
 * library: the flow is strictly linear (report, then track), so a router would
 * be more machinery than the app needs. Add `expo-router` if a third screen
 * appears.
 */

import { useState } from 'react';
import { SafeAreaView, StyleSheet } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import ReportScreen from './src/screens/ReportScreen';
import TrackScreen from './src/screens/TrackScreen';

export default function App() {
  const [filedIncidentId, setFiledIncidentId] = useState<string | null>(null);

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="auto" />
      {filedIncidentId === null ? (
        <ReportScreen onComplete={setFiledIncidentId} />
      ) : (
        <TrackScreen
          incidentId={filedIncidentId}
          /* TODO: carry the real coordinates through from the intake response
             instead of defaulting to Monterey Bay. Needs the location echoed
             back on the final turn. */
          incidentLatitude={36.8044}
          incidentLongitude={-121.7869}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
});
