/** Read-only synthetic data for map + drone navigation checks. No network calls. */
import { NetworkError, type DroneApi, type DroneRequest } from '../src/lib/networkApi';

export function networkDroneFixture(visibleIds: () => string[]): DroneApi {
  const rows = [
    ['fixture-one', 'fictional_ca_1', 'Fixture request ONE'],
    ['fixture-three', 'fictional_ca_1', 'Fixture request THREE'],
    ['fixture-two', 'fictional_ca_2', 'Fixture request TWO'],
  ].map(([request_id, case_id, objective]) => ({
    request_id, case_id, objective, purpose: 'monitoring', reason: 'Synthetic navigation check',
    execution_kind: 'recorded_demo', status: 'requested', revision: 0,
    operator: null, outcome: null, allowed_transitions: [], evidence: [], events: [],
    next_review_at: '2026-01-01T12:00:00Z', escalation_criteria: 'Coordinator review',
    target_location: {latitude: 36.95, longitude: -122.02},
  } as DroneRequest));
  const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
  const permitted = () => rows.filter(row => visibleIds().includes(row.case_id));
  const denied = async (): Promise<never> => {throw new NetworkError(403);};
  return {
    list: async id => {
      if (!visibleIds().includes(id)) throw new NetworkError(404);
      return {can_create: false, requests: clone(permitted().filter(row => row.case_id === id)),
        suggestions: [], confidence_summary: {animal_group: .95, condition: .5}};
    },
    detail: async (id, requestId) => {
      const row = permitted().find(row => row.case_id === id && row.request_id === requestId);
      if (!row) throw new NetworkError(404);
      return clone(row);
    },
    create: denied, change: denied, upload: denied, photo: denied,
    monitoringQueue: async offset => {
      const items = permitted().map(row => ({
        case_id: row.case_id, request_id: row.request_id, request_status: row.status,
        queue_status: 'overdue' as const, next_review_at: row.next_review_at,
        execution_kind: row.execution_kind, objective: row.objective, can_decide: false,
      }));
      return {items: clone(items.slice(offset, offset + 50)), total: items.length,
        due_soon_hours: 24};
    },
    attention: async offset => {
      const items = permitted().slice(0, 1).map(row => ({
        case_id: row.case_id, request_id: row.request_id, revision: 0,
        kind: 'overdue' as const, attention_key: 'synthetic-attention',
        reason: 'Synthetic navigation check', since: row.next_review_at,
        objective: row.objective, execution_kind: row.execution_kind, can_acknowledge: false,
      }));
      return {items: clone(items.slice(offset, offset + 50)), total: items.length};
    },
  };
}
