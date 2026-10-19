/**
 * Re-export of the shared API client.
 *
 * The real implementation lives in `clients/shared/api.ts` so both apps use
 * one definition of the endpoints and response types. This file exists only so
 * screens can write `from '../lib/api'` without reaching outside the app
 * directory, which Metro's default resolver does not follow.
 */
import { configureApiBase } from '../../../shared/api';

// Keep the phone's LAN API URL in app source so Expo can inline it.
configureApiBase(process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000');
export * from '../../../shared/api';
