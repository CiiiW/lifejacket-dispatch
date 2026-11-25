/**
 * Turning a `Conditions` payload into display strings.
 *
 * Formatting lives here rather than in either app so the reporter and the
 * coordinator read identical numbers for the same incident. Pure functions,
 * no React, so both a phone screen and a web dashboard can use them.
 */

import type { Conditions, TidePoint } from './api';

/**
 * Triage, in words a member of the public understands.
 *
 * Separate from `severityLabel`, which is written for responders: "Guidance
 * only" is precise shorthand inside a stranding network and means nothing to
 * someone standing on a beach. `headline` is what they read first, `detail`
 * explains what it implies for them.
 */
export function reporterVerdict(severity: string | null): {
  headline: string;
  detail: string;
} {
  switch (severity) {
    case 'critical':
      return {
        headline: 'Critical',
        detail: 'This needs a trained team as soon as one can get there.',
      };
    case 'respond':
      return {
        headline: 'Needs a responder',
        detail: 'A rescue team should attend this animal.',
      };
    case 'monitor':
      return {
        headline: 'Monitor',
        detail: 'Not an emergency, but worth keeping an eye on.',
      };
    case 'guidance':
      return {
        headline: 'Looks safe',
        detail: 'This animal does not appear to need rescuing. Keep your distance.',
      };
    default:
      return {
        headline: 'Being reviewed',
        detail: 'A coordinator will look at this report.',
      };
  }
}

/** Sentence-case a single word from the backend, e.g. "rising" -> "Rising". */
function capitalise(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export interface Reading {
  label: string;
  value: string;
  /** True when the underlying lookup failed or returned nothing. */
  missing?: boolean;
  /** True when this is operationally urgent -- darkness, heavy rain, a rising tide. */
  urgent?: boolean;
}

/** How much daylight is left, in words. */
export function describeDaylight(minutes: number | null): Reading {
  if (minutes === null) {
    // Not the same as darkness, and must not be shown as "0 minutes".
    return { label: 'Daylight', value: 'Unknown', missing: true };
  }
  if (minutes === 0) {
    return { label: 'Daylight', value: 'Dark now', urgent: true };
  }
  if (minutes < 60) {
    return { label: 'Daylight', value: `${minutes} min left`, urgent: true };
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return {
    label: 'Daylight',
    value: rest ? `${hours}h ${rest}m left` : `${hours}h left`,
    urgent: minutes < 120,
  };
}

function describePrecipitation(conditions: Conditions): Reading {
  const { precipitation_mm: mm, precipitation_probability: chance } = conditions;

  if (mm === null && chance === null) {
    return { label: 'Rain', value: 'Unknown', missing: true };
  }
  if (mm !== null && mm > 0) {
    // Quantity first: it is the part that changes how a rescue goes.
    return { label: 'Rain', value: `${mm.toFixed(1)} mm falling`, urgent: mm >= 2 };
  }
  const odds = chance !== null ? `${Math.round(chance * 100)}% chance` : 'none now';
  return { label: 'Rain', value: mm === 0 ? `None now, ${odds}` : capitalise(odds) };
}

/**
 * The readings worth showing, in the order they matter for a beach rescue.
 *
 * Tide leads because it is the one that decides whether the animal refloats
 * on its own or strands further up and starts a heat-stress clock.
 */
export function conditionReadings(conditions: Conditions): Reading[] {
  const readings: Reading[] = [];

  if (conditions.is_coastal) {
    if (conditions.tide_trend) {
      readings.push({
        label: 'Tide',
        value: capitalise(conditions.tide_trend),
        urgent: conditions.tide_trend.toLowerCase() === 'rising',
      });
    } else {
      readings.push({ label: 'Tide', value: 'Unknown', missing: true });
    }
  }

  readings.push(
    conditions.temperature_c !== null
      ? { label: 'Air', value: `${Math.round(conditions.temperature_c)}°C` }
      : { label: 'Air', value: 'Unknown', missing: true },
  );

  if (conditions.sea_temperature_c !== null) {
    readings.push({ label: 'Sea', value: `${conditions.sea_temperature_c.toFixed(1)}°C` });
  }

  if (conditions.wind_speed_mph !== null) {
    const gust =
      conditions.wind_gust_mph !== null &&
      conditions.wind_gust_mph > conditions.wind_speed_mph + 2
        ? ` (gusts ${Math.round(conditions.wind_gust_mph)})`
        : '';
    readings.push({
      label: 'Wind',
      value: `${Math.round(conditions.wind_speed_mph)} mph${gust}`,
      urgent: conditions.wind_speed_mph >= 25,
    });
  } else {
    readings.push({ label: 'Wind', value: 'Unknown', missing: true });
  }

  readings.push(describePrecipitation(conditions));

  if (conditions.wave_height_m !== null) {
    readings.push({
      label: 'Waves',
      value: `${conditions.wave_height_m.toFixed(1)} m`,
      urgent: conditions.wave_height_m >= 2,
    });
  }

  readings.push(describeDaylight(conditions.minutes_to_sunset));

  if (conditions.visibility_miles !== null) {
    readings.push({
      label: 'Visibility',
      value: `${conditions.visibility_miles.toFixed(1)} mi`,
      urgent: conditions.visibility_miles < 1,
    });
  }

  if (conditions.condition) {
    readings.push({ label: 'Sky', value: capitalise(conditions.condition) });
  }

  return readings;
}

/**
 * The headline conditions on one line, for a chat message.
 *
 * Only the readings that change a decision: what the tide is doing, how cold
 * it is, and how much light is left. The full grid lives in
 * `ConditionsPanel`; this is the version that fits in a sentence.
 */
export function summariseConditions(conditions: Conditions): string {
  const parts: string[] = [];

  if (conditions.is_coastal && conditions.tide_trend) {
    parts.push(`tide ${conditions.tide_trend}`);
  }
  if (conditions.temperature_c !== null) {
    parts.push(`${Math.round(conditions.temperature_c)}°C air`);
  }
  if (conditions.sea_temperature_c !== null) {
    parts.push(`${conditions.sea_temperature_c.toFixed(0)}°C sea`);
  }
  if (conditions.precipitation_mm !== null && conditions.precipitation_mm > 0) {
    parts.push(`${conditions.precipitation_mm.toFixed(1)} mm rain`);
  }
  if (conditions.wind_speed_mph !== null && conditions.wind_speed_mph >= 15) {
    parts.push(`${Math.round(conditions.wind_speed_mph)} mph wind`);
  }

  const daylight = describeDaylight(conditions.minutes_to_sunset);
  if (!daylight.missing) {
    parts.push(daylight.value.toLowerCase());
  }

  return parts.join(' · ');
}

/** A short line naming what could not be looked up, or null if all fine. */
export function describeGaps(conditions: Conditions): string | null {
  if (conditions.unavailable.length === 0) return null;
  return `Could not check: ${conditions.unavailable.join(', ')}.`;
}

// --- Tide outlook -------------------------------------------------------------
//
// The chart and the "next low in 2h 10m" line read the same predictions, so
// they cannot disagree. Times are local (see `TideEvent`); everything here is
// relative to a moment the caller passes in: now for live conditions, the
// snapshot's own time for a stored one.

/** A tide time from the API as a Date. */
export function tideDate(time: string): Date {
  return new Date(time);
}

/** "4:52 PM". Written out rather than Intl, so web and Hermes agree. */
export function clockTime(date: Date): string {
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours % 12 || 12}:${minutes} ${hours < 12 ? 'AM' : 'PM'}`;
}

/** "in 2h 05m", "in 40 min", or "now". */
export function timeUntil(from: Date, to: Date): string {
  const minutes = Math.max(0, Math.round((to.getTime() - from.getTime()) / 60000));
  if (minutes < 1) return 'now';
  if (minutes < 60) return `in ${minutes} min`;
  return `in ${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}

/** "1.84 m", or "−0.42 m" with a true minus: low water can be below the datum. */
export function metres(value: number): string {
  return `${value.toFixed(2).replace('-', '−')} m`;
}

/** Feet, for readers of US tide tables: "6.0 ft". */
export function feet(value: number): string {
  return `${(value * 3.28084).toFixed(1).replace('-', '−')} ft`;
}

export interface TideTurn {
  kind: 'high' | 'low';
  at: Date;
  /** Null for snapshots stored before turning points were kept. */
  heightM: number | null;
}

export interface TideOutlook {
  trend: 'rising' | 'falling' | null;
  /** Predicted height at the moment asked about, or null if unknown. */
  heightM: number | null;
  nextHigh: TideTurn | null;
  nextLow: TideTurn | null;
}

/** Height on the 15-minute curve at `at`, interpolated; null outside it. */
export function heightOnCurve(curve: TidePoint[], at: Date): number | null {
  const t = at.getTime();
  for (let i = 1; i < curve.length; i += 1) {
    const a = tideDate(curve[i - 1].time).getTime();
    const b = tideDate(curve[i].time).getTime();
    if (t >= a && t <= b) {
      const f = b === a ? 0 : (t - a) / (b - a);
      return curve[i - 1].height_m + (curve[i].height_m - curve[i - 1].height_m) * f;
    }
  }
  return null;
}

/** Where the water is at `at`, which way it is going, and the next high and low. */
export function tideOutlook(conditions: Conditions, at: Date): TideOutlook {
  const turns: TideTurn[] = (conditions.tide_events ?? []).map((e) => ({
    kind: e.kind,
    at: tideDate(e.time),
    heightM: e.height_m,
  }));
  const upcoming = turns.filter((e) => e.at.getTime() >= at.getTime());

  // Older snapshots carry only the next high and low, without heights.
  const stored = (kind: 'high' | 'low', time: string | null): TideTurn | null =>
    time && tideDate(time).getTime() >= at.getTime()
      ? { kind, at: tideDate(time), heightM: null }
      : null;

  const nextHigh = upcoming.find((e) => e.kind === 'high') ?? stored('high', conditions.next_high_tide);
  const nextLow = upcoming.find((e) => e.kind === 'low') ?? stored('low', conditions.next_low_tide);

  let trend: TideOutlook['trend'] = null;
  if (upcoming.length > 0) {
    trend = upcoming[0].kind === 'high' ? 'rising' : 'falling';
  } else if (conditions.tide_trend === 'rising' || conditions.tide_trend === 'falling') {
    trend = conditions.tide_trend;
  }

  const heightM = heightOnCurve(conditions.tide_curve ?? [], at) ?? conditions.water_level_m;
  return { trend, heightM, nextHigh, nextLow };
}
