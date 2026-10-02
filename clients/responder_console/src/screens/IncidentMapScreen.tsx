/**
 * The triage map: every open incident, colour-coded by severity.
 *
 * This is the responder console's home screen and it runs on phone and web
 * from the same code, via `react-native-maps` and `react-native-web`.
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

const REFRESH_INTERVAL_MS = 30_000;

export default function IncidentMapScreen({
  onSelect,
}: {
  onSelect: (incidentId: string) => void;
}) {
  const [pins, setPins] = useState<MapPin[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setPins(await responder.listIncidents());
    } catch {
      // Keep the previous list rather than blanking the map on a flaky signal.
    } finally {
      setRefreshing(false);
    }
  }, []);

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
    return <ActivityIndicator style={styles.loading} size="large" />;
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
        <Text style={styles.heading}>
          {pins.length} open {pins.length === 1 ? 'incident' : 'incidents'}
        </Text>

        <FlatList
          data={sorted}
          keyExtractor={(item) => item.incident_id}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                void load();
              }}
            />
          }
          ListEmptyComponent={<Text style={styles.empty}>Nothing open right now.</Text>}
          renderItem={({ item }) => (
            <Pressable style={styles.row} onPress={() => onSelect(item.incident_id)}>
              <View
                style={[styles.stripe, { backgroundColor: severityColour(item.severity_level) }]}
              />
              <View style={styles.rowBody}>
                <Text style={styles.rowTitle} numberOfLines={1}>
                  {item.headline ?? item.species_common_name ?? 'Unidentified animal'}
                </Text>
                <Text style={styles.rowMeta} numberOfLines={1}>
                  {severityLabel(item.severity_level)}
                  {item.place_name ? ` · ${item.place_name}` : ''}
                  {` · ${item.status.replace(/_/g, ' ')}`}
                </Text>
              </View>
              {/* Entanglement is called out separately because it needs a team
                  with cutting authorisation, which not every centre has. */}
              {item.entanglement && <Text style={styles.tag}>ENTANGLED</Text>}
            </Pressable>
          )}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, flexDirection: 'row' },
  loading: { flex: 1 },
  map: { flex: 2 },
  panel: { flex: 1, minWidth: 320, backgroundColor: '#fff', padding: 16 },
  heading: { fontSize: 18, fontWeight: '700', marginBottom: 12 },
  empty: { color: '#5f6368', fontSize: 15 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  stripe: { width: 4, alignSelf: 'stretch', borderRadius: 2 },
  rowBody: { flex: 1 },
  rowTitle: { fontSize: 15, fontWeight: '600' },
  rowMeta: { fontSize: 13, color: '#5f6368', marginTop: 2 },
  tag: {
    fontSize: 10,
    fontWeight: '800',
    color: '#b3261e',
    borderWidth: 1,
    borderColor: '#b3261e',
    borderRadius: 4,
    paddingHorizontal: 4,
    paddingVertical: 2,
  },
});
