/**
 * The map: where the animal is, and who is coming to it.
 *
 * Part of this screen exists for one reason. Someone who has just reported a
 * dying animal is standing there with nothing to do, and the most reassuring
 * thing the app can show them is that help is real and moving. It deliberately
 * does not promise an arrival time as a commitment -- the ETA is a
 * straight-line estimate and is labelled as approximate. A coordinator still
 * has to approve every dispatch.
 *
 * The pin can also be moved. A GPS fix says where the *reporter* is, which is
 * not always where the animal is: people photograph from a headland, back
 * away from an aggressive sea lion, or walk on before thinking to report. A
 * hand-placed pin is recorded with `source: "map_pin"` so a responder knows
 * which kind of claim they are searching from.
 */

import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import MapView, { Marker, type MapPressEvent } from 'react-native-maps';

import { reporter, type Conditions, type ResponderEta } from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';
import ConditionsPanel from '../../../shared/ConditionsPanel';

/** How often to re-check. Frequent enough to feel live, gentle on battery. */
const POLL_INTERVAL_MS = 15_000;

export default function TrackScreen({
  incidentId,
  incidentLatitude,
  incidentLongitude,
  locationKnown = true,
  conditions = null,
  onPlacePin,
  placingPin = false,
}: {
  incidentId: string;
  incidentLatitude: number;
  incidentLongitude: number;
  /**
   * Weather, tide, and daylight where the animal is. The reporter is standing
   * in these conditions, and until now could only see the agent's conclusions
   * about them.
   */
  conditions?: Conditions | null;
  /**
   * False while the coordinates are a regional fallback rather than the
   * reporter's own GPS fix. Said out loud rather than quietly showing the
   * wrong bay, which would read as "we know where you are".
   */
  locationKnown?: boolean;
  /**
   * Submit a hand-placed pin. Routed back through the report screen rather
   * than called here, because setting a location advances the conversation
   * and there must be one owner of that.
   */
  onPlacePin?: (latitude: number, longitude: number) => void;
  /** True while a placed pin is being sent. */
  placingPin?: boolean;
}) {
  const [etas, setEtas] = useState<ResponderEta[] | null>(null);
  const [draftPin, setDraftPin] = useState<{ latitude: number; longitude: number } | null>(
    null,
  );

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

  function handleMapPress(event: MapPressEvent) {
    if (!onPlacePin) return;
    setDraftPin(event.nativeEvent.coordinate);
  }

  return (
    <View style={styles.screen}>
      <MapView
        style={styles.map}
        onPress={handleMapPress}
        initialRegion={{
          latitude: incidentLatitude,
          longitude: incidentLongitude,
          // Tighter than the old 0.15 so a tapped pin can be placed
          // accurately -- at 0.15 a fingertip covers several hundred metres.
          latitudeDelta: locationKnown ? 0.02 : 0.15,
          longitudeDelta: locationKnown ? 0.02 : 0.15,
        }}
      >
        <Marker
          coordinate={{ latitude: incidentLatitude, longitude: incidentLongitude }}
          title="The animal"
          pinColor={colors.danger}
        />

        {/* Draggable as well as tappable: a tap gets close, a drag corrects. */}
        {draftPin && (
          <Marker
            coordinate={draftPin}
            title="New position"
            pinColor={colors.accent}
            draggable
            onDragEnd={(event) => setDraftPin(event.nativeEvent.coordinate)}
          />
        )}

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

      {onPlacePin && !draftPin && (
        <View style={styles.hint} pointerEvents="none">
          <Text style={styles.hintText}>
            Tap the map if the animal is not where you are standing.
          </Text>
        </View>
      )}

      {draftPin && (
        <View style={styles.confirm}>
          <Text style={styles.confirmText}>
            Move the animal&apos;s position to {draftPin.latitude.toFixed(5)},{' '}
            {draftPin.longitude.toFixed(5)}?
          </Text>
          <View style={styles.confirmRow}>
            <Pressable
              style={styles.secondary}
              onPress={() => setDraftPin(null)}
              disabled={placingPin}
            >
              <Text style={styles.secondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={styles.primary}
              disabled={placingPin}
              onPress={() => {
                onPlacePin?.(draftPin.latitude, draftPin.longitude);
                setDraftPin(null);
              }}
            >
              <Text style={styles.primaryText}>
                {placingPin ? 'Saving…' : 'Use this spot'}
              </Text>
            </Pressable>
          </View>
        </View>
      )}

      <ScrollView style={styles.panel} contentContainerStyle={styles.panelInner}>
        {conditions && (
          <View style={styles.conditions}>
            <ConditionsPanel conditions={conditions} title="Conditions here" compact />
          </View>
        )}

        {!locationKnown && (
          <Text style={styles.approximate}>
            Showing the regional view -- share your location on the Report tab to
            pin the animal exactly.
          </Text>
        )}

        <Text style={styles.heading}>Who is coming</Text>

        {etas === null && <ActivityIndicator style={styles.spinner} color={colors.accent} />}

        {etas?.length === 0 && (
          <Text style={styles.waiting}>
            Your report has been sent to the rescue coordinators for this area. Nobody
            has been assigned yet. Please keep your distance from the animal.
          </Text>
        )}

        {/* Plain views rather than a FlatList: the panel is a ScrollView now,
            and a nested FlatList inside one scrolls unpredictably. These
            lists are a handful of rows, so virtualisation buys nothing. */}
        {(etas ?? []).map((item) => (
          <View key={item.responder_id} style={styles.row}>
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
        ))}

        {etas && etas.length > 0 && (
          <Text style={styles.disclaimer}>
            Times are estimates based on distance, not live traffic.
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  map: { flex: 1, minHeight: 200 },
  // The map keeps a floor so it cannot be squeezed away, and the panel is a
  // ScrollView capped at half the screen: with conditions, a location
  // warning and several responders, the content overflowed and the bottom
  // was simply unreachable.
  panel: {
    ...shadow.soft,
    maxHeight: '55%',
    backgroundColor: colors.backgroundElevated,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
  },
  panelInner: { padding: spacing.lg, paddingBottom: spacing.xl },
  heading: { ...type.heading, color: colors.text, marginBottom: spacing.md },
  hint: {
    position: 'absolute',
    top: spacing.md,
    left: spacing.md,
    right: spacing.md,
    backgroundColor: 'rgba(11, 19, 43, 0.82)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  hintText: { ...type.meta, fontSize: 12, color: colors.textMuted, textAlign: 'center' },

  confirm: {
    ...glass,
    ...shadow.soft,
    position: 'absolute',
    top: spacing.md,
    left: spacing.md,
    right: spacing.md,
    padding: spacing.md,
    gap: spacing.sm,
    backgroundColor: 'rgba(11, 19, 43, 0.94)',
  },
  confirmText: { ...type.body, fontSize: 14, color: colors.text, lineHeight: 19 },
  confirmRow: { flexDirection: 'row', gap: spacing.sm },
  primary: {
    flex: 1,
    backgroundColor: colors.accent,
    borderRadius: radius.card,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  primaryText: { ...type.label, fontSize: 15, color: colors.onAccent },
  secondary: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.card,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  secondaryText: { ...type.label, fontSize: 15, color: colors.text },

  conditions: { marginBottom: spacing.md },
  approximate: {
    ...type.meta,
    fontSize: 12,
    color: colors.warning,
    marginBottom: spacing.sm,
    lineHeight: 17,
  },
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
