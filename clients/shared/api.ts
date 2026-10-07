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
  /**
   * True when this turn is an apology for a model failure rather than a real
   * step (`action` is then `service_retry`). Offer "Try again", which calls
   * `reporter.retry`.
   */
  service_error: boolean;
}

/**
 * What went wrong while this incident was being built. Mirrors the record in
 * `backend/lifejacket/services/health.py`.
 */
export interface IncidentHealth {
  llm_calls: number;
  /** Extra attempts beyond the first, including ones that then succeeded. */
  llm_retries: number;
  /** Model calls that failed even after retries. */
  failed_calls: number;
  failures: { agent: string; kind: string; attempts: number; detail: string; at: string }[];
  /** Fail-safes used: `guardrail_check_failed`, `report_unavailable`. */
  fallbacks: string[];
  /** The reporter was asked to try again and has not yet. */
  awaiting_retry: boolean;
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
  /** Part of a possible mass stranding. The detail has the numbers. */
  in_mass_stranding: boolean;
  created_at: string;
  assigned_responder_id: string | null;
  /** First photo, relative to the API root. Use `absoluteUrl` to display it. */
  photo_url: string | null;
}

export interface PhotoRef {
  photo_id: string;
  /** Relative to the API root -- pass through `absoluteUrl` before display. */
  url: string;
  content_type: string | null;
  uploaded_at: string;
}

/**
 * A driving route for the map to draw.
 *
 * `source` distinguishes a real road route from the straight-line fallback
 * used when OpenRouteService is not configured. The console labels which,
 * because a straight line must never be read as a drive.
 */
export interface RouteLine {
  /** [[longitude, latitude], ...] -- GeoJSON order, as MapLibre expects. */
  coordinates: [number, number][];
  distance_km: number | null;
  duration_minutes: number | null;
  source: 'openrouteservice' | 'straight_line';
  from_name: string | null;
}

export interface ResponderOrg {
  responder_id: string;
  name: string;
  kind: string;
  phone: string | null;
  hotline: string | null;
  response_area: string | null;
  is_on_duty: boolean;
  /** Approximate: the centre of the area it covers, not a street address. */
  latitude: number | null;
  longitude: number | null;
  last_latitude: number | null;
  last_longitude: number | null;
}

/** Turn an API-relative path (`/incidents/x/photos/y`) into a usable URL. */
export function absoluteUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith('http') ? path : `${API_BASE}${path}`;
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

/**
 * Several cetaceans stranded at one place and time. Mirrors
 * `schemas.MassStranding`. Worked out from the incidents open at the moment
 * of the request, so it can appear on an incident after it was first shown.
 */
export interface MassStranding {
  /** A lower bound: reports of the same incident are not added together. */
  animal_count: number;
  animal_group: string;
  /** The separate incidents in the event, oldest first. */
  incident_ids: string[];
  /** Every report behind it, linked duplicates included. */
  report_count: number;
  reason: string;
}

/** Full incident detail. Mirrors `incidents.IncidentDetail`. */
export interface IncidentDetail extends Omit<MapPin, 'in_mass_stranding'> {
  updated_at: string;
  species_confidence: number | null;
  /** What the reporter photographed, beside the species derived from it. */
  photos: PhotoRef[];
  /**
   * Per-species probabilities inside the identified taxon. For an "Oceanic
   * dolphins" answer: common 0.50, bottlenose 0.44.
   */
  species_candidates: { common_name: string; scientific_name: string | null; confidence: number }[];
  severity_score: number | null;
  severity_reasons: string[];
  /** How many animals this report says are in trouble. 1 unless told otherwise. */
  animal_count: number;
  mass_stranding: MassStranding | null;
  report: IncidentReport | null;
  dispatch_candidates: DispatchCandidate[];
  transcript: { role: string; content: string; agent_name: string | null; created_at: string }[];
  environment: Record<string, unknown> | null;
  reporter_phone: string | null;
  duplicate_of: string | null;
  /**
   * A nearby recent incident that may be the same animal: close in place and
   * time, but the two reports disagree on the animal group, so this one was
   * not suppressed. Dispatched normally; the coordinator decides. Null when
   * `duplicate_of` is set or the match was weak.
   */
  possible_duplicate: {
    incident_id: string;
    confidence: number;
    distance_km: number;
    hours_apart: number;
    same_species: boolean;
    reason: string;
  } | null;
  /** True when the guardrail check failed or triage confidence was low. */
  requires_human_review: boolean;
  guardrail: Record<string, unknown> | null;
  /** Null for incidents created before health was recorded. */
  health: IncidentHealth | null;
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

  /**
   * Run the last step again after a `service_error` turn. Adds nothing to the
   * conversation, unlike `reply`.
   */
  retry: (incidentId: string) =>
    request<Turn>(`/intake/${incidentId}/retry`, { method: 'POST' }),

  /** Current state without advancing it -- used when the app reopens. */
  getState: (incidentId: string) => request<Turn>(`/intake/${incidentId}`),

  /** Who is coming, and how far away. Poll while an incident is active. */
  getEtas: (incidentId: string) =>
    request<ResponderEta[]>(`/responders/incident/${incidentId}/eta`),
};

// --- Responder endpoints --------------------------------------------------

export const responder = {
  listIncidents: (options?: {
    near?: { latitude: number; longitude: number; radiusKm?: number };
    /** Also return resolved and guidance-only incidents, for a history view. */
    includeClosed?: boolean;
  }) => {
    const params = new URLSearchParams();
    if (options?.near) {
      params.set('latitude', String(options.near.latitude));
      params.set('longitude', String(options.near.longitude));
      params.set('radius_km', String(options.near.radiusKm ?? 50));
    }
    if (options?.includeClosed) params.set('include_closed', 'true');
    const query = params.toString();
    return request<MapPin[]>(`/incidents${query ? `?${query}` : ''}`);
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

  list: (onDutyOnly = false) =>
    request<ResponderOrg[]>(`/responders?on_duty_only=${onDutyOnly}`),

  /**
   * Driving route from a rescue centre to an incident.
   *
   * Routed through the backend rather than calling OpenRouteService here, so
   * the routing key is never shipped to a browser.
   */
  getRoute: (incidentId: string, responderId: string) =>
    request<RouteLine>(
      `/incidents/${incidentId}/route?responder_id=${encodeURIComponent(responderId)}`,
    ),
};

// --- Coordination ---------------------------------------------------------

export interface CoordinationCheck {
  incident_id: string;
  status: 'completed' | 'held_for_review';
  attention_items: {
    task: {
      incident_id: string;
      kind: 'needs_assignment' | 'awaiting_response' | 'human_review';
      reason: string;
      source_refs: string[];
      derived: boolean;
    };
    proposed_next_step: string;
  }[];
  responders_for_review: {
    responder_id: string;
    name: string;
    kind: string;
    response_area: string | null;
    response_type: string | null;
    active_assignment_ids: number[];
    source_ref: string;
    availability_basis: string;
  }[];
  tool_calls: string[];
  limitations: string[];
  failure_reason: string | null;
  human_approval_required: boolean;
}

export const coordination = {
  handover: (start: string, end: string, signal?: AbortSignal) =>
    request<ShiftHandover>(`/coordination/handover?${new URLSearchParams({ start, end })}`, { signal }),
  /** Makes live model calls; retrieves records and proposes review, never dispatches. */
  checkCase: (incidentId: string, signal?: AbortSignal) =>
    request<CoordinationCheck>(
      `/coordination/incidents/${encodeURIComponent(incidentId)}/check`,
      { method: 'POST', signal },
    ),
};

export interface ShiftHandover {
  start: string;
  end: string;
  generated_at: string;
  scope: string;
  changes: {
    event_id: number;
    incident_id: string;
    recorded_at: string;
    kind: string;
    actor_ref: string | null;
    details: Record<string, unknown>;
    source_ref: string;
  }[];
  current_carryover: {
    incident_id: string;
    headline: string | null;
    status: string;
    severity_level: string | null;
    assigned_responder_id: string | null;
    tasks: CoordinationCheck['attention_items'][number]['task'][];
    source_ref: string;
  }[];
  changes_truncated: boolean;
  carryover_truncated: boolean;
  limitations: string[];
}

// --- Display helpers ------------------------------------------------------

/**
 * Colour for a severity band.
 *
 * The only place a client is allowed to map a backend value to presentation.
 * Note it switches on `severity_level`, which the backend computed -- the
 * client never derives severity from condition flags itself.
 *
 * Tuned for the navy ground in `theme.ts`: the earlier set was picked against
 * white and went muddy on a dark background, which matters when the colour is
 * the only thing separating "critical" from "monitor" at a glance.
 */
export function severityColour(level: string | null): string {
  switch (level) {
    case 'critical':
      return '#FF6B6B';
    case 'respond':
      return '#FF9F45';
    case 'monitor':
      return '#FFC043';
    case 'guidance':
      return '#5BD99A';
    default:
      return '#8D99AE';
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
