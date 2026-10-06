/**
 * Incident detail: the generated report, navigation, and contacting the reporter.
 *
 * Three things here are deliberate:
 *
 * 1. **The review banner comes first.** If the guardrail agent found an
 *    unsupported claim or unsafe advice, the responder sees that *before* the
 *    report text, not buried under it.
 * 2. **Unknowns are shown, not hidden.** A responder who knows the tide was
 *    never checked plans differently from one who assumes it was fine.
 * 3. **Navigation hands off to the OS map app.** Turn-by-turn on a coast road
 *    is a solved problem, and Apple Maps and Google Maps both do it better
 *    than we would.
 */

import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {
  absoluteUrl,
  responder,
  severityColour,
  severityLabel,
  type IncidentDetail,
  type IncidentHealth,
} from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

export default function IncidentDetailScreen({
  incidentId,
  responderId,
  onLog,
  onBack,
}: {
  incidentId: string;
  responderId: string;
  onLog: (incidentId: string) => void;
  onBack: () => void;
}) {
  const [incident, setIncident] = useState<IncidentDetail | null>(null);
  const [expandedPhoto, setExpandedPhoto] = useState<string | null>(null);

  useEffect(() => {
    void responder.getIncident(incidentId).then(setIncident).catch(() => setIncident(null));
  }, [incidentId]);

  if (!incident) {
    return <ActivityIndicator style={styles.loading} size="large" color={colors.accent} />;
  }

  const { report } = incident;
  // Resolved out here rather than inside `navigate`, because TypeScript cannot
  // carry the null check above into a closure.
  const coordinates =
    incident.latitude !== null && incident.longitude !== null
      ? `${incident.latitude},${incident.longitude}`
      : null;

  /** Open the incident in the platform's native map app for driving directions. */
  function navigate() {
    if (!coordinates) return;
    const url =
      Platform.OS === 'ios'
        ? `http://maps.apple.com/?daddr=${coordinates}&dirflg=d`
        : `https://www.google.com/maps/dir/?api=1&destination=${coordinates}&travelmode=driving`;
    void Linking.openURL(url);
  }

  async function setStatus(status: string) {
    await responder.updateStatus(incidentId, status, responderId);
    setIncident(await responder.getIncident(incidentId));
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      <Pressable onPress={onBack}>
        <Text style={styles.back}>{'←'} All incidents</Text>
      </Pressable>

      {/* 1. Review banner, before anything else. */}
      {incident.requires_human_review && (
        <View style={styles.reviewBanner}>
          <Text style={styles.reviewTitle}>Held for coordinator review</Text>
          <Text style={styles.reviewBody}>
            {healthFindings(incident.health).length > 0
              ? 'Part of the automated intake did not complete. Check the findings and the transcript below before acting.'
              : 'An automated check flagged this report. Read it against the transcript below before acting on it.'}
          </Text>
          {renderFindings(healthFindings(incident.health))}
          {renderGuardrail(incident.guardrail)}
        </View>
      )}

      {/* 2. Scale. One animal and several need different responses, and this
          can become true after the incident was first opened, when someone
          else reports. Other incidents are listed so they are handled as one. */}
      {incident.mass_stranding && (
        <View style={styles.massBanner}>
          <Text style={styles.massTitle}>
            Possible mass stranding · at least {incident.mass_stranding.animal_count} animals
          </Text>
          <Text style={styles.reviewBody}>{incident.mass_stranding.reason}</Text>
          {otherIncidents(incident).length > 0 && (
            <Text style={styles.reviewBody}>
              Same event: {otherIncidents(incident).join(', ')}
            </Text>
          )}
        </View>
      )}

      {/* Retries that recovered need no action, but should not be invisible. */}
      {healthNote(incident.health) && (
        <Text style={styles.healthNote}>{healthNote(incident.health)}</Text>
      )}

      <View style={[styles.severity, { backgroundColor: severityColour(incident.severity_level) }]}>
        <Text style={styles.severityText}>
          {severityLabel(incident.severity_level)}
          {incident.severity_score !== null ? ` · score ${incident.severity_score}` : ''}
        </Text>
      </View>

      <Text style={styles.headline}>
        {report?.headline ?? incident.species_common_name ?? 'Unidentified animal'}
      </Text>

      <Text style={styles.meta}>
        {incident.species_common_name ?? 'Species unidentified'}
        {incident.species_confidence !== null
          ? ` (confidence ${incident.species_confidence.toFixed(2)})`
          : ''}
        {incident.place_name ? ` · ${incident.place_name}` : ''}
      </Text>

      {/* When identification stopped at genus or family level, show the
          species it could be. Responders bring different gear for each. */}
      {incident.taxon_rank && incident.taxon_rank !== 'species' && (
        <Text style={styles.rank}>
          Identified to {incident.taxon_rank} level -- confirm species on arrival.
        </Text>
      )}
      {incident.species_candidates.length > 1 && (
        <View style={styles.probabilities}>
          {incident.species_candidates.map((s) => (
            <Text key={s.common_name} style={styles.probability}>
              {s.common_name} {'\u00b7'} {(s.confidence * 100).toFixed(0)}%
            </Text>
          ))}
        </View>
      )}

      {/* The evidence, next to the conclusions drawn from it. A responder
          deciding whether to drive two hours wants to judge the animal
          themselves, not only read what the agent made of it. */}
      {incident.photos.length > 0 && (
        <Section title={incident.photos.length === 1 ? 'Photo' : 'Photos'}>
          <Pressable
            onPress={() =>
              setExpandedPhoto((current) =>
                current === incident.photos[0].photo_id
                  ? null
                  : incident.photos[0].photo_id,
              )
            }
          >
            <Image
              source={{ uri: absoluteUrl(expandedUrl(incident, expandedPhoto)) as string }}
              style={styles.photo}
              resizeMode="cover"
            />
          </Pressable>

          {incident.photos.length > 1 && (
            <View style={styles.photoStrip}>
              {incident.photos.map((photo) => (
                <Pressable
                  key={photo.photo_id}
                  onPress={() => setExpandedPhoto(photo.photo_id)}
                >
                  <Image
                    source={{ uri: absoluteUrl(photo.url) as string }}
                    style={[
                      styles.photoThumb,
                      photo.photo_id === (expandedPhoto ?? incident.photos[0].photo_id) &&
                        styles.photoThumbActive,
                    ]}
                  />
                </Pressable>
              ))}
            </View>
          )}

          <Text style={styles.photoNote}>
            Sent by the reporter. This is what the identification agent saw.
          </Text>
        </Section>
      )}

      {incident.duplicate_of && (
        <Text style={styles.duplicate}>
          Linked as a duplicate of {incident.duplicate_of}. Not dispatched separately.
        </Text>
      )}

      {/* Same place and time as another report, different animal group. The
          system will not merge those, so this was dispatched normally and a
          person decides. */}
      {incident.possible_duplicate && (
        <Text style={styles.duplicate}>
          Possible duplicate of {incident.possible_duplicate.incident_id} (
          {incident.possible_duplicate.reason}). Check before sending a second team.
        </Text>
      )}

      <View style={styles.buttonRow}>
        {coordinates && (
          <Pressable style={styles.primary} onPress={navigate}>
            <Text style={styles.primaryText}>Navigate</Text>
          </Pressable>
        )}
        {incident.reporter_phone && (
          <Pressable
            style={styles.secondary}
            onPress={() => void Linking.openURL(`tel:${incident.reporter_phone}`)}
          >
            <Text style={styles.secondaryText}>Call reporter</Text>
          </Pressable>
        )}
      </View>

      {report && (
        <>
          <Section title="Summary">
            <Text style={styles.body}>{report.summary}</Text>
          </Section>

          <Section title="Recommended actions">
            {report.recommended_actions.map((action, i) => (
              <Text key={i} style={styles.bullet}>
                {i + 1}. {action}
              </Text>
            ))}
          </Section>

          {report.hazard_warnings.length > 0 && (
            <Section title="Hazards">
              {report.hazard_warnings.map((hazard, i) => (
                <Text key={i} style={[styles.bullet, styles.hazard]}>
                  {'•'} {hazard}
                </Text>
              ))}
            </Section>
          )}

          {report.equipment_suggestions.length > 0 && (
            <Section title="Equipment">
              {report.equipment_suggestions.map((item, i) => (
                <Text key={i} style={styles.bullet}>
                  {'•'} {item}
                </Text>
              ))}
            </Section>
          )}

          {report.access_notes && (
            <Section title="Access">
              <Text style={styles.body}>{report.access_notes}</Text>
            </Section>
          )}

          {/* 2. Unknowns, shown as plainly as the findings. */}
          {report.unknowns.length > 0 && (
            <Section title="Not established">
              {report.unknowns.map((unknown, i) => (
                <Text key={i} style={[styles.bullet, styles.unknown]}>
                  {'•'} {unknown}
                </Text>
              ))}
            </Section>
          )}
        </>
      )}

      {incident.severity_reasons.length > 0 && (
        <Section title="Why this triage level">
          {incident.severity_reasons.map((reason, i) => (
            <Text key={i} style={styles.bullet}>
              {'•'} {reason}
            </Text>
          ))}
        </Section>
      )}

      <Section title="What the reporter said">
        {incident.transcript.map((turn, i) => (
          <Text key={i} style={styles.transcriptLine}>
            <Text style={styles.transcriptRole}>{turn.role}: </Text>
            {turn.content}
          </Text>
        ))}
      </Section>

      {incident.dispatch_candidates.length > 0 && (
        <Section title="Suggested responders">
          {incident.dispatch_candidates.map((candidate) => (
            <View key={candidate.responder_id} style={styles.candidate}>
              <Text style={styles.candidateName}>
                {candidate.name} ({candidate.score.toFixed(2)})
              </Text>
              <Text style={styles.candidateWhy}>{candidate.rationale}</Text>
            </View>
          ))}
        </Section>
      )}

      <View style={styles.buttonRow}>
        <Pressable style={styles.secondary} onPress={() => void setStatus('en_route')}>
          <Text style={styles.secondaryText}>En route</Text>
        </Pressable>
        <Pressable style={styles.secondary} onPress={() => void setStatus('on_scene')}>
          <Text style={styles.secondaryText}>On scene</Text>
        </Pressable>
        <Pressable style={styles.primary} onPress={() => onLog(incidentId)}>
          <Text style={styles.primaryText}>Log outcome</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

/** URL of the photo currently shown large: the chosen one, else the first. */
function expandedUrl(incident: IncidentDetail, expandedId: string | null): string {
  const chosen = incident.photos.find((p) => p.photo_id === expandedId);
  return (chosen ?? incident.photos[0]).url;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

/** The other incidents in this one's mass stranding, if it is part of one. */
function otherIncidents(incident: IncidentDetail): string[] {
  return (incident.mass_stranding?.incident_ids ?? []).filter(
    (id) => id !== incident.incident_id,
  );
}

/**
 * Model failures that were NOT recovered from, in a coordinator's words.
 *
 * These are why an incident can be held for review with no guardrail findings:
 * the check never ran, the report was never written, or intake stalled.
 */
function healthFindings(health: IncidentHealth | null): string[] {
  if (!health) return [];

  const findings: string[] = [];
  if (health.fallbacks.includes('report_unavailable')) {
    findings.push(
      'The written report could not be generated. Severity and findings below come from the assessment.',
    );
  }
  if (health.fallbacks.includes('guardrail_check_failed')) {
    findings.push('The safety check on this report could not run, so it is unverified.');
  }
  if (health.awaiting_retry) {
    const last = health.failures[health.failures.length - 1];
    findings.push(
      `Intake stalled${last ? ` at ${last.agent}` : ''}: the reporter was asked to try again and has not yet. Consider calling them.`,
    );
  }
  return findings;
}

/** One quiet line when model calls were retried or failed, e.g. for a slow day on Vertex. */
function healthNote(health: IncidentHealth | null): string | null {
  if (!health || (health.llm_retries === 0 && health.failed_calls === 0)) return null;
  return (
    `Model calls: ${health.llm_calls} · retried ${health.llm_retries}` +
    (health.failed_calls > 0 ? ` · failed ${health.failed_calls}` : '')
  );
}

function renderFindings(findings: string[]) {
  if (findings.length === 0) return null;

  return (
    <View style={styles.findings}>
      {findings.map((finding, i) => (
        <Text key={i} style={styles.finding}>
          {'•'} {finding}
        </Text>
      ))}
    </View>
  );
}

/** Show what the guardrail check actually objected to, not just that it failed. */
function renderGuardrail(guardrail: Record<string, unknown> | null) {
  if (!guardrail) return null;

  const findings = [
    ...((guardrail.unsafe_advice as string[]) ?? []).map((t) => `Unsafe: ${t}`),
    ...((guardrail.unsupported_claims as string[]) ?? []).map((t) => `Unsupported: ${t}`),
    ...((guardrail.missing_critical_content as string[]) ?? []).map((t) => `Missing: ${t}`),
  ];
  if (findings.length === 0) return null;

  return (
    <View style={styles.findings}>
      {findings.map((finding, i) => (
        <Text key={i} style={styles.finding}>
          {'•'} {finding}
        </Text>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: {
    padding: spacing.lg,
    gap: spacing.md,
    maxWidth: 780,
    alignSelf: 'center',
    width: '100%',
  },
  loading: { flex: 1 },
  back: { ...type.label, color: colors.accent },

  reviewBanner: {
    ...glass,
    ...shadow.soft,
    backgroundColor: 'rgba(255, 192, 67, 0.10)',
    borderColor: 'rgba(255, 192, 67, 0.35)',
    borderLeftWidth: 3,
    borderLeftColor: colors.warning,
    padding: spacing.md,
  },
  massBanner: {
    ...glass,
    ...shadow.soft,
    borderLeftWidth: 3,
    borderLeftColor: colors.danger,
    padding: spacing.md,
    gap: spacing.xs,
  },
  massTitle: { ...type.label, color: colors.danger },
  reviewTitle: { ...type.label, color: colors.warning, marginBottom: spacing.xs },
  reviewBody: { ...type.meta, color: colors.textMuted, lineHeight: 19 },
  findings: { marginTop: spacing.sm, gap: 3 },
  finding: { ...type.meta, fontSize: 12.5, color: colors.warning, lineHeight: 18 },
  healthNote: { ...type.meta, fontSize: 12.5, color: colors.textMuted },

  severity: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
    borderRadius: radius.pill,
  },
  severityText: { ...type.eyebrow, fontSize: 11, color: colors.onAccent },
  headline: { ...type.display, color: colors.text, lineHeight: 32 },
  meta: { ...type.meta, color: colors.textMuted },
  duplicate: { ...type.meta, color: colors.warning, fontStyle: 'italic' },
  rank: { ...type.meta, color: colors.warning },
  probabilities: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  probability: { ...type.meta, color: colors.textMuted },

  photo: {
    width: '100%',
    height: 340,
    borderRadius: radius.sm,
    backgroundColor: colors.glassFill,
  },
  photoStrip: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  photoThumb: {
    width: 56,
    height: 56,
    borderRadius: radius.sm,
    borderWidth: 2,
    borderColor: 'transparent',
    backgroundColor: colors.glassFill,
  },
  photoThumbActive: { borderColor: colors.accent },
  photoNote: { ...type.meta, fontSize: 12, color: colors.textFaint, marginTop: spacing.xs },

  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    flexWrap: 'wrap',
    marginVertical: spacing.xs,
  },
  primary: {
    ...shadow.soft,
    backgroundColor: colors.accent,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    borderRadius: radius.card,
  },
  primaryText: { ...type.label, color: colors.onAccent, fontSize: 15 },
  secondary: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.glassFill,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    borderRadius: radius.card,
  },
  secondaryText: { ...type.label, color: colors.text, fontSize: 15 },

  section: {
    ...glass,
    gap: spacing.xs + 1,
    marginTop: spacing.sm,
    padding: spacing.md,
  },
  sectionTitle: { ...type.eyebrow, color: colors.accent },
  body: { ...type.body, color: colors.text, lineHeight: 22 },
  bullet: { ...type.body, color: colors.text, lineHeight: 22 },
  hazard: { color: colors.danger },
  unknown: { color: colors.textFaint, fontStyle: 'italic' },
  transcriptLine: { ...type.meta, color: colors.textMuted, lineHeight: 20 },
  transcriptRole: { fontWeight: '700', color: colors.text, textTransform: 'capitalize' },
  candidate: { paddingVertical: spacing.xs + 2 },
  candidateName: { ...type.label, color: colors.text, fontSize: 15 },
  candidateWhy: { ...type.meta, fontSize: 12.5, color: colors.textFaint, lineHeight: 18 },
});
