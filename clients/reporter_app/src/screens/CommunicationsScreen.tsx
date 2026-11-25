/**
 * Communications: the reporter's conversations with the rescue team, one per
 * report, and the phone number every report shares.
 *
 * Either side can write first: "it moved into the water" is exactly the kind
 * of thing a team wants to hear without having to ask. Messages reach the
 * console's Communications tab, which puts unanswered ones on top. This is not
 * an emergency line, and says so.
 */

import { type ComponentRef, useEffect, useRef, useState } from 'react';
import {
  Keyboard,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ApiError, type MyReport } from '../lib/api';
import type { SavedReport } from '../lib/reporterStore';
import { reportStatus, shortWhen } from '../lib/reportStatus';
import { useTeamThread } from '../lib/useTeamThread';
import { colors, glass, radius, spacing, type } from '../lib/theme';
import { plausiblePhone } from './PhoneSetupScreen';

export default function CommunicationsScreen({
  phone,
  onChangePhone,
  reports,
  summaries,
  seenTeam,
  onSeen,
  openIncidentId,
  onOpened,
  onRefresh,
}: {
  phone: string;
  onChangePhone: (phone: string) => void;
  reports: SavedReport[];
  summaries: Record<string, MyReport>;
  seenTeam: Record<string, number>;
  onSeen: (incidentId: string, teamCount: number) => void;
  /** A thread another tab asked to open ("Message the team" on My reports). */
  openIncidentId: string | null;
  onOpened: () => void;
  onRefresh: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (openIncidentId) {
      setSelected(openIncidentId);
      onOpened();
    }
  }, [openIncidentId, onOpened]);

  const report = reports.find((r) => r.incidentId === selected);
  if (report) {
    return (
      <Thread
        report={report}
        summary={summaries[report.incidentId]}
        onBack={() => setSelected(null)}
        onSeen={onSeen}
        onSent={onRefresh}
      />
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      <PhoneCard phone={phone} onChange={onChangePhone} />

      <Text style={styles.note}>
        Messages go to the rescue team handling each report. This is not an emergency line:
        if a person is in danger, call 911.
      </Text>

      {reports.length === 0 ? (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>No conversations yet</Text>
          <Text style={styles.muted}>
            Once you send a report, you can message the rescue team about it here.
          </Text>
        </View>
      ) : (
        reports.map((r) => {
          const summary = summaries[r.incidentId];
          const unread = Math.max(0, (summary?.team_message_count ?? 0) - (seenTeam[r.incidentId] ?? 0));
          const last = summary?.last_message;
          return (
            <Pressable
              key={r.incidentId}
              style={styles.card}
              onPress={() => setSelected(r.incidentId)}
              accessibilityRole="button"
              accessibilityLabel={`Conversation about ${title(summary)}${unread ? `, ${unread} unread` : ''}`}
            >
              <View style={styles.row}>
                <Text style={styles.cardTitle} numberOfLines={1}>
                  {title(summary)}
                </Text>
                {unread > 0 && (
                  <View style={styles.badge}>
                    <Text style={styles.badgeText}>{unread}</Text>
                  </View>
                )}
              </View>
              <Text style={styles.muted} numberOfLines={1}>
                {[summary?.place_name, shortWhen(summary?.created_at ?? r.startedAt)]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
              <Text style={[styles.preview, unread > 0 && styles.previewUnread]} numberOfLines={2}>
                {last
                  ? `${last.sender === 'team' ? 'Rescue team' : 'You'}: ${last.body}`
                  : 'No messages yet. Write to the team if anything changes.'}
              </Text>
            </Pressable>
          );
        })
      )}
    </ScrollView>
  );
}

function title(summary: MyReport | undefined): string {
  if (!summary) return 'Your report';
  return summary.species_common_name ?? (summary.complete ? 'Animal report' : 'Report not sent yet');
}

/** The number every report shares, with a way to change it. */
function PhoneCard({ phone, onChange }: { phone: string; onChange: (phone: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(phone);
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>Your phone number</Text>
      {editing ? (
        <View style={styles.editRow}>
          <TextInput
            style={[styles.input, styles.flex]}
            value={draft}
            onChangeText={setDraft}
            keyboardType="phone-pad"
            autoComplete="tel"
            autoFocus
          />
          <Pressable
            style={[styles.send, !plausiblePhone(draft) && styles.disabled]}
            disabled={!plausiblePhone(draft)}
            onPress={() => {
              onChange(draft.trim());
              setEditing(false);
            }}
          >
            <Text style={styles.sendText}>Save</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.row}>
          <Text style={styles.phone}>{phone}</Text>
          <Pressable onPress={() => setEditing(true)} hitSlop={8}>
            <Text style={styles.link}>Change</Text>
          </Pressable>
        </View>
      )}
      <Text style={styles.muted}>
        Shared with the rescue organization handling each report you send, so they can call or
        message you. Changing it also updates your reports that are still open.
      </Text>
    </View>
  );
}

/** One report's conversation. Polls while open; marks the team's messages read. */
function Thread({
  report,
  summary,
  onBack,
  onSeen,
  onSent,
}: {
  report: SavedReport;
  summary: MyReport | undefined;
  onBack: () => void;
  onSeen: (incidentId: string, teamCount: number) => void;
  onSent: () => void;
}) {
  const { messages, reply } = useTeamThread(report.incidentId, report.key);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const teamCount = messages.filter((m) => m.sender === 'team').length;

  useEffect(() => {
    onSeen(report.incidentId, teamCount);
  }, [report.incidentId, teamCount, onSeen]);

  async function send() {
    const body = draft.trim();
    if (!body) return;
    setBusy(true);
    setError(null);
    try {
      await reply(body);
      setDraft('');
      Keyboard.dismiss();
      onSent();
    } catch (problem) {
      setError(problem instanceof ApiError ? problem.message : 'Could not send. Check your connection.');
    } finally {
      setBusy(false);
    }
  }

  const status = reportStatus(summary?.status, summary?.complete);
  return (
    <View style={styles.screen}>
      <View style={styles.threadHeader}>
        <Pressable onPress={onBack} hitSlop={10} accessibilityRole="button">
          <Text style={styles.link}>‹ Conversations</Text>
        </Pressable>
        <Text style={styles.cardTitle} numberOfLines={1}>
          {title(summary)}
        </Text>
        <Text style={styles.muted} numberOfLines={1}>
          {[status.label, summary?.place_name].filter(Boolean).join(' · ')}
        </Text>
      </View>

      <ScrollView
        ref={scroll}
        style={styles.flex}
        contentContainerStyle={styles.messages}
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: false })}
        keyboardDismissMode="on-drag"
      >
        {messages.length === 0 && (
          <Text style={styles.empty}>
            Nothing here yet. The rescue team may write with a question, or you can tell them
            if anything changes: the animal moves, people or dogs come close, the tide reaches
            it.
          </Text>
        )}
        {messages.map((m) => {
          const mine = m.sender === 'you';
          return (
            <View key={m.message_id} style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
              <Text style={[styles.who, mine && styles.whoMine]}>
                {mine ? 'You' : 'Rescue team'} · {shortWhen(m.sent_at)}
              </Text>
              <Text style={mine ? styles.mineText : styles.theirsText}>{m.body}</Text>
            </View>
          );
        })}
      </ScrollView>

      {error && <Text style={styles.error}>{error}</Text>}
      <View style={styles.composer}>
        <TextInput
          style={[styles.input, styles.flex]}
          value={draft}
          onChangeText={setDraft}
          placeholder="Message the rescue team"
          placeholderTextColor={colors.textFaint}
          editable={!busy}
          maxLength={1000}
          multiline
        />
        <Pressable
          style={[styles.send, (busy || !draft.trim()) && styles.disabled]}
          onPress={() => void send()}
          disabled={busy || !draft.trim()}
        >
          <Text style={styles.sendText}>{busy ? '…' : 'Send'}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: { padding: spacing.lg, gap: spacing.md },
  flex: { flex: 1 },
  card: { ...glass, padding: spacing.md, gap: spacing.xs + 2 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  editRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  eyebrow: { ...type.eyebrow, color: colors.textFaint },
  cardTitle: { ...type.heading, color: colors.text, flexShrink: 1 },
  phone: { ...type.title, color: colors.text },
  muted: { ...type.meta, color: colors.textMuted, lineHeight: 18 },
  note: { ...type.meta, color: colors.textFaint, lineHeight: 18 },
  preview: { ...type.meta, color: colors.textFaint, lineHeight: 18 },
  previewUnread: { color: colors.text },
  link: { ...type.label, color: colors.accent },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { ...type.label, fontSize: 12, color: colors.onAccent },

  threadHeader: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: 2,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  messages: { padding: spacing.lg, gap: spacing.sm },
  empty: { ...type.meta, color: colors.textFaint, textAlign: 'center', lineHeight: 19, marginTop: spacing.xl },
  bubble: { maxWidth: '85%', borderRadius: radius.card, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  mine: { alignSelf: 'flex-end', backgroundColor: colors.accent },
  theirs: { alignSelf: 'flex-start', ...glass },
  who: { ...type.meta, fontSize: 11, color: colors.accent, marginBottom: 2 },
  whoMine: { color: colors.onAccent },
  mineText: { ...type.body, color: colors.onAccent },
  theirsText: { ...type.body, color: colors.text },
  error: { ...type.meta, color: colors.danger, paddingHorizontal: spacing.lg },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.backgroundElevated,
  },
  input: {
    ...type.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.card,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    backgroundColor: colors.glassFill,
    maxHeight: 120,
  },
  send: {
    backgroundColor: colors.accent,
    borderRadius: radius.card,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 3,
  },
  sendText: { ...type.label, color: colors.onAccent },
  disabled: { opacity: 0.45 },
});
