import { useEffect, useRef, useState } from 'react';
import maplibre, { type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { basemap } from '../lib/basemap';
import type { ObservationPoint } from '../lib/networkApi';

const DEFAULT_MAP_CENTER: [number, number] = [-121.9, 36.8];
const LOCAL_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#16283d' } }],
};
const radians = Math.PI / 180;

// Spherical destinations keep the displayed radius in meters at different latitudes.
function searchRing(center: ObservationPoint, radiusMeters: number) {
  const latitude = center.latitude * radians;
  const distance = radiusMeters / 6_371_008.8;
  const ring = Array.from({ length: 64 }, (_, index) => {
    const bearing = index * Math.PI / 32;
    const lat = Math.asin(
      Math.sin(latitude) * Math.cos(distance) +
      Math.cos(latitude) * Math.sin(distance) * Math.cos(bearing),
    );
    const longitudeDelta = Math.atan2(
      Math.sin(bearing) * Math.sin(distance) * Math.cos(latitude),
      Math.cos(distance) - Math.sin(latitude) * Math.sin(lat),
    );
    return [center.longitude + longitudeDelta / radians, lat / radians];
  });
  return [...ring, ring[0]];
}

export default function ObservationSearchMap({
  center, radiusMeters, onPick, offline = false,
}: {
  center: ObservationPoint | null;
  radiusMeters: number;
  onPick?: (center: ObservationPoint) => void;
  offline?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibre.Map | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    if (!container.current) return;
    let instance: maplibre.Map;
    try {
      instance = new maplibre.Map({
        container: container.current,
        style: offline ? LOCAL_STYLE : basemap().style,
        center: DEFAULT_MAP_CENTER,
        zoom: 4,
      });
    } catch {
      setUnavailable(true);
      return;
    }
    map.current = instance;
    instance.addControl(new maplibre.ScaleControl({ unit: 'metric' }));
    instance.on('load', () => {
      instance.addSource('observation-search', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      instance.addLayer({
        id: 'search-fill', type: 'fill', source: 'observation-search',
        filter: ['==', '$type', 'Polygon'],
        paint: { 'fill-color': '#48cae4', 'fill-opacity': 0.22 },
      });
      instance.addLayer({
        id: 'search-outline', type: 'line', source: 'observation-search',
        filter: ['==', '$type', 'Polygon'],
        paint: { 'line-color': '#48cae4', 'line-width': 2 },
      });
      instance.addLayer({
        id: 'search-center', type: 'circle', source: 'observation-search',
        filter: ['==', '$type', 'Point'],
        paint: { 'circle-color': '#48cae4', 'circle-stroke-color': '#0b132b',
          'circle-stroke-width': 2, 'circle-radius': 6 },
      });
    });
    instance.on('click', event => {
      const point = event.lngLat.wrap();
      pick.current?.({ latitude: point.lat, longitude: point.lng });
    });
    return () => { instance.remove(); map.current = null; };
  }, [offline]);

  const latitude = center?.latitude;
  const longitude = center?.longitude;
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const draw = () => {
      const source = instance.getSource<GeoJSONSource>('observation-search');
      if (!source) return;
      if (latitude === undefined || longitude === undefined) {
        source.setData({ type: 'FeatureCollection', features: [] });
        return;
      }
      const ring = radiusMeters > 0 ? searchRing({ latitude, longitude }, radiusMeters) : null;
      source.setData({
        type: 'FeatureCollection',
        features: [

          { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [longitude, latitude] } },
          ...(ring ? [{ type: 'Feature' as const, properties: {},
            geometry: { type: 'Polygon' as const, coordinates: [ring] } }] : []),
        ],
      });
      if (ring) {
        const bounds = new maplibre.LngLatBounds();
        ring.forEach(([lng, lat]) => bounds.extend([lng, lat]));
        instance.fitBounds(bounds, { padding: 34, maxZoom: 17, duration: 0 });
      } else {
        instance.setCenter([longitude, latitude]);
      }
    };
    if (instance.getSource('observation-search')) draw();
    else instance.once('load', draw);
    return () => { instance.off('load', draw); };
  }, [latitude, longitude, radiusMeters, offline]);

  if (unavailable) return <p className="lj-muted">Search-area map unavailable.</p>;
  return <div ref={container} aria-label="Observation search area map"
    style={{ height: 245, width: '100%', borderRadius: 8, overflow: 'hidden',
      cursor: onPick ? 'crosshair' : undefined, background: '#16283d' }} />;
}
