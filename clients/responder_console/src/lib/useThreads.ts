/**
 * Every reporter conversation, polled for the Communications tab and its badge.
 *
 * Polled at the app level, not inside the tab, so the tab label can say a
 * reporter is waiting for an answer while the coordinator is elsewhere.
 */

import { useCallback, useEffect, useState } from 'react';

import { coordinator, type ThreadSummary } from './api';

const POLL_MS = 10_000;

export function useThreads(enabled = true) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(() => {
    coordinator
      .threads()
      .then((next) => {
        setThreads(next);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh, enabled]);

  return { threads, loaded, refresh, awaiting: threads.filter((t) => t.awaiting_reply).length };
}
