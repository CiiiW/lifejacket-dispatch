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
  screen: { flex: 1, backgroundColor: '#fff' },
  inner: { padding: 16, gap: 18, maxWidth: 640, alignSelf: 'center', width: '100%' },
  title: { fontSize: 22, fontWeight: '700' },
  subtitle: { fontSize: 13, color: '#5f6368', marginTop: -14 },
  field: { gap: 6 },
  label: { fontSize: 15, fontWeight: '600' },
  hint: { fontSize: 13, color: '#5f6368', lineHeight: 18 },
  input: {
    borderWidth: 1,
    borderColor: '#c4c7c5',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 11,
    fontSize: 15,
  },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    borderWidth: 1.5,
    borderColor: '#c4c7c5',
    borderRadius: 18,
    paddingVertical: 9,
    paddingHorizontal: 14,
  },
  chipActive: { borderColor: '#0b57d0', backgroundColor: '#e8f0fe' },
  chipText: { fontSize: 14, color: '#3c4043' },
  chipTextActive: { color: '#0b57d0', fontWeight: '600' },
  submit: {
    backgroundColor: '#0b57d0',
    paddingVertical: 15,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 4,
  },
  submitText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
