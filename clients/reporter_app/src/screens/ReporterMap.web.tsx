import { useEffect, useRef, useState } from 'react';
import { circleMarker, map, tileLayer, type CircleMarker, type Map } from 'leaflet';
import 'leaflet/dist/leaflet.css';

export type ReportPoint = { latitude: number; longitude: number };
const BAY: ReportPoint = { latitude: 36.8, longitude: -121.79 };
const MAX_MAP_LATITUDE = 85.05112878;

export function ReporterMap({ point, onPick, offline = false }: {
  point: ReportPoint | null;
  onPick?: (point: ReportPoint) => void;
  offline?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Map | null>(null);
  const marker = useRef<CircleMarker | null>(null);
  const initialPoint = useRef(point);
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    if (!container.current) return;
    const center = initialPoint.current ?? BAY;
    const viewer = map(container.current, { scrollWheelZoom: false, maxZoom: 19 })
      .setView([center.latitude, center.longitude], initialPoint.current ? 14 : 6);
    instance.current = viewer;
    if (!offline) {
      tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        noWrap: true,
        referrerPolicy: 'strict-origin-when-cross-origin',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).on('tileerror', () => setTilesFailed(true)).addTo(viewer);
    }
    return () => { viewer.remove(); instance.current = null; marker.current = null; };
  }, [offline]);

  useEffect(() => {
    const viewer = instance.current;
    if (!viewer || !onPick) return;
    const choose = ({ lat, lng }: { lat: number; lng: number }) => {
      if (Math.abs(lat) <= MAX_MAP_LATITUDE) onPick({
        latitude: Number(lat.toFixed(6)),
        longitude: Number(viewer.wrapLatLng([lat, lng]).lng.toFixed(6)),
      });
    };
    const click = ({ latlng }: { latlng: { lat: number; lng: number } }) => choose(latlng);
    viewer.on('click', click);
    return () => { viewer.off('click', click); };
  }, [onPick, offline]);

  useEffect(() => {
    const viewer = instance.current;
    if (!viewer) return;
    if (!point || Math.abs(point.latitude) > MAX_MAP_LATITUDE) {
      marker.current?.remove();
      marker.current = null;
      return;
    }
    const coordinates: [number, number] = [point.latitude, point.longitude];
    if (marker.current) marker.current.setLatLng(coordinates);
    else marker.current = circleMarker(coordinates, {
      radius: 8, color: '#fff', weight: 3, fillColor: '#a24530', fillOpacity: 1,
      interactive: false,
    }).addTo(viewer);
    viewer.panInside(coordinates, { animate: false });
  }, [point, offline]);

  return <>
    <div className="report-map" ref={container} aria-label={onPick ? 'Pick the animal location on a map' : 'Reported animal location map'} />
    {offline ? <p className="muted">Map imagery is omitted from this offline demo.</p>
      : tilesFailed && <p role="status">Some map tiles could not load. You can still enter coordinates.</p>}
    {onPick && <button type="button" className="secondary" onClick={() => {
      const viewer = instance.current;
      if (!viewer) return;
      const center = viewer.wrapLatLng(viewer.getCenter());
      if (Math.abs(center.lat) <= MAX_MAP_LATITUDE) onPick({
        latitude: Number(center.lat.toFixed(6)), longitude: Number(center.lng.toFixed(6)),
      });
    }}>Place pin at map center</button>}
  </>;
}
