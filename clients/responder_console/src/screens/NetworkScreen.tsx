import { Text, View } from 'react-native';
import { colors, spacing } from '../lib/theme';

export default function NetworkScreen() {
  return (
    <View style={{ padding: spacing.xl, backgroundColor: colors.background, flex: 1 }}>
      <Text style={{ color: colors.text, fontSize: 24 }}>Rescue network</Text>
      <Text style={{ color: colors.textMuted, marginTop: spacing.md }}>
        Open the web console in your browser to sign in and view your approved cases.
      </Text>
    </View>
  );
}
