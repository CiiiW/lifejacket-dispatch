import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { coordination, type ShiftHandover } from "../lib/api";
import { colors, spacing, type } from "../lib/theme";

export default function HandoverScreen({
  onSelect,
}: {
  onSelect: (id: string) => void;
}) {
  const [end, setEnd] = useState(() => new Date().toISOString());
  const [start, setStart] = useState(() =>
    new Date(Date.now() - 8 * 3600000).toISOString(),
  );
  const [report, setReport] = useState<ShiftHandover | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function load() {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setReport(null);
    setError(null);
    try {
      const result = await coordination.handover(start, end, controller.signal);
      if (!controller.signal.aborted) setReport(result);
    } catch {
      if (!controller.signal.aborted)
        setError(
          "Handover unavailable. Check the API and choose a timezone-qualified window of at most seven days.",
        );
    } finally {
      if (!controller.signal.aborted) {
        request.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.inner}>
      <Text style={styles.title}>Shift handover</Text>
      <Text style={styles.meta}>Installation-wide | UTC</Text>
      <View style={styles.controls}>
        <View style={styles.field}>
          <Text style={styles.label}>Shift start</Text>
          <TextInput
            accessibilityLabel="Shift start"
            value={start}
            editable={!loading}
            onChangeText={(value) => {
              setStart(value);
              setReport(null);
            }}
            style={styles.input}
          />
        </View>
        <View style={styles.field}>
          <Text style={styles.label}>Shift end</Text>
          <TextInput
            accessibilityLabel="Shift end"
            value={end}
            editable={!loading}
            onChangeText={(value) => {
              setEnd(value);
              setReport(null);
            }}
            style={styles.input}
          />
        </View>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: loading, busy: loading }}
        disabled={loading}
        onPress={() => void load()}
        style={styles.button}
      >
        <Text style={styles.label}>
          {loading ? "Loading..." : "Load handover"}
        </Text>
      </Pressable>
      {loading && <ActivityIndicator color={colors.accent} />}
      {error && (
        <Text accessibilityRole="alert" style={styles.warning}>
          {error}
        </Text>
      )}
      {report && (
        <>
          <Text style={styles.meta}>Generated {report.generated_at}</Text>
          {(report.changes_truncated || report.carryover_truncated) && (
            <Text style={styles.warning}>
              Partial result: a retrieval limit was reached.
            </Text>
          )}
          <Text style={styles.heading}>
            Current carryover ({report.current_carryover.length})
          </Text>
          {report.current_carryover.length === 0 && (
            <Text style={styles.meta}>No open cases recorded.</Text>
          )}
          {report.current_carryover.map((incident) => (
            <Pressable
              key={incident.incident_id}
              accessibilityRole="button"
              onPress={() => onSelect(incident.incident_id)}
              style={styles.row}
            >
              <Text style={styles.label}>
                {incident.incident_id} |{" "}
                {incident.headline ?? "Unidentified animal"}
              </Text>
              <Text style={styles.meta}>
                {incident.status} |{" "}
                {incident.severity_level ?? "Urgency unknown"}
              </Text>
              <Text style={styles.meta}>
                Assigned responder:{" "}
                {incident.assigned_responder_id ?? "None recorded"}
              </Text>
              {incident.tasks.map((task) => (
                <Text key={task.kind} style={styles.warning}>
                  {task.reason}
                </Text>
              ))}
              <Text style={styles.meta}>{incident.source_ref}</Text>
            </Pressable>
          ))}
          <Text style={styles.heading}>
            Recorded shift changes ({report.changes.length})
          </Text>
          {report.changes.length === 0 && (
            <Text style={styles.meta}>
              No events recorded in this window. Older changes may not have been
              tracked.
            </Text>
          )}
          {report.changes.map((event) => (
            <View key={event.event_id} style={styles.row}>
              <Pressable
                accessibilityRole="button"
                onPress={() => onSelect(event.incident_id)}
              >
                <Text style={styles.label}>
                  {event.incident_id} | {event.kind.replaceAll("_", " ")}
                </Text>
              </Pressable>
              <Text style={styles.meta}>
                {event.recorded_at} | Actor reference:{" "}
                {event.actor_ref ?? "Not recorded"}
              </Text>
              <Text selectable style={styles.meta}>
                {JSON.stringify(event.details, null, 2)}
              </Text>
              <Text selectable style={styles.meta}>
                {event.source_ref}
              </Text>
            </View>
          ))}
          {report.limitations.map((note, index) => (
            <Text key={index} style={styles.meta}>
              {note}
            </Text>
          ))}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  inner: {
    padding: spacing.lg,
    gap: spacing.md,
    width: "100%",
    maxWidth: 780,
    alignSelf: "center",
  },
  title: { ...type.title, letterSpacing: 0, color: colors.text },
  heading: { ...type.heading, letterSpacing: 0, color: colors.text },
  label: { ...type.label, color: colors.text },
  meta: { ...type.meta, lineHeight: 20, color: colors.textMuted },
  warning: { ...type.meta, lineHeight: 20, color: colors.warning },
  controls: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  field: { flexGrow: 1, flexBasis: 280, gap: spacing.xs },
  input: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: 8,
    color: colors.text,
    padding: spacing.sm,
    fontSize: 13,
  },
  button: {
    minHeight: 44,
    alignSelf: "flex-start",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderRadius: 8,
    borderColor: colors.accent,
  },
  row: {
    paddingVertical: spacing.md,
    gap: spacing.xs,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
});
