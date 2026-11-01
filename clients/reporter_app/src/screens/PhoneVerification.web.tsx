import { useEffect, useRef, useState } from 'react';
import { phoneAuth, type PhoneChallenge } from '../lib/phoneAuth.web';
import type { PhoneUser } from '../lib/phoneReporterApi';

export function PhoneVerification({ onVerified, configured, driver = phoneAuth }: {
  onVerified: (user: PhoneUser) => void; configured: boolean; driver?: typeof phoneAuth;
}) {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const challenge = useRef<PhoneChallenge | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const active = useRef(true);
  const lock = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; challenge.current?.dispose(); }; }, []);
  useEffect(() => { if (!cooldown) return; const timer = setTimeout(() => setCooldown((v) => Math.max(0, v - 1)), 1000); return () => clearTimeout(timer); }, [cooldown]);
  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (lock.current || !consent || cooldown || !configured || !container.current) return;
    lock.current = true; setBusy(true); setError('');
    challenge.current?.dispose(); challenge.current = null; setCode(''); setSent(false);
    try {
      const next = await driver.requestCode(phone.trim(), container.current);
      if (!active.current) { next.dispose(); return; }
      challenge.current = next; setSent(true); setCooldown(60);
    } catch { if (active.current) setError('Code could not be sent. Check the number, complete the security check, and try again later.'); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    if (lock.current || !challenge.current || !/^[0-9]{6}$/.test(code)) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const user = await challenge.current.confirm(code);
      if (!active.current) return;
      if (!user.phoneNumber) throw new Error('Phone missing');
      setCode(''); challenge.current.dispose(); challenge.current = null; onVerified(user);
    } catch { if (active.current) { setCode(''); setError('The code could not be verified. Try again or request a new code.'); } }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  return <section className="card">
    <h2>Verify your phone</h2><p>No password needed. Verify before submitting a report or opening your previous reports.</p>
    {!configured && <p role="status">SMS sign-in is awaiting setup. You can prepare a draft, but submission and tracking are unavailable.</p>}
    <form onSubmit={send}>
      <label>Phone number<input type="tel" autoComplete="tel" placeholder="+1…" pattern="\+[1-9][0-9]{7,14}" required value={phone} disabled={busy || sent} onChange={(e) => setPhone(e.target.value)} /></label>
      <label className="choice"><input type="checkbox" checked={consent} disabled={busy || sent} onChange={(e) => setConsent(e.target.checked)} />I agree to receive a verification SMS. Standard rates may apply. Google processes and stores the number for authentication and abuse prevention.</label>
      <div ref={container} />
      <button disabled={busy || !consent || !configured || cooldown > 0}>{busy ? 'Please wait…' : sent ? cooldown ? `Resend available in ${cooldown}s` : 'Resend code' : 'Send verification code'}</button>
      {sent && <button type="button" className="secondary" disabled={busy} onClick={() => { challenge.current?.dispose(); challenge.current = null; setSent(false); setCode(''); setConsent(false); setError(''); }}>Change number</button>}
    </form>
    {sent && <form onSubmit={confirm}><label>SMS code<input type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} disabled={busy} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} /></label><button disabled={busy}>Verify code</button></form>}
    {error && <p role="alert">{error}</p>}
    <small>Verification does not enroll you in monitoring or volunteer alerts.</small>
  </section>;
}
