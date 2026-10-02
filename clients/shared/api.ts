/**
 * Shared API client for both apps.
 *
 * Every call the clients make goes through here, so the base URL, error
 * handling, and response types are defined once. Copy or symlink this file
 * into each app's `src/lib/` during setup, or publish it as a local workspace
 * package once the apps stabilise.
 *
 * The types below mirror the Pydantic response models in
 * `backend/lifejacket/api/routes/`. When you change a route's response, change
 * the matching interface here -- nothing checks this automatically yet.
 */

/** Set `EXPO_PUBLIC_API_URL` to your machine's LAN IP when testing on a phone. */
export const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

// --- Response types -------------------------------------------------------

/** One turn of the intake conversation. Mirrors `intake.TurnResponse`. */
export interface Turn {
  incident_id: string;
  message: string | null;
  /** Non-empty when the answer should be a tap, not typing. */
  options: string[];
  awaiting_reply: boolean;
  complete: boolean;
  /** Drives the UI mode: `request_photo` opens the camera, etc. */
  action: string | null;
  stage: string;
  questions_asked: number;
  /** Best identification so far, e.g. "Oceanic dolphins". */
  identified_as: string | null;
  /** species | genus | family | group -- how specific `identified_as` is. */
  taxon_rank: string | null;
  severity_level: string | null;
  report_headline: string | null;
}

/** An incident as a map pin. Mirrors `incidents.MapPin`. */
export interface MapPin {
  incident_id: string;
  latitude: number | null;
  longitude: number | null;
  place_name: string | null;
  status: string;
  severity_level: string | null;
  species_common_name: string | null;
  taxon_rank: string | null;
  animal_group: string | null;
  headline: string | null;
  entanglement: boolean | null;
  created_at: string;
  assigned_responder_id: string | null;
}

export interface IncidentReport {
  headline: string;
  summary: string;
  recommended_actions: string[];
  access_notes: string | null;
  equipment_suggestions: string[];
  hazard_warnings: string[];
  unknowns: string[];
  reporter_contact_note: string | null;
}

export interface DispatchCandidate {
  responder_id: string;
  name: string;
  kind: string;
  score: number;
  distance_km: number | null;
  eta_minutes: number | null;
  rationale: string;
  matched_capabilities: string[];
  contact_phone: string | null;
  contact_email: string | null;
}

/** Full incident detail. Mirrors `incidents.IncidentDetail`. */
export interface IncidentDetail extends MapPin {
  updated_at: string;
  species_confidence: number | null;
  /**
   * Per-species probabilities inside the identified taxon. For an "Oceanic
   * dolphins" answer: common 0.50, bottlenose 0.44.
   */
  species_candidates: { common_name: string; scientific_name: string | null; confidence: number }[];
  severity_score: number | null;
  severity_reasons: string[];
  report: IncidentReport | null;
  dispatch_candidates: DispatchCandidate[];
  transcript: { role: string; content: string; agent_name: string | null; created_at: string }[];
  environment: Record<string, unknown> | null;
  reporter_phone: string | null;
  duplicate_of: string | null;
  /** True when the guardrail check failed or triage confidence was low. */
  requires_human_review: boolean;
  guardrail: Record<string, unknown> | null;
}

export interface ResponderEta {
  responder_id: string;
  name: string;
  latitude: number | null;
  longitude: number | null;
  distance_km: number | null;
  eta_minutes: number | null;
  status: string;
}

// --- Transport ------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Make a request and parse the JSON response.
 *
 * FastAPI returns errors as `{"detail": "..."}`, so that message is surfaced
 * rather than a bare status code -- the detail is usually the actionable part
 * ("'enormous' is not a valid answer for 'reported_size'").
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // Body was not JSON; the status text is the best we have.
    }
    throw new ApiError(detail, response.status);
  }

  return response.json() as Promise<T>;
}

// --- Reporter endpoints ---------------------------------------------------

export const reporter = {
  start: (reporterPhone?: string) =>
    request<Turn>('/intake/start', {
      method: 'POST',
      body: JSON.stringify({ reporter_phone: reporterPhone ?? null }),
    }),

  /**
   * Upload a photo.
   *
   * React Native's `fetch` accepts `{uri, name, type}` as a FormData file,
   * which is not valid DOM typing -- hence the cast. On web, pass a real Blob.
   */
  uploadPhoto: (incidentId: string, uri: string, mimeType = 'image/jpeg') => {
    const form = new FormData();
    form.append('file', { uri, name: 'photo.jpg', type: mimeType } as unknown as Blob);
    return request<Turn>(`/intake/${incidentId}/photo`, { method: 'POST', body: form });
  },

  setLocation: (incidentId: string, latitude: number, longitude: number, accuracy?: number) =>
    request<Turn>(`/intake/${incidentId}/location`, {
      method: 'POST',
      body: JSON.stringify({ latitude, longitude, accuracy_meters: accuracy ?? null }),
    }),

  reply: (incidentId: string, text: string) =>
    request<Turn>(`/intake/${incidentId}/reply`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),

  /** Current state without advancing it -- used when the app reopens. */
  getState: (incidentId: string) => request<Turn>(`/intake/${incidentId}`),

  /** Who is coming, and how far away. Poll while an incident is active. */
  getEtas: (incidentId: string) =>
    request<ResponderEta[]>(`/responders/incident/${incidentId}/eta`),
};

// --- Responder endpoints --------------------------------------------------

export const responder = {
  listIncidents: (near?: { latitude: number; longitude: number; radiusKm?: number }) => {
    const query = near
      ? `?latitude=${near.latitude}&longitude=${near.longitude}&radius_km=${near.radiusKm ?? 50}`
      : '';
    return request<MapPin[]>(`/incidents${query}`);
  },

  getIncident: (incidentId: string) => request<IncidentDetail>(`/incidents/${incidentId}`),

  updateStatus: (incidentId: string, status: string, responderId?: string) =>
    request<{ incident_id: string; status: string }>(`/incidents/${incidentId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status, responder_id: responderId ?? null }),
    }),

  /** Close an incident with the responder's notes. */
  logIncident: (
    incidentId: string,
    body: {
      responder_id: string;
      confirmed_species?: string;
      outcome?: string;
      actions_taken?: string;
      notes?: string;
      report_was_accurate?: boolean;
    },
  ) =>
    request<{ incident_id: string; status: string; logged: boolean }>(
      `/incidents/${incidentId}/log`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  /** Push the responder's live position so the reporter can watch them approach. */
  updateLocation: (responderId: string, latitude: number, longitude: number) =>
    request<{ responder_id: string }>(`/responders/${responderId}/location`, {
      method: 'POST',
      body: JSON.stringify({ latitude, longitude }),
    }),

  setDuty: (responderId: string, isOnDuty: boolean) =>
    request<{ responder_id: string; is_on_duty: boolean }>(
      `/responders/${responderId}/duty`,
      { method: 'POST', body: JSON.stringify({ is_on_duty: isOnDuty }) },
    ),

  list: (onDutyOnly = false) => request<unknown[]>(`/responders?on_duty_only=${onDutyOnly}`),
};

// --- Display helpers ------------------------------------------------------

/**
 * Colour for a severity band.
 *
 * The only place a client is allowed to map a backend value to presentation.
 * Note it switches on `severity_level`, which the backend computed -- the
 * client never derives severity from condition flags itself.
 */
export function severityColour(level: string | null): string {
  switch (level) {
    case 'critical':
      return '#b3261e';
    case 'respond':
      return '#e8710a';
    case 'monitor':
      return '#f9ab00';
    case 'guidance':
      return '#1e8e3e';
    default:
      return '#5f6368';
  }
}

export function severityLabel(level: string | null): string {
  switch (level) {
    case 'critical':
      return 'Critical';
    case 'respond':
      return 'Respond';
    case 'monitor':
      return 'Monitor';
    case 'guidance':
      return 'Guidance only';
    default:
      return 'Unknown';
  }
}
