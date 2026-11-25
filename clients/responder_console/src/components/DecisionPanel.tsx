/**
 * What happens to an incoming report: the coordinator's four options.
 *
 *   Ignore           close it with a reason
 *   Send a team      offer it to a rescue centre (the existing offer flow)
 *   Send volunteers  ask nearby volunteers to check in (VolunteerPanel)
 *   Send a drone     plan a survey flight -- simulation only
 *
 * One option is marked "suggested" from the triage band, matching what each
 * band means in `SeverityLevel`: critical and respond need a professional
 * team, monitor is a volunteer watching, guidance needs no response. It is a
 * suggestion: the coordinator decides, and can combine options (a drone and
 * volunteers on the same case, say). Every decision lands in the log below.
 */

import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import {
  coordinator,
  type AssignmentRecord,
  type DecisionEntry,
  type DroneSurvey,
  type IgnoreReason,
  type IncidentDetail,
} from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';
import {
  ActionButton,
  Chip,
  ErrorLine,
  StatusPill,
  formatTime,
  messageOf,
  type Tone,
} from './controls';
import VolunteerMap from './VolunteerMap';
import VolunteerPanel from './VolunteerPanel';

type Choice = 'ignore' | 'team' | 'volunteers' | 'drone';

const CHOICES: { key: Choice; label: string; hint: string }[] = [
  { key: 'ignore', label: 'Ignore', hint: 'Close with a reason' },
  { key: 'team', label: 'Send a team', hint: 'Offer to a rescue centre' },
  { key: 'volunteers', label: 'Send volunteers', hint: 'Ask nearby volunteers' },
  { key: 'drone', label: 'Send a drone', hint: 'Plan a survey (simulation)' },
];

const CLOSED = new Set(['resolved', 'cancelled', 'guidance_only']);
const CLOSED_LABEL: Record<string, string> = {
  resolved: 'Resolved',
  cancelled: 'Ignored (cancelled)',
  guidance_only: 'Ignored (guidance only)',
};

function suggested(severity: string | null): Choice | null {
  if (severity === 'critical' || severity === 'respond') return 'team';
  if (severity === 'monitor') return 'volunteers';
  if (severity === 'guidance') return 'ignore';
  return null;
}

export default function DecisionPanel({
  incident,
  actor,
  onChanged,
}: {
  incident: IncidentDetail;
  actor: string;
  onChanged: () => void;
}) {
  const incidentId = incident.incident_id;
  const [choice, setChoice] = useState<Choice | null>(null);
  const [log, setLog] = useState<DecisionEntry[]>([]);
  const closed = CLOSED.has(incident.status);
  const hint = suggested(incident.severity_level);

  const refreshLog = useCallback(() => {
    coordinator.decisions(incidentId).then(setLog).catch(() => undefined);
  }, [incidentId]);
  useEffect(refreshLog, [refreshLog]);

  const changed = useCallback(() => {
    refreshLog();
    onChanged();
  }, [refreshLog, onChanged]);

  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>Decide</Text>
      <Text style={styles.title}>What happens to this report?</Text>
      {closed && (
        <Text style={styles.closed}>
          {CLOSED_LABEL[incident.status] ?? 'Closed'}. Actions are disabled; the log below
          shows what was decided.
        </Text>
      )}

      <View style={styles.choices}>
        {CHOICES.map(({ key, label, hint: subtitle }) => {
          const active = choice === key;
          return (
            <Pressable
              key={key}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              onPress={() => setChoice(active ? null : key)}
              style={[styles.choice, active && styles.choiceActive]}
            >
              <Text style={[styles.choiceLabel, active && styles.choiceLabelActive]}>
                {label}
              </Text>
              <Text style={styles.choiceHint}>{subtitle}</Text>
              {hint === key && !closed && (
                <Text style={styles.suggested}>
                  Suggested for {incident.severity_level}
                </Text>
              )}
            </Pressable>
          );
        })}
      </View>

      {choice === 'ignore' && (
        <IgnorePanel incidentId={incidentId} actor={actor} closed={closed} onChanged={changed} />
      )}
      {choice === 'team' && (
        <TeamPanel incident={incident} actor={actor} closed={closed} onChanged={changed} />
      )}
      {choice === 'volunteers' && (
        <VolunteerPanel incident={incident} actor={actor} closed={closed} onChanged={changed} />
      )}
      {choice === 'drone' && (
        <DronePanel incident={incident} actor={actor} closed={closed} onChanged={changed} />
      )}

      {log.length > 0 && (
        <View style={styles.log}>
          <Text style={styles.eyebrow}>Decision log</Text>
          {log.map((entry) => (
            <Text key={entry.event_id} style={styles.logLine}>
              <Text style={styles.logTime}>{formatTime(entry.recorded_at)} </Text>
              {entry.summary}
            </Text>
          ))}
        </View>
      )}
    </View>
  );
}

// --- 1. Ignore ----------------------------------------------------------------

const REASONS: { key: IgnoreReason; label: string }[] = [
  { key: 'false_report', label: 'False report' },
  { key: 'healthy_animal', label: 'Healthy animal' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'animal_left', label: 'Animal has left' },
  { key: 'out_of_area', label: 'Outside our area' },
  { key: 'other', label: 'Other' },
];

function IgnorePanel({
  incidentId,
  actor,
  closed,
  onChanged,
}: {
  incidentId: string;
  actor: string;
  closed: boolean;
  onChanged: () => void;
}) {
  const [reason, setReason] = useState<IgnoreReason | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await coordinator.ignore(incidentId, reason, note, actor);
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.panel}>
      <Text style={styles.muted}>
        Closes the case. "Healthy animal" marks it guidance-only; every other reason
        cancels it. Volunteer alerts still waiting on a reply are stood down, but
        anyone who already checked in is on their way: tell them directly.
      </Text>
      <View style={styles.wrapRow}>
        {REASONS.map((r) => (
          <Chip
            key={r.key}
            label={r.label}
            active={reason === r.key}
            disabled={closed}
            onPress={() => setReason(r.key)}
          />
        ))}
      </View>
      <TextInput
        style={styles.input}
        placeholder="Optional note for the log"
        placeholderTextColor={colors.textFaint}
        maxLength={300}
        value={note}
        onChangeText={setNote}
        editable={!closed}
      />
      <ActionButton
        kind="danger"
        label="Ignore this report"
        disabled={!reason || closed}
        busy={busy}
        onPress={() => void confirm()}
      />
      <ErrorLine message={error} />
    </View>
  );
}

// --- 2. Send a team --------------------------------------------------------------

const OFFER_STATUS: Record<string, { label: string; tone: Tone }> = {
  offered: { label: 'Offered, awaiting answer', tone: 'warning' },
  accepted: { label: 'Accepted', tone: 'success' },
  en_route: { label: 'En route', tone: 'success' },
  on_scene: { label: 'On scene', tone: 'success' },
  declined: { label: 'Declined', tone: 'muted' },
  completed: { label: 'Completed', tone: 'muted' },
};
const OPEN_OFFERS = new Set(['offered', 'accepted', 'en_route', 'on_scene']);

function TeamPanel({
  incident,
  actor,
  closed,
  onChanged,
}: {
  incident: IncidentDetail;
  actor: string;
  closed: boolean;
  onChanged: () => void;
}) {
  const incidentId = incident.incident_id;
  const [offers, setOffers] = useState<AssignmentRecord[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    coordinator.assignments(incidentId).then(setOffers).catch((e) => setError(messageOf(e)));
  }, [incidentId]);
  useEffect(load, [load]);

  async function act(key: string, run: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await run();
      load();
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(null);
    }
  }

  const openFor = new Set(
    offers.filter((o) => OPEN_OFFERS.has(o.status)).map((o) => o.responder_id),
  );

  return (
    <View style={styles.panel}>
      <Text style={styles.muted}>
        An offer is not an acceptance. Record the team's answer when they confirm.
      </Text>
      {incident.dispatch_candidates.length === 0 && (
        <Text style={styles.muted}>
          No team matched this report's area and animal. Matching runs when intake
          finishes.
        </Text>
      )}
      {incident.dispatch_candidates.map((candidate) => (
        <View key={candidate.responder_id} style={styles.item}>
          <View style={styles.itemText}>
            <Text style={styles.name}>
              {candidate.name}
              <Text style={styles.muted}>
                {'  '}match {candidate.score.toFixed(2)}
                {candidate.distance_km !== null ? ` · ${candidate.distance_km} km` : ''}
                {candidate.eta_minutes !== null ? ` · ~${candidate.eta_minutes} min` : ''}
              </Text>
            </Text>
            <Text style={styles.faint} numberOfLines={3}>
              {candidate.rationale}
            </Text>
          </View>
          {openFor.has(candidate.responder_id) ? (
            <StatusPill label="Offered" tone="warning" />
          ) : (
            <ActionButton
              label="Offer case"
              kind="primary"
              disabled={closed}
              busy={busy === `offer:${candidate.responder_id}`}
              onPress={() =>
                void act(`offer:${candidate.responder_id}`, () =>
                  coordinator.offerTeam(incidentId, candidate, actor),
                )
              }
            />
          )}
        </View>
      ))}

      {offers.length > 0 && <Text style={styles.eyebrow}>Offers</Text>}
      {offers.map((offer) => {
        const status = OFFER_STATUS[offer.status] ?? { label: offer.status, tone: 'muted' };
        return (
          <View key={offer.assignment_id} style={styles.item}>
            <View style={styles.itemText}>
              <Text style={styles.name}>{offer.responder_name ?? offer.responder_id}</Text>
              <Text style={styles.faint}>Offered {formatTime(offer.offered_at)}</Text>
            </View>
            {offer.status === 'offered' && !closed ? (
              <View style={styles.wrapRow}>
                <ActionButton
                  label="Team accepted"
                  busy={busy === `yes:${offer.assignment_id}`}
                  onPress={() =>
                    void act(`yes:${offer.assignment_id}`, () =>
                      coordinator.teamReply(offer.assignment_id, true),
                    )
                  }
                />
                <ActionButton
                  label="Declined"
                  busy={busy === `no:${offer.assignment_id}`}
                  onPress={() =>
                    void act(`no:${offer.assignment_id}`, () =>
                      coordinator.teamReply(offer.assignment_id, false),
                    )
                  }
                />
              </View>
            ) : (
              <StatusPill label={status.label} tone={status.tone} />
            )}
          </View>
        );
      })}
      <ErrorLine message={error} />
    </View>
  );
}

// --- 4. Send a drone (simulation) ----------------------------------------------

function DronePanel({
  incident,
  actor,
  closed,
  onChanged,
}: {
  incident: IncidentDetail;
  actor: string;
  closed: boolean;
  onChanged: () => void;
}) {
  const [plan, setPlan] = useState<DroneSurvey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function planSurvey() {
    setBusy(true);
    setError(null);
    try {
      setPlan(await coordinator.droneSurvey(incident.incident_id, actor));
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.panel}>
      <Text style={styles.muted}>
        Plans a survey grid over the animal with LifeJacket's drone planner, inside its
        server-side safety limits. Simulation only: nothing is sent to an aircraft.
      </Text>
      <ActionButton
        label={plan ? 'Plan again' : 'Plan survey flight'}
        kind="primary"
        disabled={closed}
        busy={busy}
        onPress={() => void planSurvey()}
      />
      {plan && (
        <>
          <View style={styles.wrapRow}>
            <StatusPill
              label={plan.status === 'ready_for_review' ? 'Ready for review' : 'Blocked'}
              tone={plan.status === 'ready_for_review' ? 'success' : 'danger'}
            />
            <StatusPill label="Simulation" tone="accent" />
          </View>
          <View style={styles.stats}>
            <Stat label="Route" value={plan.distance_m !== null ? `${(plan.distance_m / 1000).toFixed(1)} km` : '—'} />
            <Stat label="Flight" value={plan.duration_s !== null ? `${Math.round(plan.duration_s / 60)} min` : '—'} />
            <Stat
              label="Battery left"
              value={
                plan.estimated_battery_remaining_percent !== null
                  ? `${Math.round(plan.estimated_battery_remaining_percent)}%`
                  : '—'
              }
            />
            <Stat label="Altitude" value={`${plan.altitude_m} m`} />
            <Stat label="Waypoints" value={String(plan.waypoint_count)} />
          </View>
          {plan.blocked_reasons.map((reason) => (
            <Text key={reason} style={styles.reason}>
              {reason}
            </Text>
          ))}
          <Text style={styles.faint}>{plan.launch_note}</Text>
          {incident.latitude !== null && incident.longitude !== null && (
            <VolunteerMap
              incident={{
                latitude: incident.latitude,
                longitude: incident.longitude,
                label: incident.species_common_name ?? 'Reported animal',
              }}
              volunteers={[]}
              selected={NO_SELECTION}
              onToggle={IGNORE_TOGGLE}
              survey={plan}
              height={240}
            />
          )}
        </>
      )}
      <ErrorLine message={error} />
    </View>
  );
}

const NO_SELECTION: ReadonlySet<string> = new Set();
const IGNORE_TOGGLE = () => undefined;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    ...glass,
    ...shadow.soft,
    padding: spacing.lg,
    gap: spacing.md,
    borderColor: colors.borderStrong,
  },
  eyebrow: { ...type.eyebrow, color: colors.textFaint },
  title: { ...type.heading, color: colors.text },
  closed: { ...type.meta, color: colors.warning },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  choice: {
    ...glass,
    flexGrow: 1,
    flexBasis: 150,
    padding: spacing.md,
    gap: 2,
  },
  choiceActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  choiceLabel: { ...type.label, color: colors.text },
  choiceLabelActive: { color: colors.accent },
  choiceHint: { ...type.meta, fontSize: 12, color: colors.textMuted },
  suggested: { ...type.meta, fontSize: 11, fontWeight: '700', color: colors.accent, marginTop: 2 },
  panel: { gap: spacing.md, paddingTop: spacing.xs },
  muted: { ...type.meta, color: colors.textMuted, fontWeight: '400' },
  faint: { ...type.meta, fontSize: 12, color: colors.textFaint },
  reason: { ...type.meta, color: colors.warning },
  wrapRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, alignItems: 'center' },
  input: {
    ...type.body,
    color: colors.text,
    padding: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.backgroundElevated,
  },
  item: {
    ...glass,
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.md,
    padding: spacing.md,
  },
  itemText: { flex: 1, minWidth: 200, gap: 2 },
  name: { ...type.label, color: colors.text },
  stats: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  stat: { ...glass, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, minWidth: 92 },
  statValue: { ...type.heading, color: colors.text },
  statLabel: { ...type.meta, fontSize: 11, color: colors.textFaint },
  log: {
    gap: spacing.xs,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  logLine: { ...type.meta, color: colors.textMuted },
  logTime: { color: colors.textFaint },
});
