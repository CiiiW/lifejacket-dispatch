/**
 * Status and thread summary for every report this phone holds, kept fresh.
 *
 * One request for all of them (`POST /intake/my-reports`, keys in the body)
 * every 15 seconds: often enough that a team's message or "on the way" shows
 * up while someone waits on the beach, gentle enough on battery.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { reporter, type MyReport } from './api';
import { MAX_REPORTS, type SavedReport } from './reporterStore';

const POLL_MS = 15_000;

export function useMyReports(reports: SavedReport[]) {
  const [byId, setById] = useState<Record<string, MyReport>>({});
  // Which reports the server still recognises, from the last answer that
  // arrived; null until one has. A report deleted on the server, or from a
  // database that was reset, stops being listed rather than lingering.
  const [known, setKnown] = useState<Set<string> | null>(null);
  const refs = useMemo(
    () =>
      reports
        .slice(0, MAX_REPORTS)
        .map((r) => ({ incident_id: r.incidentId, reporter_key: r.key })),
    [reports],
  );

  const refresh = useCallback(() => {
    if (refs.length === 0) return;
    reporter
      .myReports(refs)
      .then((list) => {
        setById(Object.fromEntries(list.map((r) => [r.incident_id, r])));
        setKnown(new Set(list.map((r) => r.incident_id)));
      })
      .catch(() => {
        // Keep the last good copy; the next poll tries again.
      });
  }, [refs]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return { byId, known, refresh };
}
