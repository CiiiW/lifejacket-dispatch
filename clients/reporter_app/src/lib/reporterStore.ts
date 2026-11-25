/**
 * What this phone remembers between launches: the reporter's number, the
 * reports it has filed with the key each came with, and which team messages
 * have been read.
 *
 * One small JSON file in the app's own documents folder (sandboxed, and
 * encrypted by the device when locked). A report's key is what lets the app
 * read its status and the rescue team's messages (`POST /intake/my-reports`,
 * `/intake/{id}/messages`); losing the file loses access to those threads,
 * not the reports, which the rescue network still has.
 *
 * Uses expo-file-system's stable `legacy` API, which Expo Go ships, rather
 * than adding a storage dependency.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  documentDirectory,
  getInfoAsync,
  readAsStringAsync,
  writeAsStringAsync,
} from 'expo-file-system/legacy';

export interface SavedReport {
  incidentId: string;
  /** Proves this device filed the report. Never sent in a URL. */
  key: string;
  startedAt: string;
  latitude: number | null;
  longitude: number | null;
}

interface Saved {
  version: 1;
  phone: string | null;
  /** Newest first. */
  reports: SavedReport[];
  /** Team messages already seen, per report: the unread count is the rest. */
  seenTeam: Record<string, number>;
}

const EMPTY: Saved = { version: 1, phone: null, reports: [], seenTeam: {} };
const FILE = documentDirectory ? `${documentDirectory}lifejacket-reporter.json` : null;
/** The server answers for at most 50 reports per request. */
export const MAX_REPORTS = 50;

function isReport(value: unknown): value is SavedReport {
  const r = value as SavedReport;
  return !!r && typeof r.incidentId === 'string' && typeof r.key === 'string';
}

async function load(): Promise<Saved> {
  if (!FILE) return EMPTY;
  try {
    if (!(await getInfoAsync(FILE)).exists) return EMPTY;
    const parsed = JSON.parse(await readAsStringAsync(FILE)) as Partial<Saved>;
    return {
      version: 1,
      phone: typeof parsed.phone === 'string' && parsed.phone ? parsed.phone : null,
      reports: Array.isArray(parsed.reports) ? parsed.reports.filter(isReport) : [],
      seenTeam: parsed.seenTeam && typeof parsed.seenTeam === 'object' ? parsed.seenTeam : {},
    };
  } catch (error) {
    // A damaged file must not lock someone out of reporting.
    console.warn('[LifeJacket] could not read saved reports:', error);
    return EMPTY;
  }
}

export function useReporterStore() {
  const [state, setState] = useState<Saved>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const writing = useRef(Promise.resolve());

  useEffect(() => {
    let active = true;
    void load().then((saved) => {
      if (!active) return;
      setState(saved);
      setLoaded(true);
    });
    return () => {
      active = false;
    };
  }, []);

  // Write after every change -- but only once the file has been read, or the
  // empty default would overwrite it. Writes are queued so they land in order.
  useEffect(() => {
    if (!loaded || !FILE) return;
    const text = JSON.stringify(state);
    writing.current = writing.current
      .then(() => writeAsStringAsync(FILE, text))
      .catch((error) => console.warn('[LifeJacket] could not save reports:', error));
  }, [state, loaded]);

  const setPhone = useCallback((phone: string) => setState((s) => ({ ...s, phone })), []);

  const addReport = useCallback(
    (report: SavedReport) =>
      setState((s) =>
        s.reports.some((r) => r.incidentId === report.incidentId)
          ? s
          : { ...s, reports: [report, ...s.reports].slice(0, MAX_REPORTS) },
      ),
    [],
  );

  const placeReport = useCallback(
    (incidentId: string, latitude: number, longitude: number) =>
      setState((s) => ({
        ...s,
        reports: s.reports.map((r) =>
          r.incidentId === incidentId ? { ...r, latitude, longitude } : r,
        ),
      })),
    [],
  );

  const markSeen = useCallback(
    (incidentId: string, teamCount: number) =>
      setState((s) =>
        (s.seenTeam[incidentId] ?? 0) >= teamCount
          ? s
          : { ...s, seenTeam: { ...s.seenTeam, [incidentId]: teamCount } },
      ),
    [],
  );

  return {
    loaded,
    phone: state.phone,
    reports: state.reports,
    seenTeam: state.seenTeam,
    setPhone,
    addReport,
    placeReport,
    markSeen,
  };
}
