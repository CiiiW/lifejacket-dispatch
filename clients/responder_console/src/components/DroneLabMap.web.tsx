import { useState } from 'react';

import TriageMap from './TriageMap.web';
import type { DronePlan, DronePoint, HistoricalDensity, MapPin, SurveyBox } from '../lib/api';

const NO_CENTRES: [] = [];

export default function DroneLabMap({
  plan, sample, trace, density, selectedCell, pins = [], surveyArea = null,
  onDrawSurvey, drawing = false,
}: {
  plan: DronePlan | null; sample: DronePoint | null; trace: DronePoint[];
  density: HistoricalDensity | null;
  selectedCell: HistoricalDensity['cells'][number] | null;
  /** Live incidents, so a survey area can be chosen relative to real reports. */
  pins?: MapPin[];
  surveyArea?: SurveyBox | null;
  onDrawSurvey?: (box: SurveyBox) => void;
  drawing?: boolean;
}) {
  // Selection is local here. The Drone Lab has no incident list to drive, but
  // the clicked dot still needs its highlight ring to tie it to its card.
  const [selected, setSelected] = useState<string | null>(null);

  return <TriageMap pins={pins} centres={NO_CENTRES} route={null} density={density}
    showDensity={density?.available ?? false} selectedId={selected} onSelect={setSelected}
    historicalCell={selectedCell}
    surveyArea={surveyArea} onDrawSurvey={onDrawSurvey} drawing={drawing}
    // The survey area is the subject here, not the incident spread.
    fitToPins={false}
    dronePlan={plan} droneSample={sample} droneTrace={trace} />;
}
