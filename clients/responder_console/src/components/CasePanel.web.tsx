/**
 * Case detail shown in the triage page's side panel, in place of the list.
 *
 * Fetches the same `/incidents/{id}` record the full Incident tab uses, so what
 * a coordinator reads here and there cannot disagree. Everything is rendered as
 * plain text -- headlines, summaries and reasons come from reporters and model
 * output.
 *
 * Not shown yet, because the API does not serve them: a response timeline and
 * the full list of participating centres.
 */

import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import {
  absoluteUrl,
  responder,
  severityColour,
  severityLabel,
  type IncidentDetail,
  type MapPin,
} from '../lib/api';
import { colors, radius, spacing, type } from '../lib/theme';

export default function CasePanel({
  pin,
  leadCentre,
  onBack,
  onOpenFull,
}: {
  /** The list-level record: shown instantly while the full one loads. */
  pin: MapPin;
  leadCentre: string | null;
  onBack: () => void;
  onOpenFull: () => void;
}) {
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    setDetail(null);
    setFailed(false);
    responder
      .getIncident(pin.incident_id)
      .then((record) => current && setDetail(record))
      .catch(() => current && setFailed(true));
    return () => {
      current = false;
    };
  }, [pin.incident_id]);

  const photo = detail?.photos[0] ? absoluteUrl(detail.photos[0].url) : absoluteUrl(pin.photo_url);
  const colour = severityColour(pin.severity_level);
  const reasons = detail?.severity_reasons ?? [];
  const actions = detail?.report?.recommended_actions ?? [];
  const hazards = detail?.report?.hazard_warnings ?? [];

  return (
    <View style={styles.root}>
      <Pressable style={styles.back} onPress={onBack} accessibilityRole="button">
        <Text style={styles.backText}>‹ All incidents</Text>
      </Pressable>

      <ScrollView contentContainerStyle={styles.body}>
        <View style={styles.titleRow}>
          <View style={[styles.stripe, { backgroundColor: colour }]} />
          <View style={styles.titleText}>
            <Text style={styles.title}>
              {pin.headline ?? pin.species_common_name ?? 'Unidentified animal'}
            </Text>
            <Text style={styles.meta}>
              <Text style={{ color: colour, fontWeight: '700' }}>
                {severityLabel(pin.severity_level)}
              </Text>
              {` · ${pin.status.replace(/_/g, ' ')}`}
            </Text>
          </View>
        </View>

        {(pin.entanglement || pin.in_mass_stranding) && (
          <View style={styles.tags}>
            {pin.entanglement && <Text style={styles.tag}>ENTANGLED</Text>}
            {pin.in_mass_stranding && <Text style={styles.tag}>MASS STRANDING</Text>}
          </View>
        )}

        {photo ? (
          <Image source={{ uri: photo }} style={styles.photo} resizeMode="cover" />
        ) : (
          <View style={[styles.photo, styles.noPhoto]}>
            <Text style={styles.muted}>No photo</Text>
          </View>
        )}

        <Field label="Animal" value={pin.species_common_name ?? 'Not identified yet'} />
        <Field
          label="Location"
          value={[
            pin.place_name,
            pin.latitude !== null && pin.longitude !== null
              ? `${pin.latitude.toFixed(4)}, ${pin.longitude.toFixed(4)}`
              : null,
          ]
            .filter(Boolean)
            .join(' · ') || 'Unknown'}
        />
        <Field label="Lead centre" value={leadCentre ?? 'Not assigned yet'} />
        <Field
          label="Reported"
          value={new Date(pin.created_at).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
          })}
        />

        {!detail && !failed && <ActivityIndicator color={colors.accent} style={styles.loading} />}
        {failed && <Text style={styles.muted}>Could not load the full report.</Text>}

        {detail?.report?.summary ? (
          <Section title="Summary">
            <Text style={styles.text}>{detail.report.summary}</Text>
          </Section>
        ) : null}

        {reasons.length > 0 && (
          <Section title="Why this urgency">
            {reasons.map((reason) => (
              <Text key={reason} style={styles.text}>{`• ${reason}`}</Text>
            ))}
          </Section>
        )}

        {hazards.length > 0 && (
          <Section title="Hazards">
            {hazards.map((item) => (
              <Text key={item} style={styles.text}>{`• ${item}`}</Text>
            ))}
          </Section>
        )}

        {actions.length > 0 && (
          <Section title="Recommended actions">
            {actions.map((item) => (
              <Text key={item} style={styles.text}>{`• ${item}`}</Text>
            ))}
          </Section>
        )}

        <Pressable style={styles.open} onPress={onOpenFull} accessibilityRole="button">
          <Text style={styles.openText}>Open full report</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
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

const styles = StyleSheet.create({
  root: { flex: 1 },
  back: { alignSelf: 'flex-start', paddingVertical: spacing.sm },
  backText: { ...type.meta, color: colors.accent, fontWeight: '700', fontSize: 14 },
  body: { paddingBottom: spacing.xl, gap: spacing.md },
  titleRow: { flexDirection: 'row', gap: spacing.md, alignItems: 'stretch' },
  stripe: { width: 4, borderRadius: 2 },
  titleText: { flex: 1, gap: 2 },
  title: { ...type.title, color: colors.text },
  meta: { ...type.meta, color: colors.textMuted },
  tags: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  tag: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.8,
    color: colors.warning,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingVertical: 2,
    paddingHorizontal: 8,
  },
  photo: { width: '100%', height: 190, borderRadius: radius.card, backgroundColor: colors.glassFill },
  noPhoto: { alignItems: 'center', justifyContent: 'center' },
  field: { gap: 2 },
  label: { ...type.meta, color: colors.textFaint, fontSize: 11, textTransform: 'uppercase' },
  value: { ...type.meta, color: colors.text, fontSize: 14 },
  section: { gap: spacing.xs, marginTop: spacing.sm },
  sectionTitle: { ...type.meta, color: colors.textMuted, fontWeight: '700', fontSize: 12 },
  text: { ...type.meta, color: colors.text, fontSize: 13, lineHeight: 19 },
  muted: { ...type.meta, color: colors.textMuted },
  loading: { marginVertical: spacing.md },
  open: {
    marginTop: spacing.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingVertical: spacing.sm,
  },
  openText: { ...type.meta, color: colors.text, fontWeight: '700' },
});
