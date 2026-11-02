/**
 * The triage map: incidents, rescue centres, and the route between them.
 *
 * MapLibre GL rather than `react-native-maps`, which has no web renderer.
 * This file is web-only (see `IncidentMapScreen.web.tsx`) and talks to
 * MapLibre's imperative API directly, because wrapping a WebGL map in React
 * state is a reliable way to redraw it sixty times a second by accident.
 *
 * What is drawn:
 *
 * - **Incidents**, coloured by the severity the backend computed. Clicking
 *   one selects it, which is the same action as clicking its list row.
 * - **Rescue centres**, as small seafoam rings. Their coordinates are
 *   service-area centroids, not street addresses, so they are deliberately
 *   drawn smaller and dimmer than incidents -- see `/responders/geocode`.
 * - **A route** from the suggested centre to the selected incident, fetched
 *   from the backend (which holds the OpenRouteService key). Dashed when it
 *   is the straight-line fallback rather than a real road route.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import maplibre, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { absoluteUrl, severityColour, severityLabel, type HistoricalDensity, type MapPin,
  type ResponderOrg, type RouteLine,
  type DronePlan, type DronePoint , type SurveyBox } from '../lib/api';
import { basemap } from '../lib/basemap';
import { colors, fontFamily, radius, spacing, type } from '../lib/theme';

const ROUTE_SOURCE = 'route';
const DENSITY_SOURCE = 'historical-density';
const DENSITY_LAYER = 'historical-heatmap';
const DEFAULT_CENTRE: [number, number] = [-121.9, 36.8]; // Monterey Bay
const SURVEY_SOURCE = 'survey-area';

/** Two drag corners in any order -> a normalised south/north/west/east box. */
function cornersToBox(a: maplibre.LngLat, b: maplibre.LngLat): SurveyBox {
  return {
    south: Math.min(a.lat, b.lat),
    north: Math.max(a.lat, b.lat),
    west: Math.min(a.lng, b.lng),
    east: Math.max(a.lng, b.lng),
  };
}

/** A box as a closed polygon, or an empty collection to clear it. */
function boxFeature(box: SurveyBox | null) {
  if (!box) return { type: 'FeatureCollection' as const, features: [] };
  return {
    type: 'FeatureCollection' as const,
    features: [{
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'Polygon' as const,
        coordinates: [[
          [box.west, box.south], [box.east, box.south],
          [box.east, box.north], [box.west, box.north],
          [box.west, box.south],
        ]],
      },
    }],
  };
}

const POPUP_CLASS = 'lj-incident-popup';
const POPUP_STYLE_ID = 'lj-incident-popup-style';

/**
 * Restyle MapLibre's popup chrome to the navy card.
 *
 * Markers are styled inline, but popup chrome is drawn from MapLibre's own
 * stylesheet, so this is the one place CSS is unavoidable. Injected once, on
 * first use, rather than at import time: this module is also loaded by the
 * native bundle's type checking, which has no `document`.
 *
 * The tip is hidden rather than recoloured. MapLibre colours it per anchor
 * direction at the same specificity, so overriding it correctly takes eight
 * rules; instead the card is offset clear of the dot, and the clicked dot
 * takes the selected ring, which is what ties a card to its pin.
 */
function installPopupStyle() {
  if (document.getElementById(POPUP_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = POPUP_STYLE_ID;
  style.textContent = `
    .${POPUP_CLASS} .maplibregl-popup-content {
      background: ${colors.backgroundElevated};
      border: 1px solid ${colors.border};
      border-radius: ${radius.card}px;
      padding: 0;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
    }
    .${POPUP_CLASS} .maplibregl-popup-tip { display: none; }
    .${POPUP_CLASS} .maplibregl-popup-close-button {
      top: 2px;
      right: 2px;
      color: ${colors.textMuted};
      background: transparent;
      border: 0;
      border-radius: ${radius.sm}px;
      font-size: 17px;
      line-height: 1;
      padding: 3px 7px;
    }
    .${POPUP_CLASS} .maplibregl-popup-close-button:hover {
      color: ${colors.text};
      background: ${colors.glassFill};
    }
    /* Clicking the card should not leave a focus ring behind, but a keyboard
       user still needs one -- so suppress it only for the pointer case. */
    .${POPUP_CLASS} .maplibregl-popup-close-button:focus { outline: none; }
    .${POPUP_CLASS} .maplibregl-popup-close-button:focus-visible {
      outline: 2px solid ${colors.accent};
      outline-offset: -2px;
    }
  `;
  document.head.appendChild(style);
}

const MARKER_STYLE_ID = 'lj-marker-style';
const CLUSTER_RADIUS_PX = 36;
// Past this zoom, pins that still overlap are the same spot, so grouping them
// would only hide them behind a count that cannot be opened further.
const CLUSTER_MAX_ZOOM = 15;
const SEVERITY_RANK = ['critical', 'respond', 'monitor', 'guidance'];

/**
 * Nobody has taken these yet. `dispatched` means centres were notified but none
 * has claimed the case, so it still needs eyes; accepted, en route and on scene
 * mean a team owns it.
 */
const NEEDS_ATTENTION = new Set(['awaiting_dispatch', 'dispatched']);

/**
 * Keyframes for the attention pulse. Reduced-motion users get a still halo, so
 * "unclaimed" is still readable without any movement.
 */
function installMarkerStyle() {
  if (document.getElementById(MARKER_STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = MARKER_STYLE_ID;
  style.textContent = `
    @keyframes lj-pulse {
      0% { transform: scale(1); opacity: 1; }
      85%, 100% { transform: scale(4.2); opacity: 0; }
    }
    .lj-pulse-ring {
      position: absolute;
      inset: 0;
      border-radius: 50%;
      pointer-events: none;
      animation: lj-pulse 1.3s ease-out infinite;
    }
    .lj-pulse-ring.lj-pulse-late { animation-delay: 0.65s; }
    @media (prefers-reduced-motion: reduce) {
      .lj-pulse-ring { animation: none; opacity: 0.5; transform: scale(2); }
      .lj-pulse-ring.lj-pulse-late { display: none; }
    }
  `;
  document.head.appendChild(style);
}

/** A round marker; `pulsing` adds an expanding halo behind it. */
function markerDot(opts: {
  size: number;
  colour: string;
  border: string;
  pulsing: boolean;
  label?: string;
}): HTMLElement {
  const wrap = document.createElement('div');
  wrap.style.cssText = `width:${opts.size}px;height:${opts.size}px;cursor:pointer`;
  if (opts.pulsing) {
    // Two rings, half a cycle apart, so the pulse reads as continuous.
    ['', ' lj-pulse-late'].forEach((extra) => {
      const ring = document.createElement('span');
      ring.className = 'lj-pulse-ring' + extra;
      ring.style.background = opts.colour;
      ring.style.border = `3px solid ${opts.colour}`;
      wrap.appendChild(ring);
    });
  }
  const dot = document.createElement('div');
  dot.style.cssText = [
    'position:absolute', 'inset:0', 'border-radius:50%',
    `background:${opts.colour}`, `border:${opts.border}`,
    opts.pulsing
      ? `box-shadow:0 0 0 4px ${opts.colour}55, 0 0 14px ${opts.colour}`
      : 'box-shadow:0 2px 8px rgba(0,0,0,0.5)',
    'display:flex', 'align-items:center', 'justify-content:center',
    `font-family:${fontFamily}`, 'font-size:10px', 'font-weight:800', 'color:#0B132B',
  ].join(';');
  if (opts.label) dot.textContent = opts.label;
  wrap.appendChild(dot);
  return wrap;
}

interface PinCluster {
  pins: MapPin[];
  longitude: number;
  latitude: number;
}

/**
 * Greedy grouping by on-screen distance, so what is grouped depends on the zoom
 * level the coordinator is looking at, not on a fixed geographic radius.
 */
function clusterPins(mapInstance: MapLibreMap, pins: MapPin[]): PinCluster[] {
  const groups: { pins: MapPin[]; x: number; y: number }[] = [];
  pins.forEach((pin) => {
    const point = mapInstance.project([pin.longitude as number, pin.latitude as number]);
    const hit = groups.find((g) => Math.hypot(g.x - point.x, g.y - point.y) <= CLUSTER_RADIUS_PX);
    if (hit) {
      const n = hit.pins.length;
      hit.x = (hit.x * n + point.x) / (n + 1);
      hit.y = (hit.y * n + point.y) / (n + 1);
      hit.pins.push(pin);
    } else {
      groups.push({ pins: [pin], x: point.x, y: point.y });
    }
  });
  return groups.map((g) => ({
    pins: g.pins,
    longitude: g.pins.reduce((sum, p) => sum + (p.longitude as number), 0) / g.pins.length,
    latitude: g.pins.reduce((sum, p) => sum + (p.latitude as number), 0) / g.pins.length,
  }));
}

/**
 * One pin as a summary card, built as DOM rather than React because the popup
 * it goes into is owned by MapLibre.
 *
 * Every field is written with `textContent`, never `innerHTML`: headlines,
 * species and place names all originate in reporter submissions and model
 * output, so interpolating them into markup would be an injection sink.
 *
 * The layout deliberately mirrors a triage list row -- severity stripe, photo,
 * title, meta line, flags -- so the two read as the same object.
 */
function incidentCard(pin: MapPin, leadCentre: string | null): HTMLElement {
  const card = document.createElement('div');
  card.style.cssText = [
    'display:flex', 'gap:10px', 'align-items:flex-start',
    'width:264px', 'padding:11px 26px 11px 11px',
    `font-family:${fontFamily}`, `color:${colors.text}`,
  ].join(';');

  const stripe = document.createElement('div');
  stripe.style.cssText = [
    'flex:0 0 4px', 'align-self:stretch', 'border-radius:2px',
    `background:${severityColour(pin.severity_level)}`,
  ].join(';');
  card.appendChild(stripe);

  const photo = absoluteUrl(pin.photo_url);
  if (photo) {
    const image = document.createElement('img');
    image.src = photo;
    image.alt = '';
    image.style.cssText = [
      'flex:0 0 50px', 'width:50px', 'height:50px',
      `border-radius:${radius.sm}px`, 'object-fit:cover',
      `background:${colors.glassFill}`,
    ].join(';');
    card.appendChild(image);
  }

  const body = document.createElement('div');
  body.style.cssText = 'display:flex;flex-direction:column;gap:3px;min-width:0';

  const title = document.createElement('div');
  title.style.cssText = 'font-size:14px;font-weight:700;letter-spacing:-0.2px;line-height:1.25';
  title.textContent = pin.headline ?? pin.species_common_name ?? 'Unidentified animal';
  body.appendChild(title);

  const meta = document.createElement('div');
  meta.style.cssText = `font-size:12px;line-height:1.3;color:${colors.textMuted}`;
  const severity = document.createElement('span');
  severity.style.color = severityColour(pin.severity_level);
  severity.style.fontWeight = '600';
  severity.textContent = severityLabel(pin.severity_level);
  meta.appendChild(severity);
  meta.appendChild(
    document.createTextNode(
      [pin.place_name, pin.status.replace(/_/g, ' ')]
        .filter((part): part is string => Boolean(part))
        .map((part) => ` · ${part}`)
        .join(''),
    ),
  );
  body.appendChild(meta);

  // Entanglement needs a team with cutting authorisation and a mass stranding
  // needs more than one, so both change who gets dispatched. Called out here
  // for the same reason the list rows call them out.
  const flags = [
    pin.entanglement ? 'ENTANGLED' : null,
    pin.in_mass_stranding ? 'MASS STRANDING' : null,
  ].filter((flag): flag is string => flag !== null);
  if (flags.length) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;margin-top:1px';
    flags.forEach((text) => {
      const tag = document.createElement('span');
      tag.style.cssText = [
        'font-size:9px', 'font-weight:800', 'letter-spacing:0.8px',
        `color:${colors.warning}`, `border:1px solid ${colors.border}`,
        'border-radius:999px', 'padding:1px 6px',
      ].join(';');
      tag.textContent = text;
      row.appendChild(tag);
    });
    body.appendChild(row);
  }

  const lead = document.createElement('div');
  lead.style.cssText = `font-size:12px;line-height:1.3;color:${colors.textMuted}`;
  lead.textContent = leadCentre ? `Lead centre: ${leadCentre}` : 'Lead centre: not assigned yet';
  body.appendChild(lead);

  const when = document.createElement('div');
  when.style.cssText = `font-size:11px;color:${colors.textFaint};margin-top:1px`;
  when.textContent = `Reported ${new Date(pin.created_at).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })}`;
  body.appendChild(when);

  card.appendChild(body);
  return card;
}

export default function TriageMap({
  pins,
  centres,
  route,
  density,
  showDensity,
  dronePlan = null,
  droneSample = null,
  droneTrace = [],
  historicalCell = null,
  surveyArea = null,
  onDrawSurvey,
  drawing = false,
  fitToPins = true,
  popup = true,
  selectedId,
  onSelect,
}: {
  pins: MapPin[];
  centres: ResponderOrg[];
  route: RouteLine | null;
  density: HistoricalDensity | null;
  showDensity: boolean;
  dronePlan?: DronePlan | null;
  droneSample?: DronePoint | null;
  droneTrace?: DronePoint[];
  historicalCell?: HistoricalDensity['cells'][number] | null;
  /** The survey box, drawn as a filled rectangle so its extent is visible. */
  surveyArea?: SurveyBox | null;
  /** Called with a new box when the user finishes dragging one out. */
  onDrawSurvey?: (box: SurveyBox) => void;
  /** While true, dragging draws a box instead of panning the map. */
  drawing?: boolean;
  /**
   * Auto-zoom to fit the incident pins. The Drone Lab turns this off: there
   * the survey area is the subject, and fitting to every incident in the
   * country would zoom straight back out of it.
   */
  fitToPins?: boolean;
  /** Show the small summary card on click. The triage page shows a side panel instead. */
  popup?: boolean;
  selectedId: string | null;
  onSelect: (incidentId: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef<maplibre.Marker[]>([]);
  const droneMarker = useRef<maplibre.Marker | null>(null);
  const ready = useRef(false);
  const tiles = basemap();

  // The open incident card, and which pin it belongs to. Held in refs rather
  // than state because the popup is a MapLibre object: re-rendering on open
  // would tear down and rebuild every marker underneath it.
  const card = useRef<maplibre.Popup | null>(null);
  const cardPin = useRef<string | null>(null);

  const closeCard = useCallback(() => {
    card.current?.remove();
    card.current = null;
    cardPin.current = null;
  }, []);

  const openCard = useCallback((pin: MapPin, leadCentre: string | null) => {
    if (!map.current) return;
    installPopupStyle();
    card.current?.remove();
    card.current = new maplibre.Popup({
      className: POPUP_CLASS,
      // Clear of the largest marker, since the tip is hidden.
      offset: 16,
      closeOnClick: true,
      // MapLibre caps popups at 240px, which would wrap the card's own layout.
      maxWidth: 'none',
      // MapLibre focuses the close button on open by default, which draws a
      // focus ring on every pin click and pulls focus out of the page for a
      // card that is only a read-only summary. Tab still reaches the button.
      focusAfterOpen: false,
    })
      .setLngLat([pin.longitude as number, pin.latitude as number])
      .setDOMContent(incidentCard(pin, leadCentre))
      .addTo(map.current);
    // Dismissing via the close button or a map click bypasses closeCard, so
    // the refs have to be cleared from the popup's own event.
    card.current.on('close', () => {
      if (cardPin.current === pin.incident_id) {
        card.current = null;
        cardPin.current = null;
      }
    });
    cardPin.current = pin.incident_id;
  }, []);

  // MapLibre only follows window resizes. When the page splits the screen with
  // a draggable divider the container changes size on its own, so watch it.
  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => map.current?.resize());
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Create the map once. Re-creating it on every render would flash and lose
  // the user's pan and zoom.
  useEffect(() => {
    if (map.current || !container.current) return;

    map.current = new maplibre.Map({
      container: container.current,
      style: tiles.style,
      center: DEFAULT_CENTRE,
      zoom: 5.5,
      attributionControl: { compact: true },
    });
    map.current.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
    map.current.on('load', () => {
      ready.current = true;
      if (!map.current) return;
      map.current.addSource(DENSITY_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({
        id: DENSITY_LAYER,
        type: 'heatmap',
        source: DENSITY_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'heatmap-weight': ['get', 'weight'],
          'heatmap-intensity': 0.7,
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 4, 12, 9, 36],
          'heatmap-opacity': 0.68,
          'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)', 0.25, '#48CAE4', 0.55, '#FFCB5B', 1, '#FF704F'],
        },
      });
      map.current.addSource(ROUTE_SOURCE, {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } },
      });
      map.current.addLayer({
        id: 'route-line',
        type: 'line',
        source: ROUTE_SOURCE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': colors.accent,
          'line-width': 4,
          'line-opacity': 0.9,
        },
      });
      map.current.addSource('drone-survey', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } },
      });
      map.current.addLayer({ id: 'drone-survey-line', type: 'line', source: 'drone-survey',
        paint: { 'line-color': colors.warning, 'line-width': 3, 'line-dasharray': [2, 1] } });
      map.current.addSource('drone-trace', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({id: 'drone-trace-line', type: 'line', source: 'drone-trace',
        paint: {'line-color': colors.accent, 'line-width': 3}});
      // Under the route line, so the dashed waypoints stay readable on top.
      map.current.addSource(SURVEY_SOURCE, {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({ id: 'survey-area-fill', type: 'fill', source: SURVEY_SOURCE,
        paint: { 'fill-color': colors.warning, 'fill-opacity': 0.14 } });
      map.current.addLayer({ id: 'survey-area-line', type: 'line', source: SURVEY_SOURCE,
        paint: { 'line-color': colors.warning, 'line-width': 2 } });
      map.current.addSource('selected-historical-cell', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.current.addLayer({ id: 'selected-historical-cell-line', type: 'line',
        source: 'selected-historical-cell',
        paint: { 'line-color': colors.accent, 'line-width': 2 } });
    });

    return () => {
      map.current?.remove();
      map.current = null;
      droneMarker.current = null;
      card.current = null;
      cardPin.current = null;
      ready.current = false;
    };
  }, [tiles.style]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource(DENSITY_SOURCE) as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: 'FeatureCollection',
        features: (density?.cells ?? []).map((cell) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: [cell.longitude, cell.latitude] },
          properties: { weight: cell.band === '100+' ? 1 : cell.band === '25-99' ? 0.65 : 0.35 },
        })),
      });
      map.current?.setLayoutProperty(DENSITY_LAYER, 'visibility', showDensity ? 'visible' : 'none');
    };
    if (ready.current) draw();
    else map.current?.once('load', draw);
  }, [density, showDensity]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('selected-historical-cell') as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      const half = (density?.grid_degrees ?? 0.1) / 2;
      const cell = historicalCell;
      source.setData({ type: 'FeatureCollection', features: cell ? [{
        type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[
          [cell.longitude - half, cell.latitude - half],
          [cell.longitude + half, cell.latitude - half],
          [cell.longitude + half, cell.latitude + half],
          [cell.longitude - half, cell.latitude + half],
          [cell.longitude - half, cell.latitude - half],
        ]] },
      }] : [] });
      if (cell) map.current?.fitBounds([
        [cell.longitude - half, cell.latitude - half],
        [cell.longitude + half, cell.latitude + half],
      ], { padding: 40, duration: 400 });
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [historicalCell, density?.grid_degrees]);

  // Paint the committed survey box. Separate from the drag handler so the
  // box stays on screen between edits, which is what makes its extent legible.
  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource(SURVEY_SOURCE) as maplibre.GeoJSONSource | undefined;
      source?.setData(boxFeature(surveyArea));
      // Zoom to the area whenever it changes. A survey that fits the
      // planner's range is a few hundred metres across, which is invisible at
      // the statewide default zoom -- so the first drag is always too big.
      // Fitting here turns that into a usable loop: drag, land on the area,
      // drag again at the right scale.
      if (surveyArea && map.current) {
        map.current.fitBounds(
          [[surveyArea.west, surveyArea.south], [surveyArea.east, surveyArea.north]],
          { padding: 90, maxZoom: 17, duration: 600 },
        );
      }
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [surveyArea]);

  // Drag out a new survey box.
  //
  // Panning is disabled while this is active, because a drag has to mean one
  // thing or the other. The live rectangle is painted into the same source as
  // the committed one, so what you drag is exactly what you get.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !drawing || !onDrawSurvey) return;

    let origin: maplibre.LngLat | null = null;
    const canvas = instance.getCanvas();
    const previousCursor = canvas.style.cursor;
    canvas.style.cursor = 'crosshair';
    instance.dragPan.disable();

    const paint = (box: SurveyBox | null) => {
      const source = instance.getSource(SURVEY_SOURCE) as maplibre.GeoJSONSource | undefined;
      source?.setData(boxFeature(box));
    };

    const down = (event: maplibre.MapMouseEvent) => { origin = event.lngLat; };
    const move = (event: maplibre.MapMouseEvent) => {
      if (origin) paint(cornersToBox(origin, event.lngLat));
    };
    const up = (event: maplibre.MapMouseEvent) => {
      if (!origin) return;
      const box = cornersToBox(origin, event.lngLat);
      origin = null;
      // A click is not a drag. Anything this small is a misclick, so restore
      // the previous box rather than committing a zero-width area the
      // planner would reject.
      if (box.north - box.south < 1e-5 || box.east - box.west < 1e-5) {
        paint(surveyArea);
        return;
      }
      onDrawSurvey(box);
    };

    instance.on('mousedown', down);
    instance.on('mousemove', move);
    instance.on('mouseup', up);
    return () => {
      instance.off('mousedown', down);
      instance.off('mousemove', move);
      instance.off('mouseup', up);
      instance.dragPan.enable();
      canvas.style.cursor = previousCursor;
    };
  }, [drawing, onDrawSurvey, surveyArea]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('drone-survey') as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      const coordinates = dronePlan?.waypoints.map(p => [p.longitude, p.latitude]) ?? [];
      source.setData({ type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates } });
      map.current?.setPaintProperty('drone-survey-line', 'line-color',
        dronePlan?.status === 'blocked' ? colors.danger : colors.warning);
      if (coordinates.length && map.current) {
        const bounds = new maplibre.LngLatBounds();
        coordinates.forEach(point => bounds.extend([point[0], point[1]]));
        map.current.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
      }
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [dronePlan?.plan_id]);

  useEffect(() => {
    if (!map.current) return;
    if (!droneSample) { droneMarker.current?.remove(); droneMarker.current = null; return; }
    if (!droneMarker.current) {
      const element = document.createElement('div');
      element.style.cssText = 'width:18px;height:18px;background:#FFC043;border:3px solid #fff;border-radius:50%;';
      element.title = 'Synthetic drone telemetry';
      droneMarker.current = new maplibre.Marker({ element });
    }
    droneMarker.current.setLngLat([droneSample.longitude, droneSample.latitude]).addTo(map.current);
  }, [droneSample]);

  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource('drone-trace') as maplibre.GeoJSONSource | undefined;
      source?.setData({type: 'FeatureCollection', features: droneTrace.length > 1 ? [{
        type: 'Feature', properties: {}, geometry: {type: 'LineString',
          coordinates: droneTrace.map(p => [p.longitude, p.latitude])},
      }] : []});
    };
    if (ready.current) draw(); else map.current?.once('load', draw);
    return () => { map.current?.off('load', draw); };
  }, [droneTrace]);

  // Redraw markers whenever the data or the selection changes. Markers are
  // DOM elements, so they are torn down and rebuilt rather than diffed.
  // Grouping depends on zoom, so markers are rebuilt when a zoom finishes.
  const [zoomTick, setZoomTick] = useState(0);
  useEffect(() => {
    const instance = map.current;
    if (!instance) return;
    const bump = () => setZoomTick((tick) => tick + 1);
    instance.on('zoomend', bump);
    return () => {
      instance.off('zoomend', bump);
    };
  }, []);

  useEffect(() => {
    if (!map.current) return;
    installMarkerStyle();

    markers.current.forEach((marker) => marker.remove());
    markers.current = [];

    centres
      .filter((centre) => centre.latitude !== null && centre.longitude !== null)
      .forEach((centre) => {
        const element = document.createElement('div');
        element.style.cssText = [
          'width:9px', 'height:9px', 'border-radius:50%',
          `border:2px solid ${colors.accent}`,
          'background:rgba(72,202,228,0.25)',
          'cursor:help',
        ].join(';');
        element.title = `${centre.name}\n(approximate: centre of its service area)`;
        markers.current.push(
          new maplibre.Marker({ element })
            .setLngLat([centre.longitude as number, centre.latitude as number])
            .addTo(map.current as MapLibreMap),
        );
      });

    const located = pins.filter((pin) => pin.latitude !== null && pin.longitude !== null);
    const mapInstance = map.current as MapLibreMap;
    const grouped: PinCluster[] =
      mapInstance.getZoom() < CLUSTER_MAX_ZOOM
        ? clusterPins(mapInstance, located)
        : located.map((pin) => ({
            pins: [pin],
            longitude: pin.longitude as number,
            latitude: pin.latitude as number,
          }));

    grouped.forEach((group) => {
      let element: HTMLElement;

      if (group.pins.length === 1) {
        const pin = group.pins[0];
        const selected = pin.incident_id === selectedId;
        const size = selected ? 24 : 18;
        element = markerDot({
          size,
          colour: severityColour(pin.severity_level),
          border: `${selected ? 3 : 2}px solid ${selected ? colors.accent : 'rgba(255,255,255,0.85)'}`,
          pulsing: NEEDS_ATTENTION.has(pin.status),
        });
        element.title = pin.headline ?? pin.species_common_name ?? 'Unidentified animal';
        element.onclick = (event) => {
          // Markers live inside the map's canvas container, so without this
          // the click also reaches the map and `closeOnClick` shuts the card
          // in the same gesture that opened it. Only `click` is stopped;
          // mousedown and mouseup still reach the survey-area drag handler.
          event.stopPropagation();
          onSelect(pin.incident_id);
          const lead = pin.assigned_responder_id
            ? (centres.find((c) => c.responder_id === pin.assigned_responder_id)?.name ?? null)
            : null;
          if (!drawing && popup) openCard(pin, lead);
        };
      } else {
        // The worst severity wins the colour, and any unclaimed case makes the
        // whole group pulse: a count must never hide the one that needs help.
        const worst = group.pins.reduce((best, pin) =>
          SEVERITY_RANK.indexOf(pin.severity_level ?? 'guidance') <
          SEVERITY_RANK.indexOf(best.severity_level ?? 'guidance')
            ? pin
            : best,
        );
        const holdsSelected = group.pins.some((pin) => pin.incident_id === selectedId);
        const unclaimed = group.pins.filter((pin) => NEEDS_ATTENTION.has(pin.status)).length;
        element = markerDot({
          size: holdsSelected ? 24 : 18,
          colour: severityColour(worst.severity_level),
          border: `${holdsSelected ? 3 : 2}px solid ${holdsSelected ? colors.accent : 'rgba(255,255,255,0.85)'}`,
          pulsing: unclaimed > 0,
          label: String(group.pins.length),
        });
        element.title =
          `${group.pins.length} incidents · ${unclaimed} unclaimed. Click to zoom in.`;
        element.onclick = (event) => {
          event.stopPropagation();
          const bounds = new maplibre.LngLatBounds();
          group.pins.forEach((pin) =>
            bounds.extend([pin.longitude as number, pin.latitude as number]),
          );
          const [sw, ne] = [bounds.getSouthWest(), bounds.getNorthEast()];
          if (sw.lng === ne.lng && sw.lat === ne.lat) {
            // Same spot: fitting a zero-size box would not zoom, so step in.
            mapInstance.easeTo({
              center: [sw.lng, sw.lat],
              zoom: Math.min(mapInstance.getZoom() + 3, 17),
            });
          } else {
            mapInstance.fitBounds(bounds, { padding: 100, maxZoom: CLUSTER_MAX_ZOOM, duration: 500 });
          }
        };
      }

      markers.current.push(
        new maplibre.Marker({ element })
          .setLngLat([group.longitude, group.latitude])
          .addTo(mapInstance),
      );
    });

    // A card outliving its pin would describe an incident no longer shown --
    // filters and refreshes can both drop one out from under an open card.
    if (cardPin.current && !pins.some((pin) => pin.incident_id === cardPin.current)) {
      closeCard();
    }
  }, [pins, centres, selectedId, onSelect, drawing, popup, openCard, closeCard, zoomTick]);

  // A drag has to mean one thing at a time, and a card sitting over the area
  // being drawn is in the way of judging it.
  useEffect(() => {
    if (drawing) closeCard();
  }, [drawing, closeCard]);

  // Fit to the incidents once there are some, so a coordinator does not open
  // the console to an empty ocean.
  useEffect(() => {
    const located = pins.filter((p) => p.latitude !== null && p.longitude !== null);
    if (!map.current || located.length === 0 || !fitToPins) return;

    const bounds = new maplibre.LngLatBounds();
    located.forEach((p) => bounds.extend([p.longitude as number, p.latitude as number]));
    map.current.fitBounds(bounds, { padding: 80, maxZoom: 9, duration: 600 });
  }, [pins, fitToPins]);

  // Choosing a case from the list should bring it into view, but never yank the
  // map when it is already visible.
  useEffect(() => {
    const target = pins.find((p) => p.incident_id === selectedId);
    const instance = map.current;
    if (!instance || !target || target.latitude === null || target.longitude === null) return;
    const point: [number, number] = [target.longitude, target.latitude];
    if (!instance.getBounds().contains(point)) instance.easeTo({ center: point, duration: 500 });
  }, [selectedId, pins]);

  // Draw (or clear) the route line.
  useEffect(() => {
    const draw = () => {
      const source = map.current?.getSource(ROUTE_SOURCE) as maplibre.GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: 'Feature',
        properties: {},
        geometry: { type: 'LineString', coordinates: route?.coordinates ?? [] },
      });
      // A straight line is not a drive. Dash it so the two cannot be confused
      // at a glance.
      map.current?.setPaintProperty(
        'route-line',
        'line-dasharray',
        route?.source === 'straight_line' ? [2, 2] : [1],
      );
    };

    if (ready.current) draw();
    else map.current?.once('load', draw);
  }, [route]);

  return (
    <View style={styles.wrap}>
      <div ref={container} style={{ position: 'absolute', inset: 0 }} />

      <View style={styles.badge} pointerEvents="none">
        <Text style={styles.badgeText}>{tiles.label}</Text>
        {dronePlan && <Text style={styles.badgeText}>Synthetic survey route · {dronePlan.status.replace(/_/g, ' ')}</Text>}
        {showDensity && density && <Text style={styles.badgeText}>
          Historical reports · 10–24 / 25–99 / 100+ per ~11 km cell
        </Text>}
        {route && (
          <Text style={styles.badgeText}>
            {route.source === 'straight_line'
              ? `${route.distance_km ?? '?'} km straight line from ${route.from_name ?? 'centre'}`
              : `${route.distance_km ?? '?'} km / ${route.duration_minutes ?? '?'} min drive`}
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, overflow: 'hidden', borderRadius: radius.card },
  badge: {
    position: 'absolute',
    left: spacing.md,
    bottom: spacing.md,
    backgroundColor: 'rgba(11, 19, 43, 0.82)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
    gap: 2,
  },
  badgeText: { ...type.meta, fontSize: 11, color: colors.textMuted },
});
