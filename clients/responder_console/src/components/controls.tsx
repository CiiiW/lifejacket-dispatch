/**
 * Small controls shared by the coordinator panels (decisions, volunteers,
 * reporter chat), so they read as one system. Per the design spec, seafoam is
 * reserved for the active or primary state; everything else is glass.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radius, spacing, type } from '../lib/theme';

type ButtonKind = 'primary' | 'secondary' | 'danger';

export function ActionButton({
  label,
  onPress,
  kind = 'secondary',
  disabled = false,
  busy = false,
}: {
  label: string;
  onPress: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  busy?: boolean;
}) {
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        styles[kind],
        inactive && styles.disabled,
        pressed && styles.pressed,
      ]}
    >
      {busy ? (
        <ActivityIndicator
          size="small"
          color={kind === 'primary' ? colors.onAccent : colors.text}
        />
      ) : (
        <Text
          style={[
            styles.buttonText,
            kind === 'primary' && styles.primaryText,
            kind === 'danger' && styles.dangerText,
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

/** A selectable option. Active means chosen, so it gets the seafoam outline. */
export function Chip({
  label,
  active,
  onPress,
  disabled = false,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.chip, active && styles.chipActive, disabled && styles.disabled]}
    >
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

export type Tone = 'warning' | 'success' | 'muted' | 'danger' | 'accent';

const TONE_COLOUR: Record<Tone, string> = {
  warning: colors.warning,
  success: colors.success,
  muted: colors.textFaint,
  danger: colors.danger,
  accent: colors.accent,
};

export function StatusPill({ label, tone }: { label: string; tone: Tone }) {
  const colour = TONE_COLOUR[tone];
  return (
    <View style={[styles.pill, { borderColor: colour }]}>
      <Text style={[styles.pillText, { color: colour }]}>{label}</Text>
    </View>
  );
}

export function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return <Text style={styles.error}>{message}</Text>;
}

/** "3:42 PM" today, "Nov 24, 3:42 PM" otherwise. */
export function formatTime(iso: string): string {
  const when = new Date(iso);
  const sameDay = when.toDateString() === new Date().toDateString();
  return when.toLocaleString([], {
    ...(sameDay ? {} : { month: 'short', day: 'numeric' }),
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** An API error's message, or a generic line for anything else. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Try again.';
}

const styles = StyleSheet.create({
  button: {
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 40,
  },
  primary: { backgroundColor: colors.accent, borderColor: colors.accent },
  secondary: { backgroundColor: colors.glassFillStrong, borderColor: colors.borderStrong },
  danger: { backgroundColor: 'rgba(255, 107, 107, 0.12)', borderColor: colors.danger },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.8 },
  buttonText: { ...type.label, color: colors.text },
  primaryText: { color: colors.onAccent },
  dangerText: { color: colors.danger },

  chip: {
    paddingVertical: spacing.xs + 2,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.glassFill,
  },
  chipActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  chipText: { ...type.meta, color: colors.textMuted },
  chipTextActive: { color: colors.accent, fontWeight: '600' },

  pill: {
    paddingVertical: 2,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  pillText: { ...type.meta, fontSize: 12, fontWeight: '600' },

  error: { ...type.meta, color: colors.danger },
});
