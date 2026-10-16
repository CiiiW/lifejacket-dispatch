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

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import MapView, { Marker } from 'react-native-maps';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import { File } from 'expo-file-system';

import LocationPicker, { type PickedLocation } from '../components/LocationPicker';

import {
  ApiError,
  reporter,
  severityColour,
  type Conditions,
  type Turn,
} from '../lib/api';
import { reporterVerdict, summariseConditions } from '../../../shared/conditions';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

/**
 * One entry in the transcript.
 *
 * A photo and a location are shown as themselves -- a thumbnail and a small
 * map -- rather than as the words "[photo sent]". A reporter should be able to
 * glance back and confirm they sent the right picture, the way any messaging
 * app lets them.
 */
type Bubble =
  | { kind: 'text'; from: 'agent' | 'me'; text: string }
  | { kind: 'photo'; from: 'me'; uri: string }
  | { kind: 'location'; from: 'me'; latitude: number; longitude: number; accuracy?: number }
  /**
   * A fact the system worked out, announced the moment it is known.
   *
   * Three agents run behind each turn and the reporter used to see none of
   * it -- only a spinner, then eventually a question. Conditions, species,
   * triage and advice now land in the transcript as they are established.
   */
  | { kind: 'status'; label: string; text: string; provisional?: boolean }
  /**
   * The triage outcome, sized and coloured so it is read first, with the
   * reasons that produced it.
   *
   * `reasons` comes from the deterministic scorer -- the actual rules that
   * fired, not a model's account of its own thinking. A reporter told their
   * animal is critical deserves to know which fact made it so.
   */
  | {
      kind: 'verdict';
      severity: string;
      headline: string;
      detail: string;
      reasons: string[];
      conditionsNote?: string | null;
      provisional?: boolean;
    }
  /**
   * Which teams cover this incident. Shown last, after the verdict and the
   * instructions, because it answers "what happens now" rather than "what do
   * I do". Worded as matched, not contacted -- see `ReporterTeam` in the API.
   */
  /**
   * The safety line, and each instruction as its own card.
   *
   * The agent's closing paragraph put all of this in one block of prose --
   * a safety sentence, "What you can do now:", four bullets and a sign-off.
   * Someone standing over a hurt animal reads a card they can act on; they
   * skim a paragraph.
   */
  | { kind: 'safety'; text: string }
  | { kind: 'instruction'; index: number; total: number; text: string }
  | { kind: 'closing'; text: string }
  | { kind: 'teams'; teams: { name: string; distance_km: number | null }[] }
  /**
   * A team has actually been assigned by a coordinator.
   *
   * This is the one event in the whole flow the reporter most wants and
   * cannot otherwise see in the chat: it happens after intake finishes, so
   * the conversation has to keep listening for it (see the poll below).
   */
  | { kind: 'dispatched'; names: string[] };

/**
 * Tints cycled across the instruction cards.
 *
 * Seafoam first because it is the app's own accent, then three hues far
 * enough apart to be told apart at a glance in sunlight. Deliberately not
 * red or amber: those mean danger elsewhere in the app, and a step like
 * "keep dogs away" is not a hazard warning.
 */
const STEP_TINTS = ['#48CAE4', '#5BD99A', '#9D8DF1', '#F58FB5'];

/** How often to check whether a team has been dispatched, once intake ends. */
const DISPATCH_POLL_MS = 15_000;

/** Labels for what the system is doing, so the wait is not unexplained. */
const WAIT_LABELS: Record<string, string> = {
  start: 'Starting your report…',
  photo: 'Looking at your photo…',
  location: 'Checking the tide, weather and daylight where you are…',
  reply: 'Working out what this means…',
};

export default function ReportScreen({
  onComplete,
  onIncident,
  onLocation,
  onConditions,
  pendingPin = null,
  onPinSubmitted,
}: {
  onComplete: (incidentId: string) => void;
  /** Fires as soon as an incident id exists, so other tabs can open. */
  onIncident?: (incidentId: string) => void;
  /** Fires when the reporter shares GPS, so the map tab can centre on it. */
  onLocation?: (latitude: number, longitude: number) => void;
  /** Weather/tide/daylight, which arrive with every turn once located. */
  onConditions?: (conditions: Conditions) => void;
  /**
   * A pin the reporter placed on the Map tab, waiting to be submitted.
   *
   * Handed in rather than submitted there, because setting a location
   * advances the conversation and this screen owns that.
   */
  pendingPin?: { latitude: number; longitude: number } | null;
  onPinSubmitted?: () => void;
}) {
  const [turn, setTurn] = useState<Turn | null>(null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [waitLabel, setWaitLabel] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  // Non-null while the map picker is open, holding the starting fix.
  const [pickerStart, setPickerStart] = useState<{
    latitude: number;
    longitude: number;
    accuracy?: number;
  } | null>(null);
  const scrollRef = useRef<ScrollView>(null);

  // What has already been announced, so a fact is reported when it changes
  // rather than repeated after every turn.
  const announced = useRef<{
    conditions: boolean;
    species: string | null;
    severity: string | null;
  }>({ conditions: false, species: null, severity: null });

  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [bubbles]);

  /**
   * Turn a fresh response into status bubbles for anything newly established.
   *
   * Ordered the way it becomes known: where you are, what the animal is, how
   * urgent it is, what to do about it.
   */
  const announceFacts = useCallback((next: Turn): Bubble[] => {
    const notes: Bubble[] = [];
    const seen = announced.current;

    if (next.conditions && !seen.conditions) {
      const summary = summariseConditions(next.conditions);
      if (summary) {
        seen.conditions = true;
        notes.push({ kind: 'status', label: 'Conditions', text: summary });
      }
    }

    if (next.identified_as && next.identified_as !== seen.species) {
      const first = seen.species === null;
      seen.species = next.identified_as;

      // Written as a sentence rather than a bare name. "California Sea Lion ·
      // 95%" assumes the reader knows what that line is for; "I think this is
      // a California Sea Lion" does not.
      const confidence =
        next.species_confidence !== null
          ? `, and I am ${Math.round(next.species_confidence * 100)}% sure`
          : '';
      // A genus or family answer is a real answer, not a failure -- but the
      // reporter should know it covers several lookalike species.
      const rank =
        next.taxon_rank && next.taxon_rank !== 'species'
          ? `. That is a ${next.taxon_rank}, which covers a few similar species that cannot be told apart from this distance`
          : '';

      notes.push({
        kind: 'status',
        label: first ? 'Species identified' : 'Species updated',
        text: `From your photo, this looks like a ${next.identified_as}${confidence}${rank}.`,
        provisional: !next.complete,
      });
    }

    if (next.severity_level && next.severity_level !== seen.severity) {
      seen.severity = next.severity_level;
      const verdict = reporterVerdict(next.severity_level);
      notes.push({
        kind: 'verdict',
        severity: next.severity_level,
        headline: verdict.headline,
        detail: verdict.detail,
        // The actual rules that fired, plus what the animal looks like.
        // Without these the verdict is an unexplained label.
        reasons: [
          ...(next.injury_summary ? [next.injury_summary] : []),
          ...next.severity_reasons,
        ],
        conditionsNote: next.environmental_rationale,
        provisional: !next.complete,
      });
    }

    // Advice is deliberately NOT announced as a status note. The closing
    // message carries the same safety guidance and instructions as agent
    // prose, so a note repeated it almost word for word.
    return notes;
  }, []);

  /**
   * Run an API call, show its message, and keep the UI consistent.
   *
   * Centralised so every call path gets the same spinner and error handling --
   * a network failure mid-intake must not leave the screen stuck.
   */
  const run = useCallback(
    async (call: () => Promise<Turn>, waiting?: string) => {
    setBusy(true);
    setWaitLabel(waiting ?? WAIT_LABELS.reply);
    try {
      const next = await call();
      setTurn(next);
      onIncident?.(next.incident_id);
      if (next.conditions) {
        onConditions?.(next.conditions);
      }

      // Order on the final turn: the verdict (from `announceFacts`), then the
      // agent's instructions, then who the report went to. Urgency first,
      // then what to do about it, then what happens next.
      const notes = announceFacts(next);

      // On the final turn the advice is rendered as cards from the structured
      // fields, so `next.message` -- which is the same advice as one
      // paragraph -- is deliberately not shown. Showing both duplicated it.
      const advice: Bubble[] = [];
      if (next.complete) {
        if (next.safety_guidance) {
          advice.push({ kind: 'safety', text: next.safety_guidance });
        }
        next.reporter_instructions.forEach((step, index) =>
          advice.push({
            kind: 'instruction',
            index: index + 1,
            total: next.reporter_instructions.length,
            text: step,
          }),
        );
        if (next.closing_note) {
          advice.push({ kind: 'closing', text: next.closing_note });
        }
        if (next.matched_teams.length > 0) {
          advice.push({ kind: 'teams', teams: next.matched_teams });
        }
      }

      const prose: Bubble[] =
        next.message && !next.complete
          ? [{ kind: 'text', from: 'agent', text: next.message }]
          : [];

      setBubbles((prev) => [...prev, ...notes, ...prose, ...advice]);

      if (next.complete) {
        onComplete(next.incident_id);
      }
    } catch (error) {
      // The reporter gets a plain sentence; the real cause goes to the Expo
      // terminal. Without this, a network-level failure and a bad file path
      // are indistinguishable from "Could not reach LifeJacket."
      console.warn('[LifeJacket] request failed:', error);
      const message =
        error instanceof ApiError ? error.message : 'Could not reach LifeJacket.';
      Alert.alert('Something went wrong', message);
    } finally {
      setBusy(false);
      setWaitLabel(null);
    }
    },
    [onComplete, onIncident, onConditions, announceFacts],
  );

  // Submit a pin placed on the Map tab. `source: 'map_pin'` is recorded so a
  // responder can tell a hand-placed position from a GPS fix.
  useEffect(() => {
    if (!pendingPin || !turn || busy) return;
    const { latitude, longitude } = pendingPin;
    setBubbles((prev) => [
      ...prev,
      { kind: 'location', from: 'me', latitude, longitude },
    ]);
    onLocation?.(latitude, longitude);
    void run(
      () => reporter.setLocation(turn.incident_id, latitude, longitude, undefined, 'map_pin'),
      WAIT_LABELS.location,
    ).then(() => onPinSubmitted?.());
  }, [pendingPin, turn, busy, run, onLocation, onPinSubmitted]);

  /**
   * After intake finishes, keep watching for an actual dispatch.
   *
   * A coordinator approves every dispatch by hand, which happens minutes to
   * hours after the conversation ends -- so the single thing the reporter
   * most wants to know ("is someone coming?") lands outside the chat
   * entirely unless it is polled for. The Map tab shows ETAs; this puts the
   * moment it changes into the transcript, where they are already looking.
   */
  const dispatchSeen = useRef<Set<string>>(new Set());
  useEffect(() => {
    const incidentId = turn?.incident_id;
    if (!incidentId || !turn?.complete) return;

    let cancelled = false;

    async function poll() {
      try {
        const etas = await reporter.getEtas(incidentId as string);
        if (cancelled) return;

        const fresh = etas
          .map((eta) => eta.name)
          .filter((name) => !dispatchSeen.current.has(name));
        if (fresh.length === 0) return;

        fresh.forEach((name) => dispatchSeen.current.add(name));
        setBubbles((prev) => [...prev, { kind: 'dispatched', names: fresh }]);
      } catch {
        // A failed poll is not worth an alert; the next one will likely work.
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), DISPATCH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [turn?.incident_id, turn?.complete]);

  // Start the report as soon as the screen opens. One fewer tap matters when
  // someone is standing in front of a distressed animal. The ref guards
  // against a second start if `run` is ever re-created.
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void run(() => reporter.start(), WAIT_LABELS.start);
  }, [run]);

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

    const asset = result.assets?.[0];
    if (!asset?.uri) {
      // Guard rather than assume: a camera result with no usable file would
      // otherwise reach `fetch` as an undefined URI, which fails as a network
      // error and reads to the user as "could not reach the server".
      console.warn('[LifeJacket] camera returned no usable asset:', result);
      Alert.alert('Photo problem', 'The camera did not return a usable photo. Try again.');
      return;
    }

    // `File` implements `Blob`, which is the only file part React Native 0.86
    // accepts in a FormData -- the older `{ uri, name, type }` object fails
    // with "Unsupported FormDataPart implementation".
    const file = new File(asset.uri);
    console.warn('[LifeJacket] uploading photo:', asset.uri, file.type, file.size);

    setBubbles((prev) => [...prev, { kind: 'photo', from: 'me', uri: asset.uri }]);
    await run(
      () => reporter.uploadPhoto(turn.incident_id, file, asset.fileName ?? 'photo.jpg'),
      WAIT_LABELS.photo,
    );
  }

  /**
   * Step one of sharing a location: get a fix and show it on a map.
   *
   * Nothing is sent yet. The reporter confirms on the map, because a GPS fix
   * says where *they* are and the animal is often somewhere else.
   */
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

    setLocating(true);
    try {
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      setPickerStart({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy ?? undefined,
      });
    } catch (error) {
      console.warn('[LifeJacket] could not get a position:', error);
      Alert.alert(
        'Could not find you',
        'Your location could not be read. Try again, or move somewhere with a clearer view of the sky.',
      );
    } finally {
      setLocating(false);
    }
  }

  /** Step two: the reporter has confirmed the pin, so send it. */
  async function confirmLocation(picked: PickedLocation) {
    if (!turn) return;
    setPickerStart(null);

    setBubbles((prev) => [
      ...prev,
      {
        kind: 'location',
        from: 'me',
        latitude: picked.latitude,
        longitude: picked.longitude,
        accuracy: picked.accuracy,
      },
    ]);
    onLocation?.(picked.latitude, picked.longitude);
    await run(
      () =>
        reporter.setLocation(
          turn.incident_id,
          picked.latitude,
          picked.longitude,
          picked.accuracy,
          // Honest about which it is: a moved pin is no longer a GPS reading.
          picked.moved ? 'map_pin' : 'device_gps',
        ),
      WAIT_LABELS.location,
    );
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || !turn) return;

    setBubbles((prev) => [...prev, { kind: 'text', from: 'me', text: trimmed }]);
    setDraft('');
    await run(() => reporter.reply(turn.incident_id, trimmed));
  }

  const action = turn?.action;
  const needsPhoto = action === 'request_photo' || action === 'request_better_photo';
  const needsLocation = action === 'request_location';
  const isQuestion = action === 'ask_clarifying_question';
  // The backend could not run a step (model failure). Nothing was lost; the
  // same step runs again when the reporter taps the button.
  const needsRetry = action === 'service_retry';

  return (
    <View style={styles.screen}>
      {pickerStart && (
        <LocationPicker
          visible
          initialLatitude={pickerStart.latitude}
          initialLongitude={pickerStart.longitude}
          initialAccuracy={pickerStart.accuracy}
          saving={busy}
          onConfirm={(picked) => void confirmLocation(picked)}
          onCancel={() => setPickerStart(null)}
        />
      )}

      <View style={styles.header}>
        <Text style={styles.title}>Report an animal</Text>
        {turn?.identified_as && (
          <Text style={styles.progress}>Looks like: {turn.identified_as}</Text>
        )}
      </View>

      {/* Once triage is settled the outcome stays on screen. Scrolling back
          through the transcript to remember whether it was critical is not
          something to ask of someone standing next to the animal. */}
      {turn?.complete && turn.severity_level && (
        <View
          style={[
            styles.banner,
            { backgroundColor: severityColour(turn.severity_level) },
          ]}
        >
          <Text style={styles.bannerHeadline}>
            {reporterVerdict(turn.severity_level).headline}
          </Text>
          <Text style={styles.bannerDetail}>
            {reporterVerdict(turn.severity_level).detail}
          </Text>
        </View>
      )}

      <ScrollView ref={scrollRef} style={styles.transcript} contentContainerStyle={styles.transcriptInner}>
        {bubbles.map((bubble, index) => (
          <TranscriptBubble key={index} bubble={bubble} />
        ))}
        {busy && (
          <View style={styles.working}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.workingText}>{waitLabel ?? 'Working…'}</Text>
          </View>
        )}
      </ScrollView>

      <View style={styles.actions}>
        {needsPhoto && (
          <Pressable style={styles.primary} onPress={takePhoto} disabled={busy}>
            <Text style={styles.primaryText}>Take a photo</Text>
          </Pressable>
        )}

        {/* One button. It opens a map so the pin can be checked and moved
            before anything is sent -- see LocationPicker. */}
        {needsLocation && (
          <Pressable
            style={[styles.primary, (busy || locating) && styles.primaryDisabled]}
            onPress={shareLocation}
            disabled={busy || locating}
          >
            <Text style={styles.primaryText}>
              {locating ? 'Finding you…' : 'Share location'}
            </Text>
          </Pressable>
        )}

        {needsRetry && turn && (
          <Pressable
            style={styles.primary}
            onPress={() => void run(() => reporter.retry(turn.incident_id))}
            disabled={busy}
          >
            <Text style={styles.primaryText}>Try again</Text>
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

/**
 * One transcript entry, rendered as what it is.
 *
 * Photos and locations get their own treatment: a thumbnail and a small
 * non-interactive map. The map is deliberately not pannable -- it is a
 * receipt showing what was sent, not a tool. The Map tab is for exploring.
 */
function TranscriptBubble({ bubble }: { bubble: Bubble }) {
  if (bubble.kind === 'verdict') {
    const tint = severityColour(bubble.severity);
    return (
      <View style={[styles.verdict, { borderColor: tint }]}>
        <View style={styles.verdictRow}>
          <View style={[styles.verdictDot, { backgroundColor: tint }]} />
          <Text style={[styles.verdictHeadline, { color: tint }]}>{bubble.headline}</Text>
          {bubble.provisional && <Text style={styles.verdictProvisional}>so far</Text>}
        </View>
        <Text style={styles.verdictDetail}>{bubble.detail}</Text>

        {bubble.reasons.length > 0 && (
          <View style={styles.reasons}>
            <Text style={styles.reasonsLabel}>Why</Text>
            {bubble.reasons.map((reason) => (
              <Text key={reason} style={styles.reasonLine}>
                • {reason}
              </Text>
            ))}
          </View>
        )}

        {bubble.conditionsNote && (
          <Text style={styles.verdictConditions}>{bubble.conditionsNote}</Text>
        )}
      </View>
    );
  }

  if (bubble.kind === 'dispatched') {
    const names = bubble.names.join(', ');
    return (
      <View style={[styles.verdict, { borderColor: colors.success }]}>
        <View style={styles.verdictRow}>
          <View style={[styles.verdictDot, { backgroundColor: colors.success }]} />
          <Text style={[styles.verdictHeadline, { color: colors.success }]}>
            Help is on the way
          </Text>
        </View>
        <Text style={styles.verdictDetail}>
          {bubble.names.length === 1
            ? `${names} has been assigned to this report.`
            : `${names} have been assigned to this report.`}
        </Text>
        <Text style={styles.verdictConditions}>
          You can watch them approach on the Map tab.
        </Text>
      </View>
    );
  }

  if (bubble.kind === 'safety') {
    // Amber, and first: the one card that is about the reporter's own safety
    // rather than the animal's.
    return (
      <View style={[styles.card, styles.safetyCard]}>
        <Text style={styles.cardLabel}>Keep yourself safe</Text>
        <Text style={styles.cardBody}>{bubble.text}</Text>
      </View>
    );
  }

  if (bubble.kind === 'instruction') {
    // Each step numbered and tinted, cycling through the palette so a list of
    // four is four distinct things rather than one grey block.
    const tint = STEP_TINTS[(bubble.index - 1) % STEP_TINTS.length];
    return (
      <View style={[styles.card, { borderLeftColor: tint, borderLeftWidth: 4 }]}>
        <View style={styles.stepRow}>
          <View style={[styles.stepNumber, { backgroundColor: tint }]}>
            <Text style={styles.stepNumberText}>{bubble.index}</Text>
          </View>
          <Text style={[styles.cardLabel, { color: tint }]}>
            Step {bubble.index} of {bubble.total}
          </Text>
        </View>
        <Text style={styles.cardBody}>{bubble.text}</Text>
      </View>
    );
  }

  if (bubble.kind === 'closing') {
    return (
      <View style={[styles.card, styles.closingCard]}>
        <Text style={styles.cardBody}>{bubble.text}</Text>
      </View>
    );
  }

  if (bubble.kind === 'teams') {
    return (
      <View style={styles.status}>
        <Text style={styles.statusLabel}>Rescue teams for this area</Text>
        {bubble.teams.map((team) => (
          <Text key={team.name} style={styles.teamLine}>
            • {team.name}
            {team.distance_km !== null ? ` — ${Math.round(team.distance_km)} km away` : ''}
          </Text>
        ))}
        {/* Precise wording matters: nothing has been dispatched yet, and
            telling someone a team is on the way when none is would be worse
            than telling them nothing. */}
        <Text style={styles.teamNote}>
          Your report has gone to the coordinators who cover this area. One of
          them decides who attends — follow progress on the Map tab.
        </Text>
      </View>
    );
  }

  // A status note is the system reporting a finding, not a party in the
  // conversation -- so it sits across the full width rather than on a side.
  if (bubble.kind === 'status') {
    return (
      <View style={styles.status}>
        <Text style={styles.statusLabel}>
          {bubble.label}
          {bubble.provisional ? ' · so far' : ''}
        </Text>
        <Text style={styles.statusText}>{bubble.text}</Text>
      </View>
    );
  }

  const side = bubble.from === 'me' ? styles.mine : styles.theirs;

  if (bubble.kind === 'photo') {
    return (
      <View style={[styles.bubble, styles.mediaBubble, side]}>
        <Image source={{ uri: bubble.uri }} style={styles.photo} resizeMode="cover" />
      </View>
    );
  }

  if (bubble.kind === 'location') {
    return (
      <View style={[styles.bubble, styles.mediaBubble, side]}>
        <MapView
          style={styles.miniMap}
          pointerEvents="none"
          scrollEnabled={false}
          zoomEnabled={false}
          rotateEnabled={false}
          pitchEnabled={false}
          initialRegion={{
            latitude: bubble.latitude,
            longitude: bubble.longitude,
            latitudeDelta: 0.008,
            longitudeDelta: 0.008,
          }}
        >
          <Marker
            coordinate={{ latitude: bubble.latitude, longitude: bubble.longitude }}
            pinColor={colors.danger}
          />
        </MapView>
        <Text style={styles.locationCaption}>
          {bubble.latitude.toFixed(5)}, {bubble.longitude.toFixed(5)}
          {bubble.accuracy ? ` · ±${Math.round(bubble.accuracy)} m` : ''}
        </Text>
      </View>
    );
  }

  return (
    <View style={[styles.bubble, side]}>
      <Text style={bubble.from === 'me' ? styles.mineText : styles.theirsText}>
        {bubble.text}
      </Text>
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
  banner: {
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.card,
    gap: 1,
  },
  bannerHeadline: { ...type.heading, fontSize: 17, color: colors.onAccent },
  bannerDetail: { ...type.meta, fontSize: 12.5, color: colors.onAccent, lineHeight: 17 },
  transcript: { flex: 1 },
  transcriptInner: { padding: spacing.lg, gap: spacing.sm },
  bubble: { maxWidth: '85%', padding: spacing.md, borderRadius: radius.lg },
  /** Media fills its bubble, so the padding would just be a border. */
  mediaBubble: { padding: spacing.xs, maxWidth: '78%' },
  photo: { width: 230, height: 300, borderRadius: radius.card },
  miniMap: { width: 230, height: 150, borderRadius: radius.card },
  locationCaption: {
    ...type.meta,
    fontSize: 11,
    color: colors.onAccent,
    paddingHorizontal: spacing.sm,
    paddingTop: spacing.xs,
    paddingBottom: 2,
  },
  theirs: { ...glass, alignSelf: 'flex-start' },
  mine: { ...shadow.soft, alignSelf: 'flex-end', backgroundColor: colors.accent },
  theirsText: { ...type.body, fontSize: 16, color: colors.text, lineHeight: 22 },
  mineText: { ...type.body, fontSize: 16, color: colors.onAccent, lineHeight: 22 },
  working: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  workingText: { ...type.meta, fontSize: 12.5, color: colors.textMuted, flex: 1 },

  status: {
    ...glass,
    alignSelf: 'stretch',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    gap: 3,
    borderLeftWidth: 2,
    borderLeftColor: colors.accent,
  },
  statusLabel: { ...type.eyebrow, fontSize: 10, color: colors.accent },
  statusText: { ...type.body, fontSize: 14, color: colors.text, lineHeight: 20 },

  verdict: {
    ...glass,
    ...shadow.soft,
    alignSelf: 'stretch',
    borderWidth: 1.5,
    padding: spacing.md,
    gap: spacing.xs,
  },
  verdictRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  verdictDot: { width: 10, height: 10, borderRadius: 5 },
  verdictHeadline: { ...type.title, fontSize: 20 },
  verdictProvisional: { ...type.meta, fontSize: 11, color: colors.textFaint },
  verdictDetail: { ...type.body, fontSize: 14, color: colors.text, lineHeight: 20 },
  reasons: {
    marginTop: spacing.xs,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 2,
  },
  reasonsLabel: { ...type.eyebrow, fontSize: 9.5, color: colors.textFaint },
  reasonLine: { ...type.meta, fontSize: 13, color: colors.textMuted, lineHeight: 18 },
  verdictConditions: {
    ...type.meta,
    fontSize: 12,
    color: colors.textFaint,
    lineHeight: 17,
    marginTop: spacing.xs,
  },

  card: {
    ...glass,
    ...shadow.soft,
    alignSelf: 'stretch',
    padding: spacing.md,
    gap: spacing.xs,
  },
  safetyCard: {
    backgroundColor: 'rgba(255, 192, 67, 0.10)',
    borderColor: 'rgba(255, 192, 67, 0.40)',
    borderLeftWidth: 4,
    borderLeftColor: colors.warning,
  },
  closingCard: { backgroundColor: colors.glassFill },
  cardLabel: { ...type.eyebrow, fontSize: 10, color: colors.warning },
  cardBody: { ...type.body, fontSize: 15, color: colors.text, lineHeight: 21 },
  stepRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  stepNumber: {
    width: 20,
    height: 20,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: { ...type.label, fontSize: 12, color: colors.onAccent },

  teamLine: { ...type.body, fontSize: 14, color: colors.text, lineHeight: 20 },
  teamNote: {
    ...type.meta,
    fontSize: 12,
    color: colors.textMuted,
    lineHeight: 17,
    marginTop: spacing.xs,
  },
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
  primaryDisabled: { opacity: 0.6 },
  secondary: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: colors.glassFill,
    paddingVertical: spacing.md,
    borderRadius: radius.card,
    alignItems: 'center',
  },
  secondaryText: { ...type.label, fontSize: 15, color: colors.text },
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
