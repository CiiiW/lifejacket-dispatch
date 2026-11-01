import { getApps, initializeApp } from 'firebase/app';
import {
  browserPopupRedirectResolver,
  getAuth,
  GoogleAuthProvider,
  initializeAuth,
  inMemoryPersistence,
  onIdTokenChanged,
  signInWithPopup,
  signOut,
} from 'firebase/auth';
import type { TokenUser } from './networkApi';

const config = {
  apiKey: process.env.EXPO_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.EXPO_PUBLIC_FIREBASE_APP_ID,
};
export const networkSignInConfigured = Object.values(config).every(Boolean);
function auth() {
  if (!networkSignInConfigured) throw new Error('Sign-in unavailable');
  const existing = getApps().find((app) => app.name === 'lifejacket-network');
  if (existing) return getAuth(existing);
  // No ID/refresh tokens in application localStorage or sessionStorage.
  return initializeAuth(initializeApp(config, 'lifejacket-network'), {
    persistence: inMemoryPersistence,
    popupRedirectResolver: browserPopupRedirectResolver,
  });
}
export function observeNetworkUser(
  next: (user: TokenUser | null) => void,
  failed: () => void,
): () => void {
  return onIdTokenChanged(auth(), next, failed);
}
export async function signInToNetwork(): Promise<void> {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: 'select_account' });
  await signInWithPopup(auth(), provider);
}
export async function signOutOfNetwork(): Promise<void> {
  await signOut(auth());
}
