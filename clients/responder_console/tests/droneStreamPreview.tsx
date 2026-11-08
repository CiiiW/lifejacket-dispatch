import React from 'react';
import { createRoot } from 'react-dom/client';
import { DroneRequests } from '../src/screens/DroneRequests.web';
import { createNetworkApi, NetworkError } from '../src/lib/networkApi';
const api=createNetworkApi(new URL('./api',location.href).href,{uid:'synthetic-demo',getIdToken:async()=>'synthetic-demo'},'A').drones!;
const simulateOutage=new URLSearchParams(location.search).has('simulate_outage');
if(simulateOutage){
  const read=api.streamPreview!;let polls=0;
  api.streamPreview=(...args)=>{
    polls++;
    if(polls>=3 && polls<=5)return Promise.reject(new NetworkError(503));
    return read(...args);
  };
}
const root=createRoot(document.getElementById('root')!);
void api.list('case').then(list=>root.render(<main style={{maxWidth:1000,margin:'auto',padding:28}}>
  <h1>LifeJacket · observation rehearsal</h1>
  {simulateOutage && <p>Temporary API outage rehearsal: preview requests 3–5 fail, then recover.</p>}
  <p className="lj-notice">Isolated synthetic case and recorded test-pattern video. No real account, animal or aircraft.</p>
  <DroneRequests api={api} id="case" initialRequestId={list.requests[0]?.request_id}/>
</main>)).catch(()=>root.render(<p>Rehearsal unavailable.</p>));
