/**
 * Web build of the triage map.
 *
 * The native file (`IncidentMapScreen.tsx`) uses `react-native-maps`, which
 * is iOS/Android only. On web this renders MapLibre GL instead -- see
 * `components/TriageMap.web.tsx` -- so the console gets a real map in a
 * browser. Metro picks this `.web.tsx` file automatically when bundling for
 * web. The two files share the list panel but not the map.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import CasePanel from '../components/CasePanel.web';
import TriageMap from '../components/TriageMap.web';
import {
  absoluteUrl,
  responder,
  severityColour,
  severityLabel,
  type MapPin,
  type HistoricalDensity,
  type ResponderOrg,
  type RouteLine,
} from '../lib/api';
import { colors, glass, radius, shadow, spacing, type } from '../lib/theme';

const REFRESH_INTERVAL_MS = 30_000;

// The list panel is user-resizable. Bounds keep both sides usable: the panel
// rows need room for a title and tags, and the map needs room to be a map.
const PANEL_DEFAULT_WIDTH = 380;
const PANEL_MIN_WIDTH = 300;
const MAP_MIN_WIDTH = 360;
const PANEL_KEY_STEP = 24;

/** Statuses that mean the incident already ended, so its row reads as done. */
const CLOSED_STATUSES = new Set(['resolved', 'guidance_only']);
const isClosed = (status: string) => CLOSED_STATUSES.has(status);

export default function IncidentMapScreen({
  onSelect,
}: {
  onSelect: (incidentId: string) => void;
}) {
  const [pins, setPins] = useState<MapPin[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [centres, setCentres] = useState<ResponderOrg[]>([]);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [route, setRoute] = useState<RouteLine | null>(null);
  const [density, setDensity] = useState<HistoricalDensity | null>(null);
  const [showDensity, setShowDensity] = useState(false);
  const [panelWidth, setPanelWidth] = useState(PANEL_DEFAULT_WIDTH);
  const [mapExpanded, setMapExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const clampPanel = useCallback(
    (width: number) =>
      Math.max(PANEL_MIN_WIDTH, Math.min(width, window.innerWidth - MAP_MIN_WIDTH)),
    [],
  );

  // Drag from the divider: the panel is on the right, so moving left widens it.
  // Listeners go on `window` so the drag keeps tracking over the map canvas,
  // which would otherwise swallow the pointer events.
  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = panelWidth;
      setDragging(true);
      const previousSelect = document.body.style.userSelect;
      document.body.style.userSelect = 'none';

      const move = (e: PointerEvent) => setPanelWidth(clampPanel(startWidth - (e.clientX - startX)));
      const stop = () => {
        setDragging(false);
        document.body.style.userSelect = previousSelect;
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', stop);
        window.removeEventListener('pointercancel', stop);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
    },
    [panelWidth, clampPanel],
  );

  const dividerKey = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'ArrowLeft') setPanelWidth((w) => clampPanel(w + PANEL_KEY_STEP));
      else if (event.key === 'ArrowRight') setPanelWidth((w) => clampPanel(w - PANEL_KEY_STEP));
      else return;
      event.preventDefault();
    },
    [clampPanel],
  );

  useEffect(() => {
    responder.historicalDensity().then(setDensity).catch(() => setDensity(null));
  }, []);

  const load = useCallback(async () => {
    try {
      setPins(await responder.listIncidents({ includeClosed: showClosed }));
    } catch {
      // Keep the previous list rather than blanking the map on a flaky signal.
    } finally {
      setRefreshing(false);
    }
  }, [showClosed]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // The rescue-centre directory changes rarely, so it is fetched once rather
  // than on the incident refresh timer.
  useEffect(() => {
    responder
      .list()
      .then(setCentres)
      .catch(() => setCentres([]));
  }, []);

  /**
   * Clicking a pin or row highlights it and asks the backend to route the
   * nearest-by-straight-line centre to it, which is a reasonable stand-in
   * until a coordinator has actually assigned someone.
   */
  const highlight = useCallback(
    (incidentId: string) => {
      setHighlighted(incidentId);
      setDetailId(incidentId);
      setRoute(null);

      const pin = (pins ?? []).find((p) => p.incident_id === incidentId);
      const located = centres.filter((c) => c.latitude !== null && c.longitude !== null);
      if (!pin || pin.latitude === null || pin.longitude === null || located.length === 0) {
        return;
      }

      const nearest = located.reduce((best, candidate) => {
        const distance = (c: ResponderOrg) =>
          ((c.latitude as number) - (pin.latitude as number)) ** 2 +
          ((c.longitude as number) - (pin.longitude as number)) ** 2;
        return distance(candidate) < distance(best) ? candidate : best;
      });

      responder
        .getRoute(incidentId, nearest.responder_id)
        .then(setRoute)
        .catch(() => setRoute(null));
    },
    [pins, centres],
  );

  // Sort the list by urgency rather than by time: a coordinator opening the
  // console needs the worst case first, not the newest.
  const order = ['critical', 'respond', 'monitor', 'guidance'];
  const sorted = [...(pins ?? [])].sort(
    (a, b) =>
      order.indexOf(a.severity_level ?? 'guidance') -
      order.indexOf(b.severity_level ?? 'guidance'),
  );

  const detailPin = detailId ? ((pins ?? []).find((p) => p.incident_id === detailId) ?? null) : null;

  if (pins === null) {
    return <ActivityIndicator style={styles.loading} size="large" color={colors.accent} />;
  }

  return (
    <View style={styles.screen}>
      <View style={styles.mapWrap}>
        <TriageMap
          pins={pins}
          centres={centres}
          route={route}
          density={density}
          showDensity={showDensity}
          selectedId={highlighted}
          onSelect={highlight}
          popup={false}
        />
        <Pressable
          style={styles.expandButton}
          accessibilityRole="button"
          accessibilityLabel={mapExpanded ? 'Show incident list' : 'Expand map'}
          onPress={() => setMapExpanded((current) => !current)}
        >
          <Text style={styles.expandText}>{mapExpanded ? 'Show list' : 'Expand map'}</Text>
        </Pressable>
      </View>

      {!mapExpanded && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize map and incident list"
          aria-valuenow={panelWidth}
          tabIndex={0}
          onPointerDown={startDrag}
          onKeyDown={dividerKey}
          onDoubleClick={() => setPanelWidth(PANEL_DEFAULT_WIDTH)}
          title="Drag to resize · double-click to reset"
          style={{
            flex: '0 0 8px',
            cursor: 'col-resize',
            touchAction: 'none',
            background: dragging ? colors.accent : colors.border,
            opacity: dragging ? 0.8 : 1,
          }}
        />
      )}

      <View style={[styles.panel, { width: panelWidth }, mapExpanded && styles.panelHidden]}>
        {detailPin && (
          <CasePanel
            pin={detailPin}
            leadCentre={
              centres.find((c) => c.responder_id === detailPin.assigned_responder_id)?.name ?? null
            }
            onBack={() => {
              setDetailId(null);
              setHighlighted(null);
              setRoute(null);
            }}
            onOpenFull={() => onSelect(detailPin.incident_id)}
          />
        )}
        <View style={detailPin ? styles.listHidden : styles.listShown}>
        <Pressable
          style={[styles.filter, { alignSelf: 'flex-start', marginBottom: spacing.sm }, showDensity && styles.filterActive]}
          disabled={!density?.available || density.cells.length === 0}
          onPress={() => setShowDensity((current) => !current)}
        >
          <Text style={[styles.filterText, showDensity && styles.filterTextActive]}>
            {showDensity ? 'Hide historical reports' : 'Show historical reports'}
          </Text>
        </Pressable>
        <Text style={styles.densityNote}>
          {density?.available ? density.caveat : 'Historical data has not been imported here.'}
        </Text>
        <View style={styles.panelHeader}>
          <Text style={styles.heading}>
            {pins.length} {showClosed ? '' : 'open '}
            {pins.length === 1 ? 'incident' : 'incidents'}
          </Text>
          <Pressable
            style={[styles.filter, showClosed && styles.filterActive]}
            onPress={() => setShowClosed((previous) => !previous)}
          >
            <Text style={[styles.filterText, showClosed && styles.filterTextActive]}>
              {showClosed ? 'Open only' : 'Show closed'}
            </Text>
          </Pressable>
        </View>

        <FlatList
          data={sorted}
          keyExtractor={(item) => item.incident_id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              tintColor={colors.accent}
              onRefresh={() => {
                setRefreshing(true);
                void load();
              }}
            />
          }
          ListEmptyComponent={
            <Text style={styles.empty}>
              Nothing open right now. Reports arrive here as the intake agent
              finishes them.
            </Text>
          }
          renderItem={({ item }) => (
            <Pressable
              style={[
                styles.row,
                isClosed(item.status) && styles.rowClosed,
                item.incident_id === highlighted && styles.rowHighlighted,
              ]}
              // One tap highlights on the map and routes to it; the chevron
              // opens the full report. Opening a report is a bigger move than
              // glancing at where the animal is.
              onPress={() => highlight(item.incident_id)}
            >
              <View
                style={[styles.stripe, { backgroundColor: severityColour(item.severity_level) }]}
              />
              {item.photo_url ? (
                <Image
                  source={{ uri: absoluteUrl(item.photo_url) as string }}
                  style={styles.thumb}
                />
              ) : (
                <View style={[styles.thumb, styles.thumbEmpty]} />
              )}
              <View style={styles.rowBody}>
                <Text style={styles.rowTitle} numberOfLines={1}>
                  {item.headline ?? item.species_common_name ?? 'Unidentified animal'}
                </Text>
                <Text style={styles.rowMeta} numberOfLines={1}>
                  <Text style={{ color: severityColour(item.severity_level) }}>
                    {severityLabel(item.severity_level)}
                  </Text>
                  {item.place_name ? ` · ${item.place_name}` : ''}
                  {` · ${item.status.replace(/_/g, ' ')}`}
                </Text>
              </View>
              {/* Entanglement is called out separately because it needs a team
                  with cutting authorisation, which not every centre has. */}
              {item.entanglement && <Text style={styles.tag}>ENTANGLED</Text>}
              {/* Several animals, possibly across several rows of this list. */}
              {item.in_mass_stranding && <Text style={styles.tag}>MASS STRANDING</Text>}

              <Pressable
                style={styles.open}
                onPress={() => onSelect(item.incident_id)}
              >
                <Text style={styles.openText}>Open</Text>
              </Pressable>
            </Pressable>
          )}
        />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, flexDirection: 'row', backgroundColor: colors.background },
  loading: { flex: 1 },
  densityNote: { ...type.meta, color: colors.textMuted, fontSize: 11, marginBottom: spacing.md },

  mapWrap: { flex: 1, minWidth: MAP_MIN_WIDTH, padding: spacing.lg },
  expandButton: {
    position: 'absolute',
    top: spacing.lg + spacing.sm,
    left: spacing.lg + spacing.sm,
    backgroundColor: colors.backgroundElevated,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: spacing.md,
  },
  expandText: { ...type.meta, color: colors.text, fontWeight: '600' },

  // Kept mounted but hidden while the map is expanded, so the list's scroll
  // position and highlighted row survive collapsing and re-opening.
  panelHidden: { display: 'none' },
  // The list stays mounted under the detail card so its scroll position survives.
  listShown: { flex: 1 },
  listHidden: { display: 'none' },

  panel: {
    flexGrow: 0,
    flexShrink: 0,
    backgroundColor: colors.backgroundElevated,
    borderLeftWidth: 1,
    borderLeftColor: colors.border,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
  },
  panelHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  heading: { ...type.title, color: colors.text },
  filter: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingVertical: 5,
    paddingHorizontal: spacing.md,
  },
  filterActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  filterText: { ...type.meta, fontSize: 12, color: colors.textMuted },
  filterTextActive: { color: colors.accent, fontWeight: '700' },
  list: { gap: spacing.sm, paddingBottom: spacing.xl },
  empty: { ...type.meta, color: colors.textFaint, lineHeight: 19 },

  row: {
    ...glass,
    ...shadow.soft,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  rowClosed: { opacity: 0.55 },
  rowHighlighted: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  thumb: { width: 46, height: 46, borderRadius: radius.sm, backgroundColor: colors.glassFill },
  thumbEmpty: { borderWidth: 1, borderColor: colors.border },
  open: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
  },
  openText: { ...type.meta, fontSize: 11.5, color: colors.text },
  stripe: { width: 4, alignSelf: 'stretch', minHeight: 34, borderRadius: radius.pill },
  rowBody: { flex: 1, gap: 3 },
  rowTitle: { ...type.label, color: colors.text, fontSize: 15 },
  rowMeta: { ...type.meta, color: colors.textMuted, fontSize: 12.5 },
  tag: {
    ...type.eyebrow,
    fontSize: 9,
    color: colors.danger,
    borderWidth: 1,
    borderColor: colors.danger,
    borderRadius: radius.sm,
    paddingHorizontal: 5,
    paddingVertical: 3,
    overflow: 'hidden',
  },
});
