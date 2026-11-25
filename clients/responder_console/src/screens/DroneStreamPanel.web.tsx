import { DroneRecordingPanel } from './DroneRecordingPanel.web';
import { useEffect, useRef, useState } from 'react';
import { type DroneApi, type DroneRequest, type DroneStream, networkErrorMessage, NetworkError } from '../lib/networkApi';

const activeStatuses = new Set(['waiting', 'connected', 'interrupted']);

function PrivatePublishingAddress({address}:{address:string}) {
  const [visible, setVisible] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(address);
      setCopyStatus('Private address copied.');
    } catch {
      setCopyStatus('Clipboard unavailable. Show the address to copy it manually.');
    }
  }

  return <details open>
    <summary>Private publishing address</summary>
    <p>Share only with the responsible operator. Paste the full address into RTMP. It grants publishing access for 30 minutes.</p>
    <label>Publishing address<input readOnly type={visible ? 'text' : 'password'} value={address}
      onFocus={e=>e.currentTarget.select()}/></label>
    <button type="button" className="secondary" onClick={()=>void copyAddress()}>Copy private address</button>
    <button type="button" className="secondary" aria-pressed={visible}
      onClick={()=>setVisible(!visible)}>{visible ? 'Hide private address' : 'Show private address'}</button>
    <p role="status">{copyStatus}</p>
  </details>;
}

export function DroneStreamPanel({api,id,request,onChanged,onUnavailable}:{api:DroneApi;id:string;request:DroneRequest;onChanged:()=>Promise<void>;onUnavailable:(e:unknown)=>void}) {
  const [available,setAvailable]=useState<boolean|null>(null);
  const [streams,setStreams]=useState<DroneStream[]>([]);
  const [selected,setSelected]=useState<string>('');
  const [view,setView]=useState<DroneStream|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [grant,setGrant]=useState<{streamId:string; address:string} | null>(null);
  const [label,setLabel]=useState('');
  const [rights,setRights]=useState('');
  const [source,setSource]=useState('');
  const [demoAvailable,setDemoAvailable]=useState(false);
  const [demo,setDemo]=useState(false);
  const [description,setDescription]=useState('');
  const [elapsed,setElapsed]=useState(0);
  const clock=useRef(0);
  const alive=useRef<AbortController|null>(null);
  const lock=useRef(false);
  function failure(e:unknown) {
    setView(null);
    if(e instanceof NetworkError && e.status===503){
      if(!selected)setAvailable(false);
      else setError('Observation preview is temporarily unavailable. Retrying…');
      return;
    }
    setGrant(null);
    setError(networkErrorMessage(e));
    if(e instanceof NetworkError && [401,403,404].includes(e.status)) onUnavailable(e);
  }
  useEffect(()=>{
    const c=new AbortController();alive.current=c;
    setAvailable(null);setStreams([]);setSelected('');setView(null);setGrant(null);setError('');setDemoAvailable(false);setDemo(false);
    return ()=>{c.abort();};
  },[api,id,request.request_id]);
  useEffect(()=>{
    const c=new AbortController();
    if(api.streams) void api.streams(id,request.request_id,c.signal).then(value=>{
      if(!c.signal.aborted){setAvailable(true);setDemoAvailable(value.demo_suggestions_available===true);setStreams(value.streams);setSelected(previous=>value.streams.some(s=>s.stream_id===previous)?previous:value.streams[0]?.stream_id||'');}
    }).catch(e=>{if(!c.signal.aborted)failure(e);});
    return ()=>c.abort();
  },[api,id,request.request_id,request.revision]);
  useEffect(()=>{
    const c=new AbortController();let timer:ReturnType<typeof setTimeout>;
    setView(null);
    async function poll(){
      if(!selected || !api.streamPreview)return;
      try {
        const value=await api.streamPreview(id,request.request_id,selected,c.signal);
        if(c.signal.aborted)return;
        clock.current=performance.now();setElapsed(0);setAvailable(true);setView(value);setError('');
        setStreams(previous=>previous.map(s=>s.stream_id===value.stream_id?{...s,status:value.status,can_manage:value.can_manage}:s));
        if(!value.can_manage || !activeStatuses.has(value.status)) {
          setGrant(previous=>previous?.streamId===value.stream_id ? null : previous);
        }
      }catch(e){if(c.signal.aborted)return;failure(e);}
      if(!c.signal.aborted)timer=setTimeout(()=>void poll(),1000);
    }
    void poll();
    const ticker=setInterval(()=>setElapsed((performance.now()-clock.current)/1000),500);
    return ()=>{c.abort();clearTimeout(timer);clearInterval(ticker);};
  },[api,id,request.request_id,selected]);
  async function action(fn:(signal:AbortSignal)=>Promise<void>){
    if(lock.current || !alive.current || alive.current.signal.aborted)return;
    lock.current=true;setBusy(true);setError('');
    const signal=alive.current.signal;
    try{await fn(signal);if(!signal.aborted)await onChanged();}
    catch(e){if(!signal.aborted)failure(e);}
    finally{lock.current=false;if(!signal.aborted)setBusy(false);}
  }
  if(!api.streams || available===false)return <p className="lj-notice">Live observation is not configured in this environment. Saved evidence remains available for review.</p>;
  if(available===null)return <p className="lj-muted">Checking observation streaming…</p>;
  const canManage=request.allowed_transitions.length>0 && request.status==='in_progress';
  const operatorFlight=request.execution_kind==='operator_flight';
  const fresh=view?.status==='connected' && (view.frame_age_seconds??Infinity)+elapsed<=6;
  const suggestion=fresh && view.suggested_frame && view.suggested_frame.age_seconds+elapsed<=6 ? view.suggested_frame : null;
  const active=streams.some(s=>['waiting','connected','interrupted'].includes(s.status));
  return <section className="lj-panel" aria-label="Case live preview" style={{marginTop:20}}>
    <h3>Live observation session</h3>
    <p className="lj-muted">Sampled preview · up to 2 frames/second. Save a useful frame for coordinator review.</p>
    {request.execution_kind==='recorded_demo' && <p className="lj-notice">Recorded footage rehearsal · no live aircraft connection.</p>}
    {error && <p role="alert">{error}</p>}
    {canManage && !active && <form aria-label="Open observation stream" onSubmit={e=>{
      e.preventDefault();void action(async signal=>{
        const value=await api.openStream!(id,request.request_id,{revision:request.revision,label,rights_note:rights,source_url:source||null,demo_suggestions:demoAvailable&&demo},signal);
        if (signal.aborted) return;
        setGrant(value.publish_url ? { streamId: value.stream_id, address: value.publish_url } : null);
        setSelected(value.stream_id);
        setStreams(previous => [value, ...previous]);
      });
    }}>
      <label>Session label<input required maxLength={120} value={label} onChange={e=>setLabel(e.target.value)}/></label>
      <label>Credits and reuse terms<input required maxLength={1000} value={rights} onChange={e=>setRights(e.target.value)}/></label>
      {request.execution_kind==='recorded_demo' && <label>Recording source reference<input required type="url" value={source} onChange={e=>setSource(e.target.value)}/></label>}
      {demoAvailable && <label><input type="checkbox" checked={demo} onChange={e=>setDemo(e.target.checked)}/>Suggest frames for a staged plush demo</label>}
      <button disabled={busy}>Open private session</button>
    </form>}
    {canManage && grant?.streamId===selected && <PrivatePublishingAddress key={grant.streamId} address={grant.address}/>}
    {operatorFlight && <details>
      <summary>Connect Litchi or DJI Fly</summary>
      <p>Connect the iPhone to the Mini 2 controller and use one flight app at a time. Confirm the live camera image before starting RTMP. Keep the motors off for a ground check.</p>
      <ul>
        <li><strong>Litchi</strong> · FPV → Share Video Stream → RTMP Streaming. Allow Local Network access if prompted.
          If the prompt does not appear, try Litchi Vue from the same menu, then return to RTMP.</li>
        <li><strong>DJI Fly</strong> · Camera view → Transmission → Live Streaming Platforms → RTMP.</li>
      </ul>
      <p>Use the full private publishing address. Check for <strong>Connected</strong> and a new reception time in LifeJacket.</p>
    </details>}
    {streams.length>0 && <label>Observation session<select value={selected} onChange={e=>{setView(null);setGrant(null);setSelected(e.target.value);}}>
      {streams.map(s=><option key={s.stream_id} value={s.stream_id}>{s.source.label} · {s.status}</option>)}
    </select></label>}
    {view && <>
      <p role="status"><strong>{view.status==='connected'&&!fresh?'Interrupted · preview is stale':view.status.replaceAll('_',' ')}</strong> · expires {new Date(view.expires_at).toLocaleTimeString()}</p>
      {fresh && view.frame ? <img src={'data:image/jpeg;base64,'+view.frame.jpeg_base64} alt="Current sampled observation preview" style={{width:'100%',maxWidth:640,borderRadius:8}}/>:
        <p className="lj-notice">{view.status==='waiting'?'Waiting for the operator or rehearsal publisher.':'No current image. Do not interpret a frozen feed as an unchanged animal.'}</p>}
      {operatorFlight && canManage && !fresh && activeStatuses.has(view.status) &&
        <p className="lj-muted">If the receiver shows no new frames, check that the camera image is visible in the flight app, the phone can reach the private receiver, and RTMP streaming is active.</p>}
      <p className="lj-muted">Last received {view.last_frame_at?new Date(view.last_frame_at).toLocaleString():'No frames yet'}. Reception time is not camera capture time. Location is unverified.</p>
      {canManage && view.can_manage && <>
        <label>Observation to save<input maxLength={2000} value={description} onChange={e=>setDescription(e.target.value)}/></label>
        <button disabled={busy || !fresh || !view.frame || !description.trim()} onClick={()=>{
          const frame=view.frame;if(!frame)return;
          void action(async signal=>{await api.captureStream!(id,request.request_id,view.stream_id,{revision:request.revision,frame_id:frame.frame_id,description},signal);if(!signal.aborted)setDescription('');});
        }}>Save displayed frame as evidence</button>
        {suggestion && <div className="lj-panel">
          <h4>Suggested staged plush frame</h4>
          <img src={'data:image/jpeg;base64,'+suggestion.jpeg_base64} alt="Suggested frame from the staged plush detector" style={{width:'100%',maxWidth:320,borderRadius:8}}/>
          <p>YOLOX-S COCO teddy bear score {suggestion.demo_plush_score.toFixed(2)}.</p>
          <button className="secondary" disabled={busy} onClick={()=>void action(async signal=>{
            await api.captureStream!(id,request.request_id,view.stream_id,{revision:request.revision,frame_id:suggestion.frame_id,description:description.trim()||'Staged plush candidate selected for review.'},signal);
            if(!signal.aborted)setDescription('');
          })}>Save suggested frame as evidence</button>
        </div>}
        <button className="secondary" disabled={busy} onClick={()=>void action(async signal=>{
          await api.endStream!(id,request.request_id,view.stream_id,{revision:request.revision},signal);
          if(!signal.aborted){setGrant(null);setView(null);}
        })}>End observation session</button>
      </>}
    </>}
    {selected && <DroneRecordingPanel api={api} id={id} request={request} streamId={selected} onUnavailable={onUnavailable}/>}
    <p className="lj-muted">Saved frames enter the existing evidence review. Streaming does not change severity, dispatch responders or control the drone.</p>
  </section>;
}
