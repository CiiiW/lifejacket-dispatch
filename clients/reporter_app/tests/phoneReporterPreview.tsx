/** Isolated UI fixture. Never imported by index.ts or the application entry. */
import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { PhoneReporterPage } from '../src/screens/PhoneReporter.web';
import type { PhoneReporterApi, Draft } from '../src/lib/phoneReporterApi';

const user = { uid:'fictional-phone-user', phoneNumber:'+12025550123', getIdToken:async()=>'fictional-unused-token' };
let phase = 'received';
let failStatus = false;
let submitted = false;
let completedDraft = false;
let presence = 'unspecified';
const turn = {
  incident_id:'fictional-report', message:'Add a photo from a safe distance.',
  complete:false, awaiting_reply:false, action:'request_photo', stage:'identifying', options:[],
  questions_asked:0, identified_as:null, taxon_rank:null, species_confidence:null,
  severity_level:null, severity_reasons:[], environmental_rationale:null,
  injury_summary:null, recommended_action:null, safety_guidance:'Keep a safe distance; do not handle the animal.',
  reporter_instructions:[], closing_note:null, matched_teams:[], report_headline:null,
  conditions:null, service_error:false, detections:[], detection_photo_id:null,
  detection_photo_url:null, detection_status:'pending', selected_detection:null,
} satisfies Draft['turn'];
const api: PhoneReporterApi = {
  start:async()=>({turn:completedDraft?{...turn,complete:true,action:null,stage:'complete'}:turn, draft_key:'fictional-never-sent', expires_at:'2026-11-03T00:00:00Z'}),
  photo:async()=>({...turn,action:'request_location',message:'Where was the animal seen?'}),
  turn:async()=>({...turn, action:null, complete:true,stage:'complete'}),
  submit:async()=>{submitted=true;return {case_id:'fictional-report',submitted:true};},
  reports:async()=>submitted?[{case_id:'fictional-report',submitted_at:'2026-11-01T12:00:00Z'}]:[],
  status:async()=>{
    if(failStatus) throw new Error('Fictional unavailable');
    return {case_id:'fictional-report',phase,message:phase==='animal_located'?'The team has located the animal.':phase==='accepted'?'A team has taken your report.':'Report received; awaiting team confirmation.',arrival_eta_minutes:null,eta_updated_at:null,eta_is_estimate:false,reporter_can_leave:true,leaving_cancels_report:false,presence};
  },
  presence:async(_,__,next)=>{presence=next;return {};},
};
const driver = {
  requestCode:async()=>({confirm:async(code:string)=>{if(code!=='123456')throw new Error('Fictional invalid code');return user;},dispose:()=>{}}),
  signOut:async()=>{},
};
function Preview() {
  const [ready,setReady]=useState(true);
  const stable=useMemo(()=>api,[]);
  return <><aside style={{padding:12,background:'#fff2c2',color:'#241b00',font:'13px system-ui'}}>
    <strong>Fictional phone-report UI test — no real SMS, sign-in, API or rescue case.</strong>
    <p>Fixture code: 123456. No real SMS is sent.</p>
    <label style={{color:'#241b00'}}><input type="checkbox" style={{width:'auto'}} onChange={(e)=>{completedDraft=e.target.checked;}} />Start with completed fictional draft</label>
    <label style={{color:'#241b00'}}>Fictional response phase<select aria-label="Fictional response phase" onChange={(e)=>{phase=e.target.value;}}><option value="received">Received</option><option value="accepted">Accepted</option><option value="animal_located">Animal located</option></select></label>
    <label style={{color:'#241b00'}}><input type="checkbox" style={{width:'auto'}} onChange={(e)=>{failStatus=e.target.checked;}} />Simulate unavailable status</label>
    <label style={{color:'#241b00'}}><input type="checkbox" style={{width:'auto'}} checked={ready} onChange={(e)=>setReady(e.target.checked)} />Fixture phone provider ready</label>
  </aside><PhoneReporterPage api={stable} configured={ready} authDriver={driver} /></>;
}
createRoot(document.getElementById('root')!).render(<Preview />);
