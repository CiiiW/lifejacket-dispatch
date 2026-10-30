/** Local synthetic experiments. The review acknowledgment is not authentication. */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import DroneLabMap from '../components/DroneLabMap';
import { drones, type DroneMissionRequest, type DronePlan, type DroneScenario,
  responder, type HistoricalDensity, type DroneSimulationResult, type SitlRun, type SitlRunSummary , type MapPin, type SurveyBox } from '../lib/api';
import { colors, glass, radius, spacing, type } from '../lib/theme';

const fields = ['home latitude', 'home longitude', 'south', 'north', 'west', 'east'] as const;
type AreaDraft = Record<typeof fields[number], string>;
function areaDraft(mission: DroneMissionRequest): AreaDraft {
  return { 'home latitude': String(mission.home.latitude),
    'home longitude': String(mission.home.longitude),
    south: String(mission.survey_area.south), north: String(mission.survey_area.north),
    west: String(mission.survey_area.west), east: String(mission.survey_area.east) };
}

export default function DroneLabScreen() {
  const [sitlRuns, setSitlRuns] = useState<SitlRunSummary[]>([]);
  const [sitlRun, setSitlRun] = useState<SitlRun | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [sitlError, setSitlError] = useState<string | null>(null);
  const [density, setDensity] = useState<HistoricalDensity | null>(null);
  const [densityError, setDensityError] = useState(false);
  const [draft, setDraft] = useState<AreaDraft | null>(null);
  const [mission, setMission] = useState<DroneMissionRequest | null>(null);
  const [plan, setPlan] = useState<DronePlan | null>(null);
  const [run, setRun] = useState<DroneSimulationResult | null>(null);
  const [scenario, setScenario] = useState<DroneScenario>('nominal');
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(false);
  const [pins, setPins] = useState<MapPin[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);

  // `attempt` exists so the Retry button can rerun this. Without it a single
  // failed load -- the API not up yet, or restarted while this tab was open --
  // left `mission` null forever, and every control below is gated on it, so
  // the screen simply had no buttons and looked frozen.
  useEffect(() => {
    let active = true;
    setError(null);
    drones.demo().then(value => { if (active) { setMission(value); setDraft(areaDraft(value)); } })
      .catch(() => { if (active) setError('Could not load the demo. Check that the local API is running.'); });
    responder.historicalDensity().then(value => { if (active) setDensity(value); })
      .catch(() => { if (active) setDensityError(true); });
    // Context only: a survey area is easier to judge against real reports.
    // Failure is silent -- the planner does not depend on these.
    responder.listIncidents().then(value => { if (active) setPins(value); }).catch(() => {});
    return () => { active = false; };
  }, [attempt]);

  useEffect(() => {
    if (!run || !playing) return;
    if (frame >= run.samples.length - 1) { setPlaying(false); return; }
    const timer = setTimeout(() => setFrame(current => current + 1), 100);
    return () => clearTimeout(timer);
  }, [run, playing, frame]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const summaries = await drones.runs();
        const detail = selectedRun ? await drones.run(selectedRun) : null;
        if (active) { setSitlRuns(summaries); setSitlRun(detail); setSitlError(null); }
      } catch { if (active) setSitlError('Saved SITL runs unavailable. Check the API run folder.'); }
      if (active) timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [selectedRun]);

  function reset(next: DroneMissionRequest) {
    setSelectedRun(null); setSitlRun(null); setMission(next); setPlan(null); setRun(null); setReviewed(false);
    setFrame(0); setPlaying(false); setError(null);
  }

  async function build() {
    if (!mission || !draft) return;
    if (fields.some(key => !draft[key].trim() || !Number.isFinite(Number(draft[key])))) {
      setError('Enter a numeric coordinate in every survey field.'); return;
    }
    const next: DroneMissionRequest = { ...mission,
      home: { latitude: Number(draft['home latitude']), longitude: Number(draft['home longitude']) },
      survey_area: { south: Number(draft.south), north: Number(draft.north),
        west: Number(draft.west), east: Number(draft.east) } };
    setMission(next);
    setBusy(true); setError(null); setRun(null); setPlaying(false); setReviewed(false);
    try { setPlan(await drones.plan(next)); }
    catch (reason) { setPlan(null); setError(reason instanceof Error ? reason.message : 'Planning failed.'); }
    finally { setBusy(false); }
  }

  async function simulate() {
    if (!plan || !reviewed || plan.status === 'blocked') return;
    setBusy(true); setError(null); setPlaying(false);
    try { setRun(await drones.simulate(plan, scenario)); setFrame(0); setPlaying(true); }
    catch (reason) { setRun(null); setError(reason instanceof Error ? reason.message : 'Simulation failed.'); }
    finally { setBusy(false); }
  }

  const context = mission?.historical_context;
  const selectedCell = density?.cells.find(cell => context &&
    Math.round(cell.latitude / density.grid_degrees - 0.5) === context.latitude_index &&
    Math.round(cell.longitude / density.grid_degrees - 0.5) === context.longitude_index) ?? null;
  const sample = run?.samples[frame] ?? null;
  const sitlSample = sitlRun?.samples.at(-1) ?? null;
  const mapSample = sitlSample ?? sample;
  const stale = sitlRun ? Date.now() - Date.parse(sitlRun.updated_at) > 10000 : false;
  const shownEvent = run?.events.find(event => event.elapsed_s <= (sample?.elapsed_s ?? -1));
  /**
   * Accept a box dragged on the map.
   *
   * Home moves with it. The planner blocks any survey area more than
   * `max_home_radius_m` from home, so keeping the old home point would make
   * every area drawn away from it come back blocked with zero waypoints.
   * Home lands just south of the area's south edge: outside the box, so the
   * takeoff and return legs stay visible, and centred on it, so the far
   * corners are as close as this placement allows.
   */
  function applyDrawnArea(box: SurveyBox) {
    if (!mission) return;
    const next = {
      ...mission,
      survey_area: box,
      home: {
        latitude: Number((box.south - 0.0008).toFixed(6)),
        longitude: Number(((box.west + box.east) / 2).toFixed(6)),
      },
    };
    setDrawing(false);
    reset(next);
    setDraft(areaDraft(next));
  }

  return (
    <View style={styles.screen}>
      <View style={styles.map}>
        <DroneLabMap plan={sitlRun?.plan ?? plan} sample={mapSample} trace={sitlRun?.samples ?? []}
            density={density} selectedCell={selectedCell} pins={pins}
            surveyArea={mission?.survey_area ?? null}
            onDrawSurvey={applyDrawnArea} drawing={drawing} />
      </View>
      <ScrollView style={styles.panel} contentContainerStyle={styles.content}>
        <Text style={styles.title}>Drone Lab</Text>
        <Text style={styles.notice}>SIMULATION ONLY · NO FLIGHT AUTHORIZATION</Text>

        {/* Above the fold on purpose: this used to render last, so a failed
            load was invisible without scrolling past every other card. */}
        {error && (
          <View style={styles.card}>
            <Text accessibilityRole="alert" style={styles.error}>{error}</Text>
            <Action label="Retry" onPress={() => setAttempt(current => current + 1)} />
          </View>
        )}
        <Text style={styles.body}>
          Use historical report density as context, choose a small survey, review its
          route, then replay a mock flight. Home and survey coordinates are simulation
          inputs; motion, wind and battery are synthetic.
        </Text>
        {!mission && !error && <ActivityIndicator color={colors.accent} />}
        {densityError && <Text style={styles.meta}>Historical layer unavailable. The synthetic demo still works.</Text>}
        {density && !density.available && <Text style={styles.meta}>
          No NOAA import in this database. Use the synthetic demo, or import your authorized workbook
          with scripts/local_demo.py --import-noaa /path/to/workbook.xlsx.
        </Text>}
        {mission && <>
          {density?.available && <View style={styles.card}>
            <Text style={styles.heading}>Historical report density</Text>
            <Text style={styles.meta}>{density.caveat}</Text>
            <Text style={styles.meta}>Select an aggregate cell as context. This does not set a base or flight destination.</Text>
            <ScrollView style={{ maxHeight: 180 }} nestedScrollEnabled>
              {density.cells.map(cell => <Action key={`${cell.latitude},${cell.longitude}`}
                label={`${cell.latitude.toFixed(2)}, ${cell.longitude.toFixed(2)} · ${cell.band} reports`}
                active={cell === selectedCell} disabled={busy || !density.dataset_sha256}
                onPress={() => reset({ ...mission, historical_context: {
                  dataset_id: 'noaa_ca_2006_2025', dataset_sha256: density.dataset_sha256!,
                  latitude_index: Math.round(cell.latitude / density.grid_degrees - 0.5),
                  longitude_index: Math.round(cell.longitude / density.grid_degrees - 0.5),
                } })} />)}
            </ScrollView>
            {!density.cells.length && <Text style={styles.meta}>No cells meet the public threshold.</Text>}
            {selectedCell && <Text style={styles.body}>
              Selected cell: latitude {(selectedCell.latitude - density.grid_degrees / 2).toFixed(4)} to{' '}
              {(selectedCell.latitude + density.grid_degrees / 2).toFixed(4)}, longitude{' '}
              {(selectedCell.longitude - density.grid_degrees / 2).toFixed(4)} to{' '}
              {(selectedCell.longitude + density.grid_degrees / 2).toFixed(4)}.
              Enter a much smaller survey inside this cell and a nearby simulated home.
            </Text>}
          </View>}
          <Action label="Use synthetic demo area" disabled={busy} onPress={() => {
            drones.demo().then(value => { reset(value); setDraft(areaDraft(value)); })
              .catch(() => setError('Could not load the synthetic area.'));
          }} />
          <Action label={drawing ? 'Drawing — drag on the map, or tap to cancel' : 'Draw survey area on map'}
            active={drawing} disabled={busy} onPress={() => setDrawing(current => !current)} />
          {drawing && <Text style={styles.meta}>
            Drag a rectangle over the map. Panning is paused until you finish.
            Home moves to just south of the area, and an area much over a
            kilometre across will be blocked as too far from it.
          </Text>}
          {!drawing && <Text style={styles.meta}>
            The amber rectangle is the survey area. Red and amber dots are current incidents.
          </Text>}

          {/* Closed by default. Six labelled inputs are taller than the panel
              on a laptop, and they pushed "Build survey plan" off screen; the
              demo area is already filled in, so most runs never open this. */}
          {draft && <View style={styles.card}>
            <Pressable accessibilityRole="button" accessibilityState={{ expanded: editing }}
              onPress={() => setEditing(current => !current)} style={styles.cardHeader}>
              <Text style={styles.heading}>Simulation coordinates</Text>
              <Text style={styles.chevron}>{editing ? '\u2212' : '+'}</Text>
            </Pressable>
            {!editing && <Text style={styles.meta}>
              home {draft['home latitude']}, {draft['home longitude']} · tap to edit
            </Text>}
            {editing && fields.map(key => <View key={key}>
              <Text style={styles.meta}>{key}</Text>
              <TextInput accessibilityLabel={key} value={draft[key]} editable={!busy}
                style={styles.input} onChangeText={value => {
                  setDraft({ ...draft, [key]: value }); reset(mission);
                }} />
            </View>)}
          </View>}
          <View style={styles.choices}>
            <Action label="Normal wind" disabled={busy} active={mission.simulated_wind_mps === 3}
              onPress={() => reset({ ...mission, simulated_wind_mps: 3 })} />
            <Action label="High wind" disabled={busy} active={mission.simulated_wind_mps === 12}
              onPress={() => reset({ ...mission, simulated_wind_mps: 12 })} />
          </View>
          <Text style={styles.body}>
            Altitude {mission.altitude_m} m · simulated wind {mission.simulated_wind_mps} m/s
          </Text>
          <Action label="Build survey plan" disabled={busy} onPress={() => void build()} />
        </>}
        {plan && <View style={styles.card}>
          <Text style={styles.heading}>{plan.status === 'blocked' ? 'Plan blocked' : 'Ready for review'}</Text>
          {plan.blocked_reasons.map(reason => <Text style={styles.error} key={reason}>{reason}</Text>)}
          <Text style={styles.body}>
            {plan.waypoints.length} waypoints · {plan.distance_m ?? '—'} m ·{' '}
            {plan.duration_s === null ? '—' : (plan.duration_s / 60).toFixed(1)} min estimated
          </Text>
          <Text style={styles.body}>Estimated battery at landing: {plan.estimated_battery_remaining_percent ?? '—'}%</Text>
          {plan.status === 'ready_for_review' && <>
            <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: reviewed }}
              disabled={busy} onPress={() => setReviewed(current => !current)}>
              <Text style={styles.review}>{reviewed ? '☑' : '☐'} I reviewed this synthetic route</Text>
            </Pressable>
            <Text style={styles.meta}>Choose a mock scenario:</Text>
            <View style={styles.choices}>
              {(['nominal', 'low_battery', 'link_loss'] as const).map(value =>
                <Action key={value} label={value.replace(/_/g, ' ')} active={scenario === value}
                  disabled={busy || playing} onPress={() => { setScenario(value); setRun(null); setFrame(0); }} />)}
            </View>
            <Action label="Run mock flight" disabled={busy || !reviewed || playing}
              onPress={() => void simulate()} />
          </>}
        </View>}
        {sample && run && <View style={styles.card}>
          <Text style={styles.heading}>{playing ? 'Replaying mock telemetry' : `Mock run ${run.status}`}</Text>
          <Text style={styles.meta}>Scenario: {run.scenario.replace(/_/g, ' ')}</Text>
          <Text style={styles.body}>
            {sample.elapsed_s.toFixed(0)} simulated seconds · {sample.phase} · {sample.altitude_m} m
          </Text>
          <Text style={styles.body}>Synthetic battery: {sample.battery_percent}%</Text>
          <Text style={styles.meta}>Replay is accelerated. No real-time vehicle connection.</Text>
          {shownEvent && <Text style={styles.error}>{shownEvent.message}</Text>}
          {!playing && <Action label="Replay trace" onPress={() => { setFrame(0); setPlaying(true); }} />}
        </View>}
        {busy && <ActivityIndicator color={colors.accent} />}
        {/* Below the planner: on a laptop this card is usually empty --
            SITL runs are written by the local companion, which only runs on
            the GCP VM -- and above the planner it pushed the primary action
            off screen. */}
        <View style={styles.card}>
          <Text style={styles.heading}>Saved SITL flights</Text>
          <Text style={styles.meta}>ArduPilot simulator telemetry · refreshes every 2 seconds. Start and cancel flights from the local companion terminal.</Text>
          {sitlError && <Text style={styles.error}>{sitlError}</Text>}
          {!sitlRuns.length && <Text style={styles.meta}>No saved flights in this API's run folder.</Text>}
          {sitlRuns.map(item => <Action key={item.run_id}
            label={`${item.status} · ${item.started_at.slice(0, 19)} · ${item.run_id.slice(0, 8)}`}
            active={selectedRun === item.run_id} onPress={() => { setPlaying(false); setSitlRun(null); setSelectedRun(item.run_id); }} />)}
          {selectedRun && <Action label="Return to mock planner" onPress={() => { setSelectedRun(null); setSitlRun(null); }} />}
          {sitlRun && <>
            <Text style={styles.body}>Status: {sitlRun.status} · {stale ? 'snapshot older than 10 seconds' : 'snapshot current'}</Text>
            {sitlRun.outcome && <Text style={styles.body}>{sitlRun.outcome}</Text>}
            {sitlSample && <Text style={styles.body}>
              Altitude {sitlSample.altitude_m.toFixed(1)} m · mode {sitlSample.mode} · waypoint {sitlSample.waypoint_seq}{'\n'}
              Battery {sitlSample.battery_percent === null ? 'unavailable' : `${sitlSample.battery_percent}%`} · {sitlSample.armed ? 'armed' : 'disarmed'}
            </Text>}
            <Text style={styles.meta}>Dashed amber: planned route. Solid teal: measured SITL trace.</Text>
            <Text style={styles.body}>Samples: {sitlRun.samples.length} · max horizontal deviation: {sitlRun.metrics.max_route_deviation_m?.toFixed(1) ?? '—'} m</Text>
            <Text style={styles.meta}>{sitlRun.observations.length} observations · A simulated flight does not create a wildlife incident.</Text>
            {sitlRun.events.slice(-5).map((event, i) => <Text key={i} style={styles.meta}>{event.elapsed_s.toFixed(1)}s · {event.message}</Text>)}
          </>}
        </View>
        <Text style={styles.meta}>
          This mock checks app integration and basic route constraints. Flight dynamics,
          terrain, camera coverage, wildlife restrictions and autopilot recovery still
          need separate validation. Mock replay is temporary; SITL flights are saved by the local companion.
        </Text>
      </ScrollView>
    </View>
  );
}

function Action({ label, onPress, disabled = false, active = false }: {
  label: string; onPress: () => void; disabled?: boolean; active?: boolean;
}) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
    disabled={disabled} style={[styles.button, active && styles.active, disabled && styles.disabled]}>
    <Text style={styles.buttonText}>{label}</Text>
  </Pressable>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, flexDirection: 'row', flexWrap: 'wrap', backgroundColor: colors.background },
  map: { flex: 2, minWidth: 280, minHeight: 350, padding: spacing.lg },
  panel: { flex: 1, minWidth: 310, backgroundColor: colors.backgroundElevated },
  content: { padding: spacing.lg, gap: spacing.md },
  cardHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  chevron: { ...type.label, fontSize: 18, color: colors.textFaint },
  title: { ...type.title, color: colors.text },
  heading: { ...type.heading, color: colors.text },
  notice: { ...type.eyebrow, color: colors.warning },
  body: { ...type.body, color: colors.textMuted, lineHeight: 21 },
  meta: { ...type.meta, color: colors.textFaint, lineHeight: 18 },
  review: { ...type.label, color: colors.accent, paddingVertical: spacing.sm },
  error: { ...type.meta, color: colors.danger, lineHeight: 20 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  card: { ...glass, padding: spacing.md, gap: spacing.sm },
  button: { borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  active: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  disabled: { opacity: 0.4 },
  input: { color: colors.text, borderColor: colors.borderStrong, borderWidth: 1,
    borderRadius: radius.sm, padding: spacing.sm },
  buttonText: { ...type.label, color: colors.text },
});
