/**
 * After the report is filed: the map showing who is coming and how far away.
 *
 * This screen exists for one reason. Someone who has just reported a dying
 * animal is standing there with nothing to do, and the most reassuring thing
 * the app can show them is that help is real and moving.
 *
 * It deliberately does not promise an arrival time as a commitment -- the ETA
 * is a straight-line estimate and is labelled as approximate. A coordinator
 * still has to approve every dispatch.
 */

import { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';

import { reporter, type ResponderEta } from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

/** How often to re-check. Frequent enough to feel live, gentle on battery. */
const POLL_INTERVAL_MS = 15_000;

export default function TrackScreen({
  incidentId,
  incidentLatitude,
  incidentLongitude,
}: {
  incidentId: string;
  incidentLatitude: number;
  incidentLongitude: number;
}) {
  const [etas, setEtas] = useState<ResponderEta[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const next = await reporter.getEtas(incidentId);
        if (!cancelled) setEtas(next);
      } catch {
        // A failed poll is not worth interrupting the user over; the next one
        // will probably succeed. Keep showing the last known state.
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [incidentId]);

  return (
    <View style={styles.screen}>
      <MapView
        style={styles.map}
        initialRegion={{
          latitude: incidentLatitude,
          longitude: incidentLongitude,
          latitudeDelta: 0.15,
          longitudeDelta: 0.15,
        }}
      >
        <Marker
          coordinate={{ latitude: incidentLatitude, longitude: incidentLongitude }}
          title="The animal"
          pinColor={colors.danger}
        />

        {etas
          ?.filter((eta) => eta.latitude !== null && eta.longitude !== null)
          .map((eta) => (
            <Marker
              key={eta.responder_id}
              coordinate={{ latitude: eta.latitude!, longitude: eta.longitude! }}
              title={eta.name}
              description={
                eta.eta_minutes !== null ? `about ${eta.eta_minutes} min away` : eta.status
              }
              pinColor={colors.accent}
            />
          ))}
      </MapView>

      <View style={styles.panel}>
        <Text style={styles.heading}>Who is coming</Text>

        {etas === null && <ActivityIndicator style={styles.spinner} color={colors.accent} />}

        {etas?.length === 0 && (
          <Text style={styles.waiting}>
            Your report has been sent to the rescue coordinators for this area. Nobody
            has been assigned yet. Please keep your distance from the animal.
          </Text>
        )}

        <FlatList
          data={etas ?? []}
          keyExtractor={(item) => item.responder_id}
          renderItem={({ item }) => (
            <View style={styles.row}>
              <View style={styles.rowMain}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.status}>{item.status.replace(/_/g, ' ')}</Text>
              </View>
              <View style={styles.rowEnd}>
                {item.eta_minutes !== null && (
                  <Text style={styles.eta}>~{item.eta_minutes} min</Text>
                )}
                {item.distance_km !== null && (
                  <Text style={styles.distance}>{item.distance_km} km away</Text>
                )}
              </View>
            </View>
          )}
        />

        {etas && etas.length > 0 && (
          <Text style={styles.disclaimer}>
            Times are estimates based on distance, not live traffic.
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  map: { flex: 1 },
  panel: {
    ...shadow.soft,
    maxHeight: '45%',
    padding: spacing.lg,
    backgroundColor: colors.backgroundElevated,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
  },
  heading: { ...type.heading, color: colors.text, marginBottom: spacing.md },
  spinner: { marginVertical: spacing.md },
  waiting: { ...type.body, color: colors.textMuted, lineHeight: 21 },
  row: {
    ...glass,
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  rowMain: { flex: 1 },
  rowEnd: { alignItems: 'flex-end' },
  name: { ...type.label, fontSize: 16, color: colors.text },
  status: { ...type.meta, color: colors.textFaint, marginTop: 2 },
  eta: { ...type.heading, fontSize: 16, color: colors.accent },
  distance: { ...type.meta, color: colors.textFaint, marginTop: 2 },
  disclaimer: { ...type.meta, fontSize: 12, color: colors.textFaint, marginTop: spacing.md },
});
