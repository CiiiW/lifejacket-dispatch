import { useEffect, useRef, useState } from 'react';
import { phoneAuth, phoneConfigured } from '../lib/phoneAuth.web';
import { createPhoneReporterApi, type Draft, type PhoneReporterApi, type PhoneUser, type ReportReceipt, type ReportStatus } from '../lib/phoneReporterApi';
import { PhoneVerification } from './PhoneVerification.web';

import './phoneReporter.css';

export function PhoneReporterPage({ api, configured = phoneConfigured, authDriver = phoneAuth }: {
  api: PhoneReporterApi; configured?: boolean; authDriver?: typeof phoneAuth;
}) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [user, setUser] = useState<PhoneUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reply, setReply] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [channels, setChannels] = useState<string[]>([]);
  const [receipts, setReceipts] = useState<ReportReceipt[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<ReportStatus | null>(null);
  const epoch = useRef(0);
  const lock = useRef(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; epoch.current += 1; }; }, []);
  async function run<T>(operation: () => Promise<T>, success: (value: T) => void) {
    if (lock.current) return;
    lock.current = true; const generation = epoch.current;
    setBusy(true); setError(''); setNotice('');
    try { const value = await operation(); if (active.current && generation === epoch.current) success(value); }
    catch (e) { if (active.current && generation === epoch.current) setError(e instanceof Error ? e.message : 'Request unavailable.'); }
    finally { if (active.current && generation === epoch.current) { lock.current = false; setBusy(false); } }
  }
  // Poll only the selected own-case projection, clearing stale status on failure.
  useEffect(() => {
    setStatus(null);
    if (!selected || !user) return;
    let cancelled = false;
    let pending = false;
    async function poll() {
      if (pending) return; pending = true;
      try { const next = await api.status(selected!, user!); if (!cancelled) { setStatus(next); setError(''); } }
      catch { if (!cancelled) { setStatus(null); setError('Case status is unavailable. Verify your number again if your session expired.'); } }
      finally { pending = false; }
    }
    void poll(); const timer = setInterval(() => void poll(), 30000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [selected, user, api]);
  function changeTurn(turn: Draft['turn']) { setDraft((current) => current ? { ...current, turn } : null); setReply(''); }
  function selectReceipt(id: string) { setStatus(null); setSelected(id); }
  function toggle(channel: string) { setChannels((current) => current.includes(channel) ? current.filter((v) => v !== channel) : [...current, channel]); }
  async function logout() {
    epoch.current += 1; lock.current = false; setBusy(false); setUser(null); setSelected(null);
    setStatus(null); setReceipts([]); setDraft(null); setChannels([]); setReply(''); setLatitude(''); setLongitude(''); setError(''); setNotice('');
    try { await authDriver.signOut(); } catch { setError('The view has been cleared. Close the tab to finish signing out.'); }
  }
  return <main className="reporter">
    <header className="chat-header">
      <img src="./lifejacket-sea-otter.webp" alt="" width={56} height={56} />
      <div>
        <h1>LifeJacket</h1>
        <p>Prepare the photo and location first. Verify your phone before submitting.</p>
      </div>
    </header>
    {error && <div className="card error" role="alert">{error}</div>}
    {notice && <div className="card" role="status">{notice}</div>}
    <section className="card">
      <h2>{draft ? draft.turn.complete ? 'Draft ready for submission' : 'Prepare your report' : 'Start a report'}</h2>
      <p className="notice">Keep a safe distance from wildlife. You may leave the scene; leaving does not cancel a submitted report.</p>
      {!draft ? <><button disabled={busy} onClick={() => run(api.start, setDraft)}>Prepare a report</button><p><small>No registration is needed to prepare a draft. Drafts expire after 24 hours; this browser keeps the draft key only while the page stays open.</small></p></> : <>
        <p className="reference">Draft {draft.turn.incident_id} · Not submitted</p>
        <p className="chat-incoming">{draft.turn.complete ? 'Your draft is complete. Nothing has been submitted or accepted by a rescue team yet.' : draft.turn.message}</p>
        {draft.turn.identified_as && <p>Possible identification: {draft.turn.identified_as}</p>}
        {draft.turn.safety_guidance && <p>{draft.turn.safety_guidance}</p>}
        {!draft.turn.complete && <>
          {['request_photo','request_better_photo'].includes(draft.turn.action || '') && <label>Animal photo<input type="file" accept="image/jpeg,image/png,image/webp,image/heic" capture="environment" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (!file) return; if (file.size > 15 * 1024 * 1024) { setError('Choose a photo smaller than 15 MB.'); return; } void run(() => api.photo(draft, file), changeTurn); }} /></label>}
          {draft.turn.action === 'request_location' && <form onSubmit={(e) => { e.preventDefault(); void run(() => api.turn(draft, { action:'location', latitude:Number(latitude), longitude:Number(longitude) }), changeTurn); }}>
            <p>Enter where the animal was seen. This is not ongoing location sharing.</p>
            <div className="grid"><label>Animal latitude<input type="number" min={-90} max={90} step="any" required disabled={busy} value={latitude} onChange={(e) => setLatitude(e.target.value)} /></label><label>Animal longitude<input type="number" min={-180} max={180} step="any" required disabled={busy} value={longitude} onChange={(e) => setLongitude(e.target.value)} /></label></div>
            <button disabled={busy}>Use animal location</button>
          </form>}
          {draft.turn.awaiting_reply && !draft.turn.service_error && draft.turn.action !== 'ask_which_animal' && <form onSubmit={(e) => { e.preventDefault(); void run(() => api.turn(draft, { action:'reply', text:reply }), changeTurn); }}>
            <div className="toolbar">{draft.turn.options.map((option) => <button key={option} type="button" className="secondary" disabled={busy} onClick={() => run(() => api.turn(draft, { action:'reply', text:option }), changeTurn)}>{option}</button>)}</div>
            <label>Your answer<input value={reply} required maxLength={4000} disabled={busy} onChange={(e) => setReply(e.target.value)} /></label><button disabled={busy}>Send answer</button>
          </form>}
          {draft.turn.action === 'ask_which_animal' && draft.turn.detections.map((animal, index) => <button key={index} disabled={busy} onClick={() => run(() => api.turn(draft, { action:'animal', number:index + 1 }), changeTurn)}>{index + 1}. {animal.description}</button>)}
          {draft.turn.service_error && <button disabled={busy} onClick={() => run(() => api.turn(draft, { action:'retry' }), changeTurn)}>Try this step again</button>}
        </>}
      </>}
    </section>
    {!user ? <PhoneVerification configured={configured} driver={authDriver} onVerified={(next) => { setUser(next); setError(''); }} /> : <section className="card">
      <h2>Phone verified</h2><p>No password is needed. Your reports belong to this verified account.</p>
      <div className="toolbar"><button className="secondary" disabled={busy} onClick={() => run(() => api.reports(user), (next) => { setReceipts(next); if (!next.length) setNotice('No submitted reports for this account.'); })}>Load my reports</button><button className="secondary" onClick={logout}>Sign out and clear this page</button></div>
    </section>}
    {draft?.turn.complete && <section className="card"><h2>Submit your report</h2><p>How may the response team contact you about this report? Both choices are optional.</p>
      <label className="choice"><input type="checkbox" disabled={busy} checked={channels.includes('call')} onChange={() => toggle('call')} />Phone call about this case</label>
      <label className="choice"><input type="checkbox" disabled={busy} checked={channels.includes('text')} onChange={() => toggle('text')} />Text about this case</label>
      <p><small>These choices do not allow future monitoring or volunteer invitations. No ongoing location sharing is enabled.</small></p>
      <button disabled={busy || !user} onClick={() => user && run(() => api.submit(draft, user, channels), (result) => { setDraft(null); setChannels([]); selectReceipt(result.case_id); setNotice('Report received. A team has not yet confirmed a response.'); })}>{busy ? 'Please wait…' : user ? 'Submit report' : 'Verify your phone to submit'}</button>
    </section>}
    {user && receipts.length > 0 && <section className="card"><h2>Your submitted reports</h2><div className="toolbar">{receipts.map((receipt) => <button className="secondary" key={receipt.case_id} onClick={() => selectReceipt(receipt.case_id)}>{receipt.case_id}</button>)}</div></section>}
    {user && selected && <section className="card"><h2>Your case update</h2><p className="reference">Report {selected}</p>
      <button className="secondary" disabled={busy} onClick={() => { setStatus(null); void run(() => api.status(selected, user), setStatus); }}>Refresh case update</button>
      {!status ? <p role="status">Waiting for a current case update…</p> : <>
        <p role="status">{status.message}</p>
        <p>{status.arrival_eta_minutes !== null && status.eta_is_estimate ? `Approximate arrival: ${Math.ceil(status.arrival_eta_minutes)} minutes. Updated ${status.eta_updated_at}.` : 'An arrival estimate is not available.'}</p>
        <p>You may leave whenever you need to. Your report stays active.</p>
        <button className="secondary" disabled={busy} onClick={() => run(() => api.preferences(selected, user, []), () => setNotice('Current-case call and text permission withdrawn. Your report has not been cancelled.'))}>Stop calls and texts about this case</button>
        <div className="toolbar"><button className="secondary" disabled={busy} onClick={() => run(() => api.presence(selected, user, 'nearby'), () => setNotice('Recorded: you are still nearby.'))}>I’m still nearby</button><button className="secondary" disabled={busy} onClick={() => run(() => api.presence(selected, user, 'left'), () => setNotice('Recorded: you have left. Your report has not been cancelled.'))}>I’ve left the scene</button></div>
      </>}
    </section>}
    {busy && <p role="status">Working on your request…</p>}
  </main>;
}

export default function PhoneReporter() {
  try {
    return <PhoneReporterPage api={createPhoneReporterApi(process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000')} />;
  } catch {
    return <main><p role="alert">The reporter API address needs configuration.</p></main>;
  }
}
