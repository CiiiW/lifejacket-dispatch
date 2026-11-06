import React from 'react';
import { createRoot } from 'react-dom/client';
import { DroneRequests } from '../src/screens/DroneRequests.web';
import { Shell } from '../src/screens/NetworkScreen.web';
import { type DroneApi, type DroneRequest } from '../src/lib/networkApi';

let rows: DroneRequest[] = [];
let seq=0;
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const next:Record<string,string[]> = {requested:['approved','declined','cancelled'],
  approved:['in_progress','cancelled','failed'],in_progress:['evidence_ready','cancelled','failed'],
  evidence_ready:['reviewed','cancelled','failed']};
const api:DroneApi={
  async list(){return {can_create:true,requests:clone(rows)};},
  async detail(_id,r){return clone(rows.find(x=>x.request_id===r)!);},
  async create(id,b){
    if (b.purpose==='monitoring' && !b.next_review_at) throw new Error('Monitoring requires a review time');
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
    <p>No backend, actual flight, NOAA media or real rescue case. UI fixture only.</p></header>
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
