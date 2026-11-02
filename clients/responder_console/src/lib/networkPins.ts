import type { MapPin } from './api';
import type { NetworkCase } from './networkApi';

/**
 * A permissioned case as a map pin. Fields `/network/cases` does not return are
 * left empty rather than looked up elsewhere: there is deliberately no fallback
 * to the unauthenticated `/incidents` API.
 */
export function toMapPin(row: NetworkCase): MapPin {
  return {
    incident_id: row.incident_id,
    latitude: row.latitude,
    longitude: row.longitude,
    place_name: null,
    status: row.status,
    severity_level: row.severity_level,
    species_common_name: row.species_common_name,
    taxon_rank: null,
    animal_group: row.animal_group,
    headline: null,
    entanglement: null,
    in_mass_stranding: false,
    created_at: row.created_at,
    assigned_responder_id: null,
    photo_url: null,
  };
}
