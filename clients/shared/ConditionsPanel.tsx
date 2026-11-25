/**
 * Weather, tide and daylight at the animal: the tide first, as a chart with
 * the next low and high, then the other readings as tiles.
 *
 * Shared by both apps deliberately. The reporter standing on the beach and
 * the coordinator deciding whether to send a team should see the same numbers
 * for the same incident -- two implementations would eventually disagree.
 *
 * Every reading says when it was taken. Live conditions (fetched as the case
 * is opened) count down to the next turn of the tide and move the chart's
 * marker every minute; a stored snapshot is described as of its own time, so a
 * report six hours old never claims low water is "in 0 minutes".
 *
 * Uses only react-native primitives (react-native-web maps them on the web),
 * so it renders in the phone app and the browser console alike.
 */

import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { Conditions, TidePoint } from './api';
import {
  clockTime,
  conditionReadings,
  describeGaps,
  feet,
  metres,
  tideDate,
  tideOutlook,
  timeUntil,
  type TideTurn,
} from './conditions';
import TideChart from './TideChart';
import { colors, glass, radius, spacing, type } from './theme';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default function ConditionsPanel({
  conditions,
  title = 'Conditions',
  compact = false,
  bare = false,
  note = null,
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
  /** A line about freshness the caller knows and this panel cannot, e.g. a failed refresh. */
  note?: string | null;
}) {
  const live = conditions?.live === true;
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => {
    if (!live) return undefined;
    setClock(new Date());
    const timer = setInterval(() => setClock(new Date()), 60_000);
    return () => clearInterval(timer);
  }, [live]);

  if (conditions === null) {
    return null;
  }

  const taken = conditions.local_time ? new Date(conditions.local_time) : null;
  // Live readings are measured from the ticking clock; a snapshot from the
  // moment it was taken.
  const at = live ? clock : (taken ?? clock);
  const outlook = tideOutlook(conditions, at);
  const curve = conditions.tide_curve ?? [];
  const readings = conditionReadings(conditions).filter((reading) => reading.label !== 'Tide');
  const gaps = describeGaps(conditions);
  const rising = outlook.trend === 'rising';

  return (
    <View style={bare ? styles.bare : [styles.card, compact && styles.cardCompact]}>
      {!bare && <Text style={styles.title}>{title}</Text>}

      <View style={styles.freshness}>
        {live && <View style={styles.liveDot} />}
        <Text style={styles.freshnessText}>
          {live
            ? `Live · updated ${taken ? clockTime(taken) : clockTime(clock)}`
            : taken
              ? `As of ${clockTime(taken)}, ${shortDate(taken)}`
              : 'Time of reading unknown'}
        </Text>
      </View>
      {note && <Text style={styles.note}>{note}</Text>}

      {conditions.is_coastal ? (
        <View style={[styles.tide, compact && styles.tideCompact]}>
          <View style={styles.tideTop}>
            <View style={styles.tideNow}>
              <Text style={styles.eyebrow}>Tide</Text>
              <Text style={[styles.trend, compact && styles.trendCompact, rising && styles.trendRising]}>
                {rising ? '↑ Rising' : outlook.trend === 'falling' ? '↓ Falling' : 'Unknown'}
              </Text>
              {outlook.heightM !== null && (
                <Text style={styles.level}>
                  {metres(outlook.heightM)}
                  <Text style={styles.levelSecondary}> · {feet(outlook.heightM)}</Text>
                </Text>
              )}
              {outlook.trend && (
                <Text style={styles.implication}>
                  {rising
                    ? 'Water is coming toward the animal and may refloat it.'
                    : 'Water is moving away from the animal.'}
                </Text>
              )}
            </View>

            <View style={styles.turns}>
              <Turn label="Next low" turn={outlook.nextLow} at={at} live={live} />
              <Turn label="Next high" turn={outlook.nextHigh} at={at} live={live} />
            </View>
          </View>

          {curve.length > 1 && (
            <View style={styles.chart}>
              <Text style={styles.eyebrow}>{chartTitle(curve, live)}</Text>
              <TideChart
                curve={curve}
                events={conditions.tide_events ?? []}
                now={at}
                height={compact ? 64 : 84}
              />
            </View>
          )}
        </View>
      ) : (
        <Text style={styles.inland}>
          No tide station in range -- treat this as an inland location.
        </Text>
      )}

      <View style={styles.tiles}>
        {readings.map((reading) => (
          <View key={reading.label} style={[styles.tile, compact && styles.tileCompact]}>
            <Text style={styles.tileLabel}>{reading.label}</Text>
            <Text
              style={[
                styles.tileValue,
                reading.urgent && styles.valueUrgent,
                reading.missing && styles.valueMissing,
              ]}
            >
              {reading.value}
            </Text>
          </View>
        ))}
      </View>

      {conditions.is_coastal && conditions.tide_station_name && (
        <Text style={styles.source}>
          Tide predicted (not measured) for NOAA station {conditions.tide_station_name}
          {conditions.tide_station_distance_km != null
            ? `, ${conditions.tide_station_distance_km} km away`
            : ''}
          ; heights above mean lower low water. Weather from Open-Meteo.
        </Text>
      )}

      {gaps && <Text style={styles.gaps}>{gaps}</Text>}
    </View>
  );
}

/** The next high or low: its time, height, and (when live) how long until it. */
function Turn({
  label,
  turn,
  at,
  live,
}: {
  label: string;
  turn: TideTurn | null;
  at: Date;
  live: boolean;
}) {
  const details = turn
    ? [turn.heightM !== null ? metres(turn.heightM) : null, live ? timeUntil(at, turn.at) : null]
        .filter(Boolean)
        .join(' · ')
    : '';
  return (
    <View style={styles.turn}>
      <Text style={styles.eyebrow}>{label}</Text>
      <Text style={[styles.turnTime, !turn && styles.valueMissing]}>
        {turn ? clockTime(turn.at) : 'Unknown'}
        {turn && !sameDay(turn.at, at) ? <Text style={styles.turnDay}> {dayWord(turn.at, at)}</Text> : null}
      </Text>
      {details ? <Text style={styles.turnDetails}>{details}</Text> : null}
    </View>
  );
}

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** "tomorrow" for the next day, else the weekday. */
function dayWord(date: Date, from: Date): string {
  const next = new Date(from);
  next.setDate(from.getDate() + 1);
  return sameDay(date, next) ? 'tomorrow' : WEEKDAYS[date.getDay()];
}

/** "Nov 24". */
function shortDate(date: Date): string {
  return `${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

function chartTitle(curve: TidePoint[], live: boolean): string {
  const day = tideDate(curve[0].time);
  if (live && sameDay(day, new Date())) return "Today's tide";
  return `Tide on ${WEEKDAYS[day.getDay()]}, ${shortDate(day)}`;
}

const styles = StyleSheet.create({
  card: { ...glass, padding: spacing.md, gap: spacing.md },
  cardCompact: { padding: spacing.sm + 2, gap: spacing.sm },
  bare: { gap: spacing.md },
  title: { ...type.eyebrow, color: colors.accent },

  freshness: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  liveDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.accent },
  freshnessText: { ...type.meta, fontSize: 12, color: colors.textMuted },
  note: { ...type.meta, fontSize: 12, color: colors.textFaint, marginTop: -spacing.sm },

  tide: {
    backgroundColor: colors.glassFill,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.card,
    padding: spacing.md,
    gap: spacing.md,
  },
  tideCompact: { padding: spacing.sm + 2, gap: spacing.sm },
  tideTop: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  tideNow: { gap: 2, flexShrink: 1, minWidth: 180 },
  eyebrow: { ...type.eyebrow, fontSize: 10, color: colors.textFaint },
  trend: { ...type.title, color: colors.text },
  trendCompact: { fontSize: 18 },
  trendRising: { color: colors.warning },
  level: { ...type.label, fontSize: 15, color: colors.text },
  levelSecondary: { ...type.meta, fontSize: 12, color: colors.textFaint, fontWeight: '400' },
  implication: { ...type.meta, fontSize: 12.5, color: colors.textMuted, marginTop: 2 },

  turns: { flexDirection: 'row', gap: spacing.lg },
  turn: { gap: 2, minWidth: 96 },
  turnTime: { ...type.heading, color: colors.text },
  turnDay: { ...type.meta, fontSize: 12, color: colors.textFaint, fontWeight: '400' },
  turnDetails: { ...type.meta, fontSize: 12.5, color: colors.textMuted },

  chart: { gap: spacing.xs },

  inland: { ...type.meta, fontSize: 12.5, color: colors.textMuted },

  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  tile: {
    flexGrow: 1,
    // Wide enough that a console card wraps into even rows of four and a phone
    // into rows of two, rather than six and a stretched pair.
    flexBasis: 150,
    gap: 2,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm + 2,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.glassFill,
  },
  tileCompact: { flexBasis: 104, paddingVertical: 6 },
  tileLabel: { ...type.eyebrow, fontSize: 9.5, letterSpacing: 0.8, color: colors.textFaint },
  // No textTransform: capitalising everything turned "6 mph" into "6 Mph"
  // and "4h 33m left" into "4h 33m Left". Words that need a capital get one
  // in `conditions.ts`, where it is known which are words and which are units.
  tileValue: { ...type.label, fontSize: 14.5, color: colors.text },
  valueUrgent: { color: colors.warning },
  valueMissing: { color: colors.textFaint, fontStyle: 'italic' },

  source: { ...type.meta, fontSize: 11, color: colors.textFaint, lineHeight: 16 },
  gaps: { ...type.meta, fontSize: 11.5, color: colors.warning },
});
