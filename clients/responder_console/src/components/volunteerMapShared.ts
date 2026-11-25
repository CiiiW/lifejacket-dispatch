/**
 * Shared by `VolunteerMap.tsx` (native) and `VolunteerMap.web.tsx`, so both
 * draw the same states in the same colours.
 */

import type { DroneSurvey, NearbyVolunteer } from '../lib/api';
import { colors } from '../lib/theme';

export interface VolunteerMapProps {
  incident: { latitude: number; longitude: number; label: string };
  volunteers: NearbyVolunteer[];
  selected: ReadonlySet<string>;
  onToggle: (volunteerId: string) => void;
  /** A planned drone survey to outline, if any. */
  survey?: DroneSurvey | null;
  height?: number;
}

export interface VolunteerTone {
  fill: string;
  border: string;
  label: string;
  /** Can be tapped to select for an alert. */
  selectable: boolean;
}

/** How a volunteer is drawn, from their alert state and eligibility. */
export function volunteerTone(volunteer: NearbyVolunteer, selected: boolean): VolunteerTone {
  const status = volunteer.alert?.status;
  if (status === 'checked_in')
    return { fill: colors.success, border: colors.success, label: 'Checked in', selectable: false };
  if (status === 'awaiting_reply')
    return { fill: colors.warning, border: colors.warning, label: 'Awaiting reply', selectable: false };
  if (!volunteer.eligible)
    return {
      fill: 'transparent',
      border: colors.textFaint,
      label: volunteer.ineligible_reason ?? 'Not available',
      selectable: false,
    };
  if (selected)
    return { fill: colors.accent, border: colors.accent, label: 'Selected', selectable: true };
  const settled = status === 'declined' ? "Can't go" : status === 'cancelled' ? 'Stood down' : null;
  return {
    fill: 'rgba(244, 247, 251, 0.18)',
    border: colors.text,
    label: settled ?? 'Available',
    selectable: true,
  };
}
