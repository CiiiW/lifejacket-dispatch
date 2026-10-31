import {useEffect, useState} from 'react';
import {Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {API_BASE, droneDemo, type DemoFrame} from '../lib/api';
import {colors, glass, radius, spacing, type} from '../lib/theme';

export default function DroneDemoScreen() {
  const [rows, setRows] = useState<DemoFrame[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const row = rows.find(r => r.demo_id === selected);
  async function refresh() {
    setBusy(true); setError(null);
    try {setRows(await droneDemo.list());}
    catch {setError('Demo queue unavailable. It must be enabled in this demo environment.');}
    finally {setBusy(false);}
  }
  useEffect(() => {void refresh();}, []);
  async function review(decision: 'kept' | 'rejected') {
    if (!row) return;
    setBusy(true); setError(null);
    try {
      const updated = await droneDemo.review(row, actor.trim(), decision, note.trim());
      setRows(current => current.map(r => r.demo_id === updated.demo_id ? updated : r));
      setNote('');
    } catch {setError('Could not save. Refresh to load the latest review, then try again.');}
    finally {setBusy(false);}
  }
  const visible = rows.filter(r => filter === 'all' || r.status === filter);
  return <ScrollView contentContainerStyle={styles.page}>
    <Text style={styles.title}>Drone demo review</Text>
    <View style={styles.banner}><Text style={styles.label}>DEMO ONLY · No rescue dispatch</Text>
      <Text style={styles.body}>Toy and synthetic footage stays separate from wildlife observations.
        Keeping a frame does not confirm injury, create a case or notify a rescue center.</Text></View>
    <View style={styles.actions}>
      {['all', 'pending', 'kept', 'rejected'].map(status => <Pressable key={status}
        accessibilityRole="button" onPress={() => setFilter(status)} style={styles.button}>
        <Text style={{color: filter === status ? colors.accent : colors.text}}>{status}</Text>
      </Pressable>)}
      <Pressable accessibilityRole="button" disabled={busy} onPress={refresh} style={styles.button}>
        <Text style={styles.label}>{busy ? 'Loading…' : 'Refresh'}</Text></Pressable>
    </View>
    {error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    <Text style={styles.meta}>{rows.length} latest frames · Frame count is not animal count.</Text>
    {!visible.length && <Text style={styles.body}>No frames in this view. Import a prepared demo clip, then refresh.</Text>}
    <View style={styles.columns}>
      <View style={styles.list}>{visible.map(item => <Pressable key={item.demo_id}
        accessibilityRole="button" accessibilityLabel={`Review frame at ${item.metadata.offset_seconds.toFixed(3)} seconds`}
        onPress={() => {setSelected(item.demo_id); setNote('');}} style={[styles.card,
          selected === item.demo_id && {borderColor: colors.accent}]}>
        <Text style={styles.label}>{item.metadata.evidence_kind === 'toy_demo' ? 'Toy demo' : 'Synthetic test'} · {item.status}</Text>
        <Text style={styles.body}>{item.metadata.offset_seconds.toFixed(3)}s · {item.metadata.source}</Text>
        <Text style={styles.meta}>{item.metadata.detection_status === 'completed'
          ? `${item.metadata.detection?.animals.length ?? 0} candidate(s)`
          : item.metadata.detection_status === 'failed' ? 'Detection failed' : 'Not analyzed'}</Text>
      </Pressable>)}</View>
      {row && <View style={styles.detail}>
        <Text style={styles.heading}>Frame at {row.metadata.offset_seconds.toFixed(3)} seconds</Text>
        <Image accessibilityLabel="Demo evidence frame" source={{uri: `${API_BASE}${row.photo_url}`}}
          style={styles.image} resizeMode="contain" />
        <Text style={styles.body}>Capture time: {row.metadata.captured_at ?? 'Unknown'}</Text>
        <Text style={styles.body}>Location: unknown · GPS matching is not available yet.</Text>
        <Text style={styles.meta}>Source: {row.metadata.source}</Text>
        <Text style={styles.meta}>Permission: {row.metadata.rights_note}</Text>
        <Text style={styles.meta}>Model: {row.metadata.detector_model ?? 'No completed analysis'}</Text>
        {row.metadata.detection?.animals.map((animal, index) => <Text key={index} style={styles.body}>
          Candidate {index + 1}: {animal.description} ({animal.kind})</Text>)}
        <Text style={styles.meta}>Candidates are unverified. Empty results do not prove no animal was present.</Text>
        <TextInput accessibilityLabel="Reviewer name" placeholder="Reviewer name" value={actor}
          onChangeText={setActor} style={styles.input} placeholderTextColor={colors.textFaint} />
        <TextInput accessibilityLabel="Review note" placeholder="What did you observe?" value={note}
          onChangeText={setNote} multiline style={styles.input} placeholderTextColor={colors.textFaint} />
        <View style={styles.actions}>{(['kept', 'rejected'] as const).map(decision =>
          <Pressable key={decision} accessibilityRole="button"
            disabled={busy || !actor.trim() || !note.trim()} onPress={() => review(decision)}
            style={[styles.button, (busy || !actor.trim() || !note.trim()) && {opacity: 0.45}]}>
            <Text style={styles.label}>{decision === 'kept' ? 'Keep demo frame' : 'Reject frame'}</Text>
          </Pressable>)}</View>
        {row.reviews.map((entry, index) => <Text key={index} style={styles.meta}>
          {entry.actor} · {entry.decision} · {entry.note} · {entry.recorded_at}</Text>)}
      </View>}
    </View>
  </ScrollView>;
}
const styles = StyleSheet.create({
  page: {padding: spacing.lg, gap: spacing.md},
  title: {...type.heading, fontSize: 26, color: colors.text},
  heading: {...type.heading, color: colors.text},
  label: {...type.label, color: colors.accent},
  body: {...type.meta, color: colors.text},
  meta: {...type.meta, color: colors.textMuted},
  error: {...type.meta, color: '#ff9d9d'},
  banner: {...glass, padding: spacing.md, borderRadius: radius.card, gap: spacing.sm},
  actions: {flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm},
  button: {padding: spacing.sm, borderRadius: 8, backgroundColor: colors.backgroundElevated},
  columns: {flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg},
  list: {flexGrow: 1, flexBasis: 280, gap: spacing.sm},
  card: {...glass, padding: spacing.md, borderRadius: radius.card, gap: spacing.sm},
  detail: {...glass, flexGrow: 2, flexBasis: 400, padding: spacing.md, gap: spacing.sm,
    borderRadius: radius.card},
  image: {width: '100%', height: 280},
  input: {color: colors.text, padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    borderRadius: 8},
});
