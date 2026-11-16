import { useEffect, useRef, useState } from 'react';
import { type DroneApi, type DroneRequest, NetworkError, networkErrorMessage } from '../lib/networkApi';
import { DroneStreamPanel } from './DroneStreamPanel.web';
import { DroneFollowupPanel } from './DroneFollowupPanel.web';

export function ObservationWorkspace({api,id,request,canManage,onChanged,onUnavailable}:{api:DroneApi;id:string;request:DroneRequest;canManage:boolean;onChanged:()=>Promise<void>;onUnavailable:(e:unknown)=>void}) {
  const [selected,setSelected]=useState('');
  const [photo,setPhoto]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const url=useRef('');
  const pending=useRef<AbortController|null>(null);
  const evidence=request.evidence||[];
  const current=evidence.find(e=>e.evidence_id===selected);
  function clearPhoto(){if(url.current)URL.revokeObjectURL(url.current);url.current='';setPhoto('');}
  useEffect(()=>{
    setSelected('');clearPhoto();setError('');setBusy(false);
    return ()=>{pending.current?.abort();clearPhoto();};
  },[api,id,request.request_id]);
  useEffect(()=>{
    if(selected && !evidence.some(e=>e.evidence_id===selected)){
      pending.current?.abort();clearPhoto();setSelected('');setBusy(false);
    }
  },[request.evidence,selected]);
  async function choose(evidenceId:string){
    pending.current?.abort();const controller=new AbortController();pending.current=controller;
    clearPhoto();setSelected(evidenceId);setBusy(true);setError('');
    try{
      const blob=await api.photo(id,request.request_id,evidenceId,controller.signal);
      if(controller.signal.aborted)return;
      url.current=URL.createObjectURL(blob);setPhoto(url.current);
    }catch(e){
      if(controller.signal.aborted)return;
      setError(networkErrorMessage(e));clearPhoto();
      if(e instanceof NetworkError && [401,403,404].includes(e.status))onUnavailable(e);
    }finally{if(!controller.signal.aborted)setBusy(false);}
  }
  return <section className="lj-observation-workspace" aria-label="Observation workspace" style={{margin:'24px 0',border:'1px solid #63818c',borderRadius:14,padding:'clamp(12px,3vw,24px)'}}>
    <style>{`.lj-observation-columns{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:20px;align-items:start}.lj-observation-columns>*{min-width:0}.lj-evidence-card{display:block;width:100%;text-align:left;white-space:normal}.lj-evidence-card[aria-pressed=true]{outline:2px solid #61d7ec;outline-offset:2px}.lj-observation-workspace video,.lj-observation-workspace img{max-width:100%}@media(max-width:850px){.lj-observation-columns{grid-template-columns:minmax(0,1fr)}}`}</style>
    <header>
      <div className="lj-eyebrow">Case observation · {id}</div>
      <h3 style={{fontSize:24,margin:'8px 0'}}>Observe, compare, review</h3>
      <p>{request.objective}</p>
      <p className="lj-muted">{request.execution_kind==='recorded_demo'?'Recorded demonstration':'Operator observation'} · {evidence.length} saved photo(s) · {request.status==='reviewed'?'Human review recorded':['cancelled','declined','failed'].includes(request.status)?'Observation '+request.status:'Coordinator review pending'}</p>
      <p className="lj-notice">{request.target_location.latitude===null || request.target_location.longitude===null?'Location unavailable.':'Reported case location is available; the animal’s position in the video is unverified.'} AI findings remain advisory until reviewed.</p>
    </header>
    <div className="lj-observation-columns">
      <div aria-label="Live and recorded footage">
        <h4>1 · Watch the footage</h4>
        <DroneStreamPanel api={api} id={id} request={request} onChanged={onChanged} onUnavailable={onUnavailable}/>
        {!api.streams && <p className="lj-notice">Live video is not available in this environment. Saved photos can still be reviewed.</p>}
      </div>
      <div aria-label="Evidence and advisory findings">
        <h4>2 · Inspect saved photos</h4>
        <p className="lj-muted">Open the unmodified saved frame, then use the same evidence in AI review below.</p>
        {error && <p role="alert">{error}</p>}
        {!evidence.length && <p className="lj-notice">No saved evidence yet. Save a useful frame from the preview or attach a photo below.</p>}
        <div aria-label="Saved observation photos">{evidence.map((item,index)=><button key={item.evidence_id} type="button" className="secondary lj-evidence-card" aria-pressed={selected===item.evidence_id} onClick={()=>void choose(item.evidence_id)}>
          <strong>Photo {index+1} · {item.description}</strong><br/>
          <small>{item.received_at?'Received '+new Date(item.received_at).toLocaleString():item.captured_at?'Captured '+new Date(item.captured_at).toLocaleString():'Capture time unknown'}</small>
        </button>)}</div>
        {busy && <p role="status">Loading original saved frame…</p>}
        {photo && current && <figure style={{margin:'16px 0'}}>
          <img src={photo} alt={'Original saved frame: '+current.description} style={{width:'100%',borderRadius:8}}/>
          <figcaption><strong>{current.description}</strong><p className="lj-muted">{current.rights_note} · {current.source_kind.replaceAll('_',' ')} · video offset {current.frame_offset_seconds??'unknown'}</p>
            {current.received_at && <p className="lj-muted">Server reception time is recorded. Camera capture time is unknown.</p>}
            {current.source_url && <a href={current.source_url} target="_blank" rel="noreferrer">Source reference</a>}
          </figcaption>
        </figure>}
        <h4>3 · Review advisory findings</h4>
        <DroneFollowupPanel api={api} id={id} request={request} canManage={canManage} selectedEvidenceId={selected} onEvidenceSelected={evidenceId=>void choose(evidenceId)} onChanged={onChanged} onUnavailable={onUnavailable}/>
      </div>
    </div>
    {request.allowed_transitions.length>0 && <a href={'#observation-review-'+request.request_id}>Go to request update and human review</a>}
    <p className="lj-muted">Record the human finding in the request review below. Saving evidence or running AI does not dispatch responders or change the original intake assessment.</p>
  </section>;
}
