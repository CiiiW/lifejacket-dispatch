import type { Turn } from '../../../shared/api';

export type PhoneUser = { uid: string; phoneNumber: string | null; getIdToken: (force?: boolean) => Promise<string> };
export type Draft = { turn: Turn; draft_key: string; expires_at: string };
export type ReportStatus = {
  case_id: string; phase: string; message: string; arrival_eta_minutes: number | null;
  eta_updated_at: string | null; eta_is_estimate: boolean; presence: string;
  reporter_can_leave: boolean; leaving_cancels_report: boolean;
};
export type ReportReceipt = { case_id: string; submitted_at: string };

export function createPhoneReporterApi(base: string, transport: typeof fetch = fetch, timeoutMs = 60000) {
  const url = new URL(base);
  if (url.username || url.password || url.search || url.hash ||
    (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(url.hostname))))
    throw new Error('A secure reporter API address is required.');
  const root = url.href.replace(/\/$/, '');
  const id = (value: string) => {
    if (!/^[A-Za-z0-9_-]{1,40}$/.test(value)) throw new Error('Report unavailable.');
    return value;
  };
  async function request<T>(path: string, payload: Record<string, unknown> | FormData, user?: PhoneUser): Promise<T> {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    try {
      return await Promise.race([
        new Promise<never>((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('Request timed out. Check its status before trying again.')); }, timeoutMs); }),
        (async () => {
          const token = user ? await user.getIdToken() : null;
          if (controller.signal.aborted) throw new Error('Request timed out.');
          const form = payload instanceof FormData;
          const response = await transport(`${root}/reporter${path}`, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
            headers: form ? {} : { 'Content-Type': 'application/json' },
            body: form ? payload : JSON.stringify({ ...payload, ...(user ? { id_token: token } : {}) }),
          });
          if (!response.ok) throw new Error(response.status === 401 ? 'Verify your phone number again.' : response.status === 404 ? 'This report or draft is unavailable to this session.' : response.status === 503 ? 'Reporting setup is not complete yet. Please try later.' : 'The request was not completed. Check the report and try again.');
          return await response.json() as T;
        })(),
      ]);
    } catch (error) {
      if (error instanceof Error && /^(Verify|This report|Reporting setup|The request|Request timed)/.test(error.message)) throw error;
      throw new Error('Could not connect to LifeJacket. Please try again.');
    } finally { clearTimeout(timer!); }
  }
  return {
    start: () => request<Draft>('/drafts', {}),
    turn: (draft: Draft, action: Record<string, unknown>) => request<Turn>(`/drafts/${id(draft.turn.incident_id)}/turn`, { ...action, draft_key: draft.draft_key }),
    photo: (draft: Draft, file: File) => {
      const form = new FormData(); form.append('draft_key', draft.draft_key); form.append('file', file);
      return request<Turn>(`/drafts/${id(draft.turn.incident_id)}/photo`, form);
    },
    submit: (draft: Draft, user: PhoneUser, channels: string[]) => request<{ case_id: string; submitted: boolean }>(`/drafts/${id(draft.turn.incident_id)}/submit`, { draft_key: draft.draft_key, contact_channels: channels }, user),
    reports: (user: PhoneUser) => request<ReportReceipt[]>('/reports', {}, user),
    status: (caseId: string, user: PhoneUser) => request<ReportStatus>(`/reports/${id(caseId)}/status`, {}, user),
    presence: (caseId: string, user: PhoneUser, presence: string) => request(`/reports/${id(caseId)}/presence`, { presence }, user),
  };
}
export type PhoneReporterApi = ReturnType<typeof createPhoneReporterApi>;
