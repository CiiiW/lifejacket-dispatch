/**
 * Send volunteers: see who is near the incident, alert them, record replies.
 *
 * The rules come from `docs/reporter_participation.md`, and the API enforces
 * them; this panel explains them:
 *
 * - An alert is an invitation, not an assignment. With no SMS provider set
 *   up, nothing is actually sent ("simulated"), and a reply is recorded here
 *   by whoever received it.
 * - Watching from a distance (monitor cases) is open to any volunteer.
 *   Hands-on support (respond and critical) needs a trained responder, and
 *   supports a team rather than replacing one.
 * - Only volunteers near this incident are shown, never their numbers.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import {
  coordinator,
  type IncidentDetail,
  type NearbyVolunteer,
  type NearbyVolunteers,
  type VolunteerAlert,
  type VolunteerSummary,
} from '../lib/api';
import { colors, glass, radius, spacing, type } from '../lib/theme';
import {
  ActionButton,
  ErrorLine,
  StatusPill,
  formatTime,
  messageOf,
  type Tone,
} from './controls';
import VolunteerMap from './VolunteerMap';
import { volunteerTone } from './volunteerMapShared';

const ALERT_STATUS: Record<VolunteerAlert['status'], { label: string; tone: Tone }> = {
  awaiting_reply: { label: 'Awaiting reply', tone: 'warning' },
  checked_in: { label: 'Checked in', tone: 'success' },
  declined: { label: "Can't go", tone: 'muted' },
  cancelled: { label: 'Stood down', tone: 'muted' },
};

const MAX_ALERT_CHARS = 480;

/** The text the volunteers would get. Safety lines are never optional. */
function draftMessage(incident: IncidentDetail, task: NearbyVolunteers['task']): string {
  const animal = incident.species_common_name ?? 'an animal in trouble';
  const place = incident.place_name ?? 'a beach near you';
  return task === 'observe'
    ? `LifeJacket volunteer alert: ${animal} reported at ${place}. Could you watch it ` +
        'from a safe distance (at least 50 yards), keep people and dogs back, and report ' +
        "any changes? Never touch or move it. Reply YES if you can go, NO if you can't."
    : `LifeJacket volunteer alert: ${animal} at ${place} needs a rescue team, which ` +
        'could use a trained volunteer to support it on arrival. Do not approach the ' +
        "animal before the team arrives. Reply YES if you can go, NO if you can't.";
}

function alertOpen(volunteer: NearbyVolunteer): boolean {
  return volunteer.alert?.status === 'awaiting_reply' || volunteer.alert?.status === 'checked_in';
}

export default function VolunteerPanel({
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
  const [nearby, setNearby] = useState<NearbyVolunteers | null>(null);
  const [alerts, setAlerts] = useState<VolunteerAlert[]>([]);
  const [roster, setRoster] = useState<VolunteerSummary | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [found, sent, summary] = await Promise.all([
      coordinator.volunteers(incidentId),
      coordinator.alerts(incidentId),
      coordinator.volunteerSummary(),
    ]);
    setNearby(found);
    setAlerts(sent);
    setRoster(summary);
    // Draft once, so a coordinator's edits are not overwritten on reload.
    setMessage((current) => current ?? draftMessage(incident, found.task));
  }, [incidentId, incident]);

  useEffect(() => {
    load().catch((e) => setError(messageOf(e)));
  }, [load]);

  const toggle = useCallback((volunteerId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(volunteerId)) next.delete(volunteerId);
      else next.add(volunteerId);
      return next;
    });
  }, []);

  const volunteers = nearby?.volunteers ?? [];
  const selectable = useMemo(
    () => volunteers.filter((v) => v.eligible && !alertOpen(v)),
    [volunteers],
  );
  const alerted = volunteers.filter((v) => v.alert && !selectable.includes(v));
  const unavailable = volunteers.filter((v) => !v.eligible && !v.alert);

  async function act(key: string, run: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await run();
      await load();
      onChanged();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(null);
    }
  }

  function send() {
    void act('send', async () => {
      await coordinator.sendAlerts(incidentId, [...selected], (message ?? '').trim(), actor);
      setSelected(new Set());
    });
  }

  if (roster && roster.total === 0) {
    return (
      <View style={styles.block}>
        <Text style={styles.heading}>No volunteers loaded</Text>
        <Text style={styles.muted}>
          Load the fictional demo roster: 25 invented volunteers across California, with
          555-01xx phone numbers (reserved for fiction) and street-level base areas.
        </Text>
        <ActionButton
          label="Load fictional demo volunteers"
          kind="primary"
          busy={busy === 'seed'}
          onPress={() => void act('seed', () => coordinator.seedVolunteers())}
        />
        <ErrorLine message={error} />
      </View>
    );
  }

  if (incident.latitude === null || incident.longitude === null) {
    return (
      <View style={styles.block}>
        <Text style={styles.muted}>
          This report has no location yet, so there is nobody to find nearby.
        </Text>
      </View>
    );
  }

  const checkedIn = alerts.filter((a) => a.status === 'checked_in').length;
  const waiting = alerts.filter((a) => a.status === 'awaiting_reply').length;

  return (
    <View style={styles.block}>
      {nearby && (
        <View style={styles.task}>
          <Text style={styles.eyebrow}>
            {nearby.task === 'observe' ? 'Task: watch' : 'Task: support a team'}
          </Text>
          <Text style={styles.body}>{nearby.task_description}</Text>
        </View>
      )}

      <VolunteerMap
        incident={{
          latitude: incident.latitude,
          longitude: incident.longitude,
          label: incident.species_common_name ?? 'Reported animal',
        }}
        volunteers={volunteers}
        selected={selected}
        onToggle={toggle}
      />

      <View style={styles.rowBetween}>
        <Text style={styles.heading}>
          {selectable.length} can be alerted
          <Text style={styles.muted}>
            {' '}· within {nearby?.search_radius_km ?? 60} km, nearest first
          </Text>
        </Text>
        {selectable.length > 0 && (
          <Pressable
            onPress={() =>
              setSelected(new Set(selectable.slice(0, 3).map((v) => v.volunteer_id)))
            }
          >
            <Text style={styles.link}>Select nearest 3</Text>
          </Pressable>
        )}
      </View>

      {selectable.map((v) => (
        <VolunteerRow
          key={v.volunteer_id}
          volunteer={v}
          selected={selected.has(v.volunteer_id)}
          onPress={closed ? undefined : () => toggle(v.volunteer_id)}
        />
      ))}
      {alerted.map((v) => (
        <VolunteerRow key={v.volunteer_id} volunteer={v} selected={false} />
      ))}

      {unavailable.length > 0 && (
        <Pressable onPress={() => setShowUnavailable((s) => !s)}>
          <Text style={styles.link}>
            {showUnavailable ? 'Hide' : 'Show'} {unavailable.length} not available for this task
          </Text>
        </Pressable>
      )}
      {showUnavailable &&
        unavailable.map((v) => <VolunteerRow key={v.volunteer_id} volunteer={v} selected={false} />)}

      {selected.size > 0 && !closed && (
        <View style={styles.compose}>
          <Text style={styles.eyebrow}>Alert text</Text>
          <TextInput
            style={styles.input}
            multiline
            maxLength={MAX_ALERT_CHARS}
            value={message ?? ''}
            onChangeText={setMessage}
            placeholderTextColor={colors.textFaint}
          />
          <Text style={styles.faint}>
            {(message ?? '').length}/{MAX_ALERT_CHARS} · Simulated: these volunteers are
            fictional, so no text is sent.
          </Text>
          <ActionButton
            kind="primary"
            label={`Send alert to ${selected.size} volunteer${selected.size === 1 ? '' : 's'}`}
            busy={busy === 'send'}
            disabled={!(message ?? '').trim()}
            onPress={send}
          />
        </View>
      )}

      {alerts.length > 0 && (
        <View style={styles.alerts}>
          <Text style={styles.eyebrow}>
            Alerts sent · {checkedIn} checked in · {waiting} awaiting reply
          </Text>
          {alerts.map((alert) => {
            const status = ALERT_STATUS[alert.status];
            return (
              <View key={alert.alert_id} style={styles.alertRow}>
                <View style={styles.alertText}>
                  <Text style={styles.name}>
                    {alert.volunteer_name}
                    <Text style={styles.muted}>
                      {'  '}••{alert.phone_last4}
                      {alert.distance_km !== null ? ` · ${alert.distance_km} km` : ''}
                    </Text>
                  </Text>
                  <Text style={styles.faint}>
                    Sent {formatTime(alert.sent_at)} (simulated)
                    {alert.responded_at ? ` · replied ${formatTime(alert.responded_at)}` : ''}
                  </Text>
                </View>
                {alert.status === 'awaiting_reply' && !closed ? (
                  <View style={styles.replyButtons}>
                    <ActionButton
                      label="Checked in"
                      busy={busy === `in:${alert.alert_id}`}
                      onPress={() =>
                        void act(`in:${alert.alert_id}`, () =>
                          coordinator.recordReply(alert.alert_id, 'checked_in', actor),
                        )
                      }
                    />
                    <ActionButton
                      label="Can't go"
                      busy={busy === `no:${alert.alert_id}`}
                      onPress={() =>
                        void act(`no:${alert.alert_id}`, () =>
                          coordinator.recordReply(alert.alert_id, 'declined', actor),
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
        </View>
      )}

      <ErrorLine message={error} />
    </View>
  );
}

function VolunteerRow({
  volunteer,
  selected,
  onPress,
}: {
  volunteer: NearbyVolunteer;
  selected: boolean;
  onPress?: () => void;
}) {
  const tone = volunteerTone(volunteer, selected);
  const trained = volunteer.qualification === 'trained_responder';
  // An awaiting or accepted alert is shown as status; a past "can't go" or a
  // stand-down leaves the volunteer selectable again.
  const open = alertOpen(volunteer);
  return (
    <Pressable
      accessibilityRole={onPress ? 'checkbox' : undefined}
      accessibilityState={onPress ? { checked: selected } : undefined}
      disabled={!onPress}
      onPress={onPress}
      style={[styles.row, selected && styles.rowSelected]}
    >
      <View style={[styles.dot, { backgroundColor: tone.fill, borderColor: tone.border }]} />
      <View style={styles.rowText}>
        <Text style={styles.name}>
          {volunteer.name}
          <Text style={styles.muted}>
            {'  '}
            {volunteer.distance_km} km · {trained ? 'Trained responder' : 'Observer'}
          </Text>
        </Text>
        <Text style={styles.faint}>
          {volunteer.address}
          {volunteer.skills.length ? ` · ${volunteer.skills.join(', ')}` : ''}
        </Text>
        {!volunteer.eligible && !volunteer.alert && (
          <Text style={styles.reason}>{volunteer.ineligible_reason}</Text>
        )}
        {volunteer.alert && !open && onPress && (
          <Text style={styles.faint}>
            Last alert: {ALERT_STATUS[volunteer.alert.status].label}
          </Text>
        )}
      </View>
      {volunteer.alert && (open || !onPress) ? (
        <StatusPill
          label={ALERT_STATUS[volunteer.alert.status].label}
          tone={ALERT_STATUS[volunteer.alert.status].tone}
        />
      ) : onPress ? (
        <View style={[styles.check, selected && styles.checkOn]}>
          {selected && <Text style={styles.checkMark}>✓</Text>}
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  block: { gap: spacing.md },
  task: { ...glass, padding: spacing.md, gap: spacing.xs },
  eyebrow: { ...type.eyebrow, color: colors.textFaint },
  heading: { ...type.label, color: colors.text },
  body: { ...type.body, color: colors.text },
  muted: { ...type.meta, color: colors.textMuted, fontWeight: '400' },
  faint: { ...type.meta, fontSize: 12, color: colors.textFaint },
  reason: { ...type.meta, fontSize: 12, color: colors.warning },
  link: { ...type.meta, color: colors.accent, fontWeight: '600' },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  row: {
    ...glass,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  rowSelected: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  dot: { width: 12, height: 12, borderRadius: 6, borderWidth: 2 },
  rowText: { flex: 1, gap: 2 },
  name: { ...type.label, color: colors.text },
  check: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.borderStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkOn: { borderColor: colors.accent, backgroundColor: colors.accent },
  checkMark: { color: colors.onAccent, fontWeight: '800', fontSize: 13 },
  compose: { ...glass, padding: spacing.md, gap: spacing.sm },
  input: {
    ...type.body,
    color: colors.text,
    minHeight: 96,
    padding: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.backgroundElevated,
    textAlignVertical: 'top',
  },
  alerts: { gap: spacing.sm },
  alertRow: {
    ...glass,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    flexWrap: 'wrap',
  },
  alertText: { flex: 1, minWidth: 180, gap: 2 },
  replyButtons: { flexDirection: 'row', gap: spacing.sm },
});
