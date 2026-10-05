/**
 * The triage map: incidents, rescue centres, and the route between them.
 *
 * MapLibre GL rather than `react-native-maps`, which has no web renderer.
 * This file is web-only (see `IncidentMapScreen.web.tsx`) and talks to
 * MapLibre's imperative API directly, because wrapping a WebGL map in React
 * state is a reliable way to redraw it sixty times a second by accident.
 *
 * What is drawn:
 *
 * - **Incidents**, coloured by the severity the backend computed. Clicking
 *   one selects it, which is the same action as clicking its list row.
 * - **Rescue centres**, as small seafoam rings. Their coordinates are
 *   service-area centroids, not street addresses, so they are deliberately
 *   drawn smaller and dimmer than incidents -- see `/responders/geocode`.
 * - **A route** from the suggested centre to the selected incident, fetched
 *   from the backend (which holds the OpenRouteService key). Dashed when it
 *   is the straight-line fallback rather than a real road route.
 */

import { useEffect, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import maplibre, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { severityColour, type MapPin, type ResponderOrg, type RouteLine } from '../lib/api';
import { basemap } from '../lib/basemap';
import { colors, radius, spacing, type } from '../lib/theme';

const ROUTE_SOURCE = 'route';
const DEFAULT_CENTRE: [number, number] = [-121.9, 36.8]; // Monterey Bay

export default function TriageMap({
  pins,
  centres,
  route,
  selectedId,
  onSelect,
}: {
  pins: MapPin[];
  centres: ResponderOrg[];
  route: RouteLine | null;
  selectedId: string | null;
  onSelect: (incidentId: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<maplibre.Marker[]>([]);
  const ready = useRef(false);
  const tiles = basemap();

  // Create the map once. Re-creating it on every render would flash and lose
  // the user's pan and zoom.
  useEffect(() => {
    if (map.current || !container.current) return;

    map.current = new maplibre.Map({
      container: container.current,
      style: tiles.style,
      center: DEFAULT_CENTRE,
      zoom: 5.5,
      attributionControl: { compact: true },
    });
    map.current.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
    map.current.on('load', () => {
      ready.current = true;
      if (!map.current) return;
      map.current.addSource(ROUTE_SOURCE, {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } },
      });
      map.current.addLayer({
        id: 'route-line',
        type: 'line',
        source: ROUTE_SOURCE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': colors.accent,
          'line-width': 4,
          'line-opacity': 0.9,
        },
      });
    });

    return () => {
      map.current?.remove();
      map.current = null;
      ready.current = false;
    };
  }, [tiles.style]);

  // Redraw markers whenever the data or the selection changes. Markers are
  // DOM elements, so they are torn down and rebuilt rather than diffed.
  useEffect(() => {
    if (!map.current) return;

    markers.current.forEach((marker) => marker.remove());
    markers.current = [];

    centres
      .filter((centre) => centre.latitude !== null && centre.longitude !== null)
      .forEach((centre) => {
        const element = document.createElement('div');
        element.style.cssText = [
          'width:9px', 'height:9px', 'border-radius:50%',
          `border:2px solid ${colors.accent}`,
          'background:rgba(72,202,228,0.25)',
          'cursor:help',
        ].join(';');
        element.title = `${centre.name}\n(approximate: centre of its service area)`;
        markers.current.push(
          new maplibre.Marker({ element })
            .setLngLat([centre.longitude as number, centre.latitude as number])
            .addTo(map.current as MapLibreMap),
        );
      });

    pins
      .filter((pin) => pin.latitude !== null && pin.longitude !== null)
      .forEach((pin) => {
        const selected = pin.incident_id === selectedId;
        const element = document.createElement('div');
        const size = selected ? 22 : 16;
        element.style.cssText = [
          `width:${size}px`, `height:${size}px`, 'border-radius:50%',
          `background:${severityColour(pin.severity_level)}`,
          `border:${selected ? 3 : 2}px solid ${selected ? colors.accent : 'rgba(255,255,255,0.85)'}`,
          'cursor:pointer',
          'box-shadow:0 2px 8px rgba(0,0,0,0.5)',
        ].join(';');
        element.title = pin.headline ?? pin.species_common_name ?? 'Unidentified animal';
        element.onclick = () => onSelect(pin.incident_id);

        markers.current.push(
          new maplibre.Marker({ element })
            .setLngLat([pin.longitude as number, pin.latitude as number])
            .addTo(map.current as MapLibreMap),
        );
      });
  }, [pins, centres, selectedId, onSelect]);

  // Fit to the incidents once there are some, so a coordinator does not open
  // the console to an empty ocean.
  useEffect(() => {
    const located = pins.filter((p) => p.latitude !== null && p.longitude !== null);
    if (!map.current || located.length === 0) return;

    const bounds = new maplibre.LngLatBounds();
    located.forEach((p) => bounds.extend([p.longitude as number, p.latitude as number]));
    map.current.fitBounds(bounds, { padding: 80, maxZoom: 9, duration: 600 });
  }, [pins]);

  // Draw (or clear) the route line.
  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource(ROUTE_SOURCE) as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: 'Feature',
        properties: {},
        geometry: { type: 'LineString', coordinates: route?.coordinates ?? [] },
      });
      // A straight line is not a drive. Dash it so the two cannot be confused
      // at a glance.
      map.current?.setPaintProperty(
        'route-line',
        'line-dasharray',
        route?.source === 'straight_line' ? [2, 2] : [1],
      );
    };

    if (ready.current) draw();
    else map.current?.once('load', draw);
  }, [route]);

  return (
    <View style={styles.wrap}>
      <div ref={container} style={{ position: 'absolute', inset: 0 }} />

      <View style={styles.badge} pointerEvents="none">
        <Text style={styles.badgeText}>{tiles.label}</Text>
        {route && (
          <Text style={styles.badgeText}>
            {route.source === 'straight_line'
              ? `${route.distance_km ?? '?'} km straight line from ${route.from_name ?? 'centre'}`
              : `${route.distance_km ?? '?'} km / ${route.duration_minutes ?? '?'} min drive`}
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, overflow: 'hidden', borderRadius: radius.card },
  badge: {
    position: 'absolute',
    left: spacing.md,
    bottom: spacing.md,
    backgroundColor: 'rgba(11, 19, 43, 0.82)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
    gap: 2,
  },
  badgeText: { ...type.meta, fontSize: 11, color: colors.textMuted },
});
