/** Dedicated authenticated network access. Never falls back to the legacy API. */
export type NetworkRole =
  'reporter' | 'volunteer' | 'noaa' | 'center_coordinator' | 'rescuer';
export type CaseScope =
  | 'all_allowed'
  | 'my_center'
  | 'assigned_to_me'
  | 'leading'
  | 'supporting'
  | 'receiving';
export interface NetworkSession {
  account_id: string;
  role: NetworkRole;
  selected_organization_id: string | null;
  authorized_states: string[];
  email: string | null;
  email_verified: boolean;
  organizations: {
    organization_id: string;
    name: string;
    role: NetworkRole;
    states: string[];
  }[];
}
export interface NetworkCase {
  incident_id: string;
  status: string;
  state_code: string | null;
  latitude: number | null;
  longitude: number | null;
  animal_group: string | null;
  species_common_name: string | null;
  severity_level: string | null;
  lead_organization_id: string | null;
  created_at: string;
}
export interface ReporterUpdate {
  case_id: string;
  phase: string;
  message: string;
  arrival_eta_minutes: number | null;
  eta_is_estimate: boolean;
  reporter_can_leave: boolean;
  leaving_cancels_report: boolean;
}
export interface CaseResponse {
  case_id: string;
  phase: string;
  revision: number;
  allowed_transitions: string[];
  contact_channels: ('phone' | 'text')[];
  closure_reasons: string[];
}
export interface CaseContact {
  case_id: string;
  phone_number: string;
  channels: ('phone' | 'text')[];
  presence: string;
}
export interface TokenUser {
  uid: string;
  getIdToken(forceRefresh?: boolean): Promise<string>;
}
export class NetworkError extends Error {
  readonly status: number;
  constructor(status: number) {
    super('Network request unavailable');
    this.status = status;
  }
}
export function networkErrorMessage(error: unknown): string {
  if (error instanceof NetworkError) {
    if (error.status === 401)
      return 'Your sign-in has expired. Sign out and sign in again.';
    if (error.status === 403)
      return 'This access is no longer approved. Return to your personal account or contact your coordinator.';
    if (error.status === 404)
      return 'This case is unavailable for your account.';
    if (error.status === 409)
      return 'This case changed. Refresh it before confirming another update.';
    if (error.status === 503)
      return 'Network access is temporarily unavailable. Please try again later.';
  }
  return 'Unable to load this view. Check your connection and try again.';
}
export interface NetworkApi {
  me(signal?: AbortSignal): Promise<NetworkSession>;
  cases(
    scope: CaseScope,
    offset: number,
    signal?: AbortSignal,
  ): Promise<NetworkCase[]>;
  case(id: string, signal?: AbortSignal): Promise<NetworkCase>;
  report(id: string, signal?: AbortSignal): Promise<ReporterUpdate>;
  response(id: string, signal?: AbortSignal): Promise<CaseResponse>;
  changeResponse(
    id: string,
    revision: number,
    phase: string,
    closureReason: string | null,
    signal?: AbortSignal,
  ): Promise<CaseResponse>;
  contact(id: string, signal?: AbortSignal): Promise<CaseContact>;
}
export function createNetworkApi(
  baseUrl: string,
  user: TokenUser,
  organization: string | null,
  transport: typeof fetch = fetch,
  timeoutMs = 15000,
): NetworkApi {
  const base = new URL(baseUrl);
  if (
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    (base.protocol !== 'https:' &&
      !(
        base.protocol === 'http:' &&
        ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)
      ))
  ) {
    throw new Error(
      'Use an HTTPS API endpoint (or local development loopback)',
    );
  }
  if (organization !== null && !/^[A-Za-z0-9_-]{1,64}$/.test(organization))
    throw new Error('Invalid organization');
  const prefix = base.href.replace(/\/$/, '');
  async function request<T>(
    path: string,
    signal?: AbortSignal,
    body?: Record<string, unknown>,
  ): Promise<T> {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (signal?.aborted) cancel();
    signal?.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(cancel, timeoutMs);
    let tokenCancelled: (() => void) | undefined;
    try {
      // The SDK token refresh cannot be cancelled, but its late result must
      // never send an HTTP request after sign-out/context change or timeout.
      const token = await new Promise<string>((resolve, reject) => {
        tokenCancelled = () =>
          reject(new DOMException('Request cancelled', 'AbortError'));
        if (controller.signal.aborted) {
          tokenCancelled();
          return;
        }
        controller.signal.addEventListener('abort', tokenCancelled, {
          once: true,
        });
        user.getIdToken().then(resolve, reject);
      });
      if (controller.signal.aborted)
        throw new DOMException('Request cancelled', 'AbortError');
      if (!token) throw new NetworkError(401);
      const response = await transport(prefix + path, {
        method: body ? 'PATCH' : 'GET',
        ...(body ? { body: JSON.stringify(body) } : {}),
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(organization
            ? { 'X-LifeJacket-Organization': organization }
            : {}),
        },
        signal: controller.signal,
        credentials: 'same-origin',
        cache: 'no-store',
        redirect: 'error',
      });
      if (!response.ok) throw new NetworkError(response.status);
      return (await response.json()) as T;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      if (tokenCancelled)
        controller.signal.removeEventListener('abort', tokenCancelled);
    }
  }

  function caseId(id: string) {
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new NetworkError(404);
    return encodeURIComponent(id);
  }
  return {
    me: (signal) => request('/access/me', signal),
    cases: (scope, offset, signal) => {
      if (
        ![
          'all_allowed',
          'my_center',
          'assigned_to_me',
          'leading',
          'supporting',
          'receiving',
        ].includes(scope) ||
        !Number.isInteger(offset) ||
        offset < 0 ||
        offset > 100000
      )
        throw new Error('Invalid case query');
      return request(
        `/network/cases?scope=${scope}&limit=50&offset=${offset}`,
        signal,
      );
    },
    case: (id, signal) => request(`/network/cases/${caseId(id)}`, signal),
    report: (id, signal) => request(`/network/reports/${caseId(id)}`, signal),
    response: (id, signal) =>
      request(`/network/cases/${caseId(id)}/response`, signal),
    contact: (id, signal) =>
      request(`/network/cases/${caseId(id)}/reporter-contact`, signal),
    changeResponse: (id, revision, phase, closureReason, signal) => {
      if (
        !Number.isInteger(revision) ||
        revision < 0 ||
        ![
          'accepted',
          'en_route',
          'on_scene',
          'animal_located',
          'closed',
        ].includes(phase)
      )
        throw new Error('Invalid response update');
      return request(`/network/cases/${caseId(id)}/response`, signal, {
        revision,
        phase,
        confirmed: true,
        closure_reason: closureReason,
      });
    },
  };
}
