import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { MonitoringQueue } from './MonitoringQueue.web';
import { DroneRequests } from './DroneRequests.web';
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
const css = `
.lj-network{box-sizing:border-box;background:#0b132b;color:#f4f7fb;min-height:100vh;padding:32px;font:15px/1.55 Inter,system-ui,sans-serif;width:100%;overflow:auto}
.lj-network *{box-sizing:border-box}.lj-network h1{font-size:30px;letter-spacing:-.8px;margin:0}.lj-network h2{font-size:21px;margin:0 0 12px}.lj-network p{margin:8px 0 16px}.lj-network small,.lj-muted{color:#a9b4c6}.lj-top{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:28px}.lj-eyebrow{color:#48cae4;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px}.lj-panel{padding:24px;background:#101a38;border:1px solid #ffffff20;border-radius:14px;margin-bottom:18px}.lj-signin{max-width:560px;margin:7vh auto}.lj-toolbar{display:flex;gap:16px;align-items:end;flex-wrap:wrap}.lj-network label{display:flex;flex-direction:column;gap:6px;color:#a9b4c6;font-size:13px}.lj-network select,.lj-network input{background:#0b132b;color:#f4f7fb;padding:10px;border:1px solid #ffffff40;border-radius:7px;min-width:180px;font:inherit}.lj-network button{font:inherit;background:#48cae4;color:#06182e;border:1px solid transparent;padding:10px 16px;border-radius:7px;cursor:pointer;font-weight:650}.lj-network button.secondary{background:transparent;color:#dce6f1;border-color:#ffffff40}.lj-network button:disabled{opacity:.5;cursor:default}.lj-network button:focus-visible,.lj-network select:focus-visible,.lj-network input:focus-visible{outline:3px solid #ffc043;outline-offset:3px}.lj-error{border-color:#ff6b6b80;color:#ffc6c6}.lj-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,1fr);gap:22px}.lj-cases{display:flex;flex-direction:column;gap:10px}.lj-network .lj-case{background:#101a38;border-color:#ffffff20;color:#f4f7fb;text-align:left;display:block;width:100%;padding:18px}.lj-network .lj-case[aria-pressed=true]{border-color:#48cae4;background:#162a46}.lj-case strong{display:block;font-size:17px}.lj-case .lj-meta{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;color:#a9b4c6;font-weight:400}.lj-pill{display:inline-block;color:#48cae4;border:1px solid #48cae450;padding:3px 10px;border-radius:20px;font-size:12px}.lj-network dl{display:grid;grid-template-columns:120px 1fr;gap:10px;margin:0}.lj-network dt{color:#a9b4c6}.lj-network dd{margin:0;overflow-wrap:anywhere}.lj-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px}.lj-notice{border-left:3px solid #48cae4;padding-left:14px}.lj-id{font-size:12px;overflow-wrap:anywhere;color:#a9b4c6}.lj-network form{display:flex;gap:12px;align-items:end;flex-wrap:wrap}@media(max-width:760px){.lj-network{padding:20px}.lj-grid{grid-template-columns:1fr}.lj-panel{padding:18px}.lj-network h1{font-size:26px}.lj-network select{max-width:100%}.lj-toolbar label{width:100%}.lj-signin{margin:5vh auto}}
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
  const [offset, setOffset] = useState(0);
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
    setSession(null);
    setRows([]);
    setError('');
    setBusy(true);
    (async () => {
      try {
        const verified = await api.me(controller.signal);
        if (verified.selected_organization_id !== organization)
          throw new Error('Organization context mismatch');
        const professional = ['noaa', 'center_coordinator', 'rescuer'].includes(
          verified.role,
        );
        const cases = professional
          ? await api.cases(scope, offset, controller.signal)
          : [];
        if (current) {
          setSession(verified);
          setRows(cases);
        }
      } catch (failure) {
        if (current) {
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
  }, [api, organization, scope, offset, refresh]);
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
                  setOffset(0);
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
          {api.drones && session.role !== 'noaa' && <MonitoringQueue api={api.drones} revision={monitorRevision} onOpen={(caseId,requestId)=>{setDroneRequest(requestId);setSelected(caseId);}}/>}
          <div className="lj-grid">
            <section aria-label="Accessible cases">
              <div className="lj-cases">
                {rows.length ? (
                  rows.map((row) => (
                    <button
                      className="lj-case"
                      key={row.incident_id}
                      aria-pressed={selected === row.incident_id}
                      onClick={() => {setDroneRequest(undefined);setSelected(row.incident_id);}}
                    >
                      <strong>
                        {text(row.species_common_name ?? row.animal_group)}
                      </strong>
                      <span className="lj-id">Case {row.incident_id}</span>
                      <div className="lj-meta">
                        <span>{row.state_code ?? 'State under review'}</span>
                        <span>{text(row.status)}</span>
                        <span>{text(row.severity_level)}</span>
                      </div>
                    </button>
                  ))
                ) : (
                  <div className="lj-panel">
                    <h2>No cases in this view</h2>
                    <p className="lj-muted">
                      Try another filter or refresh later. Only cases available
                      to your verified account appear here.
                    </p>
                  </div>
                )}
              </div>
              <nav className="lj-pagination" aria-label="Case pages">
                <button
                  className="secondary"
                  disabled={offset === 0}
                  onClick={() => {
                    setSelected(null);
                    setOffset((v) => Math.max(0, v - 50));
                  }}
                >
                  Previous
                </button>
                <span>Page {offset / 50 + 1}</span>
                <button
                  className="secondary"
                  disabled={rows.length < 50 || offset >= 100000}
                  onClick={() => {
                    setSelected(null);
                    setOffset((v) => v + 50);
                  }}
                >
                  Next
                </button>
              </nav>
            </section>
            <aside aria-label="Selected case">
              {selected ? (
                <CaseDetail
                  key={selected}
                  api={api}
                  id={selected}
                  droneRequest={droneRequest}
                  onMonitoringChange={monitoringChanged}
                  organizations={session.organizations}
                />
              ) : (
                <section className="lj-panel">
                  <h2>A coordinated view</h2>
                  <p className="lj-muted">
                    Select a case to see its animal location, triage status and
                    lead organization.
                  </p>
                  <p className="lj-notice">
                    Seeing a case does not assign it to your team.
                  </p>
                </section>
              )}
            </aside>
          </div>
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
      </dl>
      <CaseActions api={api} id={id} />
      {api.drones && <DroneRequests key={id} api={api.drones} id={id} initialRequestId={droneRequest} onMonitoringChange={onMonitoringChange}/>}
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
