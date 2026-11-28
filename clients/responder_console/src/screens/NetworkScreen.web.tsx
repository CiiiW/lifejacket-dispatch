import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  createNetworkApi,
  networkErrorMessage,
  type CaseScope,
  type NetworkApi,
  type NetworkCase,
  type NetworkSession,
  type ReporterUpdate,
  type TokenUser,
} from '../lib/networkApi';
import {
  networkSignInConfigured,
  observeNetworkUser,
  type NetworkUser,
  signOutOfNetwork,
} from '../lib/networkAuth.web';
import { NetworkLogin } from './NetworkLogin.web';
import { CoordinatorAttention } from './CoordinatorAttention.web';
import { MonitoringQueue } from './MonitoringQueue.web';
import { DroneRequests } from './DroneRequests.web';
import NetworkMapView from './NetworkMapView.web';
import { CaseActions } from './CaseActions.web';

const apiBase = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';
const filters: { value: CaseScope; label: string }[] = [
  { value: 'all_allowed', label: 'All accessible cases' },
  { value: 'my_center', label: 'My center' },
  { value: 'assigned_to_me', label: 'Assigned to me' },
  { value: 'leading', label: 'Leading' },
  { value: 'supporting', label: 'Supporting' },
  { value: 'receiving', label: 'Receiving' },
];
const PAGE_SIZE = 50;
// Bounds the number of requests a very large statewide or national view makes.
const MAX_CASES = 2000;

/** Walk every page of the permissioned list so the map is not limited to page one. */
async function loadAllCases(api: NetworkApi, scope: CaseScope, signal: AbortSignal) {
  const byId = new Map<string, NetworkCase>();
  for (let offset = 0; offset < MAX_CASES; offset += PAGE_SIZE) {
    const page = await api.cases(scope, offset, signal);
    page.forEach((row) => byId.set(row.incident_id, row));
    if (page.length < PAGE_SIZE) return { cases: [...byId.values()], truncatedAt: null };
  }
  return { cases: [...byId.values()], truncatedAt: MAX_CASES };
}
const css = `
.lj-network {
  --lj-ink: #173932;
  --lj-muted: #4c655e;
  --lj-action: #116957;
  --lj-edge: #ccded5;
  --lj-wash: #e9f5ee;
  box-sizing: border-box;
  background: #f3f8f5;
  color: var(--lj-ink);
  min-height: 100vh;
  padding: 24px clamp(16px, 3vw, 44px) 40px;
  font: 15px/1.5 system-ui, sans-serif;
  width: 100%;
  overflow: auto;
}
.lj-network *, .lj-network *::before, .lj-network *::after { box-sizing: border-box; }
.lj-network h1 { font: 600 clamp(2.25rem, 4vw, 3.125rem)/1.06 Georgia, serif; letter-spacing: -.045em; margin: 0; }
.lj-network h2 { font-size: 19px; line-height: 1.25; margin: 0 0 10px; letter-spacing: -.025em; }
.lj-network p { margin: 8px 0 14px; overflow-wrap: anywhere; }
.lj-network small, .lj-network .lj-muted { color: var(--lj-muted); }
.lj-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.lj-eyebrow { color: var(--lj-action); font-size: 12px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 5px; }
.lj-panel { padding: 18px; background: #fff; border: 1px solid var(--lj-edge); border-radius: 15px; margin-bottom: 14px; min-width: 0; }
.lj-signin { max-width: 560px; margin: 7vh auto; }
.lj-toolbar { display: flex; gap: 12px 16px; align-items: end; flex-wrap: wrap; }
.lj-network label { display: flex; flex-direction: column; gap: 4px; color: var(--lj-muted); font-size: 13px; font-weight: 600; min-width: 0; max-width: 100%; }
.lj-network select, .lj-network input, .lj-network textarea {
  background: #fff;
  color: var(--lj-ink);
  min-width: 0;
  max-width: 100%;
  padding: 8px 10px;
  border: 1px solid #a7c1b6;
  border-radius: 8px;
  font: inherit;
}
.lj-network input[type=checkbox] { accent-color: var(--lj-action); }
.lj-network button {
  font: inherit;
  font-weight: 660;
  color: #fff;
  background: var(--lj-action);
  border: 1px solid transparent;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
}
.lj-network button.secondary { color: var(--lj-action); background: #fff; border-color: #afc8bf; }
.lj-network button:disabled { opacity: .55; cursor: default; }
.lj-network :is(button,select,input,textarea,summary,[tabindex]):focus-visible { outline: 3px solid #a45723; outline-offset: 3px; }
.lj-network .lj-error { color: #9b2d25; border-color: #dcaea8; }
.lj-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(280px, 1fr); gap: 16px; }
.lj-cases { display: flex; flex-direction: column; gap: 8px; }
.lj-network .lj-case {
  display: block;
  width: 100%;
  padding: 11px 13px;
  background: #fff;
  border-color: var(--lj-edge);
  color: var(--lj-ink);
  text-align: left;
  overflow-wrap: anywhere;
}
.lj-network .lj-case:not(:disabled):hover, .lj-network .lj-case[aria-pressed=true] { background: var(--lj-wash); border-color: var(--lj-action); }
.lj-case strong { display: block; font-size: 15px; }
.lj-meta { display: flex; gap: 4px 10px; flex-wrap: wrap; margin-top: 4px; color: var(--lj-muted); font-size: 13px; font-weight: 400; }
.lj-pill { display: inline-block; color: var(--lj-action); background: var(--lj-wash); padding: 3px 9px; border-radius: 20px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.lj-network dl { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 8px; margin: 0; }
.lj-network dt { color: var(--lj-muted); }
.lj-network dd { margin: 0; overflow-wrap: anywhere; }
.lj-pagination { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 7px; margin-top: 12px; font-size: 13px; }
.lj-notice { border-left: 3px solid var(--lj-action); padding-left: 12px; }
.lj-id { font-size: 12px; overflow-wrap: anywhere; color: var(--lj-muted); }
.lj-network form { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }

@media (max-width: 760px) {
  .lj-network { padding: 16px 12px 28px; }
  .lj-grid { grid-template-columns: 1fr; }
  .lj-signin { margin: 5vh auto; }
}
`;

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="lj-network">
      <style>{css}</style>
      {children}
    </main>
  );
}
function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="lj-panel lj-error" role="alert">
      <p>{message}</p>
      {retry && (
        <button className="secondary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
function roleLabel(role: string) {
  return (
    (
      {
        noaa: 'NOAA',
        center_coordinator: 'Center coordinator',
        rescuer: 'Field rescuer',
        reporter: 'Personal account',
        volunteer: 'Volunteer',
      } as Record<string, string>
    )[role] ?? 'Account'
  );
}
const text = (value: string | null) =>
  value ? value.replace(/_/g, ' ') : 'Not provided';

export default function NetworkScreen() {
  const [user, setUser] = useState<NetworkUser | null>(null);
  const [revision, setRevision] = useState(0);
  const [checking, setChecking] = useState(networkSignInConfigured);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!networkSignInConfigured) return;
    try {
      return observeNetworkUser(
        (next) => {
          setUser(next);
          setRevision((v) => v + 1);
          setChecking(false);
        },
        () => {
          setUser(null);
          setChecking(false);
          setError('Sign-in is temporarily unavailable. Please try again.');
        },
      );
    } catch {
      setChecking(false);
      setError(
        'Network sign-in is not available yet. Please contact your coordinator.',
      );
    }
  }, []);
  async function logout() {
    setUser(null);
    setRevision((v) => v + 1);
    setError('');
    try {
      await signOutOfNetwork();
    } catch {
      setError(
        'The view has been cleared. Close this tab to finish signing out.',
      );
    }
  }
  // A new account never mounts the workspace before email verification.
  if (user?.emailVerified)
    return (
      <NetworkWorkspace
        key={`${user.uid}:${revision}`}
        user={user}
        onSignOut={logout}
      />
    );
  return (
    <Shell>
      <NetworkLogin
        user={user}
        configured={networkSignInConfigured}
        checking={checking}
        error={error}
        onSignOut={logout}
        onRefreshed={(next) => {
          setUser(next);
          setRevision((v) => v + 1);
        }}
      />
    </Shell>
  );
}

/** Dependency injection is for isolated tests; the app always uses managed auth and its configured API. */
export function NetworkWorkspace({
  user,
  onSignOut,
  apiFactory = createNetworkApi,
}: {
  user: TokenUser;
  onSignOut: () => void;
  apiFactory?: typeof createNetworkApi;
}) {
  const [organization, setOrganization] = useState<string | null>(null);
  return (
    <Shell>
      <header className="lj-top">
        <div>
          <div className="lj-eyebrow">LifeJacket · Rescue network</div>
          <h1>Coordinate the next response</h1>
        </div>
        <div className="lj-toolbar">
          <span className="lj-pill">Verified access</span>
          <button className="secondary" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      <SessionWorkspace
        key={`${user.uid}:${organization ?? 'personal'}`}
        user={user}
        organization={organization}
        onOrganization={setOrganization}
        apiFactory={apiFactory}
      />
    </Shell>
  );
}

function SessionWorkspace({
  user,
  organization,
  onOrganization,
  apiFactory,
}: {
  user: TokenUser;
  organization: string | null;
  onOrganization: (id: string | null) => void;
  apiFactory: typeof createNetworkApi;
}) {
  const api = useMemo(() => {
    try {
      return apiFactory(apiBase, user, organization);
    } catch {
      return null;
    }
  }, [apiFactory, user, organization]);
  const [session, setSession] = useState<NetworkSession | null>(null);
  const [rows, setRows] = useState<NetworkCase[]>([]);
  const [scope, setScope] = useState<CaseScope>('all_allowed');
  const [truncatedAt, setTruncatedAt] = useState<number | null>(null);
  // The view the data on screen belongs to. A refresh of the same view updates
  // quietly; only a new view clears the screen, so the map keeps its position.
  const loadedView = useRef<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [droneRequest, setDroneRequest] = useState<string|undefined>();
  const [monitorRevision,setMonitorRevision]=useState(0);
  const monitoringChanged=useCallback(()=>setMonitorRevision(v=>v+1),[]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((v) => v + 1), []);
  useEffect(() => {
    const timer = window.setInterval(reload, 30000);
    function visible() {
      if (document.visibilityState === 'visible') reload();
    }
    window.addEventListener('focus', reload);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', reload);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [reload]);
  useEffect(() => {
    if (!api) {
      setBusy(false);
      setError(
        'Network access is not available yet. Please contact your coordinator.',
      );
      return;
    }
    const controller = new AbortController();
    let current = true;
    const view = `${organization ?? ''}|${scope}`;
    const background = loadedView.current === view;
    if (!background) {
      setSession(null);
      setRows([]);
      setBusy(true);
    }
    setError('');
    (async () => {
      try {
        const verified = await api.me(controller.signal);
        if (verified.selected_organization_id !== organization)
          throw new Error('Organization context mismatch');
        const professional = ['noaa', 'center_coordinator', 'rescuer'].includes(
          verified.role,
        );
        const loaded = professional
          ? await loadAllCases(api, scope, controller.signal)
          : { cases: [], truncatedAt: null };
        if (current) {
          setSession(verified);
          // Keep the same array when nothing changed so the map is not re-fitted.
          setRows((previous) =>
            JSON.stringify(previous) === JSON.stringify(loaded.cases)
              ? previous
              : loaded.cases,
          );
          setTruncatedAt(loaded.truncatedAt);
          loadedView.current = view;
        }
      } catch (failure) {
        if (current) {
          loadedView.current = null;
          setSelected(null);
          setError(networkErrorMessage(failure));
        }
      } finally {
        if (current) setBusy(false);
      }
    })();
    return () => {
      current = false;
      controller.abort();
    };
  }, [api, organization, scope, refresh]);
  if (busy)
    return (
      <section className="lj-panel" role="status">
        Checking access and loading cases…
      </section>
    );
  if (error || !session || !api)
    return (
      <>
        <ErrorNotice
          message={error || 'Unable to verify this account.'}
          retry={reload}
        />
        {organization && (
          <button className="secondary" onClick={() => onOrganization(null)}>
            Return to personal account
          </button>
        )}
      </>
    );
  const professional = ['noaa', 'center_coordinator', 'rescuer'].includes(
    session.role,
  );
  return (
    <>
      <section className="lj-panel lj-toolbar" aria-label="Verified access">
        <label>
          Viewing as
          <select
            value={organization ?? ''}
            onChange={(event) => onOrganization(event.target.value || null)}
          >
            <option value="">Personal account</option>
            {session.organizations.map((org) => (
              <option key={org.organization_id} value={org.organization_id}>
                {org.name}
              </option>
            ))}
          </select>
        </label>
        <div>
          <strong>{roleLabel(session.role)}</strong>
          <div className="lj-muted">
            {session.role === 'noaa'
              ? 'Submitted cases across states'
              : professional
                ? `Approved states: ${session.authorized_states.join(', ')}`
                : 'Your reports only'}
          </div>
        </div>
        <button className="secondary" onClick={reload}>
          Refresh access
        </button>
      </section>
      {!professional ? (
        <>
          <section className="lj-panel">
            <h2>Your reports</h2>
            <p className="lj-muted">
              Use the case ID from your report receipt to check its response
              status.
            </p>
            {!session.organizations.length && (
              <p className="lj-notice">
                No professional organization access is approved for this account
                yet.
              </p>
            )}
            <ReporterLookup api={api} />
          </section>
          <p className="lj-id">Account ID: {session.account_id}</p>
        </>
      ) : (
        <>
          <div className="lj-top">
            <label>
              Show cases
              <select
                value={scope}
                onChange={(event) => {
                  setSelected(null);
                  setScope(event.target.value as CaseScope);
                }}
              >
                {filters.map((filter) => (
                  <option key={filter.value} value={filter.value}>
                    {filter.label}
                  </option>
                ))}
              </select>
            </label>
            <small>
              Access refreshes every 30 seconds and when you return to this tab.
            </small>
          </div>
          {api.drones && session.role !== 'noaa' && <CoordinatorAttention api={api.drones} revision={monitorRevision} onChange={monitoringChanged} onOpen={(caseId,requestId)=>{setDroneRequest(requestId);setSelected(caseId);}}/>}
          {api.drones && session.role !== 'noaa' && <MonitoringQueue api={api.drones} revision={monitorRevision} onOpen={(caseId,requestId)=>{setDroneRequest(requestId);setSelected(caseId);}}/>}
                    <NetworkMapView
            rows={rows}
            selected={selected}
            onSelect={(caseId) => {setDroneRequest(undefined);setSelected(caseId);}}
            truncatedAt={truncatedAt}
            detail={
              selected ? (
                <CaseDetail
                  key={selected}
                  api={api}
                  id={selected}
                  droneRequest={droneRequest}
                  onMonitoringChange={monitoringChanged}
                  organizations={session.organizations}
                />
              ) : null
            }
          />
        </>
      )}
    </>
  );
}

function CaseDetail({
  api,
  id,
  droneRequest,
  onMonitoringChange,
  organizations,
}: {
  api: NetworkApi;
  id: string;
  organizations: NetworkSession['organizations'];
  droneRequest?:string;
  onMonitoringChange?:()=>void;
}) {
  const [row, setRow] = useState<NetworkCase | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    api.case(id, controller.signal).then(
      (value) => {
        if (current) setRow(value);
      },
      (failure) => {
        if (current) setError(networkErrorMessage(failure));
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [api, id]);
  if (error) return <ErrorNotice message={error} />;
  if (!row)
    return (
      <section className="lj-panel" role="status">
        Loading case…
      </section>
    );
  return (
    <section className="lj-panel">
      <div className="lj-eyebrow">Case overview</div>
      <h2>{text(row.species_common_name ?? row.animal_group)}</h2>
      <p className="lj-id">{row.incident_id}</p>
      <dl>
        <dt>Intake record</dt>
        <dd>{text(row.status)}</dd>
        <dt>Severity</dt>
        <dd>{text(row.severity_level)}</dd>
        <dt>State</dt>
        <dd>{row.state_code ?? 'Under review'}</dd>
        <dt>Animal location</dt>
        <dd>
          {row.latitude !== null && row.longitude !== null
            ? `${row.latitude.toFixed(5)}, ${row.longitude.toFixed(5)}`
            : 'Not provided'}
        </dd>
        <dt>Lead center</dt>
        <dd>
          {row.lead_organization_id
            ? (organizations.find(
                (org) => org.organization_id === row.lead_organization_id,
              )?.name ?? 'Another response organization')
            : 'Not confirmed'}
        </dd>
        <dt>Photo</dt>
        <dd className="lj-muted">Unavailable for now</dd>
        <dt>Summary</dt>
        <dd className="lj-muted">Unavailable for now</dd>
        <dt>Why this urgency</dt>
        <dd className="lj-muted">Unavailable for now</dd>
      </dl>
      <p className="lj-notice">
        Photos, the report summary and urgency reasons will appear here once protected case
        detail and media access is added.
      </p>
      <CaseActions api={api} id={id} />
      {api.drones && <DroneRequests key={id} api={api.drones} id={id} reportedLocation={row} initialRequestId={droneRequest} onMonitoringChange={onMonitoringChange}/>}
    </section>
  );
}
function ReporterLookup({ api }: { api: NetworkApi }) {
  const [input, setInput] = useState('');
  const [id, setId] = useState('');
  return (
    <>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setId(input.trim());
        }}
      >
        <label>
          Case ID
          <input
            value={input}
            maxLength={64}
            onChange={(event) => setInput(event.target.value)}
            autoComplete="off"
            required
          />
        </label>
        <button type="submit">View response</button>
      </form>
      {id && <ReportResponse key={id} api={api} id={id} />}
    </>
  );
}
function ReportResponse({ api, id }: { api: NetworkApi; id: string }) {
  const [update, setUpdate] = useState<ReporterUpdate | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    api.report(id, controller.signal).then(
      (value) => {
        if (current) setUpdate(value);
      },
      (failure) => {
        if (current) setError(networkErrorMessage(failure));
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [api, id]);
  if (error) return <ErrorNotice message={error} />;
  if (!update) return <p role="status">Checking your report…</p>;
  return (
    <section className="lj-panel" style={{ marginTop: 20 }}>
      <span className="lj-pill">{text(update.phase)}</span>
      <h2 style={{ marginTop: 12 }}>{update.message}</h2>
      <p>
        {update.eta_is_estimate && update.arrival_eta_minutes !== null
          ? `Estimated arrival: about ${Math.ceil(update.arrival_eta_minutes)} minutes.`
          : 'An arrival estimate is not available yet.'}
      </p>
      {update.reporter_can_leave && !update.leaving_cancels_report && (
        <p className="lj-notice">
          You are welcome to leave if you need to. Leaving does not cancel your
          report.
        </p>
      )}
    </section>
  );
}
