/**
 * Messages from the rescue team about this report, polled while one exists.
 *
 * Reading them needs the key `/intake/start` returned, not just the incident
 * ID (see `backend/lifejacket/services/reporter_thread.py`). The app saves
 * each report's key on the phone (`reporterStore.ts`), so a conversation
 * survives closing the app.
 */

import { useCallback, useEffect, useState } from 'react';

import { reporter, type ReporterMessage } from './api';

const POLL_MS = 4000;

export function useTeamThread(incidentId: string | null, reporterKey: string | null) {
  const [messages, setMessages] = useState<ReporterMessage[]>([]);

  const refresh = useCallback(async () => {
    if (!incidentId || !reporterKey) return;
    try {
      setMessages(await reporter.teamMessages(incidentId, reporterKey));
    } catch {
      // Keep the last good copy on screen; the next poll tries again.
    }
  }, [incidentId, reporterKey]);

  useEffect(() => {
    setMessages([]);
    if (!incidentId || !reporterKey) return;
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [incidentId, reporterKey, refresh]);

  /** Throws the API's error, so the caller can show why a reply failed. */
  const reply = useCallback(
    async (body: string) => {
      if (!incidentId || !reporterKey) return;
      await reporter.replyToTeam(incidentId, reporterKey, body);
      await refresh();
    },
    [incidentId, reporterKey, refresh],
  );

  return { messages, reply };
}
