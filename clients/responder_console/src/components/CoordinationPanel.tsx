import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { coordination, type CoordinationCheck } from '../lib/api';
import { colors, spacing, type } from '../lib/theme';

const TASK_LABELS = {
  needs_assignment: 'Assignment needed',
  awaiting_response: 'Response outstanding',
  human_review: 'Coordinator review',
};

export default function CoordinationPanel({ incidentId }: { incidentId: string }) {
  const [result, setResult] = useState<CoordinationCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function check() {
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    setCheckedAt(null);
    try {
      const response = await coordination.checkCase(incidentId, controller.signal);
      if (controller.signal.aborted) return;
      if (response.incident_id !== incidentId) throw new Error('Case mismatch');
      setResult(response);
      setCheckedAt(new Date());
    } catch {
      if (!controller.signal.aborted) {
        setError('Coordination check unavailable. Review the case records directly.');
      }
    } finally {
      if (!controller.signal.aborted) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <View style={styles.section}>
      <View style={styles.header}>
        <Text style={styles.heading}>Coordination</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Check Coordination"
          accessibilityState={{ disabled: loading, busy: loading }}
          disabled={loading}
          onPress={() => void check()}
          style={[styles.button, loading && styles.disabled]}
        >
          {loading && <ActivityIndicator size="small" color={colors.accent} />}
          <Text style={styles.buttonText}>{loading ? 'Checking...' : 'Check Coordination'}</Text>
        </Pressable>
      </View>
      {error && <Text accessibilityRole="alert" style={styles.warning}>{error}</Text>}
      {result && (
        <View style={styles.results} accessibilityLiveRegion="polite">
          <Text style={styles.meta}>
            Checked {checkedAt?.toLocaleTimeString()} | No case changes made
          </Text>
          {result.status === 'held_for_review' ? (
            <View style={styles.item}>
              <Text style={styles.warning}>Coordination held for review</Text>
              <Text style={styles.body}>
                {result.failure_reason ?? 'The check could not be completed.'}
              </Text>
            </View>
          ) : (
            <>
              {result.attention_items.length === 0 && (
                <Text style={styles.body}>No pending checks found in the retrieved records.</Text>
              )}
              {result.attention_items.map(({ task, proposed_next_step }) => (
                <View key={task.kind} style={styles.item}>
                  <Text style={styles.itemTitle}>{TASK_LABELS[task.kind]}</Text>
                  <Text selectable style={styles.body}>{task.reason}</Text>
                  <Text style={styles.body}>{proposed_next_step}</Text>
                  <Text selectable style={styles.meta}>
                    Records: {task.source_refs.join(', ') || 'No source reference returned'}
                  </Text>
                </View>
              ))}
              {result.responders_for_review.length > 0 && (
                <>
                  <Text style={styles.itemTitle}>Responder options for review</Text>
                  {result.responders_for_review.map((responder) => (
                    <View key={responder.responder_id} style={styles.item}>
                      <Text style={styles.itemTitle}>{responder.name}</Text>
                      {responder.response_area && <Text style={styles.body}>{responder.response_area}</Text>}
                      <Text style={styles.meta}>{responder.availability_basis}</Text>
                      <Text selectable style={styles.meta}>
                        Active assignment records: {responder.active_assignment_ids.join(', ') || 'None recorded'}
                      </Text>
                      <Text selectable style={styles.meta}>Record: {responder.source_ref}</Text>
                    </View>
                  ))}
                </>
              )}
            </>
          )}
          <Text style={styles.warning}>Coordinator approval required for any action.</Text>
          <Text selectable style={styles.meta}>
            Retrieved: {result.tool_calls.join(', ') || 'No tools completed'}
          </Text>
          {result.limitations.map((limitation, index) => (
            <Text key={index} style={styles.meta}>{limitation}</Text>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { borderTopWidth: 1, borderColor: colors.border, paddingVertical: spacing.md, gap: spacing.sm },
  header: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  heading: { ...type.heading, letterSpacing: 0, color: colors.text },
  button: { minHeight: 44, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderWidth: 1, borderColor: colors.accent, borderRadius: 8, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  buttonText: { ...type.label, color: colors.accent },
  disabled: { opacity: 0.65 },
  results: { gap: spacing.sm },
  item: { borderBottomWidth: 1, borderColor: colors.border, paddingVertical: spacing.sm, gap: spacing.xs },
  itemTitle: { ...type.label, color: colors.text },
  body: { ...type.body, color: colors.text, lineHeight: 22 },
  meta: { ...type.meta, color: colors.textMuted, lineHeight: 20 },
  warning: { ...type.meta, color: colors.warning, lineHeight: 20 },
});
