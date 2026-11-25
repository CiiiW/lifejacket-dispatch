/**
 * My reports: every report this phone has sent, on a map and in a list.
 *
 * The overview answers "what have I reported, and what happened to each".
 * Tapping one opens its own map (`TrackScreen`): where the animal is, who
 * covers the area, and who is on the way. Only the reporter's own reports
 * appear: a public map of stranded animals would send onlookers to them.
 */

import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';

import type { MatchedTeam, MyReport } from '../lib/api';
import type { SavedReport } from '../lib/reporterStore';
import { reportStatus, shortWhen, type StatusTone } from '../lib/reportStatus';
import { colors, glass, radius, spacing, type } from '../lib/theme';
import TrackScreen from './TrackScreen';

const TONE_COLOUR: Record<StatusTone, string> = {
  draft: colors.warning,
  active: colors.accent,
  closed: colors.textFaint,
};

interface Row {
  saved: SavedReport;
  summary: MyReport | undefined;
  latitude: number | null;
  longitude: number | null;
}

export default function MyReportsScreen({
  reports,
  summaries,
  seenTeam,
  currentIncidentId,
  currentMatchedTeams,
  onPlacePin,
  placingPin,
  onMessage,
  onContinue,
}: {
  reports: SavedReport[];
  summaries: Record<string, MyReport>;
  seenTeam: Record<string, number>;
  /** The report open on the Report tab, if any: its pin can still be moved. */
  currentIncidentId: string | null;
  currentMatchedTeams: MatchedTeam[];
  onPlacePin: (latitude: number, longitude: number) => void;
  placingPin: boolean;
  onMessage: (incidentId: string) => void;
  /** Back to the Report tab, for the report still being written. */
  onContinue: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  const rows: Row[] = useMemo(
    () =>
      reports.map((saved) => {
        const summary = summaries[saved.incidentId];
        return {
          saved,
          summary,
          latitude: summary?.latitude ?? saved.latitude,
          longitude: summary?.longitude ?? saved.longitude,
        };
      }),
    [reports, summaries],
  );
  const placed = rows.filter((r) => r.latitude !== null && r.longitude !== null);

  const open = rows.find((r) => r.saved.incidentId === selected);
  if (open && open.latitude !== null && open.longitude !== null) {
    const isCurrent = open.saved.incidentId === currentIncidentId;
    return (
      <View style={styles.screen}>
        <View style={styles.detailHeader}>
          <Pressable onPress={() => setSelected(null)} hitSlop={10} accessibilityRole="button">
            <Text style={styles.link}>‹ All reports</Text>
          </Pressable>
          <Pressable onPress={() => onMessage(open.saved.incidentId)} hitSlop={10}>
            <Text style={styles.link}>Message the team</Text>
          </Pressable>
        </View>
        <TrackScreen
          incidentId={open.saved.incidentId}
          incidentLatitude={open.latitude}
          incidentLongitude={open.longitude}
          locationKnown
          matchedTeams={isCurrent ? currentMatchedTeams : []}
          onPlacePin={isCurrent && !open.summary?.complete ? onPlacePin : undefined}
          placingPin={isCurrent && placingPin}
        />
      </View>
    );
  }

  if (rows.length === 0) {
    return (
      <View style={styles.emptyWrap}>
        <View style={styles.card}>
          <Text style={styles.title}>No reports yet</Text>
          <Text style={styles.muted}>
            Reports you send appear here, on the map and in a list, with what happened to each.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      {placed.length > 0 && (
        <MapView style={styles.map} initialRegion={regionFor(placed)}>
          {placed.map((r) => {
            const status = reportStatus(r.summary?.status, r.summary?.complete);
            return (
              <Marker
                key={r.saved.incidentId}
                coordinate={{ latitude: r.latitude!, longitude: r.longitude! }}
                title={heading(r.summary)}
                description={`${status.label} · ${shortWhen(r.summary?.created_at ?? r.saved.startedAt)}`}
                pinColor={TONE_COLOUR[status.tone]}
                onCalloutPress={() => setSelected(r.saved.incidentId)}
              />
            );
          })}
        </MapView>
      )}

      {rows.map((r) => {
        const status = reportStatus(r.summary?.status, r.summary?.complete);
        const unread = Math.max(
          0,
          (r.summary?.team_message_count ?? 0) - (seenTeam[r.saved.incidentId] ?? 0),
        );
        const draft = status.tone === 'draft';
        const isCurrent = r.saved.incidentId === currentIncidentId;
        return (
          <View key={r.saved.incidentId} style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.title} numberOfLines={1}>
                {heading(r.summary)}
              </Text>
              <View style={[styles.chip, { borderColor: TONE_COLOUR[status.tone] }]}>
                <Text style={[styles.chipText, { color: TONE_COLOUR[status.tone] }]}>
                  {status.label}
                </Text>
              </View>
            </View>
            <Text style={styles.muted} numberOfLines={1}>
              {[r.summary?.place_name, shortWhen(r.summary?.created_at ?? r.saved.startedAt)]
                .filter(Boolean)
                .join(' · ')}
            </Text>
            <View style={styles.actions}>
              {draft && isCurrent ? (
                <Pressable style={styles.button} onPress={onContinue}>
                  <Text style={styles.buttonText}>Continue this report</Text>
                </Pressable>
              ) : (
                r.latitude !== null && (
                  <Pressable style={styles.button} onPress={() => setSelected(r.saved.incidentId)}>
                    <Text style={styles.buttonText}>Map and status</Text>
                  </Pressable>
                )
              )}
              <Pressable style={styles.button} onPress={() => onMessage(r.saved.incidentId)}>
                <Text style={styles.buttonText}>
                  Messages{unread > 0 ? ` (${unread} new)` : ''}
                </Text>
              </Pressable>
            </View>
            {draft && !isCurrent && (
              <Text style={styles.faint}>
                Not finished, so it did not reach a rescue team. Start a new report if the animal
                still needs help.
              </Text>
            )}
          </View>
        );
      })}
    </ScrollView>
  );
}

function heading(summary: MyReport | undefined): string {
  return summary?.species_common_name ?? 'Animal report';
}

/** A region that shows every report, with a little room around the edges. */
function regionFor(rows: Row[]) {
  const lats = rows.map((r) => r.latitude!);
  const lons = rows.map((r) => r.longitude!);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLon + maxLon) / 2,
    latitudeDelta: Math.max((maxLat - minLat) * 1.5, 0.05),
    longitudeDelta: Math.max((maxLon - minLon) * 1.5, 0.05),
  };
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: { padding: spacing.lg, gap: spacing.md },
  map: { height: 260, borderRadius: radius.card, overflow: 'hidden' },
  card: { ...glass, padding: spacing.md, gap: spacing.xs + 2 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  title: { ...type.heading, color: colors.text, flexShrink: 1 },
  muted: { ...type.meta, color: colors.textMuted },
  faint: { ...type.meta, fontSize: 12, color: colors.textFaint, lineHeight: 17 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  chipText: { ...type.label, fontSize: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.xs },
  button: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.glassFill,
    borderRadius: radius.card,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonText: { ...type.label, fontSize: 13.5, color: colors.text },
  link: { ...type.label, color: colors.accent },
  detailHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  emptyWrap: { flex: 1, justifyContent: 'center', padding: spacing.xl },
});
