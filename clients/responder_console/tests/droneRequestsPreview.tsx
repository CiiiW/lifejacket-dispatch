import React from 'react';
import { createRoot } from 'react-dom/client';
import { CoordinatorAttention } from '../src/screens/CoordinatorAttention.web';
import { MonitoringQueue } from '../src/screens/MonitoringQueue.web';
import { DroneRequests } from '../src/screens/DroneRequests.web';
import { Shell } from '../src/screens/NetworkScreen.web';
import { type DroneApi, type DroneRequest, type DroneSuggestion } from '../src/lib/networkApi';


const suggestionFor=(scenario:string):DroneSuggestion|null=>{
  if (scenario==='unidentified') {
    const base=suggestionFor('low_group')!;
    return {...base,suggestion_id:'4'.repeat(64),
      reason:'The animal remains unidentified after intake; a clearer view needs review.',
      signals:[{code:'identification_evidence_gap',label:'Animal group unresolved',
                confidence:null,reason:'A clearer view needs review.'}]};
  }
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
    threshold:0.9,threshold_is_validated:false as const,policy_version:'low-confidence-v2',
    urgent_parallel_review:scenario==='urgent',
    response_note:scenario==='urgent'?'Continue urgent coordinator response review; do not wait for drone evidence.':'Coordinator review is required before creating a request or arranging a flight.',
    escalation_criteria:'Escalate any new signs of distress or worsening hazards to the lead coordinator.',
  };
};
let scenario='low_group';
const consumed=new Set<string>();
function available(){
  if(rows.some(row=>row.purpose==='verification' && row.execution_kind==='operator_flight' && ['requested','approved','in_progress','evidence_ready'].includes(row.status)))return [];

  const item=suggestionFor(scenario);
  return item&&!consumed.has(item.suggestion_id)?[item]:[];
}

let rows: DroneRequest[] = [];
let seq=0;
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const next:Record<string,string[]> = {requested:['approved','declined','cancelled'],
  approved:['in_progress','cancelled','failed'],in_progress:['evidence_ready','cancelled','failed'],
  evidence_ready:['reviewed','cancelled','failed']};
const acknowledged=new Set<string>();
function fixtureAttention(){
  return rows.flatMap(row=>{
    const escalation=row.monitoring_decision?.action==='escalate'||row.outcome==='escalation_needed';
    const overdue=!row.monitoring_decision&&row.next_review_at&&Date.parse(row.next_review_at)<=Date.now();
    return (['escalation','overdue'] as const).filter(kind=>kind==='escalation'?escalation:overdue).map(kind=>({
      case_id:row.case_id,request_id:row.request_id,revision:row.revision,kind,
      attention_key:row.request_id+(kind==='escalation'?'e':'d').repeat(32),
      reason:row.monitoring_decision?.reason||row.review_note||'Scheduled review is overdue',
      since:row.next_review_at,objective:row.objective,execution_kind:row.execution_kind,can_acknowledge:true,
    })).filter(item=>!acknowledged.has(item.attention_key));
  });
}
const api:DroneApi={
  async attention(offset){const items=fixtureAttention();return {items:clone(items.slice(offset,offset+50)),total:items.length};},
  async acknowledgeAttention(_id,r,b){
    const row=rows.find(x=>x.request_id===r)!;
    if(row.revision!==b.revision||!fixtureAttention().some(x=>x.attention_key===b.attention_key))throw new Error('Stale fixture acknowledgment');
    acknowledged.add(String(b.attention_key));row.revision++;
    row.events!.push({revision:row.revision,kind:'attention_acknowledged',recorded_at:new Date().toISOString(),actor_user_id:'fictional-coordinator',note:String(b.note)});
    return clone(row);
  },
  async comparison(id,r,previous){
    const row=rows.find(x=>x.request_id===r)!;
    return {case_id:id,intake:{recorded_at:new Date().toISOString(),animal_group:'pinniped',
      species_common_name:null,severity_level:'monitor',injury_present:null,entanglement_present:false,
      confidence:{animal_group:.95,condition:.7}},
      current:clone(row),previous:clone(rows.find(x=>x.request_id===(previous||row.previous_request_id))||null),
      comparison_is_automated:false as const};
  },
  async monitoringQueue(offset){
    const items=rows.filter(r=>!r.monitoring_decision && (r.purpose==='monitoring'||r.next_review_at)).map(r=>({
      case_id:r.case_id,request_id:r.request_id,request_status:r.status,
      queue_status:r.next_review_at && Date.parse(r.next_review_at)<Date.now()?'overdue':r.status==='reviewed'?'needs_decision':'scheduled',
      next_review_at:r.next_review_at,execution_kind:r.execution_kind,objective:r.objective,can_decide:r.status==='reviewed',
    }));
    return {items:items.slice(offset,offset+50),total:items.length,due_soon_hours:24};
  },
  async monitoringDecision(id,r,b){
    const row=rows.find(x=>x.request_id===r)!;
    if(row.revision!==b.revision || row.monitoring_decision)throw new Error('Stale fixture update');
    let child:DroneRequest|undefined;
    if(b.action==='continue'){
      child=await api.create(id,{purpose:'monitoring',objective:row.objective,reason:b.reason,
        execution_kind:row.execution_kind,next_review_at:b.next_review_at,escalation_criteria:row.escalation_criteria});
      const stored=rows.find(x=>x.request_id===child!.request_id)!;
      stored.previous_request_id=r;stored.monitoring_root_request_id=row.monitoring_root_request_id||r;
    }
    row.revision++;row.monitoring_decision={action:String(b.action),reason:String(b.reason),next_request_id:child?.request_id||null};
    row.events!.push({revision:row.revision,kind:'monitoring_'+b.action,recorded_at:new Date().toISOString(),actor_user_id:'fictional-coordinator',note:String(b.reason)});
    return clone(row);
  },
  async list(){return {can_create:true,requests:clone(rows),suggestions:clone(available()),confidence_summary:{animal_group:scenario==='unidentified'?null:scenario==='low_group'?0.62:scenario==='confident_group'?0.95:0.98,condition:scenario==='missing_scores'?null:['low_condition','urgent'].includes(scenario)?0.58:0.98}};},
  async detail(_id,r){return clone(rows.find(x=>x.request_id===r)!);},
  async create(id,b){
    if (b.purpose==='monitoring' && !b.next_review_at) throw new Error('Monitoring requires a review time');
    if(b.suggestion_id){
      const previous=rows.find(row=>row.suggestion_id===b.suggestion_id && row.execution_kind===b.execution_kind);
      if(previous)return clone(previous);
      if(suggestionFor(scenario)?.suggestion_id!==b.suggestion_id || (b.execution_kind==='operator_flight'&&!available().some(s=>s.suggestion_id===b.suggestion_id)))throw new Error('Suggestion changed');
      if(b.execution_kind==='operator_flight')consumed.add(String(b.suggestion_id));
    }
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
  const [request,setRequest]=React.useState<string>();
  const [monitorRevision,setMonitorRevision]=React.useState(0);
  return <Shell><header><div className="lj-eyebrow">LifeJacket · Fictional case</div><h1>Case-linked drone workflow</h1>
    <p>Fictional case and synthetic evidence. No actual flight or NOAA footage.</p></header>
    <section className="lj-panel"><label>Test scenario<select value={scenario} onChange={e=>{
      scenario=e.target.value;setVersion(v=>v+1);
    }}><option value="low_group">Animal group unclear · 62%</option>
      <option value="low_condition">Animal group clear · condition uncertain · 58%</option>
      <option value="confident_group">Exact species unclear · animal group confident · 95%</option>
      <option value="urgent">Urgent response · condition uncertain</option>
      <option value="unidentified">Unidentified animal · photo too distant</option><option value="missing_scores">Condition confidence unavailable</option>
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
    <button className="secondary" onClick={async()=>{
      const row=await api.create('fictional-case',{purpose:'monitoring',objective:'Observe pup activity from a distance',
        reason:'Fictional monitoring scenario',execution_kind:'recorded_demo',
        next_review_at:new Date(Date.now()-3600000).toISOString(),
        escalation_criteria:'Coordinator reviews worsening condition'});
      const stored=rows.find(x=>x.request_id===row.request_id)!;
      stored.status='reviewed';stored.allowed_transitions=[];stored.outcome='still_uncertain';
      stored.review_note='Synthetic observation only';setRequest(row.request_id);setVersion(v=>v+1);setMonitorRevision(v=>v+1);
    }}>Fixture: load overdue monitoring</button>
    <button className="secondary" onClick={async()=>{
      const row=await api.create('fictional-case',{purpose:'verification',objective:'Review a possible change in condition',
        reason:'Fictional escalation scenario',execution_kind:'recorded_demo',next_review_at:null,
        escalation_criteria:'Coordinator review'});
      const stored=rows.find(x=>x.request_id===row.request_id)!;
      stored.status='reviewed';stored.allowed_transitions=[];stored.outcome='escalation_needed';
      stored.review_note='Synthetic finding: coordinator review requested.';
      setRequest(row.request_id);setVersion(v=>v+1);setMonitorRevision(v=>v+1);
    }}>Fixture: load escalation</button>
    <button className="secondary" onClick={async()=>{
      const ids:string[]=[];
      for(const period of ['Earlier','Current']){
        const row=await api.create('fictional-case',{purpose:'verification',objective:period+' synthetic observation',
          reason:'Fictional comparison scenario',execution_kind:'recorded_demo',next_review_at:null,
          escalation_criteria:'Coordinator review'});
        const stored=rows.find(x=>x.request_id===row.request_id)!;
        stored.status='reviewed';stored.allowed_transitions=[];stored.outcome='still_uncertain';
        stored.review_note=period+' synthetic finding; no animal outcome is inferred.';
        stored.evidence=[{evidence_id:'comparison-'+period,description:period+' synthetic test pattern',
          source_kind:'sample_footage',source_url:'https://www.fisheries.noaa.gov/',
          captured_at:null,frame_offset_seconds:0,rights_note:'Generated test pattern'}];
        if(ids.length)stored.previous_request_id=ids[0];
        ids.push(row.request_id);
      }
      setRequest(ids[1]);setVersion(v=>v+1);setMonitorRevision(v=>v+1);
    }}>Fixture: load evidence comparison</button>
    <CoordinatorAttention api={api} revision={monitorRevision} onChange={()=>setMonitorRevision(v=>v+1)} onOpen={(_id,r)=>setRequest(r)}/>
    <MonitoringQueue api={api} revision={monitorRevision} onOpen={(_id,r)=>setRequest(r)}/>
    <DroneRequests key={version} api={api} id="fictional-case" initialRequestId={request} onMonitoringChange={()=>setMonitorRevision(v=>v+1)}/>
  </Shell>;
}
createRoot(document.getElementById('root')!).render(<Demo/>);
