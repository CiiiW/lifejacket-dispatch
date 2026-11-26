import { useEffect, useRef, useState } from 'react';
import { ReporterMap, type ReportPoint } from './ReporterMap.web';

export type LocationInput = {
  latitude: string;
  longitude: string;
  source: 'map_pin' | 'device_gps' | 'manual';
  accuracy?: number;
};
export const emptyLocation: LocationInput = { latitude: '', longitude: '', source: 'manual' };

export function ReporterLocation({ value, onChange, onConfirm, busy, offline }: {
  value: LocationInput;
  onChange: (value: LocationInput) => void;
  onConfirm: () => void;
  busy: boolean;
  offline?: boolean;
}) {
  const [showMap, setShowMap] = useState(false);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const latitude = Number(value.latitude);
  const longitude = Number(value.longitude);
  const valid = Boolean(value.latitude.trim() && value.longitude.trim()) &&
    Number.isFinite(latitude) && Math.abs(latitude) <= 90 &&
    Number.isFinite(longitude) && Math.abs(longitude) <= 180;

  function pick(point: ReportPoint, source: LocationInput['source'], accuracy?: number) {
    onChange({latitude: String(point.latitude), longitude: String(point.longitude), source, accuracy});
  }

  function getPosition() {
    if (!navigator.geolocation) {
      setError('Location access is unavailable. Use the map or enter coordinates.');
      return;
    }
    setError('');
    setLocating(true);
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (!active.current) return;
      pick(coords, 'device_gps', Number.isFinite(coords.accuracy) ? coords.accuracy : undefined);
      setLocating(false);
      setShowMap(true);
    }, () => {
      if (!active.current) return;
      setLocating(false);
      setError('I couldn’t get your position. Use the map or enter coordinates.');
    }, { timeout: 10000, maximumAge: 0, enableHighAccuracy: true });
  }

  return <form onSubmit={event => { event.preventDefault(); if (valid && !locating) onConfirm(); }}>
    <p>Mark where you saw the animal. If you use your position, check the pin before sharing it.</p>
    <div className="toolbar">
      <button type="button" className="secondary" disabled={busy || locating} onClick={getPosition}>
        {locating ? 'Finding your position…' : 'Use my current location'}
      </button>
      <button type="button" className="secondary" disabled={busy} aria-expanded={showMap}
        onClick={() => setShowMap(!showMap)}>{showMap ? 'Hide map' : 'Pick on map'}</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {showMap && <ReporterMap point={valid ? {latitude,longitude} : null}
      onPick={busy || locating ? undefined : point => pick(point, 'map_pin')} offline={offline}/>}
    <div className="grid">
      <label>Animal latitude<input type="number" min={-90} max={90} step="any" required
        disabled={busy || locating} value={value.latitude}
        onChange={event=>onChange({ ...value, latitude: event.target.value, source: 'manual', accuracy: undefined })}/></label>
      <label>Animal longitude<input type="number" min={-180} max={180} step="any" required
        disabled={busy || locating} value={value.longitude}
        onChange={event=>onChange({ ...value, longitude: event.target.value, source: 'manual', accuracy: undefined })}/></label>
    </div>
    {value.source === 'device_gps' && value.accuracy !== undefined &&
      <p className="muted">Estimated location accuracy · {Math.round(value.accuracy)} m</p>}
    <button disabled={busy || locating || !valid}>Use animal location</button>
  </form>;
}
