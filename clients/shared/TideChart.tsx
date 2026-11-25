/**
 * One day's predicted tide as an area chart, with the highs and lows marked
 * and a marker at the moment being described.
 *
 * Drawn with plain views rather than SVG: react-native-svg is in neither app,
 * and absolutely positioned bars render the same in Expo Go and the browser.
 * At 15-minute steps the bars are a few pixels wide, so the area reads as a
 * curve. The fill stays neutral; seafoam is kept for the "now" marker, the
 * one active element.
 */

import { useState } from 'react';
import { type LayoutChangeEvent, StyleSheet, Text, View } from 'react-native';

import type { TideEvent, TidePoint } from './api';
import { clockTime, heightOnCurve, metres, tideDate } from './conditions';
import { colors, type } from './theme';

/** Room above the highest water for its label. */
const LABEL_SPACE = 30;
const AXIS_SPACE = 18;
const AXIS_HOURS = [0, 6, 12, 18, 24];

export default function TideChart({
  curve,
  events,
  now,
  height = 84,
}: {
  /** Midnight to midnight, evenly spaced. */
  curve: TidePoint[];
  events: TideEvent[];
  /** Where to draw the marker; outside the day, no marker. */
  now: Date | null;
  /** Height of the plotted area, without the labels above and below. */
  height?: number;
}) {
  const [width, setWidth] = useState(0);
  if (curve.length < 2) return null;

  const start = tideDate(curve[0].time).getTime();
  const end = tideDate(curve[curve.length - 1].time).getTime();
  const span = end - start || 1;
  const heights = curve.map((p) => p.height_m);
  const lowest = Math.min(...heights);
  const highest = Math.max(...heights);
  const range = highest - lowest || 1;
  // Keep low water visibly above the baseline, so "low" never reads as "empty".
  const floor = lowest - range * 0.15;
  const ceiling = highest + range * 0.04;
  const barHeight = (metresAbove: number) => ((metresAbove - floor) / (ceiling - floor)) * height;
  const xOf = (ms: number) => ((ms - start) / span) * width;
  const baseline = LABEL_SPACE + height;

  const nowMs = now ? now.getTime() : null;
  const nowHeight = now && nowMs !== null && nowMs >= start && nowMs <= end ? heightOnCurve(curve, now) : null;
  const turns = events.filter((e) => {
    const t = tideDate(e.time).getTime();
    return t >= start && t <= end;
  });
  // Narrow charts drop the High/Low word: the label sits on a peak or a trough.
  const narrow = width < 420;
  const labelWidth = narrow ? 52 : 70;

  return (
    <View
      onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
      style={{ height: baseline + AXIS_SPACE }}
      accessibilityRole="image"
      accessibilityLabel={`Tide chart. ${turns
        .map((e) => `${e.kind === 'high' ? 'High' : 'Low'} ${metres(e.height_m)} at ${clockTime(tideDate(e.time))}`)
        .join('. ')}.`}
    >
      {width > 0 && (
        <>
          {curve.slice(1).map((point, i) => {
            const previous = curve[i];
            // Whole-pixel edges: neighbours meet exactly. Fractional edges
            // either gap or overlap, and translucent overlaps show as stripes.
            const x0 = Math.round(xOf(tideDate(previous.time).getTime()));
            const x1 = Math.round(xOf(tideDate(point.time).getTime()));
            if (x1 <= x0) return null;
            const h = barHeight((previous.height_m + point.height_m) / 2);
            const past = nowMs !== null && tideDate(point.time).getTime() <= nowMs;
            return (
              <View
                key={point.time}
                style={[
                  styles.bar,
                  past ? styles.barPast : styles.barAhead,
                  { left: x0, width: x1 - x0, top: baseline - h, height: h },
                ]}
              />
            );
          })}

          <View style={[styles.baseline, { top: baseline, width }]} />

          {turns.map((turn) => {
            const x = xOf(tideDate(turn.time).getTime());
            const top = baseline - barHeight(turn.height_m);
            const left = Math.min(Math.max(x - labelWidth / 2, 0), width - labelWidth);
            return (
              <View key={turn.time}>
                <View style={[styles.turnDot, { left: x - 2.5, top: top - 2.5 }]} />
                <View style={[styles.turnLabel, { left, top: top - 30, width: labelWidth }]}>
                  <Text style={styles.turnHeight} numberOfLines={1}>
                    {narrow ? '' : turn.kind === 'high' ? 'High ' : 'Low '}
                    {metres(turn.height_m)}
                  </Text>
                  <Text style={styles.turnTime} numberOfLines={1}>
                    {clockTime(tideDate(turn.time))}
                  </Text>
                </View>
              </View>
            );
          })}

          {nowHeight !== null && nowMs !== null && (
            <>
              <View
                style={[styles.nowLine, { left: xOf(nowMs) - 0.75, top: LABEL_SPACE - 4, height: height + 4 }]}
              />
              <View style={[styles.nowDot, { left: xOf(nowMs) - 6, top: baseline - barHeight(nowHeight) - 6 }]} />
            </>
          )}

          {AXIS_HOURS.map((hour) => {
            const x = (hour / 24) * width;
            const edge = hour === 0 ? 'left' : hour === 24 ? 'right' : 'center';
            return (
              <Text
                key={hour}
                style={[
                  styles.axis,
                  { top: baseline + 4, textAlign: edge },
                  edge === 'left' ? { left: 0 } : edge === 'right' ? { right: 0 } : { left: x - 24 },
                ]}
              >
                {hour === 12 ? 'Noon' : hour === 6 ? '6 AM' : hour === 18 ? '6 PM' : '12 AM'}
              </Text>
            );
          })}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { position: 'absolute' },
  barPast: { backgroundColor: colors.glassFillStrong },
  barAhead: { backgroundColor: colors.borderStrong },
  baseline: { position: 'absolute', left: 0, height: 1, backgroundColor: colors.border },
  turnDot: {
    position: 'absolute',
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.textMuted,
  },
  turnLabel: { position: 'absolute', alignItems: 'center' },
  turnHeight: { ...type.meta, fontSize: 10.5, fontWeight: '700', color: colors.text },
  turnTime: { ...type.meta, fontSize: 10, color: colors.textFaint },
  nowLine: { position: 'absolute', width: 1.5, backgroundColor: colors.accent },
  nowDot: {
    position: 'absolute',
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.accent,
    borderWidth: 2,
    borderColor: colors.background,
  },
  axis: { ...type.meta, position: 'absolute', width: 48, fontSize: 10, color: colors.textFaint },
});
