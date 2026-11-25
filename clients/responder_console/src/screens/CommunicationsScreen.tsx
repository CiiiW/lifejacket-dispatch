/**
 * Communications: every conversation with a person who reported from the app.
 *
 * Reporters can write first now ("it moved into the water"), so this is the
 * inbox that keeps those from going unread: threads waiting on a reply sit on
 * top and the tab's label counts them. Each thread is the same one the
 * incident page shows; the phone number is the one the reporter shared by
 * using the app.
 */

import { useState } from 'react';
import {
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

import ReporterChat from '../components/ReporterChat';
import { formatTime } from '../components/controls';
import { severityColour, severityLabel, type ThreadSummary } from '../lib/api';
import { colors, glass, radius, spacing, type } from '../lib/theme';

export default function CommunicationsScreen({
  threads,
  loaded,
  responderId,
  onRefresh,
  onOpenIncident,
}: {
  threads: ThreadSummary[];
  loaded: boolean;
  responderId: string;
  onRefresh: () => void;
  onOpenIncident: (incidentId: string) => void;
}) {
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const [selected, setSelected] = useState<string | null>(null);
  const active = threads.find((t) => t.incident_id === selected) ?? (wide ? threads[0] : undefined);

  if (loaded && threads.length === 0) {
    return (
      <View style={styles.emptyWrap}>
        <View style={styles.card}>
          <Text style={styles.title}>No conversations yet</Text>
          <Text style={styles.muted}>
            Everyone who sends a report from the reporter app appears here, and can be messaged
            about it. Their messages to the team land here too.
          </Text>
        </View>
      </View>
    );
  }

  const list = (
    <ScrollView style={wide ? styles.listWide : styles.flex} contentContainerStyle={styles.listInner}>
      {threads.map((thread) => {
        const isActive = active?.incident_id === thread.incident_id;
        const last = thread.last_message;
        return (
          <Pressable
            key={thread.incident_id}
            onPress={() => setSelected(thread.incident_id)}
            style={[styles.item, isActive && wide && styles.itemActive]}
            accessibilityRole="button"
          >
            <View style={styles.row}>
              <Text style={styles.itemTitle} numberOfLines={1}>
                {titleOf(thread)}
              </Text>
              {thread.awaiting_reply && (
                <View style={styles.owed}>
                  <Text style={styles.owedText}>Reply needed</Text>
                </View>
              )}
            </View>
            <Text style={styles.muted} numberOfLines={1}>
              {[thread.place_name, thread.incident_id].filter(Boolean).join(' · ')}
            </Text>
            <Text
              style={[styles.preview, thread.awaiting_reply && styles.previewOwed]}
              numberOfLines={2}
            >
              {last
                ? `${last.sender === 'reporter' ? 'Reporter' : 'Team'} · ${formatTime(last.created_at)}: ${last.body}`
                : 'No messages yet'}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );

  const pane = active ? (
    <ScrollView style={styles.flex} contentContainerStyle={styles.paneInner}>
      {!wide && (
        <Pressable onPress={() => setSelected(null)} hitSlop={10}>
          <Text style={styles.link}>‹ All conversations</Text>
        </Pressable>
      )}
      <View style={styles.card}>
        <View style={styles.row}>
          <Text style={styles.title} numberOfLines={2}>
            {titleOf(active)}
          </Text>
          {active.severity_level && (
            <View style={[styles.severity, { backgroundColor: severityColour(active.severity_level) }]}>
              <Text style={styles.severityText}>{severityLabel(active.severity_level)}</Text>
            </View>
          )}
        </View>
        <Text style={styles.muted}>
          {[active.place_name, active.incident_id, active.status.replace(/_/g, ' ')]
            .filter(Boolean)
            .join(' · ')}
        </Text>
        <View style={styles.actions}>
          {active.reporter_phone ? (
            <Pressable
              style={styles.button}
              onPress={() => void Linking.openURL(`tel:${active.reporter_phone}`)}
            >
              <Text style={styles.buttonText}>
                {Platform.OS === 'web' ? `Call ${active.reporter_phone}` : 'Call reporter'}
              </Text>
            </Pressable>
          ) : (
            <Text style={styles.faint}>No phone number on this report.</Text>
          )}
          <Pressable style={styles.button} onPress={() => onOpenIncident(active.incident_id)}>
            <Text style={styles.buttonText}>Open incident</Text>
          </Pressable>
        </View>
      </View>
      <ReporterChat
        key={active.incident_id}
        incidentId={active.incident_id}
        actor={responderId}
        onSent={onRefresh}
      />
    </ScrollView>
  ) : null;

  if (wide) {
    return (
      <View style={styles.split}>
        {list}
        {pane}
      </View>
    );
  }
  return pane ?? list;
}

function titleOf(thread: ThreadSummary): string {
  return thread.headline ?? thread.species_common_name ?? 'Report in progress';
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  split: { flex: 1, flexDirection: 'row' },
  listWide: { width: 360, flexGrow: 0, borderRightWidth: 1, borderRightColor: colors.border },
  listInner: { padding: spacing.md, gap: spacing.sm },
  paneInner: { padding: spacing.lg, gap: spacing.md, maxWidth: 780, width: '100%', alignSelf: 'center' },
  item: { ...glass, padding: spacing.md, gap: 3 },
  itemActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  itemTitle: { ...type.label, color: colors.text, flexShrink: 1 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  owed: { borderRadius: radius.pill, backgroundColor: colors.warning, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  owedText: { ...type.label, fontSize: 11, color: colors.onAccent },
  preview: { ...type.meta, fontSize: 12.5, color: colors.textFaint, lineHeight: 18 },
  previewOwed: { color: colors.text },
  card: { ...glass, padding: spacing.md, gap: spacing.xs + 2 },
  title: { ...type.heading, color: colors.text, flexShrink: 1 },
  muted: { ...type.meta, color: colors.textMuted },
  faint: { ...type.meta, color: colors.textFaint },
  link: { ...type.label, color: colors.accent },
  severity: { borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 3 },
  severityText: { ...type.eyebrow, fontSize: 10, color: colors.onAccent },
  actions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm, marginTop: spacing.xs },
  button: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.glassFill,
    borderRadius: radius.card,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonText: { ...type.label, fontSize: 13.5, color: colors.text },
  emptyWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
});
