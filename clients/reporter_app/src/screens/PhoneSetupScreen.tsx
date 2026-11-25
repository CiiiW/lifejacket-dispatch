/**
 * Asked once, the first time the app opens: the reporter's phone number.
 *
 * Using LifeJacket means sharing it with the rescue organisation that handles
 * each report, so a team can call about an animal they cannot find. It is
 * asked for before the first report and never again (it is saved on the
 * phone, and can be changed on the Communications tab), so the next report
 * still starts with no form in the way.
 */

import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

/** Digits only, 7 to 15 of them: E.164's range, without judging formats. */
export function plausiblePhone(value: string): boolean {
  const digits = value.replace(/\D/g, '');
  return digits.length >= 7 && digits.length <= 15;
}

export default function PhoneSetupScreen({ onSave }: { onSave: (phone: string) => void }) {
  const [draft, setDraft] = useState('');
  const valid = plausiblePhone(draft);

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.inner}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.brand}>LifeJacket</Text>
      <View style={styles.card}>
        <Text style={styles.title}>Your phone number</Text>
        <Text style={styles.body}>
          Using LifeJacket means sharing your phone number with the rescue organization
          handling each report you send, so they can call or message you about the animal.
        </Text>
        <TextInput
          style={styles.input}
          value={draft}
          onChangeText={setDraft}
          placeholder="+1 555 010 0123"
          placeholderTextColor={colors.textFaint}
          keyboardType="phone-pad"
          autoComplete="tel"
          textContentType="telephoneNumber"
          returnKeyType="done"
          onSubmitEditing={() => valid && onSave(draft.trim())}
        />
        <Pressable
          style={[styles.primary, !valid && styles.primaryDisabled]}
          disabled={!valid}
          onPress={() => onSave(draft.trim())}
        >
          <Text style={styles.primaryText}>Continue</Text>
        </Pressable>
        <Text style={styles.small}>
          Saved on this phone. You can change it any time on the Communications tab.
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl, gap: spacing.lg },
  brand: { ...type.display, color: colors.text, textAlign: 'center' },
  card: { ...glass, ...shadow.soft, padding: spacing.lg, gap: spacing.md },
  title: { ...type.title, color: colors.text },
  body: { ...type.body, color: colors.textMuted, lineHeight: 21 },
  input: {
    ...type.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.card,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.glassFill,
  },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: radius.card,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  primaryDisabled: { opacity: 0.4 },
  primaryText: { ...type.label, color: colors.onAccent, fontSize: 16 },
  small: { ...type.meta, color: colors.textFaint, textAlign: 'center' },
});
