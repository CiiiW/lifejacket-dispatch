import React from 'react';
import { createRoot } from 'react-dom/client';
import { DroneRequests } from '../src/screens/DroneRequests.web';
import { createNetworkApi } from '../src/lib/networkApi';
const api=createNetworkApi(new URL('./api',location.href).href,{uid:'synthetic-demo',getIdToken:async()=>'synthetic-demo'},'A').drones!;
const root=createRoot(document.getElementById('root')!);
void api.list('case').then(list=>root.render(<main style={{maxWidth:1000,margin:'auto',padding:28}}>
  <h1>LifeJacket · observation rehearsal</h1>
  <p className="lj-notice">Isolated synthetic case and recorded test-pattern video. No real account, animal or aircraft.</p>
  <DroneRequests api={api} id="case" initialRequestId={list.requests[0]?.request_id}/>
</main>)).catch(()=>root.render(<p>Rehearsal unavailable.</p>));
