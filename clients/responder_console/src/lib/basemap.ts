/**
 * Which tiles the map draws, and where they come from.
 *
 * MapLibre renders; the tiles are somebody else's. Three options, in the
 * order the console prefers them:
 *
 * 1. **MapTiler** (`EXPO_PUBLIC_MAPTILER_KEY`) -- vector tiles, a proper dark
 *    style that matches the console, free tier.
 * 2. **Stadia** (`EXPO_PUBLIC_STADIA_KEY`) -- same idea, Alidade Smooth Dark.
 * 3. **OpenStreetMap raster** -- no key, works immediately, but it is light
 *    and bright against the navy UI, and OSM's tile policy forbids heavy use.
 *    This is the fallback so the map is never blank, not the intended look.
 *
 * Tile keys are necessarily public: the browser fetches the tiles, so the key
 * is in the request. Restrict them by domain in the provider's dashboard.
 * This is unlike the OpenRouteService key, which stays on the server.
 */

import type { StyleSpecification } from 'maplibre-gl';

const MAPTILER_KEY = process.env.EXPO_PUBLIC_MAPTILER_KEY ?? '';
const STADIA_KEY = process.env.EXPO_PUBLIC_STADIA_KEY ?? '';

/** OSM raster tiles, as a hand-written style so no key is needed. */
const OSM_RASTER: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

export interface Basemap {
  style: string | StyleSpecification;
  /** Shown in the corner so it is obvious which tiles are in use. */
  label: string;
  /** False for the keyless fallback, which looks wrong against the theme. */
  isDark: boolean;
}

export function basemap(): Basemap {
  if (MAPTILER_KEY) {
    return {
      style: `https://api.maptiler.com/maps/dataviz-dark/style.json?key=${MAPTILER_KEY}`,
      label: 'MapTiler',
      isDark: true,
    };
  }
  if (STADIA_KEY) {
    return {
      style:
        'https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json' +
        `?api_key=${STADIA_KEY}`,
      label: 'Stadia',
      isDark: true,
    };
  }
  return { style: OSM_RASTER, label: 'OpenStreetMap (no API key set)', isDark: false };
}
