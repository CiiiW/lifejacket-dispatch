import { getApps, initializeApp } from 'firebase/app';
import {
  browserPopupRedirectResolver,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  sendPasswordResetEmail,
  sendEmailVerification,
  reload,
  type User,
  getAuth,
  GoogleAuthProvider,
  initializeAuth,
  inMemoryPersistence,
  onIdTokenChanged,
  signInWithPopup,
  signOut,
} from 'firebase/auth';
export type NetworkUser = Pick<User, 'uid' | 'email' | 'emailVerified' | 'getIdToken'>;

const config = {
  apiKey: process.env.EXPO_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.EXPO_PUBLIC_FIREBASE_APP_ID,
};
// Identity Platform supplies API key/domain; appId is optional for Auth.
export const networkSignInConfigured = Boolean(
  config.apiKey?.trim() && config.authDomain?.trim() && config.projectId?.trim(),
);
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
  next: (user: NetworkUser | null) => void,
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

export async function signInWithNetworkPassword(email: string, password: string): Promise<void> {
  await signInWithEmailAndPassword(auth(), email.trim(), password);
}
export async function createNetworkAccount(email: string, password: string): Promise<void> {
  // Verification is a separate user action: delivery failure cannot hide account creation.
  await createUserWithEmailAndPassword(auth(), email.trim(), password);
}
export async function resetNetworkPassword(email: string): Promise<void> {
  await sendPasswordResetEmail(auth(), email.trim());
}
export async function verifyNetworkEmail(): Promise<void> {
  const user = auth().currentUser;
  if (!user) throw new Error('Sign in first');
  await sendEmailVerification(user);
}
export async function refreshNetworkUser(): Promise<NetworkUser | null> {
  const user = auth().currentUser;
  if (!user) return null;
  await reload(user);
  await user.getIdToken(true);
  return user;
}
export const networkAuthDriver = {
  login: signInWithNetworkPassword, create: createNetworkAccount,
  reset: resetNetworkPassword, verify: verifyNetworkEmail,
  refresh: refreshNetworkUser, google: signInToNetwork,
};
