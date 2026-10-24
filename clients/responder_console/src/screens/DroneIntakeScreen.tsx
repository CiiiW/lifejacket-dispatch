import { Text, View } from 'react-native';
import { colors } from '../lib/theme';

export default function DroneIntakeScreen(_: {onSelectCase: (id: string) => void}) {
  return <View style={{padding: 24}}><Text style={{color: colors.text}}>
    Open the web console to upload and review drone evidence or record external-center contact.
  </Text></View>;
}
