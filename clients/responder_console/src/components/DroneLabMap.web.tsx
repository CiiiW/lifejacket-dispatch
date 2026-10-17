import TriageMap from './TriageMap.web';
import type { DronePlan, DroneTelemetry } from '../lib/api';

const NO_PINS: [] = [];
const NO_CENTRES: [] = [];
const ignoreSelection = () => {};

export default function DroneLabMap({ plan, sample }: {
  plan: DronePlan | null; sample: DroneTelemetry | null;
}) {
  return <TriageMap pins={NO_PINS} centres={NO_CENTRES} route={null} density={null}
    showDensity={false} selectedId={null} onSelect={ignoreSelection}
    dronePlan={plan} droneSample={sample} />;
}
