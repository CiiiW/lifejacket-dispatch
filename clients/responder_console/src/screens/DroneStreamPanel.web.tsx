import { DroneRecordingPanel } from './DroneRecordingPanel.web';
import { useEffect, useRef, useState } from 'react';
import { type DroneApi, type DroneRequest, type DroneStream, networkErrorMessage, NetworkError } from '../lib/networkApi';

export function DroneStreamPanel({api,id,request,onChanged,onUnavailable}:{api:DroneApi;id:string;request:DroneRequest;onChanged:()=>Promise<void>;onUnavailable:(e:unknown)=>void}) {
  const [available,setAvailable]=useState<boolean|null>(null);
  const [streams,setStreams]=useState<DroneStream[]>([]);
  const [selected,setSelected]=useState<string>('');
  const [view,setView]=useState<DroneStream|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [grant,setGrant]=useState('');
  const [label,setLabel]=useState('');
  const [rights,setRights]=useState('');
  const [source,setSource]=useState('');
  const [description,setDescription]=useState('');
  const [elapsed,setElapsed]=useState(0);
  const clock=useRef(0);
  const alive=useRef<AbortController|null>(null);
  const lock=useRef(false);
  function failure(e:unknown) {
    setView(null);setGrant('');
    if(e instanceof NetworkError && e.status===503){
      if(!selected)setAvailable(false);
      else setError('Observation preview is temporarily unavailable. Retrying…');
      return;
    }
    setError(networkErrorMessage(e));
    if(e instanceof NetworkError && [401,403,404].includes(e.status)) onUnavailable(e);
  }
  useEffect(()=>{
    const c=new AbortController();alive.current=c;
    setAvailable(null);setStreams([]);setSelected('');setView(null);setGrant('');setError('');
    return ()=>{c.abort();};
  },[api,id,request.request_id]);
  useEffect(()=>{
    const c=new AbortController();
    if(api.streams) void api.streams(id,request.request_id,c.signal).then(value=>{
      if(!c.signal.aborted){setAvailable(true);setStreams(value.streams);setSelected(previous=>value.streams.some(s=>s.stream_id===previous)?previous:value.streams[0]?.stream_id||'');}
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
  if(!api.streams || available===false)return null;
  if(available===null)return <p className="lj-muted">Checking observation streaming…</p>;
  const canManage=request.allowed_transitions.length>0 && request.status==='in_progress';
  const fresh=view?.status==='connected' && (view.frame_age_seconds??Infinity)+elapsed<=6;
  const active=streams.some(s=>['waiting','connected','interrupted'].includes(s.status));
  return <section className="lj-panel" aria-label="Case live preview" style={{marginTop:20}}>
    <h3>Live observation session</h3>
    <p className="lj-muted">Sampled preview · up to 2 frames/second. Save a useful frame for coordinator review.</p>
    {request.execution_kind==='recorded_demo' && <p className="lj-notice">Recorded footage rehearsal · no live aircraft connection.</p>}
    {error && <p role="alert">{error}</p>}
    {canManage && !active && <form aria-label="Open observation stream" onSubmit={e=>{
      e.preventDefault();void action(async signal=>{
        const value=await api.openStream!(id,request.request_id,{revision:request.revision,label,rights_note:rights,source_url:source||null},signal);
        if(!signal.aborted){setGrant(value.publish_url||'');setSelected(value.stream_id);setStreams(previous=>[value,...previous]);}
      });
    }}>
      <label>Session label<input required maxLength={120} value={label} onChange={e=>setLabel(e.target.value)}/></label>
      <label>Credits and reuse terms<input required maxLength={1000} value={rights} onChange={e=>setRights(e.target.value)}/></label>
      {request.execution_kind==='recorded_demo' && <label>Recording source reference<input required type="url" value={source} onChange={e=>setSource(e.target.value)}/></label>}
      <button disabled={busy}>Open private session</button>
    </form>}
    {grant && <details><summary>Private publishing address · shown for this session only</summary>
      <p>Share only with the responsible operator. This address grants publishing access for 30 minutes; it does not grant case access.</p>
      <label>Publishing address<input readOnly type="password" value={grant} onFocus={e=>e.currentTarget.select()}/></label>
      <button type="button" className="secondary" onClick={()=>void navigator.clipboard.writeText(grant).catch(()=>setError('Select and copy the publishing address manually.'))}>Copy private address</button>
    </details>}
    {streams.length>0 && <label>Observation session<select value={selected} onChange={e=>{setView(null);setGrant('');setSelected(e.target.value);}}>
      {streams.map(s=><option key={s.stream_id} value={s.stream_id}>{s.source.label} · {s.status}</option>)}
    </select></label>}
    {view && <>
      <p role="status"><strong>{view.status==='connected'&&!fresh?'Interrupted · preview is stale':view.status.replaceAll('_',' ')}</strong> · expires {new Date(view.expires_at).toLocaleTimeString()}</p>
      {fresh && view.frame ? <img src={'data:image/jpeg;base64,'+view.frame.jpeg_base64} alt="Current sampled observation preview" style={{width:'100%',maxWidth:640,borderRadius:8}}/>:
        <p className="lj-notice">{view.status==='waiting'?'Waiting for the operator or rehearsal publisher.':'No current image. Do not interpret a frozen feed as an unchanged animal.'}</p>}
      <p className="lj-muted">Last received {view.last_frame_at?new Date(view.last_frame_at).toLocaleString():'No frames yet'}. Reception time is not camera capture time. Location is unverified.</p>
      {canManage && view.can_manage && <>
        <label>Observation to save<input maxLength={2000} value={description} onChange={e=>setDescription(e.target.value)}/></label>
        <button disabled={busy || !fresh || !view.frame || !description.trim()} onClick={()=>{
          const frame=view.frame;if(!frame)return;
          void action(async signal=>{await api.captureStream!(id,request.request_id,view.stream_id,{revision:request.revision,frame_id:frame.frame_id,description},signal);if(!signal.aborted)setDescription('');});
        }}>Save displayed frame as evidence</button>
        <button className="secondary" disabled={busy} onClick={()=>void action(async signal=>{
          await api.endStream!(id,request.request_id,view.stream_id,{revision:request.revision},signal);
          if(!signal.aborted){setGrant('');setView(null);}
        })}>End observation session</button>
      </>}
    </>}
    {selected && <DroneRecordingPanel api={api} id={id} request={request} streamId={selected} onUnavailable={onUnavailable}/>}
    <details><summary>Connect DJI Fly</summary>
      <p>The pilot connects the iPhone to the controller and confirms the camera view in DJI Fly. In the app's live streaming settings, choose RTMP and enter this session's private publishing address.</p>
      <p>The phone needs a working connection to the private receiver. Seeing video in DJI Fly alone does not connect it here. Test with the aircraft stationary and motors off first.</p>
    </details>
    <p className="lj-muted">Saved frames enter the existing evidence review. Streaming does not change severity, dispatch responders or control the drone.</p>
  </section>;
}
