/**
 * Volunteers around one incident, on the web console's MapLibre map.
 *
 * Each dot is a volunteer's chosen base area, not where they are now, and the
 * legend says so. Only the volunteers the API returned for this incident are
 * drawn: there is deliberately no all-volunteers layer.
 */

import { useEffect, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import maplibre, { type GeoJSONSource, type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import type { DroneSurvey } from '../lib/api';
import { basemap } from '../lib/basemap';
import { colors, radius, spacing, type } from '../lib/theme';
import { volunteerTone, type VolunteerMapProps } from './volunteerMapShared';

const SURVEY_SOURCE = 'drone-survey';

function surveyShape(survey: DroneSurvey | null | undefined): GeoJSON.FeatureCollection {
  if (!survey) return { type: 'FeatureCollection', features: [] };
  const { survey_south: s, survey_north: n, survey_west: w, survey_east: e } = survey;
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: { type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
      },
    ],
  };
}

function dot(fill: string, border: string, size: number, dashed = false): HTMLDivElement {
  const element = document.createElement('div');
  element.style.cssText = [
    `width:${size}px`, `height:${size}px`, 'border-radius:50%',
    `border:2px ${dashed ? 'dashed' : 'solid'} ${border}`,
    `background:${fill}`, 'box-shadow:0 2px 6px rgba(0,0,0,0.45)',
  ].join(';');
  return element;
}

export default function VolunteerMap({
  incident,
  volunteers,
  selected,
  onToggle,
  survey,
  height = 300,
}: VolunteerMapProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<maplibre.Marker[]>([]);
  const ready = useRef(false);
  const fitted = useRef(false);
  const tiles = basemap();

  useEffect(() => {
    if (map.current || !container.current) return;
    map.current = new maplibre.Map({
      container: container.current,
      style: tiles.style,
      center: [incident.longitude, incident.latitude],
      zoom: 11,
      attributionControl: { compact: true },
    });
    map.current.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
    map.current.on('load', () => {
      ready.current = true;
      map.current?.addSource(SURVEY_SOURCE, { type: 'geojson', data: surveyShape(null) });
      map.current?.addLayer({
        id: 'drone-survey-fill', type: 'fill', source: SURVEY_SOURCE,
        paint: { 'fill-color': colors.accent, 'fill-opacity': 0.12 },
      });
      map.current?.addLayer({
        id: 'drone-survey-line', type: 'line', source: SURVEY_SOURCE,
        paint: { 'line-color': colors.accent, 'line-width': 2, 'line-dasharray': [2, 1] },
      });
    });
    return () => {
      markers.current.forEach((marker) => marker.remove());
      map.current?.remove();
      map.current = null;
      ready.current = false;
    };
    // The map is created once per mounted panel; later props update layers.
  }, []);

  // Markers: rebuilt on every change. There are never more than a few dozen.
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    markers.current.forEach((marker) => marker.remove());
    markers.current = [];

    const animal = dot(colors.danger, '#FFFFFF', 18);
    animal.title = incident.label;
    markers.current.push(
      new maplibre.Marker({ element: animal })
        .setLngLat([incident.longitude, incident.latitude])
        .addTo(instance),
    );

    volunteers.forEach((volunteer) => {
      const tone = volunteerTone(volunteer, selected.has(volunteer.volunteer_id));
      const element = dot(tone.fill, tone.border, 13, !volunteer.eligible && !volunteer.alert);
      element.style.cursor = tone.selectable ? 'pointer' : 'default';
      element.title = `${volunteer.name} · ${volunteer.distance_km} km · ${tone.label}`;
      if (tone.selectable) {
        element.addEventListener('click', (event) => {
          event.stopPropagation();
          onToggle(volunteer.volunteer_id);
        });
      }
      markers.current.push(
        new maplibre.Marker({ element })
          .setLngLat([volunteer.longitude, volunteer.latitude])
          .addTo(instance),
      );
    });

    if (survey) {
      const launch = dot(colors.accent, colors.onAccent, 12);
      launch.title = 'Drone launch point (assumed)';
      markers.current.push(
        new maplibre.Marker({ element: launch })
          .setLngLat([survey.home_longitude, survey.home_latitude])
          .addTo(instance),
      );
    }

    // Frame the incident and the volunteers who could actually go, once.
    if (!fitted.current) {
      const reachable = volunteers.filter((v) => v.in_range);
      if (reachable.length > 0) {
        const bounds = new maplibre.LngLatBounds();
        bounds.extend([incident.longitude, incident.latitude]);
        reachable.forEach((v) => bounds.extend([v.longitude, v.latitude]));
        instance.fitBounds(bounds, { padding: 40, maxZoom: 14, duration: 0 });
        fitted.current = true;
      } else if (survey) {
        instance.jumpTo({ center: [incident.longitude, incident.latitude], zoom: 15 });
        fitted.current = true;
      }
    }
  }, [incident, volunteers, selected, onToggle, survey]);

  useEffect(() => {
    const draw = () =>
      (map.current?.getSource(SURVEY_SOURCE) as GeoJSONSource | undefined)?.setData(
        surveyShape(survey),
      );
    if (ready.current) draw();
    else map.current?.once('load', draw);
  }, [survey]);

  return (
    <View style={[styles.wrap, { height }]}>
      <div ref={container} style={{ position: 'absolute', inset: 0 }} />
      <View style={styles.legend} pointerEvents="none">
        <Text style={styles.legendText}>
          {survey ? 'Dashed box: planned survey area' : 'Dots are base areas, not live locations'}
        </Text>
        <Text style={styles.legendText}>{tiles.label}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'relative',
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
