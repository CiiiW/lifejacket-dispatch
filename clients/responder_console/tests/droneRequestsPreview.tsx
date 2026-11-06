import React from 'react';
import { createRoot } from 'react-dom/client';
import { DroneRequests } from '../src/screens/DroneRequests.web';
import { Shell } from '../src/screens/NetworkScreen.web';
import { type DroneApi, type DroneRequest } from '../src/lib/networkApi';


const suggestionFor=(scenario:string)=>{
  if (scenario==='confident_group' || scenario==='missing_scores') return null;
  const condition=scenario!=='low_group';
  const confidence=condition?0.58:0.62;
  return {
    suggestion_id:(scenario==='low_group'?'1':scenario==='low_condition'?'2':'3').repeat(64),
    purpose:'verification' as const,title:'Additional evidence suggested',
    objective:condition?'Document visible posture, movement and possible entanglement for review.':'Clarify the animal group from an additional view.',
    reason:condition?'The condition assessment remains uncertain after intake.':'The animal group remains uncertain after intake.',
    signals:[{code:condition?'condition_uncertain':'animal_group_uncertain',
      label:condition?'Condition assessment confidence':'Animal group confidence',confidence,
      reason:'Additional evidence may help the coordinator.'}],
    threshold:0.9,threshold_is_validated:false as const,policy_version:'low-confidence-v1',
    urgent_parallel_review:scenario==='urgent',
    response_note:scenario==='urgent'?'Continue urgent coordinator response review; do not wait for drone evidence.':'Coordinator review is required before creating a request or arranging a flight.',
    escalation_criteria:'Escalate any new signs of distress or worsening hazards to the lead coordinator.',
  };
};
let scenario='low_group';
const consumed=new Set<string>();
function available(){
  if(rows.some(row=>row.purpose==='verification' && ['requested','approved','in_progress','evidence_ready'].includes(row.status)))return [];

  const item=suggestionFor(scenario);
  return item&&!consumed.has(item.suggestion_id)?[item]:[];
}

let rows: DroneRequest[] = [];
let seq=0;
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const next:Record<string,string[]> = {requested:['approved','declined','cancelled'],
  approved:['in_progress','cancelled','failed'],in_progress:['evidence_ready','cancelled','failed'],
  evidence_ready:['reviewed','cancelled','failed']};
const api:DroneApi={
  async list(){return {can_create:true,requests:clone(rows),suggestions:clone(available())};},
  async detail(_id,r){return clone(rows.find(x=>x.request_id===r)!);},
  async create(id,b){
    if (b.purpose==='monitoring' && !b.next_review_at) throw new Error('Monitoring requires a review time');
    if(b.suggestion_id){if(!available().some(s=>s.suggestion_id===b.suggestion_id))throw new Error('Suggestion changed');consumed.add(String(b.suggestion_id));}
    const row={...b,request_id:String(++seq).padStart(32,'0'),case_id:id,status:'requested',revision:0,
      operator:null,outcome:null,target_location:{latitude:36.8,longitude:-121.79},
      allowed_transitions:next.requested,evidence:[],events:[{revision:0,kind:'requested',
        recorded_at:new Date().toISOString(),actor_user_id:'fictional-coordinator'}]} as unknown as DroneRequest;
    rows.unshift(row);return clone(row);
  },
  async change(_id,r,b){
    const row=rows.find(x=>x.request_id===r)!;
    if(row.revision!==b.revision)throw new Error('Stale fixture update');
    if(b.status==='evidence_ready'&&!row.evidence?.length)throw new Error('Attach synthetic evidence first');
    Object.assign(row,b,{revision:row.revision+1,allowed_transitions:next[String(b.status)]||[]});
    if(b.status==='reviewed')row.review_note=String(b.note);
    row.events!.push({revision:row.revision,kind:String(b.status),recorded_at:new Date().toISOString(),
      actor_user_id:'fictional-coordinator',note:String(b.note)});
    return clone(row);
  },
  async upload(_id,r,form){
    const row=rows.find(x=>x.request_id===r)!;
    const meta=JSON.parse(String(form.get('metadata')));
    row.revision++;row.evidence!.push({...meta,evidence_id:'synthetic-frame'});
    return {};
  },
  async photo(){return new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#17364a"/><text x="40" y="180" fill="white" font-size="22">Synthetic workflow test — no wildlife evidence</text></svg>'],{type:'image/svg+xml'});}
};
function Demo(){
  const [version,setVersion]=React.useState(0);
  return <Shell><header><div className="lj-eyebrow">LifeJacket · Fictional case</div><h1>Case-linked drone workflow</h1>
    <p>Fictional case and synthetic evidence. No actual flight or NOAA footage.</p></header>
    <section className="lj-panel"><label>Test scenario<select value={scenario} onChange={e=>{
      scenario=e.target.value;setVersion(v=>v+1);
    }}><option value="low_group">Animal group unclear · 62%</option>
      <option value="low_condition">Animal group clear · condition uncertain · 58%</option>
      <option value="confident_group">Exact species unclear · animal group confident · 95%</option>
      <option value="urgent">Urgent response · condition uncertain</option>
      <option value="missing_scores">Confidence scores unavailable</option>
    </select></label><p className="lj-muted">Scenarios test suggestion display; backend rules have separate API tests.</p></section>
    <button className="secondary" onClick={()=>{
      const row=rows.find(x=>x.status==='in_progress');
      if(!row)return;
      row.revision++;row.evidence!.push({evidence_id:'synthetic-frame',description:'Synthetic test pattern; not animal evidence',
        source_kind:'sample_footage',source_url:'https://www.fisheries.noaa.gov/',rights_note:'Generated test pattern',
        captured_at:null,frame_offset_seconds:0});
      row.events!.push({revision:row.revision,kind:'evidence_attached',recorded_at:new Date().toISOString(),actor_user_id:'fictional-coordinator'});
      setVersion(v=>v+1);
    }}>Fixture: attach synthetic frame to in-progress request</button>
    <DroneRequests key={version} api={api} id="fictional-case"/>
  </Shell>;
}
createRoot(document.getElementById('root')!).render(<Demo/>);
