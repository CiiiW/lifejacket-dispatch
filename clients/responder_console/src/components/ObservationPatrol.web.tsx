import { useEffect, useRef, useState } from 'react';

import type { DronePlan, DroneSimulationResult } from '../lib/api';
import { type DroneApi, type ObservationSearchArea, type PatrolPreview, networkErrorMessage } from '../lib/networkApi';
import ObservationSearchMap from './ObservationSearchMap.web';

function downloadSurveyWaypoints(plan: DronePlan) {
  const rows = plan.waypoints
    .filter(point => point.phase === 'survey')
    .map(point => [point.latitude.toFixed(7), point.longitude.toFixed(7)].join(','));
  const csv = ['latitude,longitude', ...rows, ''].join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `patrol-draft-${plan.plan_id}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ObservationPatrol({
  area, offline, previewPatrol,
}: {
  area: ObservationSearchArea;
  offline?: boolean;
  previewPatrol?: (planId: string | null, signal: AbortSignal, sendToSimulator?: boolean) => ReturnType<NonNullable<DroneApi['patrol']>>;
}) {
  const [preview, setPreview] = useState<PatrolPreview | null>(null);
  const [simulation, setSimulation] = useState<DroneSimulationResult | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (!playing || !simulation) return;
    if (frame >= simulation.samples.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setFrame(frame + 1), 80);
    return () => clearTimeout(timer);
  }, [frame, playing, simulation]);

  async function planOrRun(planId: string | null, sendToSimulator = false) {
    if (!previewPatrol || pending.current) return;
    const request = new AbortController();
    pending.current = request;
    setBusy(true);
    setError('');
    if (!sendToSimulator) {
      setPlaying(false);
      setSimulation(null);
      setFrame(0);
    }
    try {
      const result = await previewPatrol(planId, request.signal, sendToSimulator);
      if (request.signal.aborted) return;
      setPreview(result);
      if (!sendToSimulator) {
        setZoom(Boolean(result.plan?.waypoints.length));
        setSimulation(result.simulation);
        setPlaying(Boolean(result.simulation));
      }
    } catch (failure) {
      if (!request.signal.aborted) {
        if (!sendToSimulator) setPreview(null);
        setError(networkErrorMessage(failure));
      }
    } finally {
      pending.current = null;
      if (!request.signal.aborted) setBusy(false);
    }
  }

  const plan = preview?.plan;
  const sample = simulation?.samples[frame];
  const atEnd = simulation && frame === simulation.samples.length - 1;
  return <section aria-label="Observation search area and patrol">
    <h4>Search area · {area.radius_m / 1000} km radius</h4>
    <ObservationSearchMap center={area.center} radiusMeters={area.radius_m} offline={offline}
      route={plan?.waypoints} patrolPosition={sample} focusPatrol={zoom}/>
    <p className="lj-muted">Search center {area.center.latitude.toFixed(5)}, {area.center.longitude.toFixed(5)}</p>
    {previewPatrol && <button type="button" className="secondary" disabled={busy}
      onClick={() => void planOrRun(null)}>Preview patrol</button>}
    {error && <p role="alert" className="lj-error">{error}</p>}
    {preview?.unavailable_reason && <p role="status">{preview.unavailable_reason}</p>}
    {plan && <>
      <h4>Simulated first pass</h4>
      <p className="lj-muted">The blue circle is the search area. The amber line is one proposed pass through it.
        {' '}Camera coverage is not simulated.</p>
      {plan.distance_m !== null && <p>
        Planned route {(plan.distance_m / 1000).toFixed(2)} km · {Math.round((plan.duration_s ?? 0) / 60)} min simulated
      </p>}
      {plan.blocked_reasons.map(reason => <p key={reason} role="status">{reason}</p>)}
      {plan.waypoints.length > 0 && <button type="button" className="secondary"
        onClick={() => setZoom(!zoom)}>{zoom ? 'Show full search area' : 'Zoom to patrol'}</button>}
      {plan.status === 'ready_for_review' && <details>
        <summary>Mission handoff</summary>
        <p className="lj-muted">Download the survey coordinates for route drafting in Litchi Legacy Mission Hub.
          The pilot chooses the launch point and reviews altitude, speed, return and signal-loss settings in Litchi.</p>
        <button type="button" className="secondary" disabled={busy}
          onClick={() => downloadSurveyWaypoints(plan)}>Download draft waypoints (CSV)</button>
        <p className="lj-muted">{preview?.simulator_available
          ? 'Verify this route by uploading it to a temporary ArduPilot simulator. The simulator closes after readback.'
          : 'ArduPilot upload verification is disabled on this server.'}</p>
        <button type="button" className="secondary" disabled={busy || !preview?.simulator_available}
          onClick={() => void planOrRun(plan.plan_id, true)}>Send to simulator</button>
        {!busy && !error && preview?.upload && <p role="status">
          ArduPilot verified the upload and readback of {preview.upload.mission_items} mission items. Flight not started.
        </p>}
      </details>}
      {plan.status === 'ready_for_review' && !simulation && <button type="button" disabled={busy}
        onClick={() => void planOrRun(plan.plan_id)}>Run simulated patrol</button>}
    </>}
    {simulation && sample && <>
      <p>Simulated aircraft · {sample.phase} · {Math.round(sample.elapsed_s)} s · {Math.round(sample.battery_percent)}% battery</p>
      <button type="button" className="secondary" onClick={() => {
        if (atEnd) setFrame(0);
        setPlaying(!playing);
      }}>{playing && !atEnd ? 'Pause replay' : atEnd ? 'Replay patrol' : 'Resume replay'}</button>
      {atEnd && <p role="status">Simulation {simulation.status}. Use the case’s recorded evidence to review the observation.</p>}
    </>}
  </section>;
}
