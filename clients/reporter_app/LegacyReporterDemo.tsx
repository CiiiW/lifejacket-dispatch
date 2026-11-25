/**
 * Reporter app root.
 *
 * A tab bar over three panels, matching the responder console's chrome:
 *
 *   Report          -- the agent conversation; where a report is filed. After
 *                      one is filed, "Start another report" begins the next
 *                      without restarting the app.
 *   My reports      -- every report this phone has sent, on a map and in a
 *                      list, each with its status, map and messages.
 *   Communications  -- a conversation with the rescue team per report, and
 *                      the phone number every report shares.
 *
 * Using the app means sharing a phone number with the rescue organisation
 * handling each report, so it is asked for once, the first time the app
 * opens, and saved on the phone with the reports (`src/lib/reporterStore.ts`).
 * After that every report starts at once, with no form in the way.
 *
 * This submits through the legacy intake API and does NOT verify the
 * reporter's phone number, so it carries a banner saying so (hidden in demo
 * mode, for screen recordings: see src/lib/demo.ts). Phone-verified
 * reporting lives in the browser app (`App.web.tsx` -> PhoneReporter.web),
 * which needs native Firebase modules Expo Go does not ship.
 */

import { useCallback, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';

import CommunicationsScreen from './src/screens/CommunicationsScreen';
import MyReportsScreen from './src/screens/MyReportsScreen';
import PhoneSetupScreen from './src/screens/PhoneSetupScreen';
import ReportScreen from './src/screens/ReportScreen';
import { reporter, type MatchedTeam } from './src/lib/api';
import { DEMO_MODE } from './src/lib/demo';
import { useReporterStore } from './src/lib/reporterStore';
import { reportStatus } from './src/lib/reportStatus';
import { useMyReports } from './src/lib/useMyReports';
import { colors, spacing, type } from './src/lib/theme';

type TabName = 'report' | 'reports' | 'messages';

const TABS: { name: TabName; label: string }[] = [
  { name: 'report', label: 'Report' },
  { name: 'reports', label: 'My reports' },
  { name: 'messages', label: 'Communications' },
];

export default function App() {
  const store = useReporterStore();
  const { byId: summaries, known, refresh } = useMyReports(store.reports);

  const [tab, setTab] = useState<TabName>('report');
  // Bumped to start a new report: the Report tab remounts with fresh state.
  const [session, setSession] = useState(0);
  const [current, setCurrent] = useState<{ incidentId: string | null; complete: boolean }>({
    incidentId: null,
    complete: false,
  });
  const currentId = useRef<string | null>(null);
  const [matchedTeams, setMatchedTeams] = useState<MatchedTeam[]>([]);
  // A pin placed on My reports, handed to the Report tab to submit --
  // setting a location advances the conversation, which it owns.
  const [pendingPin, setPendingPin] = useState<{ latitude: number; longitude: number } | null>(
    null,
  );
  const [openThread, setOpenThread] = useState<string | null>(null);

  // The start turn brings the report's key. The report is saved only once the
  // reporter does something with it (a photo, a location, an answer), so an
  // opened-and-abandoned screen does not fill My reports with empty entries.
  const pending = useRef<{ incidentId: string; key: string } | null>(null);
  const { addReport, placeReport } = store;
  const handleIncident = useCallback(
    (incidentId: string, key: string | null) => {
      currentId.current = incidentId;
      setCurrent((c) => (c.incidentId === incidentId ? c : { incidentId, complete: false }));
      if (key) {
        pending.current = { incidentId, key };
      } else if (pending.current?.incidentId === incidentId) {
        addReport({
          incidentId,
          key: pending.current.key,
          startedAt: new Date().toISOString(),
          latitude: null,
          longitude: null,
        });
        pending.current = null;
      }
    },
    [addReport],
  );

  const handleLocation = useCallback(
    (latitude: number, longitude: number) => {
      if (currentId.current) placeReport(currentId.current, latitude, longitude);
    },
    [placeReport],
  );

  // Deliberately does not change tabs. Filing the report is the moment the
  // verdict and instructions appear on the Report tab, and yanking someone to
  // another tab takes that away from them mid-read.
  const handleComplete = useCallback(
    (incidentId: string) => {
      setCurrent({ incidentId, complete: true });
      refresh();
    },
    [refresh],
  );

  const beginNewReport = useCallback(() => {
    pending.current = null;
    currentId.current = null;
    setCurrent({ incidentId: null, complete: false });
    setMatchedTeams([]);
    setPendingPin(null);
    setSession((n) => n + 1);
    setTab('report');
  }, []);

  const newReport = useCallback(() => {
    const started = current.incidentId && store.reports.some((r) => r.incidentId === current.incidentId);
    if (started && !current.complete) {
      Alert.alert(
        'Start a new report?',
        'This one has not been sent to a rescue team yet. It will stay unfinished.',
        [
          { text: 'Keep going', style: 'cancel' },
          { text: 'New report', style: 'destructive', onPress: beginNewReport },
        ],
      );
      return;
    }
    beginNewReport();
  }, [current, store.reports, beginNewReport]);

  // A new number goes to the reports still open too: a team still looking
  // for the animal needs the one that works.
  const { setPhone } = store;
  const changePhone = useCallback(
    (phone: string) => {
      setPhone(phone);
      for (const report of store.reports) {
        if (reportStatus(summaries[report.incidentId]?.status, summaries[report.incidentId]?.complete).tone !== 'closed') {
          reporter.setContact(report.incidentId, phone).catch(() => undefined);
        }
      }
    },
    [setPhone, store.reports, summaries],
  );

  const openMessages = useCallback((incidentId: string) => {
    setOpenThread(incidentId);
    setTab('messages');
  }, []);

  if (!store.loaded) {
    return (
      <View style={[styles.root, styles.center]}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!store.phone) {
    return (
      <KeyboardAvoidingView style={styles.root} behavior="padding">
        <SafeAreaView style={styles.root}>
          <StatusBar style="light" />
          <PhoneSetupScreen onSave={store.setPhone} />
        </SafeAreaView>
      </KeyboardAvoidingView>
    );
  }

  // Only reports the server still has, plus the one being written now (it
  // appears there on the next poll). Hidden, not erased from the phone.
  const reports = known
    ? store.reports.filter((r) => known.has(r.incidentId) || r.incidentId === current.incidentId)
    : store.reports;

  const unread = reports.reduce(
    (total, r) =>
      total +
      Math.max(0, (summaries[r.incidentId]?.team_message_count ?? 0) - (store.seenTeam[r.incidentId] ?? 0)),
    0,
  );

  return (
    // Outermost on purpose. KeyboardAvoidingView works out how far to lift
    // its content from its own position, so it only needs no hand-tuned
    // offset when it starts at the very top of the window -- nested under the
    // tab bar it would lift by too little.
    <KeyboardAvoidingView style={styles.root} behavior="padding">
      <SafeAreaView style={styles.root}>
        <StatusBar style="light" />

        {!DEMO_MODE && (
          <View style={styles.banner}>
            <Text style={styles.bannerText}>
              Local testing — reports from here are not phone-verified
            </Text>
          </View>
        )}

        <View style={styles.tabs}>
          {TABS.map(({ name, label }) => {
            const active = tab === name;
            return (
              <Pressable
                key={name}
                style={[styles.tab, active && styles.tabActive]}
                onPress={() => setTab(name)}
              >
                <View style={styles.tabLabelRow}>
                  <Text
                    style={[styles.tabLabel, active && styles.tabLabelActive]}
                    numberOfLines={1}
                  >
                    {label}
                  </Text>
                  {name === 'messages' && unread > 0 && (
                    <View
                      style={styles.unreadDot}
                      accessibilityLabel={`${unread} new message${unread === 1 ? '' : 's'} from the rescue team`}
                    />
                  )}
                </View>
              </Pressable>
            );
          })}
        </View>

        <View style={styles.body}>
          {/* Kept mounted rather than unmounted when another tab is shown:
              remounting would restart intake and lose the transcript. A new
              report is a new `key`, which is exactly a deliberate restart. */}
          <View style={[styles.panel, tab !== 'report' && styles.hidden]}>
            {current.incidentId && store.reports.some((r) => r.incidentId === current.incidentId) && !current.complete && (
              <View style={styles.reportBar}>
                <Text style={styles.reportBarText}>Report in progress</Text>
                <Pressable onPress={newReport} hitSlop={8} accessibilityRole="button">
                  <Text style={styles.reportBarLink}>Start over</Text>
                </Pressable>
              </View>
            )}
            <ReportScreen
              key={session}
              phone={store.phone}
              onComplete={handleComplete}
              onIncident={handleIncident}
              onLocation={handleLocation}
              onMatchedTeams={setMatchedTeams}
              pendingPin={pendingPin}
              onPinSubmitted={() => setPendingPin(null)}
              onNewReport={newReport}
            />
          </View>

          {tab === 'reports' && (
            <View style={styles.panel}>
              <MyReportsScreen
                reports={reports}
                summaries={summaries}
                seenTeam={store.seenTeam}
                currentIncidentId={current.incidentId}
                currentMatchedTeams={matchedTeams}
                onPlacePin={(latitude, longitude) => setPendingPin({ latitude, longitude })}
                placingPin={pendingPin !== null}
                onMessage={openMessages}
                onContinue={() => setTab('report')}
              />
            </View>
          )}

          {tab === 'messages' && (
            <View style={styles.panel}>
              <CommunicationsScreen
                phone={store.phone}
                onChangePhone={changePhone}
                reports={reports}
                summaries={summaries}
                seenTeam={store.seenTeam}
                onSeen={store.markSeen}
                openIncidentId={openThread}
                onOpened={() => setOpenThread(null)}
                onRefresh={refresh}
              />
            </View>
          )}
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { alignItems: 'center', justifyContent: 'center' },

  banner: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.backgroundElevated,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  bannerText: { ...type.meta, color: colors.warning, textAlign: 'center' },

  tabs: {
    flexDirection: 'row',
    paddingHorizontal: spacing.sm,
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
  tabLabel: { ...type.label, fontSize: 13.5, color: colors.textMuted },
  tabLabelActive: { color: colors.accent },
  tabLabelRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.accent },

  reportBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  reportBarText: { ...type.meta, color: colors.textFaint },
  reportBarLink: { ...type.label, fontSize: 13, color: colors.accent },

  body: { flex: 1 },
  panel: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  hidden: { display: 'none' },
});
