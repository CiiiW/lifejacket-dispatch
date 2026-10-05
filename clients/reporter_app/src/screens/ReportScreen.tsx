/**
 * The reporter's intake screen: photo, location, and the agent conversation.
 *
 * The whole screen is driven by `turn.action` from the backend. The client does
 * not know the order of the intake flow -- it just renders whatever the
 * pipeline asks for next. That means changing the flow (adding a question,
 * reordering steps) is a backend change with no app release.
 *
 *   request_photo         -> show the camera button
 *   request_location      -> show the "share location" button
 *   request_better_photo  -> camera again, with the agent's reason
 *   ask_clarifying_question -> an agent's question, with tap-able options
 *   finalise              -> guidance, then the tracking map
 *
 * Every question comes from an agent and is chosen for this photo; there is
 * no scripted questionnaire. Options are shortcuts -- typed text works too.
 */

import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';

import { ApiError, reporter, type Turn } from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

interface Bubble {
  from: 'agent' | 'me';
  text: string;
}

export default function ReportScreen({
  onComplete,
}: {
  onComplete: (incidentId: string) => void;
}) {
  const [turn, setTurn] = useState<Turn | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  // Start the report as soon as the screen opens. One fewer tap matters when
  // someone is standing in front of a distressed animal.
  useEffect(() => {
    void run(() => reporter.start());
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [bubbles]);

  /**
   * Run an API call, show its message, and keep the UI consistent.
   *
   * Centralised so every call path gets the same spinner and error handling --
   * a network failure mid-intake must not leave the screen stuck.
   */
  async function run(call: () => Promise<Turn>) {
    setBusy(true);
    try {
      const next = await call();
      setTurn(next);
      if (next.message) {
        setBubbles((prev) => [...prev, { from: 'agent', text: next.message! }]);
      }
      if (next.complete) {
        onComplete(next.incident_id);
      }
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : 'Could not reach LifeJacket.';
      Alert.alert('Something went wrong', message);
    } finally {
      setBusy(false);
    }
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Camera needed',
        'LifeJacket needs the camera to photograph the animal so it can be identified.',
      );
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      // Compressed, because reporters are often on a weak coastal signal and
      // the vision model does not need a 12 MP original.
      quality: 0.7,
      exif: true,
    });
    if (result.canceled || !turn) return;

    setBubbles((prev) => [...prev, { from: 'me', text: '[photo sent]' }]);
    await run(() => reporter.uploadPhoto(turn.incident_id, result.assets[0].uri));
  }

  async function shareLocation() {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Location needed',
        'Your location is used to check the tide and to find the nearest rescue team. '
          + 'A report cannot be routed without it.',
      );
      return;
    }

    const position = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.High,
    });
    if (!turn) return;

    setBubbles((prev) => [...prev, { from: 'me', text: '[location shared]' }]);
    await run(() =>
      reporter.setLocation(
        turn.incident_id,
        position.coords.latitude,
        position.coords.longitude,
        position.coords.accuracy ?? undefined,
      ),
    );
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !turn) return;

    setBubbles((prev) => [...prev, { from: 'me', text: trimmed }]);
    setDraft('');
    await run(() => reporter.reply(turn.incident_id, trimmed));
  }

  const action = turn?.action;
  const needsPhoto = action === 'request_photo' || action === 'request_better_photo';
  const needsLocation = action === 'request_location';
  const isQuestion = action === 'ask_clarifying_question';

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Report an animal</Text>
        {turn?.identified_as && (
          <Text style={styles.progress}>Looks like: {turn.identified_as}</Text>
        )}
      </View>

      <ScrollView ref={scrollRef} style={styles.transcript} contentContainerStyle={styles.transcriptInner}>
        {bubbles.map((bubble, index) => (
          <View
            key={index}
            style={[styles.bubble, bubble.from === 'me' ? styles.mine : styles.theirs]}
          >
            <Text style={bubble.from === 'me' ? styles.mineText : styles.theirsText}>
              {bubble.text}
            </Text>
          </View>
        ))}
        {busy && <ActivityIndicator style={styles.spinner} color={colors.accent} />}
      </ScrollView>

      <View style={styles.actions}>
        {needsPhoto && (
          <Pressable style={styles.primary} onPress={takePhoto} disabled={busy}>
            <Text style={styles.primaryText}>Take a photo</Text>
          </Pressable>
        )}

        {needsLocation && (
          <Pressable style={styles.primary} onPress={shareLocation} disabled={busy}>
            <Text style={styles.primaryText}>Share my location</Text>
          </Pressable>
        )}

        {isQuestion && turn && turn.options.length > 0 && (
          <View style={styles.options}>
            {turn.options.map((option) => (
              <Pressable
                key={option}
                style={styles.option}
                onPress={() => void send(option)}
                disabled={busy}
              >
                {/* Option values are snake_case keys from the backend; show
                    them as readable words without changing what is sent. */}
                <Text style={styles.optionText}>{option.replace(/_/g, ' ')}</Text>
              </Pressable>
            ))}
          </View>
        )}

        {isQuestion && turn && (
          <View style={styles.composer}>
            <TextInput
              style={styles.input}
              value={draft}
              onChangeText={setDraft}
              placeholder="Or type your answer"
              placeholderTextColor={colors.textFaint}
              editable={!busy}
              onSubmitEditing={() => void send(draft)}
              returnKeyType="send"
            />
            <Pressable style={styles.send} onPress={() => void send(draft)} disabled={busy}>
              <Text style={styles.primaryText}>Send</Text>
            </Pressable>
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  title: { ...type.display, color: colors.text },
  progress: { ...type.meta, color: colors.accent, marginTop: 2 },
  transcript: { flex: 1 },
  transcriptInner: { padding: spacing.lg, gap: spacing.sm },
  bubble: { maxWidth: '85%', padding: spacing.md, borderRadius: radius.lg },
  theirs: { ...glass, alignSelf: 'flex-start' },
  mine: { ...shadow.soft, alignSelf: 'flex-end', backgroundColor: colors.accent },
  theirsText: { ...type.body, fontSize: 16, color: colors.text, lineHeight: 22 },
  mineText: { ...type.body, fontSize: 16, color: colors.onAccent, lineHeight: 22 },
  spinner: { marginTop: spacing.md },
  actions: {
    padding: spacing.lg,
    gap: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  primary: {
    ...shadow.soft,
    backgroundColor: colors.accent,
    paddingVertical: spacing.lg,
    borderRadius: radius.card,
    alignItems: 'center',
  },
  primaryText: { ...type.label, fontSize: 16, color: colors.onAccent },
  options: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  option: {
    borderWidth: 1,
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: spacing.lg,
  },
  optionText: { ...type.label, color: colors.accent, fontSize: 15 },
  composer: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' },
  input: {
    ...type.body,
    ...glass,
    flex: 1,
    color: colors.text,
    fontSize: 16,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  send: {
    backgroundColor: colors.accent,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    borderRadius: radius.card,
  },
});
