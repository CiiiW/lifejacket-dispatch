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

import { severityColour, type HistoricalDensity, type MapPin, type ResponderOrg, type RouteLine,
  type DronePlan, type DronePoint } from '../lib/api';
import { basemap } from '../lib/basemap';
import { colors, radius, spacing, type } from '../lib/theme';

const ROUTE_SOURCE = 'route';
const DENSITY_SOURCE = 'historical-density';
const DENSITY_LAYER = 'historical-heatmap';
const DEFAULT_CENTRE: [number, number] = [-121.9, 36.8]; // Monterey Bay

export default function TriageMap({
  pins,
  centres,
  route,
  density,
  showDensity,
  dronePlan = null,
  droneSample = null,
  droneTrace = [],
  historicalCell = null,
  selectedId,
  onSelect,
}: {
  pins: MapPin[];
  centres: ResponderOrg[];
  route: RouteLine | null;
  density: HistoricalDensity | null;
  showDensity: boolean;
  dronePlan?: DronePlan | null;
  droneSample?: DronePoint | null;
  droneTrace?: DronePoint[];
  historicalCell?: HistoricalDensity['cells'][number] | null;
  selectedId: string | null;
  onSelect: (incidentId: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<maplibre.Marker[]>([]);
  const droneMarker = useRef<maplibre.Marker | null>(null);
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
      map.current.addSource(DENSITY_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({
        id: DENSITY_LAYER,
        type: 'heatmap',
        source: DENSITY_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'heatmap-weight': ['get', 'weight'],
          'heatmap-intensity': 0.7,
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 4, 12, 9, 36],
          'heatmap-opacity': 0.68,
          'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)', 0.25, '#48CAE4', 0.55, '#FFCB5B', 1, '#FF704F'],
        },
      });
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
      map.current.addSource('drone-survey', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } },
      });
      map.current.addLayer({ id: 'drone-survey-line', type: 'line', source: 'drone-survey',
        paint: { 'line-color': colors.warning, 'line-width': 3, 'line-dasharray': [2, 1] } });
      map.current.addSource('drone-trace', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({id: 'drone-trace-line', type: 'line', source: 'drone-trace',
        paint: {'line-color': colors.accent, 'line-width': 3}});
      map.current.addSource('selected-historical-cell', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({ id: 'selected-historical-cell-line', type: 'line',
        source: 'selected-historical-cell',
        paint: { 'line-color': colors.accent, 'line-width': 2 } });
    });

    return () => {
      map.current?.remove();
      map.current = null;
      droneMarker.current = null;
      ready.current = false;
    };
  }, [tiles.style]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource(DENSITY_SOURCE) as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: 'FeatureCollection',
        features: (density?.cells ?? []).map((cell) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [cell.longitude, cell.latitude] },
          properties: { weight: cell.band === '100+' ? 1 : cell.band === '25-99' ? 0.65 : 0.35 },
        })),
      });
      map.current?.setLayoutProperty(DENSITY_LAYER, 'visibility', showDensity ? 'visible' : 'none');
    };
    if (ready.current) draw();
    else map.current?.once('load', draw);
  }, [density, showDensity]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('selected-historical-cell') as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      const half = (density?.grid_degrees ?? 0.1) / 2;
      const cell = historicalCell;
      source.setData({ type: 'FeatureCollection', features: cell ? [{
        type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
          [cell.longitude - half, cell.latitude - half],
          [cell.longitude + half, cell.latitude - half],
          [cell.longitude + half, cell.latitude + half],
          [cell.longitude - half, cell.latitude + half],
          [cell.longitude - half, cell.latitude - half],
        ]] },
      }] : [] });
      if (cell) map.current?.fitBounds([
        [cell.longitude - half, cell.latitude - half],
        [cell.longitude + half, cell.latitude + half],
      ], { padding: 40, duration: 400 });
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [historicalCell, density?.grid_degrees]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('drone-survey') as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      const coordinates = dronePlan?.waypoints.map(p => [p.longitude, p.latitude]) ?? [];
      source.setData({ type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates } });
      map.current?.setPaintProperty('drone-survey-line', 'line-color',
        dronePlan?.status === 'blocked' ? colors.danger : colors.warning);
      if (coordinates.length && map.current) {
        const bounds = new maplibre.LngLatBounds();
        coordinates.forEach(point => bounds.extend([point[0], point[1]]));
        map.current.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
      }
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [dronePlan?.plan_id]);

  useEffect(() => {
    if (!map.current) return;
    if (!droneSample) { droneMarker.current?.remove(); droneMarker.current = null; return; }
    if (!droneMarker.current) {
      const element = document.createElement('div');
      element.style.cssText = 'width:18px;height:18px;background:#FFC043;border:3px solid #fff;border-radius:50%;';
      element.title = 'Synthetic drone telemetry';
      droneMarker.current = new maplibre.Marker({ element });
    }
    droneMarker.current.setLngLat([droneSample.longitude, droneSample.latitude]).addTo(map.current);
  }, [droneSample]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('drone-trace') as maplibre.GeoJSONSource | undefined;
      source?.setData({type: 'FeatureCollection', features: droneTrace.length > 1 ? [{
        type: 'Feature', properties: {}, geometry: {type: 'LineString',
          coordinates: droneTrace.map(p => [p.longitude, p.latitude])},
      }] : []});
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [droneTrace]);

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
        {dronePlan && <Text style={styles.badgeText}>Synthetic survey route · {dronePlan.status.replace(/_/g, ' ')}</Text>}
        {showDensity && density && <Text style={styles.badgeText}>
          Historical reports · 10–24 / 25–99 / 100+ per ~11 km cell
        </Text>}
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
