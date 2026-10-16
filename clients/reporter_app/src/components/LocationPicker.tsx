/**
 * Confirm where the animal is, on a map, before sending it.
 *
 * A GPS fix says where the *reporter* is standing, which is often not where
 * the animal is: people photograph from a headland, back away from an
 * aggressive sea lion, or walk on before thinking to report. Sending the raw
 * fix silently claimed otherwise.
 *
 * So the flow is one button, then a map. It opens centred on the current
 * position with the pin already there -- the common case is one glance and
 * "Share location" -- but the pin can be dragged or the map tapped first.
 * Whether it moved is recorded: `device_gps` if untouched, `map_pin` if the
 * reporter placed it, because a responder searching a beach should know which
 * kind of claim they are working from.
 */

import { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import MapView, { Marker, type MapPressEvent } from 'react-native-maps';

import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

export interface PickedLocation {
  latitude: number;
  longitude: number;
  /** Null once the pin has been moved: the GPS accuracy no longer applies. */
  accuracy?: number;
  moved: boolean;
}

export default function LocationPicker({
  visible,
  initialLatitude,
  initialLongitude,
  initialAccuracy,
  onConfirm,
  onCancel,
  saving = false,
}: {
  visible: boolean;
  initialLatitude: number;
  initialLongitude: number;
  initialAccuracy?: number;
  onConfirm: (picked: PickedLocation) => void;
  onCancel: () => void;
  saving?: boolean;
}) {
  const [pin, setPin] = useState({
    latitude: initialLatitude,
    longitude: initialLongitude,
  });
  const [moved, setMoved] = useState(false);

  function place(event: MapPressEvent) {
    setPin(event.nativeEvent.coordinate);
    setMoved(true);
  }

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel}>
      <View style={styles.screen}>
        <View style={styles.header}>
          <Text style={styles.title}>Where is the animal?</Text>
          <Text style={styles.subtitle}>
            {moved
              ? 'Drag the pin or tap again to adjust.'
              : 'This is where you are. If the animal is somewhere else, tap the map or drag the pin.'}
          </Text>
        </View>

        <MapView
          style={styles.map}
          onPress={place}
          initialRegion={{
            latitude: initialLatitude,
            longitude: initialLongitude,
            // Close in: at a wider zoom a fingertip covers several hundred
            // metres, which makes placing a pin pointless.
            latitudeDelta: 0.004,
            longitudeDelta: 0.004,
          }}
        >
          <Marker
            coordinate={pin}
            draggable
            onDragEnd={(event) => {
              setPin(event.nativeEvent.coordinate);
              setMoved(true);
            }}
            pinColor={colors.danger}
            title="The animal"
          />
        </MapView>

        <View style={styles.footer}>
          <Text style={styles.coords}>
            {pin.latitude.toFixed(5)}, {pin.longitude.toFixed(5)}
            {moved ? ' · pin moved' : ' · your current position'}
          </Text>

          <Pressable
            style={[styles.primary, saving && styles.disabled]}
            disabled={saving}
            onPress={() =>
              onConfirm({
                ...pin,
                // A moved pin is no longer a GPS reading, so the accuracy
                // figure would be a lie.
                accuracy: moved ? undefined : initialAccuracy,
                moved,
              })
            }
          >
            <Text style={styles.primaryText}>
              {saving ? 'Sending…' : 'Share location'}
            </Text>
          </Pressable>

          <Pressable onPress={onCancel} disabled={saving}>
            <Text style={styles.cancel}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: { padding: spacing.lg, gap: spacing.xs },
  title: { ...type.title, color: colors.text },
  subtitle: { ...type.meta, color: colors.textMuted, lineHeight: 18 },
  map: { flex: 1 },
  footer: {
    ...glass,
    margin: spacing.md,
    padding: spacing.lg,
    gap: spacing.md,
    alignItems: 'stretch',
  },
  coords: { ...type.meta, fontSize: 12, color: colors.textFaint, textAlign: 'center' },
  primary: {
    ...shadow.soft,
    backgroundColor: colors.accent,
    paddingVertical: spacing.lg,
    borderRadius: radius.card,
    alignItems: 'center',
  },
  disabled: { opacity: 0.6 },
  primaryText: { ...type.label, fontSize: 16, color: colors.onAccent },
  cancel: { ...type.label, color: colors.textMuted, textAlign: 'center' },
});
