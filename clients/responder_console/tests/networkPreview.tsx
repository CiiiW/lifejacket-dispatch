import { networkDroneFixture } from './networkDroneFixture';
/** Isolated component fixture. Not imported by the application entry point. */
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import NetworkScreen, {
  NetworkWorkspace,
  Shell,
} from '../src/screens/NetworkScreen.web';
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
  {
    organization_id: 'N',
    name: 'Fictional NOAA Review',
    role: 'noaa',
    states: [],
  },
];
// Fictional cases with coordinates so the map has something to draw: two close
// together (they cluster), one unclaimed (it pulses) and one in each state.
const fixtureCase = (
  incident_id: string,
  state_code: string,
  latitude: number,
  longitude: number,
  species: string,
  group: string,
  severity: string,
  status: string,
  lead: string | null,
  created_at: string,
): NetworkCase => ({
  incident_id,
  status,
  state_code,
  latitude,
  longitude,
  animal_group: group,
  species_common_name: species,
  severity_level: severity,
  lead_organization_id: lead,
  created_at,
});
const cases: NetworkCase[] = [
  fixtureCase('fictional_ca_1', 'CA', 36.95, -122.02, 'Harbor seal (fictional)', 'seal', 'respond', 'en_route', 'A', '2026-11-01T10:00:00'),
  fixtureCase('fictional_ca_2', 'CA', 36.96, -122.01, 'Brown pelican (fictional)', 'seabird', 'respond', 'awaiting_dispatch', null, '2026-11-01T10:30:00'),
  fixtureCase('fictional_ca_3', 'CA', 36.62, -121.9, 'Sea lion (fictional)', 'sea_lion', 'critical', 'dispatched', null, '2026-11-01T09:30:00'),
  fixtureCase('fictional_ca_4', 'CA', 35.14, -120.64, 'Elephant seal (fictional)', 'seal', 'monitor', 'accepted', 'A', '2026-11-01T08:00:00'),
  fixtureCase('fictional_ak_1', 'AK', 58.3, -134.4, 'Sea lion (fictional)', 'sea_lion', 'monitor', 'accepted', 'B', '2026-11-01T09:00:00'),
  fixtureCase('fictional_ak_2', 'AK', 61.2, -149.9, 'Harbor seal (fictional)', 'seal', 'critical', 'awaiting_dispatch', null, '2026-11-01T11:00:00'),
];
const fixtureClosures = (phase: string) => [
  'no_response_needed',
  'transferred',
  ...(phase === 'on_scene' ? ['unable_to_locate'] : []),
  ...(phase === 'animal_located' ? ['rescue_complete'] : []),
];
const responseStates: Record<string, { phase: string; revision: number }> = {};
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
    drones: networkDroneFixture(() => visible().map(row => row.incident_id)),
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
    response: async (id) => {
      if (!visible().some((row) => row.incident_id === id))
        throw new NetworkError(404);
      const state = responseStates[id] ?? { phase: 'received', revision: 0 };
      const allowed = org === 'A' && state.phase !== 'closed';
      const next = (
        {
          received: 'accepted',
          accepted: 'en_route',
          en_route: 'on_scene',
          on_scene: 'animal_located',
        } as Record<string, string>
      )[state.phase];
      return {
        case_id: id,
        ...state,
        allowed_transitions: allowed ? [...(next ? [next] : []), 'closed'] : [],
        contact_channels: allowed ? ['text'] : [],
        closure_reasons: allowed ? fixtureClosures(state.phase) : [],
      };
    },
    changeResponse: async (id, revision, phase) => {
      context();
      const state = responseStates[id] ?? { phase: 'received', revision: 0 };
      if (org !== 'A') throw new NetworkError(403);
      if (revision !== state.revision) throw new NetworkError(409);
      responseStates[id] = { phase, revision: revision + 1 };
      const next = (
        {
          received: 'accepted',
          accepted: 'en_route',
          en_route: 'on_scene',
          on_scene: 'animal_located',
        } as Record<string, string>
      )[phase];
      return {
        case_id: id,
        phase,
        revision: revision + 1,
        allowed_transitions:
          phase === 'closed' ? [] : [...(next ? [next] : []), 'closed'],
        contact_channels: phase === 'closed' ? [] : ['text'],
        closure_reasons: phase === 'closed' ? [] : fixtureClosures(phase),
      };
    },
    contact: async (id) => {
      context();
      if (
        org !== 'A' ||
        !visible().some((row) => row.incident_id === id) ||
        responseStates[id]?.phase === 'closed'
      )
        throw new NetworkError(403);
      return {
        case_id: id,
        phone_number: '+12025550123',
        channels: ['text'],
        presence: 'left',
      };
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
  const fictional = {
    ...fixtureUser,
    email: 'demo@example.invalid',
    emailVerified: false,
  };
  async function call(name: string) {
    setCalls(`Fictional ${name} requested; no network request.`);
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (fail) throw new Error('Fictional failure');
  }
  return (
    <Shell>
      <div className="lj-toolbar">
        <label>
          <input
            type="checkbox"
            checked={fail}
            onChange={(e) => setFail(e.target.checked)}
          />
          Simulate auth failure
        </label>
        <label>
          <input
            type="checkbox"
            checked={verified}
            onChange={(e) => setVerified(e.target.checked)}
          />
          Simulate verified email
        </label>
        <p role="status">{calls}</p>
      </div>
      {user?.emailVerified ? (
        <section className="lj-panel">
          <h2>Fictional verification passed</h2>
          <p>
            Production still requires backend token verification and approved
            membership.
          </p>
          <button onClick={() => setUser(null)}>Sign out</button>
        </section>
      ) : (
        <NetworkLogin
          user={user}
          configured
          checking={false}
          onSignOut={() => setUser(null)}
          onRefreshed={setUser}
          driver={{
            login: async () => {
              await call('sign-in');
              setUser(fictional);
            },
            create: async () => {
              await call('account creation');
              setUser(fictional);
            },
            reset: async () => {
              await call('password reset');
            },
            verify: async () => {
              await call('verification email');
            },
            refresh: async () => {
              await call('verification check');
              return { ...fictional, emailVerified: verified };
            },
            google: async () => {
              await call('Google sign-in');
            },
          }}
        />
      )}
    </Shell>
  );
}
function Preview() {
  const [view, setView] = useState<'signed-in' | 'signed-out' | 'auth'>(
    'signed-in',
  );
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
          Fictional component test — no real sign-in, API requests or rescue
          cases.
        </strong>{' '}
        <button onClick={() => setView('signed-in')}>
          Open signed-in fixture
        </button>{' '}
        <button onClick={() => setView('signed-out')}>
          Open sign-in screen
        </button>{' '}
        <button onClick={() => setView('auth')}>
          Open fictional email flow
        </button>{' '}
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
      {view === 'auth' ? (
        <AuthPreview />
      ) : view === 'signed-in' ? (
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
