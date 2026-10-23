import TriageMap from './TriageMap.web';
import type { DronePlan, DronePoint, HistoricalDensity } from '../lib/api';

const NO_PINS: [] = [];
const NO_CENTRES: [] = [];
const ignoreSelection = () => {};

export default function DroneLabMap({ plan, sample, trace, density, selectedCell }: {
  plan: DronePlan | null; sample: DronePoint | null; trace: DronePoint[];
  density: HistoricalDensity | null;
  selectedCell: HistoricalDensity['cells'][number] | null;
}) {
  return <TriageMap pins={NO_PINS} centres={NO_CENTRES} route={null} density={density}
    showDensity={density?.available ?? false} selectedId={null} onSelect={ignoreSelection}
    historicalCell={selectedCell}
    dronePlan={plan} droneSample={sample} droneTrace={trace} />;
}
