/**
 * Message the person who filed the report, when the team needs more.
 *
 * The reporter sees these in their app's Report tab and can answer. They see
 * the text and "Rescue team" -- never who on the team wrote it. Reports that
 * did not come from the reporter app (drone intake, seeded demos, anything
 * filed before messaging existed) have no key, so nothing written here could
 * be read. For those the panel renders nothing, rather than a card that only
 * says so or a box that goes nowhere; it also stays hidden until the thread
 * has loaded, so it never flashes up and disappears.
 *
 * Quick questions follow the system's safety principles: everything is
 * answerable from where the reporter already stands. Nothing asks them to go
 * closer, touch, or move the animal.
 */

import { type ComponentRef, useCallback, useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { coordinator, type CoordinatorThread } from '../lib/api';
import { colors, glass, radius, spacing, type } from '../lib/theme';
import { ActionButton, Chip, ErrorLine, formatTime, messageOf } from './controls';

const POLL_MS = 4000;

const QUICK_QUESTIONS = [
  'Is the animal still in the same spot?',
  'Are any people or dogs near it right now?',
  'Without going closer, can you describe any injuries you can see?',
  'Is there anything wrapped around it, like net, rope or line?',
];

export default function ReporterChat({
  incidentId,
  actor,
  onSent,
}: {
  incidentId: string;
  actor: string;
  /** After a message goes out, e.g. to refresh the Communications list. */
  onSent?: () => void;
}) {
  const [thread, setThread] = useState<CoordinatorThread | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);

  const load = useCallback(() => {
    coordinator.thread(incidentId).then(setThread).catch((e) => setError(messageOf(e)));
  }, [incidentId]);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function send(text: string) {
    const body = text.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await coordinator.messageReporter(incidentId, body, actor);
      setDraft('');
      load();
      onSent?.();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  if (!thread?.reporter_connected) return null;

  const messages = thread?.messages ?? [];
  const replies = messages.filter((m) => m.sender === 'reporter').length;

  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>
        Message the reporter{messages.length ? ` · ${replies} repl${replies === 1 ? 'y' : 'ies'}` : ''}
      </Text>
      <Text style={styles.muted}>
        They see this in the reporter app, signed "Rescue team", and can answer here.
      </Text>

      {messages.length > 0 && (
        <ScrollView
          ref={scroll}
          style={styles.thread}
          contentContainerStyle={styles.threadInner}
          onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: false })}
        >
          {messages.map((m) => {
            const mine = m.sender === 'coordinator';
            return (
              <View
                key={m.message_id}
                style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleTheirs]}
              >
                <Text style={styles.bubbleWho}>
                  {mine ? 'You (team)' : 'Reporter'} · {formatTime(m.created_at)}
                </Text>
                <Text style={styles.bubbleText}>{m.body}</Text>
              </View>
            );
          })}
        </ScrollView>
      )}

      <View style={styles.quick}>
        {QUICK_QUESTIONS.map((q) => (
          <Chip key={q} label={q} active={draft === q} onPress={() => setDraft(q)} />
        ))}
      </View>

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          placeholder="Ask the reporter something"
          placeholderTextColor={colors.textFaint}
          value={draft}
          onChangeText={setDraft}
          maxLength={1000}
          multiline
        />
        <ActionButton
          label="Send"
          kind="primary"
          busy={busy}
          disabled={!draft.trim()}
          onPress={() => void send(draft)}
        />
      </View>
      <ErrorLine message={error} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: { ...glass, padding: spacing.lg, gap: spacing.md },
  eyebrow: { ...type.eyebrow, color: colors.textFaint },
  muted: { ...type.meta, color: colors.textMuted },
  thread: { maxHeight: 280 },
  threadInner: { gap: spacing.sm },
  bubble: { padding: spacing.md, borderRadius: radius.card, maxWidth: '85%', gap: 2 },
  bubbleMine: {
    alignSelf: 'flex-end',
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: 'rgba(72, 202, 228, 0.35)',
  },
  bubbleTheirs: {
    alignSelf: 'flex-start',
    backgroundColor: colors.glassFillStrong,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bubbleWho: { ...type.meta, fontSize: 11, color: colors.textFaint },
  bubbleText: { ...type.body, color: colors.text },
  quick: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  composer: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-end' },
  input: {
    ...type.body,
    flex: 1,
    color: colors.text,
    minHeight: 44,
    maxHeight: 120,
    padding: spacing.md,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.backgroundElevated,
  },
});
