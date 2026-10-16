/**
 * How a rescue team reaches the reporter.
 *
 * This is optional and asked for late on purpose. Intake starts the moment
 * the app opens, with no form, because someone standing over a hurt animal
 * should not be typing their phone number first. But a responder who arrives
 * and cannot find the animal has no way to ask "which end of the beach?"
 * unless this is filled in -- so the screen explains why rather than just
 * presenting a field.
 *
 * Whatever is typed here lands on `incidents.reporter_phone`, which is what
 * the responder console's "Call reporter" button dials.
 */

import { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { reporter } from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

export default function ContactScreen({
  incidentId,
  phone,
  onSaved,
}: {
  incidentId: string;
  phone: string;
  onSaved: (phone: string) => void;
}) {
  const [draft, setDraft] = useState(phone);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const saved = phone.length > 0 && draft === phone;

  async function save(next: string) {
    setSaving(true);
    setError(null);
    try {
      const result = await reporter.setContact(incidentId, next);
      onSaved(result.reporter_phone ?? '');
    } catch (problem) {
      console.warn('[LifeJacket] saving contact failed:', problem);
      setError('Could not save that. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      <Text style={styles.title}>Your phone number</Text>
      <Text style={styles.body}>
        Optional. A rescue team may need to call you if they cannot find the
        animal, or to ask something the photo does not show.
      </Text>
      <Text style={styles.body}>
        It is shared only with the rescue organisation handling this report.
      </Text>

      <View style={styles.card}>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder="+1 555 010 0123"
          placeholderTextColor={colors.textFaint}
          keyboardType="phone-pad"
          autoComplete="tel"
          editable={!saving}
        />

        <Pressable
          style={[styles.button, (saving || saved) && styles.buttonMuted]}
          onPress={() => void save(draft.trim())}
          disabled={saving || saved}
        >
          {saving ? (
            <ActivityIndicator color={colors.onAccent} />
          ) : (
            <Text style={styles.buttonText}>{saved ? 'Saved' : 'Save number'}</Text>
          )}
        </Pressable>

        {error && <Text style={styles.error}>{error}</Text>}

        {saved && (
          <Pressable onPress={() => void save('')} disabled={saving}>
            <Text style={styles.remove}>Remove my number</Text>
          </Pressable>
        )}
      </View>

      <Text style={styles.reference}>Report {incidentId}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: { padding: spacing.lg, gap: spacing.md },
  title: { ...type.display, color: colors.text },
  body: { ...type.body, color: colors.textMuted, lineHeight: 21 },
  card: { ...glass, padding: spacing.lg, gap: spacing.md, marginTop: spacing.sm },
  input: {
    ...type.body,
    fontSize: 17,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
    backgroundColor: colors.glassFill,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  button: {
    ...shadow.soft,
    backgroundColor: colors.accent,
    borderRadius: radius.card,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  buttonMuted: { opacity: 0.55 },
  buttonText: { ...type.label, fontSize: 16, color: colors.onAccent },
  error: { ...type.meta, color: colors.danger },
  remove: { ...type.meta, color: colors.textMuted, textAlign: 'center' },
  reference: { ...type.meta, fontSize: 11, color: colors.textFaint, marginTop: spacing.sm },
});
