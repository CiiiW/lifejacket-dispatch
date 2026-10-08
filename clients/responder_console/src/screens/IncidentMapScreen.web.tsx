/**
 * Web build of the triage map.
 *
 * The native file (`IncidentMapScreen.tsx`) uses `react-native-maps`, which
 * is iOS/Android only. On web this renders MapLibre GL instead -- see
 * `components/TriageMap.web.tsx` -- so the console gets a real map in a
 * browser. Metro picks this `.web.tsx` file automatically when bundling for
 * web. The two files share the list panel but not the map.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import TriageMap from '../components/TriageMap.web';
import {
  absoluteUrl,
  responder,
  severityColour,
  severityLabel,
  type MapPin,
  type ResponderOrg,
  type RouteLine,
} from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

const REFRESH_INTERVAL_MS = 30_000;

/** Statuses that mean the incident already ended, so its row reads as done. */
const CLOSED_STATUSES = new Set(['resolved', 'guidance_only']);
const isClosed = (status: string) => CLOSED_STATUSES.has(status);

export default function IncidentMapScreen({
  onSelect,
}: {
  onSelect: (incidentId: string) => void;
}) {
  const [pins, setPins] = useState<MapPin[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [centres, setCentres] = useState<ResponderOrg[]>([]);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [route, setRoute] = useState<RouteLine | null>(null);

  const load = useCallback(async () => {
    try {
      setPins(await responder.listIncidents({ includeClosed: showClosed }));
    } catch {
      // Keep the previous list rather than blanking the map on a flaky signal.
    } finally {
      setRefreshing(false);
    }
  }, [showClosed]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // The rescue-centre directory changes rarely, so it is fetched once rather
  // than on the incident refresh timer.
  useEffect(() => {
    responder
      .list()
      .then(setCentres)
      .catch(() => setCentres([]));
  }, []);

  /**
   * Clicking a pin or row highlights it and asks the backend to route the
   * nearest-by-straight-line centre to it, which is a reasonable stand-in
   * until a coordinator has actually assigned someone.
   */
  const highlight = useCallback(
    (incidentId: string) => {
      setHighlighted(incidentId);
      setRoute(null);

      const pin = (pins ?? []).find((p) => p.incident_id === incidentId);
      const located = centres.filter((c) => c.latitude !== null && c.longitude !== null);
      if (!pin || pin.latitude === null || pin.longitude === null || located.length === 0) {
        return;
      }

      const nearest = located.reduce((best, candidate) => {
        const distance = (c: ResponderOrg) =>
          ((c.latitude as number) - (pin.latitude as number)) ** 2 +
          ((c.longitude as number) - (pin.longitude as number)) ** 2;
        return distance(candidate) < distance(best) ? candidate : best;
      });

      responder
        .getRoute(incidentId, nearest.responder_id)
        .then(setRoute)
        .catch(() => setRoute(null));
    },
    [pins, centres],
  );

  // Sort the list by urgency rather than by time: a coordinator opening the
  // console needs the worst case first, not the newest.
  const order = ['critical', 'respond', 'monitor', 'guidance'];
  const sorted = [...(pins ?? [])].sort(
    (a, b) =>
      order.indexOf(a.severity_level ?? 'guidance') -
      order.indexOf(b.severity_level ?? 'guidance'),
  );

  if (pins === null) {
    return <ActivityIndicator style={styles.loading} size="large" color={colors.accent} />;
  }

  return (
    <View style={styles.screen}>
      <View style={styles.mapWrap}>
        <TriageMap
          pins={pins}
          centres={centres}
          route={route}
          selectedId={highlighted}
          onSelect={highlight}
        />
      </View>

      <View style={styles.panel}>
        <View style={styles.panelHeader}>
          <Text style={styles.heading}>
            {pins.length} {showClosed ? '' : 'open '}
            {pins.length === 1 ? 'incident' : 'incidents'}
          </Text>
          <Pressable
            style={[styles.filter, showClosed && styles.filterActive]}
            onPress={() => setShowClosed((previous) => !previous)}
          >
            <Text style={[styles.filterText, showClosed && styles.filterTextActive]}>
              {showClosed ? 'Open only' : 'Show closed'}
            </Text>
          </Pressable>
        </View>

        <FlatList
          data={sorted}
          keyExtractor={(item) => item.incident_id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              tintColor={colors.accent}
              onRefresh={() => {
                setRefreshing(true);
                void load();
              }}
            />
          }
          ListEmptyComponent={
            <Text style={styles.empty}>
              Nothing open right now. Reports arrive here as the intake agent
              finishes them.
            </Text>
          }
          renderItem={({ item }) => (
            <Pressable
              style={[
                styles.row,
                isClosed(item.status) && styles.rowClosed,
                item.incident_id === highlighted && styles.rowHighlighted,
              ]}
              // One tap highlights on the map and routes to it; the chevron
              // opens the full report. Opening a report is a bigger move than
              // glancing at where the animal is.
              onPress={() => highlight(item.incident_id)}
            >
              <View
                style={[styles.stripe, { backgroundColor: severityColour(item.severity_level) }]}
              />
              {item.photo_url ? (
                <Image
                  source={{ uri: absoluteUrl(item.photo_url) as string }}
                  style={styles.thumb}
                />
              ) : (
                <View style={[styles.thumb, styles.thumbEmpty]} />
              )}
              <View style={styles.rowBody}>
                <Text style={styles.rowTitle} numberOfLines={1}>
                  {item.headline ?? item.species_common_name ?? 'Unidentified animal'}
                </Text>
                <Text style={styles.rowMeta} numberOfLines={1}>
                  <Text style={{ color: severityColour(item.severity_level) }}>
                    {severityLabel(item.severity_level)}
                  </Text>
                  {item.place_name ? ` · ${item.place_name}` : ''}
                  {` · ${item.status.replace(/_/g, ' ')}`}
                </Text>
              </View>
              {/* Entanglement is called out separately because it needs a team
                  with cutting authorisation, which not every centre has. */}
              {item.entanglement && <Text style={styles.tag}>ENTANGLED</Text>}
              {/* Several animals, possibly across several rows of this list. */}
              {item.in_mass_stranding && <Text style={styles.tag}>MASS STRANDING</Text>}

              <Pressable
                style={styles.open}
                onPress={() => onSelect(item.incident_id)}
              >
                <Text style={styles.openText}>Open</Text>
              </Pressable>
            </Pressable>
          )}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, flexDirection: 'row', backgroundColor: colors.background },
  loading: { flex: 1 },

  mapWrap: { flex: 2, padding: spacing.lg },

  panel: {
    flex: 1,
    minWidth: 340,
    backgroundColor: colors.backgroundElevated,
    borderLeftWidth: 1,
    borderLeftColor: colors.border,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
  },
  panelHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  heading: { ...type.title, color: colors.text },
  filter: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingVertical: 5,
    paddingHorizontal: spacing.md,
  },
  filterActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  filterText: { ...type.meta, fontSize: 12, color: colors.textMuted },
  filterTextActive: { color: colors.accent, fontWeight: '700' },
  list: { gap: spacing.sm, paddingBottom: spacing.xl },
  empty: { ...type.meta, color: colors.textFaint, lineHeight: 19 },

  row: {
    ...glass,
    ...shadow.soft,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  rowClosed: { opacity: 0.55 },
  rowHighlighted: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  thumb: { width: 46, height: 46, borderRadius: radius.sm, backgroundColor: colors.glassFill },
  thumbEmpty: { borderWidth: 1, borderColor: colors.border },
  open: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
  },
  openText: { ...type.meta, fontSize: 11.5, color: colors.text },
  stripe: { width: 4, alignSelf: 'stretch', minHeight: 34, borderRadius: radius.pill },
  rowBody: { flex: 1, gap: 3 },
  rowTitle: { ...type.label, color: colors.text, fontSize: 15 },
  rowMeta: { ...type.meta, color: colors.textMuted, fontSize: 12.5 },
  tag: {
    ...type.eyebrow,
    fontSize: 9,
    color: colors.danger,
    borderWidth: 1,
    borderColor: colors.danger,
    borderRadius: radius.sm,
    paddingHorizontal: 5,
    paddingVertical: 3,
    overflow: 'hidden',
  },
});
