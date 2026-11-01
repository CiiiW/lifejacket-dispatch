import { useEffect, useRef, useState } from 'react';
import { networkAuthDriver, type NetworkUser } from '../lib/networkAuth.web';

/** Auth driver injection is limited to isolated UI fixtures. */
export function NetworkLogin({ user, configured, checking, error: outerError = '', onSignOut,
  onRefreshed, driver = networkAuthDriver }: {
  user: NetworkUser | null; configured: boolean; checking: boolean; error?: string;
  onSignOut: () => void; onRefreshed: (user: NetworkUser | null) => void;
  driver?: typeof networkAuthDriver;
}) {
  const [mode, setMode] = useState<'login' | 'create' | 'reset'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const generation = useRef(0);
  const locked = useRef(false);
  useEffect(() => {
    generation.current += 1;
    locked.current = false;
    setBusy(false); setPassword(''); setConfirm(''); setError(''); setMessage('');
    return () => { generation.current += 1; };
  }, [user?.uid]);
  const disabled = busy || checking || !configured;
  function changeMode(next: typeof mode) {
    setMode(next); setPassword(''); setConfirm(''); setError(''); setMessage('');
  }
  async function run(action: () => Promise<void>, success = '', failure = 'Unable to complete this request. Please try again.') {
    if (locked.current) return;
    locked.current = true;
    const current = generation.current;
    setBusy(true); setError(''); setMessage('');
    try {
      await action();
      if (current === generation.current) setMessage(success);
    } catch {
      if (current === generation.current) setError(failure);
    } finally {
      if (current === generation.current) {
        locked.current = false; setBusy(false); setPassword(''); setConfirm('');
      }
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (disabled) return;
    if (mode === 'create' && password !== confirm) { setError('Passwords must match.'); return; }
    if (mode === 'reset') {
      // Same acknowledgement for known and unknown addresses, including provider errors.
      await run(async () => { try { await driver.reset(email); } catch { /* privacy */ } },
        'If this address has an account, a password reset email may arrive. Check your inbox and spam folder.');
    } else {
      const operation = mode === 'create' ? driver.create : driver.login;
      await run(() => operation(email, password), '', mode === 'create'
        ? 'Account creation was not completed. Try signing in or resetting your password.'
        : 'Sign-in was not completed. Check your details or reset your password.');
    }
  }
  return <>
    <header className="lj-top"><div><div className="lj-eyebrow">LifeJacket</div><h1>Rescue network</h1></div></header>
    <section className="lj-panel lj-signin">
      <span className="lj-pill">Coordinated response</span>
      <h2 style={{ marginTop: 20 }}>{user ? 'Verify your email' : mode === 'create' ? 'Create your account' : mode === 'reset' ? 'Reset your password' : 'Welcome to the rescue network'}</h2>
      {(error || outerError) && <p role="alert" className="lj-error">{error || outerError}</p>}
      {message && <p role="status">{message}</p>}
      {!configured ? <p role="status">Network sign-in is not available yet. Please contact your coordinator.</p>
        : checking ? <p role="status">Checking sign-in…</p>
        : user ? <>
          <p>Verify {user.email || 'your email address'} before opening the dashboard.</p>
          <div className="lj-toolbar">
            <button disabled={disabled} onClick={() => run(driver.verify, 'Verification email sent. Check your inbox and spam folder.')}>Send verification email</button>
            <button className="secondary" disabled={disabled} onClick={() => run(async () => {
              const next = await driver.refresh();
              if (next?.emailVerified || !next) onRefreshed(next);
              else throw new Error('Not verified');
            }, '', 'Email is not verified yet, or verification could not be checked. Open the email link, then try again.')}>I’ve verified my email</button>
            <button className="secondary" disabled={disabled} onClick={onSignOut}>Sign out</button>
          </div>
        </> : <>
          <p className="lj-muted">Sign in to see your reports and the cases available to your organization.</p>
          <form onSubmit={submit} style={{ flexDirection: 'column', alignItems: 'stretch' }} aria-label={mode === 'reset' ? 'Password reset' : mode === 'create' ? 'Create account' : 'Email sign-in'}>
            <label>Email<input type="email" autoComplete="email" required maxLength={254} value={email} disabled={disabled} onChange={(e) => setEmail(e.target.value)} /></label>
            {mode !== 'reset' && <label>Password<input type="password" autoComplete={mode === 'create' ? 'new-password' : 'current-password'} required minLength={mode === 'create' ? 6 : undefined} maxLength={4096} value={password} disabled={disabled} onChange={(e) => setPassword(e.target.value)} /></label>}
            {mode === 'create' && <><small>Use at least 6 characters. Additional project password rules may apply.</small><label>Confirm password<input type="password" autoComplete="new-password" required value={confirm} disabled={disabled} onChange={(e) => setConfirm(e.target.value)} /></label></>}
            <button type="submit" disabled={disabled}>{busy ? 'Please wait…' : mode === 'create' ? 'Create account' : mode === 'reset' ? 'Send reset email' : 'Sign in'}</button>
          </form>
          <div className="lj-toolbar" style={{ marginTop: 16 }}>
            {mode !== 'login' && <button className="secondary" disabled={disabled} onClick={() => changeMode('login')}>Back to sign in</button>}
            {mode === 'login' && <><button className="secondary" disabled={disabled} onClick={() => changeMode('create')}>Create account</button><button className="secondary" disabled={disabled} onClick={() => changeMode('reset')}>Forgot password?</button></>}
            <button className="secondary" disabled={disabled} onClick={() => run(driver.google, '', 'Google sign-in was not completed. Allow the sign-in window, then try again.')}>Continue with Google</button>
          </div>
        </>}
      <p style={{ marginTop: 20 }}><small>Professional access requires a verified email and an approved organization membership. Creating an account does not grant NOAA or rescue-center access.</small></p>
    </section>
  </>;
}
