import { useEffect, useRef, useState } from 'react';
import { phoneAuth, phoneConfigured } from '../lib/phoneAuth.web';
import { createPhoneReporterApi, type Draft, type PhoneReporterApi, type PhoneUser, type ReportReceipt, type ReportStatus } from '../lib/phoneReporterApi';
import { PhoneVerification } from './PhoneVerification.web';
import { emptyLocation, ReporterLocation } from './ReporterLocation.web';
import { ReporterMap } from './ReporterMap.web';
import { AnimalChoice, ReportGuidance } from './ReporterEvidence.web';

import './phoneReporter.css';

type Exchange = { prompt: string | null; outgoing: string };

const otterImage = './lifejacket-sea-otter.webp';

export function PhoneReporterPage({ api, configured = phoneConfigured, authDriver = phoneAuth, offlineMap }: {
  api: PhoneReporterApi; configured?: boolean; authDriver?: typeof phoneAuth; offlineMap?: boolean;
}) {
  const [page, setPage] = useState<'report' | 'history'>('report');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [user, setUser] = useState<PhoneUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reply, setReply] = useState('');
  const [location, setLocation] = useState(emptyLocation);
  const [photo, setPhoto] = useState<File | null>(null);
  const [conversation, setConversation] = useState<Exchange[]>([]);
  const [showReportMap, setShowReportMap] = useState(false);
  const [submittedGuidance, setSubmittedGuidance] = useState<Draft['turn'] | null>(null);
  const [channels, setChannels] = useState<string[]>([]);
  const [receipts, setReceipts] = useState<ReportReceipt[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<ReportStatus | null>(null);
  const epoch = useRef(0);
  const lock = useRef(false);
  const active = useRef(true);
  const latestPrompt = useRef<HTMLDivElement>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; epoch.current += 1; }; }, []);
  useEffect(() => {
    if (draft) latestPrompt.current?.scrollIntoView({ block: 'nearest' });
  }, [draft]);
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
  function continueChat(turn: Draft['turn'], outgoing: string) {
    setConversation(previous => [...previous, { prompt: draft?.turn.message ?? null, outgoing }]);
    changeTurn(turn);
  }
  function selectReceipt(id: string) {
    if (id === selected) return;
    setShowReportMap(false); setStatus(null); setSelected(id);
  }
  function toggle(channel: string) { setChannels((current) => current.includes(channel) ? current.filter((v) => v !== channel) : [...current, channel]); }
  function attachPhoto(file: File) {
    if (!draft) return;
    if (file.size > 15 * 1024 * 1024) { setError('Choose a photo smaller than 15 MB.'); return; }
    void run(() => api.photo(draft, file), turn => {
      setPhoto(file); continueChat(turn, 'Shared a photo');
    });
  }
  function answer(text: string) {
    if (!draft || !text.trim()) return;
    const outgoing = text.trim();
    void run(() => api.turn(draft, { action:'reply', text:outgoing }), turn => continueChat(turn, outgoing));
  }
  async function logout() {
    epoch.current += 1; lock.current = false; setBusy(false); setUser(null); setSelected(null);
    setPage('report'); setStatus(null); setReceipts([]); setDraft(null); setChannels([]); setReply(''); setLocation(emptyLocation);
    setPhoto(null); setConversation([]); setShowReportMap(false); setSubmittedGuidance(null); setError(''); setNotice('');
    try { await authDriver.signOut(); } catch { setError('The view has been cleared. Close the tab to finish signing out.'); }
  }
  function handleVerified(next: PhoneUser) {
    setUser(next);
    setError('');
  }

  const reporting = page === 'report';
  const photoNeeded = draft?.turn.action === 'request_photo' || draft?.turn.action === 'request_better_photo';

  return <main className="reporter">
    <header className="topbar">
      <span className="wordmark">LifeJacket</span>
      <nav aria-label="Reporter navigation">
        <button type="button" disabled={busy} aria-pressed={reporting} onClick={() => setPage('report')}>Report</button>
        <button type="button" disabled={busy} aria-pressed={!reporting} onClick={() => setPage('history')}>My reports</button>
      </nav>
    </header>
    <div className="stack">
    {reporting && <section className="report-chat" aria-labelledby="report-title">
      <header className="chat-header">
        <img src={otterImage} alt="" width={56} height={56} />
        <div>
          <h1 id="report-title">Report a wildlife sighting</h1>
          {draft && <p className="reference">Private draft · Not submitted</p>}
        </div>
      </header>
      <div className="chat-body">
        {!draft && <>
          <div className="chat-bubble chat-incoming">
            <p>I can help you report a marine animal. I’ll ask for a photo, where you saw it, and a few details.</p>
            <p><strong>Keep a safe distance.</strong> Only take a photo if you can do so safely.</p>
          </div>
          <button type="button" disabled={busy} onClick={() => void run(api.start, setDraft)}>Start a report</button>
        </>}
        {draft && <>
          <ol className="transcript" aria-label="Conversation">
            {conversation.map(({ prompt, outgoing }, index) => <li key={index}>
              {prompt && <p className="chat-bubble chat-incoming"><span className="sr-only">LifeJacket: </span>{prompt}</p>}
              <p className="chat-bubble chat-outgoing"><span className="sr-only">You: </span>{outgoing}</p>
            </li>)}
          </ol>
          <div ref={latestPrompt}>
            <div className="chat-bubble chat-incoming" aria-live="polite" aria-atomic="true">
              <p><span className="sr-only">LifeJacket: </span>{draft.turn.complete
                ? user ? 'Your report is ready. Choose how the response team can contact you, then send it.'
                  : 'Your draft is ready. Verify your phone number to send it.'
                : draft.turn.message}</p>
              {draft.turn.identified_as && <p><strong>Possible identification</strong> · {draft.turn.identified_as}</p>}
            </div>
          </div>
          {draft.turn.safety_guidance && <p className="status-note safety">{draft.turn.safety_guidance}</p>}
          <ReportGuidance turn={draft.turn}/>
          {!draft.turn.complete && <div className="chat-actions">
            {photoNeeded && <div className="toolbar">
              <label className="attachment">Take a photo<input type="file" accept="image/*" capture="environment" disabled={busy} onChange={event => {
                const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) attachPhoto(file);
              }}/></label>
              <label className="attachment">Choose an animal photo<input type="file" accept="image/jpeg,image/png,image/webp,image/heic" disabled={busy} onChange={event => {
                const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) attachPhoto(file);
              }}/></label>
            </div>}
            {draft.turn.action === 'request_location' && <ReporterLocation value={location} onChange={setLocation}
              busy={busy} offline={offlineMap} onConfirm={() => void run(() => api.turn(draft, {
                action:'location', latitude:Number(location.latitude), longitude:Number(location.longitude),
                location_source:location.source, accuracy_meters:location.accuracy,
              }), turn => continueChat(turn, 'Shared the animal’s location'))}/>}
            {draft.turn.detections.length > 1 && !photoNeeded && <AnimalChoice turn={draft.turn} file={photo} busy={busy}
              onChoose={number => {
                if (draft.turn.selected_detection === number - 1) return;
                const animal = draft.turn.detections[number - 1];
                void run(() => api.turn(draft, {action:'animal', number}), turn => {
                  if (turn.selected_detection === draft.turn.selected_detection) changeTurn(turn);
                  else continueChat(turn, animal?.description || `Selected animal ${number}`);
                });
              }}/>}
            {draft.turn.awaiting_reply && !draft.turn.service_error && draft.turn.action !== 'ask_which_animal' && <form onSubmit={event => { event.preventDefault(); answer(reply); }}>
              {draft.turn.options.length > 0 && <div className="toolbar quick-replies">{draft.turn.options.map(option =>
                <button key={option} type="button" className="secondary" disabled={busy} onClick={() => answer(option)}>{option}</button>
              )}</div>}
              <div className="composer">
                <label htmlFor="report-reply" className="sr-only">Your answer</label>
                <input id="report-reply" placeholder="Type your reply…" value={reply} required maxLength={4000} disabled={busy} onChange={event => setReply(event.target.value)} />
                <button type="submit" aria-label="Send answer" disabled={busy || !reply.trim()}>Send</button>
              </div>
            </form>}
            {draft.turn.service_error && <button type="button" disabled={busy} onClick={() => run(() => api.turn(draft, { action:'retry' }), changeTurn)}>Try this step again</button>}
          </div>}
        </>}
        {draft?.turn.complete && !user &&
          <PhoneVerification configured={configured} driver={authDriver} onVerified={handleVerified} />}
        {draft?.turn.complete && user && <section className="card"><h2>Submit your report</h2><p>How may the response team contact you about this report? Both choices are optional.</p>
            <label className="choice"><input type="checkbox" disabled={busy} checked={channels.includes('call')} onChange={() => toggle('call')} />Phone call about this case</label>
            <label className="choice"><input type="checkbox" disabled={busy} checked={channels.includes('text')} onChange={() => toggle('text')} />Text about this case</label>
            <p><small>These choices do not allow future monitoring or volunteer invitations. No ongoing location sharing is enabled.</small></p>
            <button disabled={busy} onClick={() => run(() => api.submit(draft, user, channels), (result) => {
              setSubmittedGuidance(draft.turn);
              setDraft(null);
              setChannels([]);
              setPhoto(null);
              setConversation([]);
              setLocation(emptyLocation);
              setPage('history');
              selectReceipt(result.case_id);
              setNotice('Report received. A team has not yet confirmed a response.');
            })}>Submit report</button>
          </section>}
        {error && <p className="status-note error" role="alert">{error}</p>}
        {busy && <p className="chat-bubble chat-incoming chat-pending" role="status">Working on your request…</p>}
      </div>
    </section>}
    {!reporting && error && <div className="card error" role="alert">{error}</div>}
    {notice && <div className="card" role="status">{notice}</div>}
    {!reporting && <div><h1>My reports</h1><p className="muted">Check for updates on a report you sent.</p></div>}
    {!user && !reporting &&
      <PhoneVerification configured={configured} driver={authDriver} onVerified={handleVerified} />}
    {user && !reporting && <section className="card">
      <h2>Phone verified</h2>
      <div className="toolbar"><button disabled={busy} onClick={() => run(() => api.reports(user), (next) => { setReceipts(next); if (!next.length) setNotice('No submitted reports for this account.'); })}>Load my reports</button><button className="secondary" onClick={logout}>Sign out and clear this page</button></div>
    </section>}
    {!reporting && user && receipts.length > 0 && <section className="card"><h2>Your submitted reports</h2><div className="toolbar">{receipts.map((receipt) => <button className="secondary" key={receipt.case_id} onClick={() => selectReceipt(receipt.case_id)}>{receipt.case_id}</button>)}</div></section>}
    {!reporting && user && selected && <section className="card"><h2>Your case update</h2><p className="reference">Report {selected}</p>
      <button className="secondary" disabled={busy} onClick={() => { setStatus(null); void run(() => api.status(selected, user), setStatus); }}>Refresh case update</button>
      {!status ? <p role="status">Waiting for a current case update…</p> : <>
        <p role="status">{status.message}</p>
        {status.response_team && <p><strong>Response team</strong> · {status.response_team}</p>}
        {submittedGuidance?.incident_id === selected && <>
          {submittedGuidance.safety_guidance && <p className="status-note safety">{submittedGuidance.safety_guidance}</p>}
          <ReportGuidance turn={submittedGuidance}/>
        </>}
        <p>{status.arrival_eta_minutes !== null && status.eta_is_estimate ? `Approximate arrival: ${Math.ceil(status.arrival_eta_minutes)} minutes. Updated ${status.eta_updated_at}.` : 'An arrival estimate is not available.'}</p>
        <p>You may leave whenever you need to. Your report stays active.</p>
        {status.reported_location && <details onToggle={event => setShowReportMap(event.currentTarget.open)}>
          <summary>Reported animal location</summary>
          <p>{status.reported_location.place_name ?? `${status.reported_location.latitude.toFixed(5)}, ${status.reported_location.longitude.toFixed(5)}`}</p>
          {showReportMap && <ReporterMap point={status.reported_location} offline={offlineMap}/>}
        </details>}
        {status.contact_channels && <details>
          <summary>Contact preferences</summary>
          <form key={selected+status.contact_channels.join(',')} onSubmit={event => {
            event.preventDefault();
            const values = new FormData(event.currentTarget);
            const updated = ['call','text'].filter(channel => values.has(channel));
            void run(() => api.preferences(selected, user, updated), () => {
              setStatus(previous => previous?.case_id===selected ? {...previous,contact_channels:updated} : previous);
              setNotice('Contact preferences updated.');
            });
          }}>
            <label className="choice"><input type="checkbox" name="call" defaultChecked={status.contact_channels.includes('call')} disabled={busy}/>Allow calls about this case</label>
            <label className="choice"><input type="checkbox" name="text" defaultChecked={status.contact_channels.includes('text')} disabled={busy}/>Allow texts about this case</label>
            <button className="secondary" disabled={busy}>Save contact preferences</button>
          </form>
        </details>}
        <div className="toolbar"><button className="secondary" disabled={busy} onClick={() => run(() => api.presence(selected, user, 'nearby'), () => setNotice('Recorded: you are still nearby.'))}>I’m still nearby</button><button className="secondary" disabled={busy} onClick={() => run(() => api.presence(selected, user, 'left'), () => setNotice('Recorded: you have left. Your report has not been cancelled.'))}>I’ve left the scene</button></div>
      </>}
    </section>}
    {!reporting && busy && <p className="status-note" role="status">Working on your request…</p>}
    </div>
  </main>;
}

export default function PhoneReporter() {
  try {
    return <PhoneReporterPage api={createPhoneReporterApi(process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000')} />;
  } catch {
    return <main><p role="alert">The reporter API address needs configuration.</p></main>;
  }
}
