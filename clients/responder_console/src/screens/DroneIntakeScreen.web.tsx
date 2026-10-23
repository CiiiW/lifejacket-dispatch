import {useEffect, useState} from 'react';
import {Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import {API_BASE, droneIntake, type DirectoryCenter, type DroneObservation,
  type ExternalContactStatus, type ExternalHandoff} from '../lib/api';
import {colors, glass, radius, spacing, type} from '../lib/theme';

const nextStatuses: Record<ExternalContactStatus, ExternalContactStatus[]> = {
  draft: ['contact_attempted', 'escalated'], contact_attempted: ['acknowledged', 'declined', 'escalated'],
  acknowledged: ['accepted', 'declined', 'escalated'], accepted: ['completed', 'escalated'],
  declined: [], escalated: [], completed: [],
};
const contactLabels: Record<string, string> = {
  contact_attempted: 'Record contact attempt', acknowledged: 'Record acknowledgment',
  accepted: 'Record acceptance', declined: 'Record decline', escalated: 'Record escalation',
  completed: 'Record completion',
};

export default function DroneIntakeScreen({onSelectCase}: {onSelectCase: (id: string) => void}) {
  const [rows, setRows] = useState<DroneObservation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const row = rows.find(r => r.observation_id === selected) ?? null;
  const [centers, setCenters] = useState<DirectoryCenter[]>([]);
  const [handoffs, setHandoffs] = useState<ExternalHandoff[]>([]);
  const [actor, setActor] = useState('');
  const [sourceKind, setSourceKind] = useState<'real' | 'simulation'>('simulation');
  const [file, setFile] = useState<File | null>(null);
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [observedAt, setObservedAt] = useState('');
  const [description, setDescription] = useState('');
  const [area, setArea] = useState('');
  const [note, setNote] = useState('');
  const [existingId, setExistingId] = useState('');
  const [centerId, setCenterId] = useState('');
  const [verifiedContact, setVerifiedContact] = useState(false);
  const [verifiedCoverage, setVerifiedCoverage] = useState(false);
  const [verificationSource, setVerificationSource] = useState('');
  const [verificationNote, setVerificationNote] = useState('');
  const [channel, setChannel] = useState<'phone' | 'email' | 'other'>('phone');
  const [contactNote, setContactNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh(id = selected) {
    const list = await droneIntake.list();
    const [choices, contacts] = id ? await Promise.all([droneIntake.centers(id), droneIntake.handoffs(id)]) : [[], []];
    setRows(list); setCenters(choices); setHandoffs(contacts);
  }
  useEffect(() => {
    let active = true;
    droneIntake.list().then(list => {if (active) setRows(list);})
      .catch(() => {if (active) setError('Could not load drone observations.');});
    return () => {active = false;};
  }, []);
  async function act(work: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try {await work();} catch (reason) {setError(reason instanceof Error ? reason.message : 'Action failed.');}
    finally {setBusy(false);}
  }
  async function choose(id: string) {
    setSelected(id); setCenterId(''); setVerifiedContact(false); setVerifiedCoverage(false);
    setVerificationSource(''); setVerificationNote(''); setNote(''); setExistingId(''); setContactNote('');
    await refresh(id);
  }
  async function upload() {
    if (!file) throw new Error('Choose a photo.');
    if (![latitude, longitude].every(v => v.trim() && Number.isFinite(Number(v)))) throw new Error('Enter the observation coordinates.');
    const captured = new Date(observedAt);
    if (!observedAt.trim() || !Number.isFinite(captured.getTime()) || !/[zZ]|[+-]\d\d:\d\d$/.test(observedAt)) throw new Error('Enter capture time with timezone, such as 2026-10-22T14:30:00-05:00.');
    const form = new FormData();
    form.append('metadata', JSON.stringify({source_kind: sourceKind, latitude: Number(latitude),
      longitude: Number(longitude), observed_at: captured.toISOString(), operator: actor,
      description, area_terms: area.split(',').map(s => s.trim()).filter(Boolean), animal_group: 'unknown'}));
    form.append('photo', file);
    const created = await droneIntake.upload(form);
    await choose(created.observation_id);
  }

  return <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
    <Text style={styles.title}>Drone observations</Text>
    <Text style={styles.body}>Upload evidence, review it, and prepare a handoff to a center. Rescue centers can respond by phone or email without joining LifeJacket.</Text>
    <Field label="Coordinator name" value={actor} onChange={setActor} />
    <View style={styles.card}>
      <Text style={styles.heading}>1 · Add observation</Text>
      <View style={styles.actions}>
        <Action label="Simulation / test evidence" active={sourceKind === 'simulation'} onPress={() => setSourceKind('simulation')} />
        <Action label="Real captured evidence" active={sourceKind === 'real'} onPress={() => setSourceKind('real')} />
      </View>
      <Text style={styles.meta}>JPEG, PNG or WebP · 8 MiB maximum · supply the photo's capture time and location.</Text>
      <input aria-label="Observation photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy}
        onChange={event => setFile(event.target.files?.[0] ?? null)} style={{color: colors.text}} />
      <Field label="Observed latitude" value={latitude} onChange={setLatitude} />
      <Field label="Observed longitude" value={longitude} onChange={setLongitude} />
      <Field label="Capture time with timezone" value={observedAt} onChange={setObservedAt} />
      <Field label="County or local coverage area, comma separated" value={area} onChange={setArea} />
      <Field label="What is visible? Include uncertainty" value={description} onChange={setDescription} />
      <Action label="Save for review" disabled={busy || !actor.trim() || !description.trim() || !area.trim() || !file}
        onPress={() => void act(upload)} />
    </View>
    <View style={styles.card}>
      <Text style={styles.heading}>2 · Review queue</Text>
      <Action label="Refresh queue" disabled={busy} onPress={() => void act(() => refresh())} />
      {!rows.length && <Text style={styles.meta}>No observations yet.</Text>}
      {rows.map(item => <Action key={item.observation_id}
        label={`${item.source_kind} · ${item.status} · ${item.metadata.observed_at} · ${item.observation_id.slice(0,8)}`}
        active={selected === item.observation_id} disabled={busy} onPress={() => void act(() => choose(item.observation_id))} />)}
    </View>
    {row && <View style={styles.card}>
      <Text style={styles.heading}>Evidence · {row.status}</Text>
      <Image source={{uri: API_BASE + row.photo_url}} style={{width: '100%', height: 260}} resizeMode="contain" accessibilityLabel="Uploaded drone observation" />
      <a href={`${API_BASE}${row.photo_url}?download=true`} style={{color: colors.accent}}>Download original photo for a reviewed handoff</a>
      <Text style={styles.body}>{row.metadata.description}</Text>
      <Text selectable style={styles.meta}>Capture {row.metadata.observed_at} · {row.metadata.latitude}, {row.metadata.longitude}{'\n'}SHA-256 {row.sha256}</Text>
      {row.review && <Text style={styles.body}>Review: {row.review.actor} · {row.review.note}</Text>}
      {!row.incident_id && <>
        <Field label="Review notes" value={note} onChange={setNote} />
        <View style={styles.actions}>{(['verified', 'rejected'] as const).map(decision => <Action key={decision}
          label={decision === 'verified' ? 'Verify observation' : 'Reject observation'}
          disabled={busy || !actor.trim() || !note.trim()} onPress={() => void act(async () => {
            await droneIntake.review(row, actor, decision, note); await refresh();
          })} />)}</View>
      </>}
      {row.source_kind === 'simulation' && <Text style={styles.notice}>Simulation evidence stays outside live rescue cases and external handoffs.</Text>}
      {row.source_kind === 'real' && row.status === 'verified' && !row.incident_id && <>
        <Text style={styles.body}>Check existing cases for the same animal before creating a new one. A new case enters assessment with species and severity unconfirmed.</Text>
        <Action label="Create assessment case" disabled={busy || !actor.trim()} onPress={() => void act(async () => {await droneIntake.linkCase(row, actor); await refresh();})} />
        <Field label="Existing case ID, if this is the same animal" value={existingId} onChange={setExistingId} />
        <Action label="Attach to existing case" disabled={busy || !actor.trim() || !existingId.trim()} onPress={() => void act(async () => {await droneIntake.linkCase(row, actor, existingId.trim()); await refresh();})} />
      </>}
      {row.incident_id && <Action label={`Open case ${row.incident_id}`} onPress={() => onSelectCase(row.incident_id!)} />}
    </View>}
    {row?.incident_id && <View style={styles.card}>
      <Text style={styles.heading}>3 · External rescue-center handoff</Text>
      <Text style={styles.body}>Directory area matches are suggestions. Check the center's current coverage, animal-response capability and contact details. Availability is unknown.</Text>
      {!centers.length && <Text style={styles.notice}>No local directory match. Escalate to the regional stranding network for routing.</Text>}
      {centers.map(center => <View key={center.center_id} style={styles.card}>
        <Action label={center.name} active={centerId === center.center_id} disabled={busy} onPress={() => {
          setCenterId(center.center_id); setVerifiedContact(false); setVerifiedCoverage(false); setVerificationSource(''); setVerificationNote('');
        }} />
        <Text style={styles.body}>{center.response_area}{'\n'}{center.response_type}</Text>
        <Text selectable style={styles.meta}>{center.hotline || center.phone || 'No phone listed'} · {center.email || 'No email listed'}{'\n'}{center.website}{'\n'}Source: {center.directory_source}</Text>
      </View>)}
      {centerId && <>
        <Check label="I checked current coverage and capability for this observation" checked={verifiedCoverage} onPress={() => setVerifiedCoverage(v => !v)} />
        <Check label="I verified the listed contact details against an authoritative source" checked={verifiedContact} onPress={() => setVerifiedContact(v => !v)} />
        <Field label="Verification source URL" value={verificationSource} onChange={setVerificationSource} />
        <Field label="Verification notes" value={verificationNote} onChange={setVerificationNote} />
        <Action label="Prepare contact packet" disabled={busy || !actor.trim() || !verifiedContact || !verifiedCoverage || !verificationSource.trim() || !verificationNote.trim()}
          onPress={() => void act(async () => {await droneIntake.prepare(row, actor, centerId, verificationSource, verificationNote); await refresh();})} />
      </>}
      {handoffs.map(handoff => <View key={handoff.handoff_id} style={styles.card}>
        <Text style={styles.heading}>{handoff.snapshot.center.name} · {handoff.status.replace(/_/g, ' ')}</Text>
        <Text selectable style={styles.body}>{handoff.snapshot.packet_text}</Text>
        <Text style={styles.meta}>Nothing is sent by this screen. Contact the center through its verified channel, then record what happened. Contact records do not create an app assignment or ETA.</Text>
        {handoff.history.map((entry, i) => <Text key={i} style={styles.meta}>{entry.status} · {entry.actor} · {entry.note}</Text>)}
        {!!nextStatuses[handoff.status].length && <>
          <View style={styles.actions}>{(['phone', 'email', 'other'] as const).map(value => <Action key={value} label={value} active={channel === value} onPress={() => setChannel(value)} />)}</View>
          <Field label="Contact outcome / response notes" value={contactNote} onChange={setContactNote} />
          {nextStatuses[handoff.status].map(status => <Action key={status} label={contactLabels[status]} disabled={busy || !actor.trim() || !contactNote.trim()}
            onPress={() => void act(async () => {await droneIntake.recordContact(handoff, actor, status, channel, contactNote); setContactNote(''); await refresh();})} />)}
        </>}
      </View>)}
    </View>}
    {busy && <Text style={styles.meta}>Saving…</Text>}
    {error && <Text accessibilityRole="alert" style={styles.notice}>{error}</Text>}
    <Text style={styles.meta}>Coordinator names are entered manually in this prototype. Observation verification confirms the reviewed evidence; it does not establish a medical diagnosis or authorize a rescue.</Text>
  </ScrollView>;
}

function Field({label, value, onChange}: {label: string; value: string; onChange: (s: string) => void}) {
  return <View><Text style={styles.meta}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChange} style={styles.input} /></View>;
}
function Action({label, onPress, disabled = false, active = false}: {label: string; onPress: () => void; disabled?: boolean; active?: boolean}) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress}
    style={[styles.button, active && styles.active, disabled && {opacity: .4}]}><Text style={styles.body}>{label}</Text></Pressable>;
}
function Check({label, checked, onPress}: {label: string; checked: boolean; onPress: () => void}) {
  return <Pressable accessibilityRole="checkbox" accessibilityState={{checked}} onPress={onPress}><Text style={styles.body}>{checked ? '☑' : '☐'} {label}</Text></Pressable>;
}
const styles = StyleSheet.create({
  screen: {flex: 1, backgroundColor: colors.background}, content: {padding: spacing.lg, gap: spacing.md, maxWidth: 1000, width: '100%', alignSelf: 'center'},
  title: {...type.title, color: colors.text}, heading: {...type.heading, color: colors.text},
  body: {...type.body, color: colors.textMuted, lineHeight: 22}, meta: {...type.meta, color: colors.textFaint, lineHeight: 19},
  notice: {...type.body, color: colors.warning}, card: {...glass, padding: spacing.md, gap: spacing.sm},
  input: {color: colors.text, borderColor: colors.borderStrong, borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm},
  button: {borderColor: colors.borderStrong, borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm},
  active: {borderColor: colors.accent, backgroundColor: colors.accentSoft}, actions: {flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm},
});
