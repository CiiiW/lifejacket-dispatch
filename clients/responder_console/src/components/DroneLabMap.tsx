import { Text, View } from 'react-native';
import type { DronePlan, DronePoint, HistoricalDensity, MapPin, SurveyBox } from '../lib/api';
import { colors } from '../lib/theme';

export default function DroneLabMap({ plan }: {
  plan: DronePlan | null; sample: DronePoint | null; trace: DronePoint[];
  density: HistoricalDensity | null;
  selectedCell: HistoricalDensity['cells'][number] | null;
  pins?: MapPin[];
  surveyArea?: SurveyBox | null;
  onDrawSurvey?: (box: SurveyBox) => void;
  drawing?: boolean;
}) {
  return <View style={{ padding: 24 }}>
    <Text style={{ color: colors.text }}>Open the web console for the interactive route map.</Text>
    <Text style={{ color: colors.textMuted }}>{plan?.waypoints.length ?? 0} synthetic waypoints</Text>
  </View>;
}
