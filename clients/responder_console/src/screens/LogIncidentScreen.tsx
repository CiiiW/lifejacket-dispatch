/**
 * Closing an incident: the responder's write-up.
 *
 * **This is the most valuable screen in the project.** `confirmed_species` is
 * the only ground truth the system ever receives about whether the
 * identification agent was right, and `report_was_accurate` is the only
 * feedback on the generated report. Everything the team can measure about
 * real-world agent accuracy comes from what gets typed here.
 *
 * Which is why the form is short. A responder filling this in has just spent
 * two hours on a beach and is standing by their car. Four fields they will
 * actually complete beat twelve they will skip.
 */

import { useState } from 'react';
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { responder } from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

const OUTCOMES = [
  'rescued',
  'released',
  'deceased',
  'not_found',
  'no_action_needed',
] as const;

export default function LogIncidentScreen({
  incidentId,
  responderId,
  onDone,
}: {
  incidentId: string;
  responderId: string;
  onDone: () => void;
}) {
  const [confirmedSpecies, setConfirmedSpecies] = useState('');
  const [outcome, setOutcome] = useState<string | null>(null);
  const [actionsTaken, setActionsTaken] = useState('');
  const [notes, setNotes] = useState('');
  const [reportAccurate, setReportAccurate] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!outcome) {
      Alert.alert('Outcome needed', 'Please choose what happened to the animal.');
      return;
    }

    setSaving(true);
    try {
      await responder.logIncident(incidentId, {
        responder_id: responderId,
        confirmed_species: confirmedSpecies.trim() || undefined,
        outcome,
        actions_taken: actionsTaken.trim() || undefined,
        notes: notes.trim() || undefined,
        report_was_accurate: reportAccurate ?? undefined,
      });
      onDone();
    } catch (error) {
      Alert.alert('Could not save', error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      <Text style={styles.title}>Log outcome</Text>
      <Text style={styles.subtitle}>Incident {incidentId}</Text>

      <Field
        label="What was the animal, actually?"
        hint="Your identification is the ground truth we measure the system against. Please correct it even if the app got it right."
      >
        <TextInput
          style={styles.input}
          value={confirmedSpecies}
          onChangeText={setConfirmedSpecies}
          placeholder="e.g. Northern elephant seal, weaned pup"
          placeholderTextColor={colors.textFaint}
        />
      </Field>

      <Field label="Outcome">
        <View style={styles.chips}>
          {OUTCOMES.map((option) => (
            <Pressable
              key={option}
              style={[styles.chip, outcome === option && styles.chipActive]}
              onPress={() => setOutcome(option)}
            >
              <Text style={[styles.chipText, outcome === option && styles.chipTextActive]}>
                {option.replace(/_/g, ' ')}
              </Text>
            </Pressable>
          ))}
        </View>
      </Field>

      <Field label="What did you do?">
        <TextInput
          style={[styles.input, styles.multiline]}
          value={actionsTaken}
          onChangeText={setActionsTaken}
          placeholder="Actions taken on scene"
          placeholderTextColor={colors.textFaint}
          multiline
        />
      </Field>

      <Field
        label="Was the report accurate?"
        hint="Did what you found on the beach match what the report described?"
      >
        <View style={styles.chips}>
          {[
            { label: 'Yes', value: true },
            { label: 'No', value: false },
          ].map((option) => (
            <Pressable
              key={option.label}
              style={[styles.chip, reportAccurate === option.value && styles.chipActive]}
              onPress={() => setReportAccurate(option.value)}
            >
              <Text
                style={[
                  styles.chipText,
                  reportAccurate === option.value && styles.chipTextActive,
                ]}
              >
                {option.label}
              </Text>
            </Pressable>
          ))}
        </View>
      </Field>

      <Field label="Anything else">
        <TextInput
          style={[styles.input, styles.multiline]}
          value={notes}
          onChangeText={setNotes}
          placeholder="Notes for the record"
          placeholderTextColor={colors.textFaint}
          multiline
        />
      </Field>

      <Pressable style={styles.submit} onPress={() => void submit()} disabled={saving}>
        <Text style={styles.submitText}>
          {saving ? 'Saving…' : 'Save and close incident'}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      {hint && <Text style={styles.hint}>{hint}</Text>}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: {
    padding: spacing.lg,
    gap: spacing.xl,
    maxWidth: 660,
    alignSelf: 'center',
    width: '100%',
  },
  title: { ...type.display, color: colors.text },
  subtitle: { ...type.meta, color: colors.textFaint, marginTop: -spacing.lg - 2 },
  field: { gap: spacing.sm },
  label: { ...type.label, color: colors.text, fontSize: 15 },
  hint: { ...type.meta, fontSize: 12.5, color: colors.textFaint, lineHeight: 18 },
  input: {
    ...type.body,
    ...glass,
    color: colors.text,
    paddingHorizontal: spacing.md,
    paddingVertical: 11,
  },
  multiline: { minHeight: 88, textAlignVertical: 'top' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.glassFill,
    borderRadius: radius.pill,
    paddingVertical: 9,
    paddingHorizontal: spacing.lg,
  },
  chipActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  chipText: { ...type.meta, fontSize: 14, color: colors.textMuted },
  chipTextActive: { color: colors.accent, fontWeight: '700' },
  submit: {
    ...shadow.soft,
    backgroundColor: colors.accent,
    paddingVertical: 15,
    borderRadius: radius.card,
    alignItems: 'center',
    marginTop: spacing.xs,
  },
  submitText: { ...type.label, color: colors.onAccent, fontSize: 16 },
});
