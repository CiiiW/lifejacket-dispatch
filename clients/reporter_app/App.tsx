/**
 * Native entry point -- this is what Expo Go loads.
 *
 * Default is the reporter console, so the app is testable on a phone with
 * nothing configured. A deployment that has an approved HTTPS reporter web
 * app sets `EXPO_PUBLIC_REPORTER_WEB_URL`, and this hands off to it instead.
 *
 * Why that way round: the console talks to the legacy intake API and does
 * NOT verify the reporter's phone number. Native SMS verification needs a
 * development build with Firebase/APNs native modules, which Expo Go does
 * not include -- so on a phone there is no verified path to fall back to,
 * only a configured browser one. Rather than show a dead end when that is
 * absent, show the console and label it honestly.
 *
 * `EXPO_PUBLIC_LEGACY_REPORTER_DEMO=true` forces the console even when a web
 * URL is configured, for testing a deployment build locally.
 */
import { Linking, Pressable, SafeAreaView, StyleSheet, Text } from 'react-native';

import ReporterConsole from './LegacyReporterDemo';
import { colors, spacing, type } from './src/lib/theme';

export default function App() {
  const forceConsole = process.env.EXPO_PUBLIC_LEGACY_REPORTER_DEMO === 'true';
  const target = process.env.EXPO_PUBLIC_REPORTER_WEB_URL;
  const safeTarget = target && /^https:\/\/[^\s]+$/.test(target) ? target : null;

  if (safeTarget && !forceConsole) {
    return (
      <SafeAreaView style={styles.handoff}>
        <Text style={styles.brand}>LifeJacket</Text>
        <Text style={styles.lead}>
          Phone-verified reporting is available through the configured browser app.
        </Text>
        <Text style={styles.note}>
          Native SMS verification requires a development build. This app does not submit
          through an unverified fallback.
        </Text>
        <Pressable onPress={() => Linking.openURL(safeTarget)}>
          <Text style={styles.link}>Open reporter app in browser</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return <ReporterConsole />;
}

const styles = StyleSheet.create({
  handoff: {
    flex: 1,
    padding: spacing.xl,
    backgroundColor: colors.background,
    gap: spacing.lg,
  },
  brand: { ...type.display, color: colors.accent },
  lead: { ...type.body, color: colors.text },
  note: { ...type.meta, color: colors.textMuted, lineHeight: 19 },
  link: { ...type.label, color: colors.accent },
});
