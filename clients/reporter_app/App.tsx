/**
 * Reporter app root.
 *
 * A tab bar over three panels, matching the responder console's chrome:
 *
 *   Report  -- the agent conversation; where the report is actually filed
 *   Map     -- where the animal is, and who is coming to it
 *   Contact -- a phone number, so a rescue team can call back
 *
 * Previously this was a one-way switch: the conversation, then the tracking
 * map, with no way back. That hid the map until intake finished and made the
 * conversation unreachable afterwards, which is wrong in both directions --
 * a reporter waiting on a beach wants to check both.
 *
 * Map and Contact need an incident to exist, which happens on the first API
 * call. Until then they explain themselves rather than appearing broken.
 */

import { useCallback, useState } from 'react';
import { Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import ContactScreen from './src/screens/ContactScreen';
import ReportScreen from './src/screens/ReportScreen';
import TrackScreen from './src/screens/TrackScreen';
import type { Conditions } from './src/lib/api';
import { colors, glass, radius, shadow, spacing, type } from './src/lib/theme';

type TabName = 'report' | 'map' | 'contact';

const TABS: { name: TabName; label: string }[] = [
  { name: 'report', label: 'Report' },
  { name: 'map', label: 'Map' },
  { name: 'contact', label: 'Contact' },
];

/** Monterey Bay, used only until the reporter shares their actual location. */
const FALLBACK_LATITUDE = 36.8044;
const FALLBACK_LONGITUDE = -121.7869;

export default function App() {
  const [tab, setTab] = useState<TabName>('report');
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [coordinates, setCoordinates] = useState<{ latitude: number; longitude: number } | null>(
    null,
  );
  const [phone, setPhone] = useState('');
  const [conditions, setConditions] = useState<Conditions | null>(null);
  // A pin placed on the Map tab, handed to the Report tab to submit --
  // setting a location advances the conversation, which it owns.
  const [pendingPin, setPendingPin] = useState<
    { latitude: number; longitude: number } | null
  >(null);

  // Captured from the GPS fix the reporter shares, so the map centres on the
  // animal rather than on a hardcoded bay.
  const handleLocation = useCallback((latitude: number, longitude: number) => {
    setCoordinates({ latitude, longitude });
  }, []);

  const handleIncident = useCallback((id: string) => setIncidentId(id), []);

  const handleComplete = useCallback((id: string) => {
    setIncidentId(id);
    // Filing the report is the moment the map becomes the useful screen.
    setTab('map');
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />

      <View style={styles.tabs}>
        {TABS.map(({ name, label }) => {
          const active = tab === name;
          return (
            <Pressable
              key={name}
              style={[styles.tab, active && styles.tabActive]}
              onPress={() => setTab(name)}
            >
              <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.body}>
        {/* Kept mounted rather than unmounted when another tab is shown:
            remounting would restart intake and lose the transcript. */}
        <View style={[styles.panel, tab !== 'report' && styles.hidden]}>
          <ReportScreen
            onComplete={handleComplete}
            onIncident={handleIncident}
            onLocation={handleLocation}
            onConditions={setConditions}
            pendingPin={pendingPin}
            onPinSubmitted={() => setPendingPin(null)}
          />
        </View>

        {tab === 'map' && (
          <View style={styles.panel}>
            {incidentId ? (
              <TrackScreen
                incidentId={incidentId}
                incidentLatitude={coordinates?.latitude ?? FALLBACK_LATITUDE}
                incidentLongitude={coordinates?.longitude ?? FALLBACK_LONGITUDE}
                locationKnown={coordinates !== null}
                conditions={conditions}
                onPlacePin={(latitude, longitude) =>
                  setPendingPin({ latitude, longitude })
                }
                placingPin={pendingPin !== null}
              />
            ) : (
              <NotYet
                title="No report started"
                body="Send a photo on the Report tab and the map will show where the animal is."
              />
            )}
          </View>
        )}

        {tab === 'contact' && (
          <View style={styles.panel}>
            {incidentId ? (
              <ContactScreen incidentId={incidentId} phone={phone} onSaved={setPhone} />
            ) : (
              <NotYet
                title="No report started"
                body="Once a report exists you can leave a phone number here for the rescue team."
              />
            )}
          </View>
        )}
      </View>
    </SafeAreaView>
  );
}

function NotYet({ title, body }: { title: string; body: string }) {
  return (
    <View style={styles.empty}>
      <View style={styles.emptyCard}>
        <Text style={styles.emptyTitle}>{title}</Text>
        <Text style={styles.emptyBody}>{body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },

  tabs: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  tabActive: { borderBottomColor: colors.accent },
  tabLabel: { ...type.label, color: colors.textMuted },
  tabLabelActive: { color: colors.accent },

  body: { flex: 1 },
  panel: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  hidden: { display: 'none' },

  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  emptyCard: {
    ...glass,
    ...shadow.soft,
    padding: spacing.xl,
    borderRadius: radius.card,
    alignItems: 'center',
    gap: spacing.sm,
  },
  emptyTitle: { ...type.heading, color: colors.text },
  emptyBody: { ...type.meta, color: colors.textMuted, textAlign: 'center', lineHeight: 19 },
});
