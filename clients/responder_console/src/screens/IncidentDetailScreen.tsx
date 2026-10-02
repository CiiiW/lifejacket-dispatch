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
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {
  responder,
  severityColour,
  severityLabel,
  type IncidentDetail,
} from '../lib/api';

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

  useEffect(() => {
    void responder.getIncident(incidentId).then(setIncident).catch(() => setIncident(null));
  }, [incidentId]);

  if (!incident) return <ActivityIndicator style={styles.loading} size="large" />;

  const { report } = incident;
  const hasCoordinates = incident.latitude !== null && incident.longitude !== null;

  /** Open the incident in the platform's native map app for driving directions. */
  function navigate() {
    if (!hasCoordinates) return;
    const coords = `${incident.latitude},${incident.longitude}`;
    const url =
      Platform.OS === 'ios'
        ? `http://maps.apple.com/?daddr=${coords}&dirflg=d`
        : `https://www.google.com/maps/dir/?api=1&destination=${coords}&travelmode=driving`;
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
            An automated check flagged this report. Read it against the transcript
            below before acting on it.
          </Text>
          {renderGuardrail(incident.guardrail)}
        </View>
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

      {incident.duplicate_of && (
        <Text style={styles.duplicate}>
          Possible duplicate of {incident.duplicate_of}.
        </Text>
      )}

      <View style={styles.buttonRow}>
        {hasCoordinates && (
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
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
  screen: { flex: 1, backgroundColor: '#fff' },
  inner: { padding: 16, gap: 12, maxWidth: 760, alignSelf: 'center', width: '100%' },
  loading: { flex: 1 },
  back: { color: '#0b57d0', fontSize: 15, fontWeight: '500' },
  reviewBanner: {
    backgroundColor: '#fef7e0',
    borderLeftWidth: 4,
    borderLeftColor: '#f9ab00',
    padding: 12,
    borderRadius: 6,
  },
  reviewTitle: { fontWeight: '700', fontSize: 15, marginBottom: 4 },
  reviewBody: { fontSize: 14, lineHeight: 20, color: '#3c4043' },
  findings: { marginTop: 8, gap: 3 },
  finding: { fontSize: 13, color: '#8a5600', lineHeight: 18 },
  severity: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6 },
  severityText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  headline: { fontSize: 22, fontWeight: '700', lineHeight: 28 },
  meta: { fontSize: 14, color: '#5f6368' },
  duplicate: { fontSize: 14, color: '#8a5600', fontStyle: 'italic' },
  rank: { fontSize: 14, color: '#8a5600' },
  probabilities: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  probability: { fontSize: 14, color: '#3c4043' },
  buttonRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap', marginVertical: 4 },
  primary: {
    backgroundColor: '#0b57d0',
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 10,
  },
  primaryText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  secondary: {
    borderWidth: 1.5,
    borderColor: '#0b57d0',
    paddingVertical: 12,
    paddingHorizontal: 18,
    borderRadius: 10,
  },
  secondaryText: { color: '#0b57d0', fontWeight: '600', fontSize: 15 },
  section: { gap: 5, marginTop: 8 },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '800',
    color: '#5f6368',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  body: { fontSize: 15, lineHeight: 22 },
  bullet: { fontSize: 15, lineHeight: 22 },
  hazard: { color: '#b3261e' },
  unknown: { color: '#5f6368', fontStyle: 'italic' },
  transcriptLine: { fontSize: 14, lineHeight: 20, color: '#3c4043' },
  transcriptRole: { fontWeight: '700', textTransform: 'capitalize' },
  candidate: { paddingVertical: 6 },
  candidateName: { fontSize: 15, fontWeight: '600' },
  candidateWhy: { fontSize: 13, color: '#5f6368', lineHeight: 18 },
});
