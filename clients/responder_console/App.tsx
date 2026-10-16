/**
 * Responder console root. Runs on iOS, Android, and the web from this file.
 *
 * A tab bar over three screens: triage -> incident -> log. Tapping an
 * incident in triage selects it and moves to the incident tab, so the drill-
 * down still works, but every screen stays reachable from the chrome rather
 * than only through a list row. Swap in `expo-router` if the console grows
 * deep links or a sidebar.
 *
 * `RESPONDER_ID` is hardcoded until authentication exists. Every responder
 * action is attributed to it, so this must be replaced before the console is
 * used by more than one person -- see the repository README.
 */

import { useState } from 'react';
import { Pressable, SafeAreaView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';

import IncidentDetailScreen from './src/screens/IncidentDetailScreen';
import IncidentMapScreen from './src/screens/IncidentMapScreen';
import LogIncidentScreen from './src/screens/LogIncidentScreen';
import HandoverScreen from './src/screens/HandoverScreen';
import { colors, glass, radius, shadow, spacing, type } from './src/lib/theme';

// TODO: replace with the signed-in responder once auth is in place.
const RESPONDER_ID = 'org_the_marine_mammal_center_monterey_bay_operat';

type TabName = 'triage' | 'incident' | 'log' | 'handover';

const TABS: { name: TabName; label: string }[] = [
  { name: 'triage', label: 'Triage' },
  { name: 'incident', label: 'Incident' },
  { name: 'log', label: 'Log outcome' },
  { name: 'handover', label: 'Handover' },
];

export default function App() {
  const [tab, setTab] = useState<TabName>('triage');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  function select(incidentId: string) {
    setSelectedId(incidentId);
    setTab('incident');
  }

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />

      <View style={styles.header}>
        <View style={styles.brandRow}>
          <View style={styles.mark} />
          <Text style={styles.brand}>LifeJacket</Text>
          <Text style={styles.brandMeta}>Responder console</Text>
        </View>

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
      </View>

      <View style={styles.body}>
        {tab === 'handover' && <HandoverScreen onSelect={select} />}
        {tab === 'triage' && <IncidentMapScreen onSelect={select} />}

        {tab === 'incident' &&
          (selectedId ? (
            <IncidentDetailScreen
              key={selectedId}
              incidentId={selectedId}
              responderId={RESPONDER_ID}
              onLog={() => setTab('log')}
              onBack={() => setTab('triage')}
            />
          ) : (
            <NothingSelected what="incident" />
          ))}

        {tab === 'log' &&
          (selectedId ? (
            <LogIncidentScreen
              incidentId={selectedId}
              responderId={RESPONDER_ID}
              onDone={() => setTab('triage')}
            />
          ) : (
            <NothingSelected what="outcome form" />
          ))}
      </View>
    </SafeAreaView>
  );
}

/** Shown when a tab needs a selected incident and there is not one yet. */
function NothingSelected({ what }: { what: string }) {
  return (
    <View style={styles.empty}>
      <View style={styles.emptyCard}>
        <Text style={styles.emptyTitle}>No incident selected</Text>
        <Text style={styles.emptyBody}>
          Pick one in Triage to open its {what}.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },

  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    gap: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  /** A small seafoam block instead of a logo file. */
  mark: {
    width: 10,
    height: 18,
    borderRadius: 3,
    backgroundColor: colors.accent,
  },
  brand: { ...type.heading, color: colors.text },
  brandMeta: { ...type.meta, color: colors.textFaint },

  tabs: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  tab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: 2,
    borderBottomColor: 'transparent',
  },
  tabActive: { borderBottomColor: colors.accent },
  tabLabel: { ...type.label, color: colors.textMuted },
  tabLabelActive: { color: colors.accent },

  body: { flex: 1 },

  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  emptyCard: {
    ...glass,
    ...shadow.soft,
    padding: spacing.xl,
    borderRadius: radius.card,
    alignItems: 'center',
    gap: spacing.sm,
    maxWidth: 380,
  },
  emptyTitle: { ...type.heading, color: colors.text },
  emptyBody: { ...type.meta, color: colors.textMuted, textAlign: 'center' },
});
