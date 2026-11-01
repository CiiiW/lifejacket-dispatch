import { useEffect, useRef, useState } from 'react';
import {
  networkErrorMessage,
  type NetworkApi,
  type CaseContact,
  type CaseResponse,
} from '../lib/networkApi';

const labels: Record<string, string> = {
  received: 'Report received',
  accepted: 'Team accepted',
  en_route: 'Team en route',
  on_scene: 'Team arrived',
  animal_located: 'Animal located',
  closed: 'Case closed',
};
export function CaseActions({ api, id }: { api: NetworkApi; id: string }) {
  const [state, setState] = useState<CaseResponse | null>(null);
  const [contact, setContact] = useState<CaseContact | null>(null);
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const sequence = useRef(0);
  const latest = useRef<CaseResponse | null>(null);
  useEffect(() => {
    const current = ++generation.current;
    const abort = new AbortController();
    controller.current = abort;
    latest.current = null;
    setState(null);
    setContact(null);
    setTarget('');
    setReason('');
    setConfirmed(false);
    setBusy(false);
    setError('');
    setNotice('');
    lock.current = false;
    let pending = false;
    async function load() {
      if (pending || lock.current) return;
      pending = true;
      // Contact is intentionally short-lived and never survives a permission refresh.
      setContact(null);
      const ticket = ++sequence.current;
      try {
        const next = await api.response(id, abort.signal);
        if (current === generation.current && ticket === sequence.current) {
          const changed =
            JSON.stringify(latest.current) !== JSON.stringify(next);
          latest.current = next;
          setState(next);
          setError('');
          if (changed) {
            setConfirmed(false);
            setTarget('');
            setReason('');
          }
        }
      } catch (e) {
        if (
          current === generation.current &&
          ticket === sequence.current &&
          !abort.signal.aborted
        ) {
          setState(null);
          setContact(null);
          setError(networkErrorMessage(e));
        }
      } finally {
        pending = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 30000);
    const focus = () => void load();
    window.addEventListener('focus', focus);
    return () => {
      generation.current++;
      abort.abort();
      clearInterval(timer);
      window.removeEventListener('focus', focus);
    };
  }, [api, id, refresh]);
  async function action<T>(
    request: (signal: AbortSignal) => Promise<T>,
    success: (value: T) => void,
  ) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    const current = generation.current;
    const ticket = ++sequence.current;
    const signal = controller.current?.signal;
    if (!signal) {
      lock.current = false;
      setBusy(false);
      return;
    }
    try {
      const value = await request(signal);
      if (
        current === generation.current &&
        ticket === sequence.current &&
        !signal.aborted
      )
        success(value);
    } catch (e) {
      if (
        current === generation.current &&
        ticket === sequence.current &&
        !signal.aborted
      ) {
        setState(null);
        setContact(null);
        setConfirmed(false);
        setError(networkErrorMessage(e));
      }
    } finally {
      if (current === generation.current) {
        lock.current = false;
        setBusy(false);
      }
    }
  }
  const validContact =
    contact &&
    /^\+[1-9][0-9]{7,14}$/.test(contact.phone_number) &&
    state?.contact_channels.length;
  return (
    <section
      aria-label="Case response actions"
      style={{
        borderTop: '1px solid #ffffff25',
        marginTop: 20,
        paddingTop: 20,
      }}
    >
      <h2>Confirmed response</h2>
      {error && (
        <p role="alert" className="lj-error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <button
        className="secondary"
        disabled={busy}
        onClick={() => setRefresh((v) => v + 1)}
      >
        Refresh response access
      </button>
      {!state ? (
        <p className="lj-muted">
          Response actions are unavailable until access is checked.
        </p>
      ) : (
        <>
          <p role="status">
            {labels[state.phase] ?? 'Case update needs review'}
          </p>
          {state.allowed_transitions.length > 0 ? (
            <form
              aria-label="Confirm response update"
              onSubmit={(event) => {
                event.preventDefault();
                if (
                  !confirmed ||
                  !target ||
                  !state.allowed_transitions.includes(target)
                )
                  return;
                void action(
                  (signal) =>
                    api.changeResponse(
                      id,
                      state.revision,
                      target,
                      target === 'closed' ? reason : null,
                      signal,
                    ),
                  (next) => {
                    latest.current = next;
                    setState(next);
                    setContact(null);
                    setTarget('');
                    setReason('');
                    setConfirmed(false);
                    setNotice(
                      'Response update recorded. The reporter can see the updated case status.',
                    );
                  },
                );
              }}
            >
              <label>
                Next confirmed event
                <select
                  required
                  value={target}
                  disabled={busy}
                  onChange={(e) => {
                    setTarget(e.target.value);
                    setConfirmed(false);
                    setReason('');
                  }}
                >
                  <option value="">Choose an event</option>
                  {state.allowed_transitions.map((phase) => (
                    <option key={phase} value={phase}>
                      {labels[phase] ?? phase}
                    </option>
                  ))}
                </select>
              </label>
              {target === 'closed' && (
                <label>
                  Closure reason
                  <select
                    required
                    value={reason}
                    disabled={busy}
                    onChange={(e) => setReason(e.target.value)}
                  >
                    <option value="">Choose a reason</option>
                    {state.closure_reasons.map((value) => (
                      <option key={value} value={value}>
                        {value.replaceAll('_', ' ')}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label style={{ flexDirection: 'row', alignItems: 'center' }}>
                <input
                  type="checkbox"
                  style={{ minWidth: 0 }}
                  checked={confirmed}
                  disabled={busy}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                I confirm this event has actually occurred.
              </label>
              <button
                disabled={
                  busy ||
                  !target ||
                  !confirmed ||
                  (target === 'closed' && !reason)
                }
              >
                Record response update
              </button>
              <small>
                Arrival and finding the animal are separate confirmations. Only
                the lead coordinator may close the case.
              </small>
            </form>
          ) : (
            <p className="lj-muted">
              Your role has no response changes available for this case.
            </p>
          )}
          <h2 style={{ marginTop: 22 }}>Reporter contact</h2>
          {state.contact_channels.length ? (
            <>
              <p className="lj-muted">
                Current-case contact only, using the reporter’s selected
                channels.
              </p>
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  action((signal) => api.contact(id, signal), setContact)
                }
              >
                Show permitted reporter contact
              </button>
            </>
          ) : (
            <p className="lj-muted">
              Reporter contact is unavailable for your current case access or
              the reporter’s preferences.
            </p>
          )}
          {validContact && (
            <div className="lj-notice" style={{ marginTop: 16 }}>
              <p>
                Reporter availability: {contact.presence.replaceAll('_', ' ')}
              </p>
              <div className="lj-toolbar">
                {contact.channels.includes('phone') &&
                  state.contact_channels.includes('phone') && (
                    <a
                      style={{ color: '#48cae4' }}
                      href={`tel:${contact.phone_number}`}
                    >
                      Call reporter
                    </a>
                  )}
                {contact.channels.includes('text') &&
                  state.contact_channels.includes('text') && (
                    <a
                      style={{ color: '#48cae4' }}
                      href={`sms:${contact.phone_number}`}
                    >
                      Text reporter
                    </a>
                  )}
              </div>
              <small>
                Opening your phone or messaging app does not mean a call or
                message was delivered. Contact is cleared when access refreshes.
              </small>
            </div>
          )}
        </>
      )}
    </section>
  );
}
