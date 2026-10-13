/**
 * Weather, tide, and daylight, as a grid of readings.
 *
 * Shared by both apps deliberately. The reporter standing on the beach and
 * the coordinator deciding whether to send a team should see the same numbers
 * for the same incident -- two implementations would eventually disagree.
 *
 * Uses only react-native primitives (react-native-web maps them on the web),
 * so it renders in the phone app and the browser console alike.
 */

import { StyleSheet, Text, View } from 'react-native';

import type { Conditions } from './api';
import { conditionReadings, describeGaps } from './conditions';
import { colors, glass, radius, spacing, type } from './theme';

export default function ConditionsPanel({
  conditions,
  title = 'Conditions',
  compact = false,
  bare = false,
}: {
  conditions: Conditions | null;
  title?: string;
  /** Tighter spacing, for a phone panel rather than a dashboard column. */
  compact?: boolean;
  /**
   * Drop the card and the title, leaving just the readings.
   *
   * Used when the caller already provides a container -- the console wraps
   * this in its own collapsible `Section`, and two nested glass cards with
   * two headings read as a bug rather than a design.
   */
  bare?: boolean;
}) {
  if (conditions === null) {
    return null;
  }

  const readings = conditionReadings(conditions);
  const gaps = describeGaps(conditions);

  return (
    <View style={bare ? undefined : [styles.card, compact && styles.cardCompact]}>
      {!bare && <Text style={styles.title}>{title}</Text>}

      <View style={styles.grid}>
        {readings.map((reading) => (
          <View key={reading.label} style={styles.cell}>
            <Text style={styles.label}>{reading.label}</Text>
            <Text
              style={[
                styles.value,
                reading.urgent && styles.valueUrgent,
                reading.missing && styles.valueMissing,
              ]}
            >
              {reading.value}
            </Text>
          </View>
        ))}
      </View>

      {/* The full tide sentence, because "rising" alone does not say how long
          there is before the water reaches the animal. */}
      {conditions.tide_summary && conditions.is_coastal && (
        <Text style={styles.detail}>{conditions.tide_summary}</Text>
      )}

      {!conditions.is_coastal && (
        <Text style={styles.detail}>
          No tide station in range -- treat this as an inland location.
        </Text>
      )}

      {gaps && <Text style={styles.gaps}>{gaps}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { ...glass, padding: spacing.md, gap: spacing.sm },
  cardCompact: { padding: spacing.sm + 2, gap: spacing.xs + 2 },
  title: { ...type.eyebrow, color: colors.accent },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  cell: { minWidth: 78, gap: 1 },
  label: { ...type.meta, fontSize: 10.5, color: colors.textFaint, letterSpacing: 0.4 },
  // No textTransform: capitalising everything turned "6 mph" into "6 Mph"
  // and "4h 33m left" into "4h 33m Left". Words that need a capital get one
  // in `conditions.ts`, where it is known which are words and which are units.
  value: { ...type.label, fontSize: 14, color: colors.text },
  valueUrgent: { color: colors.warning },
  valueMissing: { color: colors.textFaint, fontStyle: 'italic' },
  detail: {
    ...type.meta,
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 17,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.sm,
    borderRadius: radius.sm,
  },
  gaps: { ...type.meta, fontSize: 11.5, color: colors.warning },
});
