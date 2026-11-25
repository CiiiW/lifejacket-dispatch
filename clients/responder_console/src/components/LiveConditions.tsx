/**
 * Conditions at the incident now, with the report-time snapshot as fallback.
 *
 * The incident detail carries the snapshot the agents worked from. A
 * coordinator opening the case hours later needs the water as it is now, so
 * this shows the snapshot at once, swaps in a live reading when it arrives,
 * and refreshes every ten minutes while the case stays open -- the same
 * interval the server caches a reading for, so a refresh is never wasted.
 */

import { useEffect, useState } from 'react';

import ConditionsPanel from '../../../shared/ConditionsPanel';
import { responder, type Conditions } from '../lib/api';

const REFRESH_MS = 10 * 60_000;

export default function LiveConditions({
  incidentId,
  snapshot,
}: {
  incidentId: string;
  snapshot: Conditions | null;
}) {
  const [live, setLive] = useState<Conditions | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setLive(null);
    setFailed(false);
    const load = () => {
      responder
        .liveConditions(incidentId)
        .then((conditions) => {
          if (!active) return;
          setLive(conditions);
          setFailed(false);
        })
        .catch(() => {
          // Keep any earlier live reading: it still says when it was taken.
          if (active) setFailed(true);
        });
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [incidentId]);

  const shown = live ?? snapshot;
  let note: string | null = null;
  if (!live) {
    note = failed
      ? 'From when the report came in. A fresh reading could not be fetched.'
      : 'From when the report came in. Checking current conditions...';
  } else if (failed) {
    note = 'The latest refresh failed; this is the last reading.';
  }

  return <ConditionsPanel conditions={shown} bare note={note} />;
}
