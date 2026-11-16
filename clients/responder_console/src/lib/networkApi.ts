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
  drones?: DroneApi;
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
    body?: Record<string, unknown> | FormData,
    method?: string,
    blob = false,
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
        method: method ?? (body ? 'PATCH' : 'GET'),
        ...(body ? { body: body instanceof FormData ? body : JSON.stringify(body) } : {}),
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
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
      return (blob ? await response.blob() : await response.json()) as T;
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
  function followupPath(id:string,r:string) {
    return '/network/cases/'+caseId(id)+'/drone-requests/'+caseId(r);
  }
  function streamPath(id:string,r:string) {
    return '/network/cases/'+caseId(id)+'/drone-requests/'+caseId(r)+'/streams';
  }
  return {
    drones: {
      detectorInput:(id,r,e,s)=>request(followupPath(id,r)+'/evidence/'+caseId(e)+'/detector-input',s),
      attachDetectorResult:(id,r,e,b,s)=>request(followupPath(id,r)+'/evidence/'+caseId(e)+'/detector-result',s,b,'POST'),
      frameAnalyses:(id,r,s)=>request(followupPath(id,r)+'/analysis',s),
      queueFrameAnalysis:(id,r,e,b,s)=>request(followupPath(id,r)+'/evidence/'+caseId(e)+'/analysis',s,b,'POST'),
      reminderStatus:(id,r,s)=>request(followupPath(id,r)+'/reminders',s),
      retryReminder:(id,r,b,s)=>request(followupPath(id,r)+'/reminders/retry',s,b,'POST'),
      recordings:(id,r,t,s)=>request(streamPath(id,r)+'/'+caseId(t)+'/recordings',s),
      recordingVideo:(id,r,t,v,g,s)=>request(streamPath(id,r)+'/'+caseId(t)+'/recordings/'+caseId(v)+'/'+caseId(g),s,undefined,'GET',true),
      streams:(id,r,s)=>request(streamPath(id,r),s),
      openStream:(id,r,b,s)=>request(streamPath(id,r),s,b,'POST'),
      streamPreview:(id,r,t,s)=>request(streamPath(id,r)+'/'+caseId(t)+'/preview',s),
      captureStream:(id,r,t,b,s)=>request(streamPath(id,r)+'/'+caseId(t)+'/capture',s,b,'POST'),
      endStream:(id,r,t,b,s)=>request(streamPath(id,r)+'/'+caseId(t)+'/end',s,b,'POST'),
      attention:(offset,s)=>request(`/network/monitoring/attention?offset=${offset}&limit=50`,s),
      acknowledgeAttention:(id,r,b,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}/attention`,s,b,'POST'),
      comparison:(id,r,previous,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}/comparison${previous?'?previous_id='+caseId(previous):''}`,s),
      monitoringQueue:(offset,s)=>request(`/network/monitoring?offset=${offset}&limit=50`,s),
      monitoringDecision:(id,r,b,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}/monitoring`,s,b,"POST"),
      list:(id,s)=>request(`/network/cases/${caseId(id)}/drone-requests`,s),
      detail:(id,r,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}`,s),
      create:(id,b,s)=>request(`/network/cases/${caseId(id)}/drone-requests`,s,b,'POST'),
      change:(id,r,b,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}`,s,b),
      upload:(id,r,b,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}/evidence`,s,b,'POST'),
      photo:(id,r,e,s)=>request(`/network/cases/${caseId(id)}/drone-requests/${caseId(r)}/evidence/${caseId(e)}/photo`,s,undefined,'GET',true),
    },
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

export interface MonitoringItem {
 case_id:string; request_id:string; queue_status:string; request_status:string;
 next_review_at:string|null; objective:string; execution_kind:string; can_decide:boolean;
}
export interface DroneRequest {
 previous_request_id?:string; monitoring_root_request_id?:string;
 monitoring_decision?:{action:string;reason:string;next_request_id:string|null};
  suggestion_id?: string | null;
  request_id: string; case_id: string; status: string; revision: number;
  purpose: string; execution_kind: string; objective: string; reason: string;
  operator: string | null; next_review_at: string | null; escalation_criteria: string;
  target_location: {latitude:number|null;longitude:number|null};
  allowed_transitions: string[]; outcome: string|null; review_note?:string;
  evidence?: {evidence_id:string;description:string;source_kind:string;source_url:string|null;
    captured_at:string|null;frame_offset_seconds:number|null;rights_note:string;received_at?:string;source_session_id?:string}[];
  events?: {revision:number;kind:string;recorded_at:string;actor_user_id:string;note?:string}[];
}
export interface AttentionItem {
  case_id:string;request_id:string;revision:number;kind:'escalation'|'overdue';
  attention_key:string;reason:string|null;since:string|null;objective:string;
  execution_kind:string;can_acknowledge:boolean;
}
export interface ObservationComparison {
  case_id:string;intake:{recorded_at:string;animal_group:string|null;
    species_common_name:string|null;severity_level:string|null;injury_present:boolean|null;
    entanglement_present:boolean|null;confidence:{animal_group:number|null;condition:number|null}};
  current:DroneRequest;previous:DroneRequest|null;comparison_is_automated:false;
}
export interface RecordingSegment {
  segment_id:string;offset_seconds:number;duration_seconds:number;bytes:number;sha256:string;
}
export interface DroneRecording {
  recording_id:string;status:string;started_at:string;updated_at:string;
  segments:RecordingSegment[];error_code:string|null;
}
export interface DroneStream {
  stream_id:string;request_id:string;status:string;created_at:string;expires_at:string;
  last_frame_at:string|null;frame_age_seconds:number|null;can_manage:boolean;publish_url?:string;recording_enabled?:boolean;
  source:{label:string;source_kind:string;source_url:string|null;rights_note:string};
  frame?:{frame_id:string;received_at:string;jpeg_base64:string;sha256:string}|null;
}
export interface FrameAnalysis {
  provider?:string;analysis_id:string;evidence_id:string;stage:'detect'|'assess';status:string;request_key:string;
  detection_job_id:string|null;animal_index:number|null;error_code:string|null;attempts:number;created_at:string;
  result:{model?:string;model_version?:string;detections?:{label?:string;description?:string;confidence?:number}[];limitations?:string[];
    identity_summary?:{name:string;confidence:number|null};
    assessment?:{injury?:{summary?:string};severity_level?:string}}|null;
}
export interface ReminderStatus {
  enabled:boolean;destination_configured:boolean;worker:{running:boolean;last_seen_at:string|null};
  items:{notification_id:string;kind:string;status:string;attempts:number;error_code:string|null}[];
}
export interface DroneApi {
  detectorInput?(id:string,r:string,e:string,signal?:AbortSignal):Promise<Record<string,unknown>>;
  attachDetectorResult?(id:string,r:string,e:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<FrameAnalysis>;
  recordings?(id:string,r:string,t:string,signal?:AbortSignal):Promise<{enabled:boolean;recordings:DroneRecording[];time_note:string}>;
  recordingVideo?(id:string,r:string,t:string,v:string,g:string,signal?:AbortSignal):Promise<Blob>;
  frameAnalyses?(id:string,r:string,signal?:AbortSignal):Promise<{jobs:FrameAnalysis[];worker:{running:boolean}}>;
  queueFrameAnalysis?(id:string,r:string,e:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<FrameAnalysis>;
  reminderStatus?(id:string,r:string,signal?:AbortSignal):Promise<ReminderStatus>;
  retryReminder?(id:string,r:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<unknown>;
  streams?(id:string,r:string,signal?:AbortSignal):Promise<{streams:DroneStream[]}>;
  openStream?(id:string,r:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<DroneStream>;
  streamPreview?(id:string,r:string,t:string,signal?:AbortSignal):Promise<DroneStream>;
  captureStream?(id:string,r:string,t:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<unknown>;
  endStream?(id:string,r:string,t:string,b:Record<string,unknown>,signal?:AbortSignal):Promise<unknown>;
  attention?(offset:number,signal?:AbortSignal):Promise<{items:AttentionItem[];total:number}>;
  acknowledgeAttention?(id:string,r:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<DroneRequest>;
  comparison?(id:string,r:string,previous:string|undefined,signal?:AbortSignal):Promise<ObservationComparison>;
  monitoringQueue?(offset:number,signal?:AbortSignal):Promise<{items:MonitoringItem[];total:number;due_soon_hours:number}>;
  monitoringDecision?(id:string,requestId:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<DroneRequest>;
  list(id:string,signal?:AbortSignal):Promise<{can_create:boolean;requests:DroneRequest[];suggestions?:DroneSuggestion[];confidence_summary?:{animal_group:number|null;condition:number|null}}>;
  detail(id:string,requestId:string,signal?:AbortSignal):Promise<DroneRequest>;
  create(id:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<DroneRequest>;
  change(id:string,requestId:string,body:Record<string,unknown>,signal?:AbortSignal):Promise<DroneRequest>;
  upload(id:string,requestId:string,body:FormData,signal?:AbortSignal):Promise<unknown>;
  photo(id:string,requestId:string,evidenceId:string,signal?:AbortSignal):Promise<Blob>;
}

export interface DroneSuggestion {
  suggestion_id:string; purpose:'verification'; title:string; objective:string; reason:string;
  signals:{code:string;label:string;confidence:number|null;reason:string}[];
  threshold:number; threshold_is_validated:false; policy_version:string;
  urgent_parallel_review:boolean; response_note:string; escalation_criteria:string;
}
