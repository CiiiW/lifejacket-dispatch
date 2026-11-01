/** Isolated component fixture. Not imported by the application entry point. */
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import NetworkScreen, { NetworkWorkspace, Shell } from '../src/screens/NetworkScreen.web';
import {
  NetworkError,
  type createNetworkApi,
  type NetworkCase,
  type NetworkSession,
} from '../src/lib/networkApi';

import { NetworkLogin } from '../src/screens/NetworkLogin.web';
import type { NetworkUser } from '../src/lib/networkAuth.web';

const fixtureUser = {
  uid: 'fictional-ui-user',
  getIdToken: async () => 'fictional-unused-token',
};
let revoked = false;
const organizations: NetworkSession['organizations'] = [
  {
    organization_id: 'A',
    name: 'Fictional California Center',
    role: 'center_coordinator',
    states: ['CA'],
  },
  {
    organization_id: 'B',
    name: 'Fictional Alaska Center',
    role: 'center_coordinator',
    states: ['AK'],
  },
  { organization_id: 'N', name: 'Fictional NOAA Review', role: 'noaa', states: [] },
];
const cases: NetworkCase[] = [
  {
    incident_id: 'fictional_ca_1',
    status: 'en_route',
    state_code: 'CA',
    latitude: 0,
    longitude: 0,
    animal_group: 'seal',
    species_common_name: 'Harbor seal (fictional)',
    severity_level: 'high',
    lead_organization_id: 'A',
    created_at: '2026-11-01T10:00:00',
  },
  {
    incident_id: 'fictional_ak_1',
    status: 'accepted',
    state_code: 'AK',
    latitude: 0,
    longitude: 0,
    animal_group: 'sea_lion',
    species_common_name: 'Sea lion (fictional)',
    severity_level: 'moderate',
    lead_organization_id: 'B',
    created_at: '2026-11-01T09:00:00',
  },
];
const fixtureApi: typeof createNetworkApi = (_, user, org) => {
  function context() {
    if (revoked && org === 'A') throw new NetworkError(403);
    return organizations.find((item) => item.organization_id === org);
  }
  function visible() {
    const selected = context();
    return !selected
      ? []
      : org === 'N'
        ? cases
        : cases.filter((row) => selected.states.includes(row.state_code!));
  }
  return {
    me: async () => {
      const selected = context();
      return {
        account_id: 'fictional_account',
        role: selected?.role ?? 'reporter',
        selected_organization_id: org,
        authorized_states: selected?.states ?? [],
        email: 'fictional@example.invalid',
        email_verified: true,
        organizations: organizations.filter(
          (item) => !(revoked && item.organization_id === 'A'),
        ),
      };
    },
    cases: async (scope, offset) => {
      // Intentional late response: verify changing context discards old results.
      await new Promise((resolve) => setTimeout(resolve, 300));
      return ['supporting', 'receiving', 'assigned_to_me'].includes(scope)
        ? []
        : visible().slice(offset, offset + 50);
    },
    case: async (id) => {
      const row = visible().find((row) => row.incident_id === id);
      if (!row) throw new NetworkError(404);
      return row;
    },
    report: async (id) => {
      if (id !== 'fictional_own_1') throw new NetworkError(404);
      return {
        case_id: id,
        phase: 'accepted',
        message: 'A team has taken your report.',
        arrival_eta_minutes: null,
        eta_is_estimate: false,
        reporter_can_leave: true,
        leaving_cancels_report: false,
      };
    },
  };
};
function AuthPreview() {
  const [user, setUser] = useState<NetworkUser | null>(null);
  const [fail, setFail] = useState(false);
  const [calls, setCalls] = useState('No fictional auth calls yet.');
  const [verified, setVerified] = useState(false);
  const fictional = { ...fixtureUser, email: 'demo@example.invalid', emailVerified: false };
  async function call(name: string) {
    setCalls(`Fictional ${name} requested; no network request.`);
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (fail) throw new Error('Fictional failure');
  }
  return <Shell>
    <div className="lj-toolbar">
      <label><input type="checkbox" checked={fail} onChange={(e) => setFail(e.target.checked)} />Simulate auth failure</label>
      <label><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />Simulate verified email</label>
      <p role="status">{calls}</p>
    </div>
    {user?.emailVerified ? <section className="lj-panel"><h2>Fictional verification passed</h2><p>Production still requires backend token verification and approved membership.</p><button onClick={() => setUser(null)}>Sign out</button></section> :
      <NetworkLogin user={user} configured checking={false} onSignOut={() => setUser(null)} onRefreshed={setUser}
        driver={{
          login: async () => { await call('sign-in'); setUser(fictional); },
          create: async () => { await call('account creation'); setUser(fictional); },
          reset: async () => { await call('password reset'); },
          verify: async () => { await call('verification email'); },
          refresh: async () => { await call('verification check'); return { ...fictional, emailVerified: verified }; },
          google: async () => { await call('Google sign-in'); },
        }} />}
  </Shell>;
}
function Preview() {
  const [view, setView] = useState<'signed-in' | 'signed-out' | 'auth'>('signed-in');
  const [notice, setNotice] = useState('');
  return (
    <>
      <div
        style={{
          padding: 12,
          background: '#fff2c2',
          color: '#241b00',
          font: '13px system-ui',
        }}
      >
        <strong>
          Fictional component test — no real sign-in, API requests or rescue cases.
        </strong>{' '}
        <button onClick={() => setView('signed-in')}>Open signed-in fixture</button>{' '}
        <button onClick={() => setView('signed-out')}>Open sign-in screen</button>{' '}
        <button onClick={() => setView('auth')}>Open fictional email flow</button>{' '}
        <button
          onClick={() => {
            revoked = true;
            setNotice('Fixture center revoked. Refresh access to apply.');
          }}
        >
          Revoke fixture center
        </button>{' '}
        <button
          onClick={() => {
            revoked = false;
            setNotice('Fixture reset.');
          }}
        >
          Reset fixture
        </button>{' '}
        <span role="status">{notice}</span>
      </div>
      {view === 'auth' ? <AuthPreview /> : view === 'signed-in' ? (
        <NetworkWorkspace
          user={fixtureUser}
          apiFactory={fixtureApi}
          onSignOut={() => setView('signed-out')}
        />
      ) : (
        <NetworkScreen />
      )}
    </>
  );
}
createRoot(document.getElementById('root')!).render(<Preview />);
