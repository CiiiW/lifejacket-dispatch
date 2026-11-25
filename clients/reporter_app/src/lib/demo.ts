/**
 * Demo mode, for screen recordings and presentations.
 *
 * Set `EXPO_PUBLIC_DEMO_MODE=true` in `.env`, then restart with
 * `npx expo start -c` -- the value is built into the bundle, so a Metro that
 * is already running keeps the old one. It changes two things, nothing else:
 *
 * - **"Share location" never reads the phone's GPS.** The map opens on Jetty
 *   Beach, Moss Landing instead: on the sand, about 17 m inland of the mapped
 *   shoreline, with a NOAA tide station 0.4 km away. A recording made at home
 *   then shows neither where the presenter lives nor an "inland" report with
 *   no tide data.
 * - **The local-testing banner is hidden.** It warns real users that this
 *   console does not verify phone numbers, which an audience watching a
 *   recording does not need telling.
 *
 * The position is sent as a `map_pin`, never as `device_gps`. It is a placed
 * pin, and a responder reading the case should not be told otherwise.
 */

export const DEMO_MODE = process.env.EXPO_PUBLIC_DEMO_MODE === 'true';

/** Jetty Beach, Moss Landing, Monterey Bay. See the note above. */
export const DEMO_LOCATION = { latitude: 36.80968, longitude: -121.78995 } as const;
