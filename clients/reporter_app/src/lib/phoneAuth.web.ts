import { getApps, initializeApp } from 'firebase/app';
import { getAuth, initializeAuth, inMemoryPersistence, RecaptchaVerifier, signInWithPhoneNumber, signOut } from 'firebase/auth';
import type { PhoneUser } from './phoneReporterApi';

const config = {
  apiKey: process.env.EXPO_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID,
};
export const phoneConfigured = process.env.EXPO_PUBLIC_REPORTER_PHONE_ENABLED === 'true' && Boolean(config.apiKey && config.authDomain && config.projectId);
function auth() {
  if (!phoneConfigured) throw new Error('Phone sign-in unavailable');
  const existing = getApps().find((app) => app.name === 'lifejacket-reporter');
  return existing ? getAuth(existing) : initializeAuth(initializeApp(config, 'lifejacket-reporter'), { persistence: inMemoryPersistence });
}
export type PhoneChallenge = { confirm: (code: string) => Promise<PhoneUser>; dispose: () => void };
export const phoneAuth = {
  async requestCode(phone: string, container: HTMLElement): Promise<PhoneChallenge> {
    if (!/^\+[1-9][0-9]{7,14}$/.test(phone)) throw new Error('Use an international phone number.');
    const managed = auth();
    const verifier = new RecaptchaVerifier(managed, container, { size: 'normal' });
    try {
      const confirmation = await signInWithPhoneNumber(managed, phone, verifier);
      return { confirm: async (code) => (await confirmation.confirm(code)).user, dispose: () => verifier.clear() };
    } catch { verifier.clear(); throw new Error('Phone verification unavailable.'); }
  },
  async signOut() { if (phoneConfigured) await signOut(auth()); },
};
