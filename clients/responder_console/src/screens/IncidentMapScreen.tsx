/**
 * The triage map: every open incident, colour-coded by severity.
 *
 * This is the responder console's home screen, for iOS/Android via
 * `react-native-maps`. That library has no web renderer, so the web build
 * uses `IncidentMapScreen.web.tsx` instead (a placeholder in place of the
 * map; everything else is identical) -- Metro picks it automatically.
 *
 * Note what the client does *not* do: it never computes a severity colour from
 * condition flags. It reads `severity_level`, which the backend's
 * `dispatch/severity.py` already decided. One implementation, one source of
 * truth, and a scoring change needs no app release.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import MapView, { Marker } from 'react-native-maps';

import { responder, severityColour, severityLabel, type MapPin } from '../lib/api';
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

  const located = pins?.filter((p) => p.latitude !== null && p.longitude !== null) ?? [];

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
      <MapView
        style={styles.map}
        initialRegion={{
          latitude: located[0]?.latitude ?? 36.8,
          longitude: located[0]?.longitude ?? -121.79,
          latitudeDelta: 2,
          longitudeDelta: 2,
        }}
      >
        {located.map((pin) => (
          <Marker
            key={pin.incident_id}
            coordinate={{ latitude: pin.latitude!, longitude: pin.longitude! }}
            pinColor={severityColour(pin.severity_level)}
            title={pin.species_common_name ?? 'Unidentified animal'}
            description={pin.headline ?? pin.place_name ?? undefined}
            onCalloutPress={() => onSelect(pin.incident_id)}
          />
        ))}
      </MapView>

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
          ListEmptyComponent={<Text style={styles.empty}>Nothing open right now.</Text>}
          renderItem={({ item }) => (
            <Pressable
              style={[styles.row, isClosed(item.status) && styles.rowClosed]}
              onPress={() => onSelect(item.incident_id)}
            >
              <View
                style={[styles.stripe, { backgroundColor: severityColour(item.severity_level) }]}
              />
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
  map: { flex: 2 },
  panel: {
    flex: 1,
    minWidth: 320,
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
  empty: { ...type.meta, color: colors.textFaint },
  row: {
    ...glass,
    ...shadow.soft,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  rowClosed: { opacity: 0.55 },
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
