import { useEffect, useRef, useState } from 'react';
import { type DroneApi, type DroneRecording, type DroneRequest, type RecordingSegment, NetworkError, networkErrorMessage } from '../lib/networkApi';

export function DroneRecordingPanel({api,id,request,streamId,onUnavailable}:{api:DroneApi;id:string;request:DroneRequest;streamId:string;onUnavailable:(e:unknown)=>void}) {
  const [recordings,setRecordings]=useState<DroneRecording[]>([]);
  const [enabled,setEnabled]=useState(false);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const [media,setMedia]=useState<{url:string;title:string;seek:number}|null>(null);
  const mediaUrl=useRef('');
  const pending=useRef<AbortController|null>(null);
  const player=useRef<HTMLVideoElement|null>(null);
  function clearMedia(){
    if(mediaUrl.current)URL.revokeObjectURL(mediaUrl.current);
    mediaUrl.current='';setMedia(null);setLoading(false);
  }
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    setRecordings([]);setEnabled(false);setError('');clearMedia();
    async function poll(){
      try {
        const value=await api.recordings!(id,request.request_id,streamId,controller.signal);
        if(controller.signal.aborted)return;
        setRecordings(value.recordings);setEnabled(value.enabled);setError('');
      }catch(e){
        if(controller.signal.aborted)return;
        pending.current?.abort();clearMedia();setRecordings([]);
        setError(networkErrorMessage(e));
        if(e instanceof NetworkError && [401,403,404].includes(e.status)){
          onUnavailable(e);return;
        }
      }
      if(!controller.signal.aborted)timer=setTimeout(()=>void poll(),3000);
    }
    if(api.recordings)void poll();
    return ()=>{controller.abort();clearTimeout(timer);pending.current?.abort();clearMedia();};
  },[api,id,request.request_id,streamId]);
  async function play(recording:DroneRecording,segment:RecordingSegment,seek=0){
    if(!api.recordingVideo)return;
    pending.current?.abort();const controller=new AbortController();pending.current=controller;
    clearMedia();setLoading(true);setError('');
    try{
      const blob=await api.recordingVideo(id,request.request_id,streamId,recording.recording_id,segment.segment_id,controller.signal);
      if(controller.signal.aborted)return;
      const url=URL.createObjectURL(blob);mediaUrl.current=url;
      setMedia({url,title:`Recording ${new Date(recording.started_at).toLocaleTimeString()} · ${segment.offset_seconds.toFixed(0)}s`,seek});
    }catch(e){
      if(controller.signal.aborted)return;
      setError(networkErrorMessage(e));
      if(e instanceof NetworkError && [401,403,404].includes(e.status))onUnavailable(e);
    }finally{if(!controller.signal.aborted)setLoading(false);}
  }
  if(!api.recordings)return null;
  const evidence=(request.evidence||[]).filter(e=>e.source_session_id===streamId && e.received_at);
  return <section aria-label="Received video recordings" style={{marginTop:24}}>
    <h3>Received recordings</h3>
    <p className="lj-muted">{enabled?'Recording is enabled for this receiver.':'New recording is not enabled on this receiver.'} Live preview and recording are separate; check the status below.</p>
    <p className="lj-muted">Private video segments preserve the received stream, without AI overlays or audio. They may have connection gaps. Keep the aircraft original separately.</p>
    {error && <p role="alert">{error}</p>}
    {!recordings.length && <p className="lj-notice">No recording received yet. The receiver must be running and recording enabled before footage appears here.</p>}
    {recordings.map(recording=><div key={recording.recording_id} className="lj-panel">
      <p><strong>{recording.status.replaceAll('_',' ')}</strong> · started {new Date(recording.started_at).toLocaleString()} · {recording.segments.length} playable segment(s)</p>
      {recording.error_code && <p role="status">Recording needs attention: {recording.error_code==='storage_limit'?'Session storage limit reached; preview may continue.':recording.error_code==='receiver_restarted'?'Receiver restarted; a recording gap may exist.':'Recording interrupted or unavailable. Check the receiver.'}</p>}
      {recording.segments.map(segment=><button key={segment.segment_id} type="button" className="secondary" disabled={loading} onClick={()=>void play(recording,segment)}>
        Play {segment.offset_seconds.toFixed(0)}–{(segment.offset_seconds+segment.duration_seconds).toFixed(0)}s
      </button>)}
    </div>)}
    {loading && <p role="status">Loading private recording…</p>}
    {media && <div><h4>{media.title}</h4><video key={media.url} ref={player} src={media.url} controls preload="metadata" style={{width:'100%',maxWidth:760,borderRadius:8}} onLoadedMetadata={()=>{if(player.current)player.current.currentTime=Math.max(0,Math.min(media.seek,player.current.duration||0));}} onError={()=>setError('This recording cannot be played in this browser. The stream codec may be unsupported.')}/></div>}
    {!!evidence.length && <><h4>Saved evidence moments</h4><p className="lj-muted">Approximate links based on server reception time; buffering can shift the video moment. The saved photo remains the exact selected evidence.</p>{evidence.map(e=>{
      const timestamp=Date.parse(e.received_at!);
      let match:{recording:DroneRecording;segment:RecordingSegment;seek:number}|undefined;
      for(const recording of recordings){
        const offset=(timestamp-Date.parse(recording.started_at))/1000;
        const segment=recording.segments.find(s=>offset>=s.offset_seconds && offset<s.offset_seconds+s.duration_seconds);
        if(segment)match={recording,segment,seek:offset-segment.offset_seconds};
      }
      const target=match;
      return <p key={e.evidence_id}>{e.description} · {new Date(timestamp).toLocaleTimeString()} {target?<button type="button" disabled={loading} onClick={()=>void play(target.recording,target.segment,target.seek)}>Open nearby video</button>:<span className="lj-muted">No corresponding playable segment yet</span>}</p>;
    })}</>}
    <p className="lj-muted">Times are relative to each received recording. Camera capture time and animal location remain unverified. Recordings do not change case urgency or dispatch anyone.</p>
  </section>;
}
