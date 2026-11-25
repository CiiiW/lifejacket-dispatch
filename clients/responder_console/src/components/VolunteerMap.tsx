/**
 * Volunteers around one incident, on a native map (react-native-maps).
 * Same states and colours as the web version; see `volunteerMapShared.ts`.
 */

import { StyleSheet, Text, View } from 'react-native';
import MapView, { Marker, Polygon } from 'react-native-maps';

import { colors, radius, spacing, type } from '../lib/theme';
import { volunteerTone, type VolunteerMapProps } from './volunteerMapShared';

export default function VolunteerMap({
  incident,
  volunteers,
  selected,
  onToggle,
  survey,
  height = 300,
}: VolunteerMapProps) {
  const reachable = volunteers.filter((v) => v.in_range);
  const span = survey
    ? 0.006
    : Math.max(
        0.05,
        ...reachable.map((v) =>
          2.4 * Math.max(Math.abs(v.latitude - incident.latitude),
            Math.abs(v.longitude - incident.longitude)),
        ),
      );

  return (
    <View style={[styles.wrap, { height }]}>
      <MapView
        style={StyleSheet.absoluteFill}
        initialRegion={{
          latitude: incident.latitude,
          longitude: incident.longitude,
          latitudeDelta: span,
          longitudeDelta: span,
        }}
      >
        <Marker
          coordinate={{ latitude: incident.latitude, longitude: incident.longitude }}
          pinColor={colors.danger}
          title={incident.label}
        />
        {volunteers.map((volunteer) => {
          const tone = volunteerTone(volunteer, selected.has(volunteer.volunteer_id));
          return (
            <Marker
              key={volunteer.volunteer_id}
              coordinate={{ latitude: volunteer.latitude, longitude: volunteer.longitude }}
              pinColor={tone.selectable || volunteer.alert ? tone.border : colors.textFaint}
              title={volunteer.name}
              description={`${volunteer.distance_km} km · ${tone.label}`}
              onPress={() => {
                if (tone.selectable) onToggle(volunteer.volunteer_id);
              }}
            />
          );
        })}
        {survey && (
          <>
            <Polygon
              coordinates={[
                { latitude: survey.survey_south, longitude: survey.survey_west },
                { latitude: survey.survey_south, longitude: survey.survey_east },
                { latitude: survey.survey_north, longitude: survey.survey_east },
                { latitude: survey.survey_north, longitude: survey.survey_west },
              ]}
              strokeColor={colors.accent}
              fillColor="rgba(72, 202, 228, 0.12)"
              strokeWidth={2}
            />
            <Marker
              coordinate={{ latitude: survey.home_latitude, longitude: survey.home_longitude }}
              pinColor={colors.accent}
              title="Drone launch point (assumed)"
            />
          </>
        )}
      </MapView>
      <View style={styles.legend} pointerEvents="none">
        <Text style={styles.legendText}>
          {survey ? 'Box: planned survey area' : 'Pins are base areas, not live locations'}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: radius.card,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  legend: {
    position: 'absolute',
    left: spacing.sm,
    bottom: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: radius.sm,
    backgroundColor: 'rgba(11, 19, 43, 0.82)',
  },
  legendText: { ...type.meta, fontSize: 11, color: colors.textMuted },
});
