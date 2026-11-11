import {useEffect,useRef,useState} from 'react';
import {type DroneApi,type DroneRequest,type FrameAnalysis,type ReminderStatus,NetworkError,networkErrorMessage} from '../lib/networkApi';

export function DroneFollowupPanel({api,id,request,canManage,selectedEvidenceId,onEvidenceSelected,onChanged,onUnavailable}:{api:DroneApi;id:string;request:DroneRequest;canManage:boolean;selectedEvidenceId?:string;onEvidenceSelected?:(id:string)=>void;onChanged:()=>Promise<void>;onUnavailable:(e:unknown)=>void}){
  const [jobs,setJobs]=useState<FrameAnalysis[]>([]);
  const [aiEnabled,setAIEnabled]=useState(false);
  const [aiLoaded,setAILoaded]=useState(false);
  const [aiWorker,setAIWorker]=useState(false);
  const [reminders,setReminders]=useState<ReminderStatus|null>(null);
  const [frame,setFrame]=useState('');
  const [detection,setDetection]=useState('');
  const [animal,setAnimal]=useState('');
  const [confirmed,setConfirmed]=useState(false);
  const [detectorFile,setDetectorFile]=useState<File|null>(null);
  const [detectorConfirmed,setDetectorConfirmed]=useState(false);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const active=useRef<AbortController|null>(null);const lock=useRef(false);
  const key=useRef(crypto.randomUUID());
  function failure(e:unknown){setError(networkErrorMessage(e));
    if(e instanceof NetworkError && [401,403,404].includes(e.status)){setJobs([]);setReminders(null);setAIEnabled(false);onUnavailable(e);}}
  async function refresh(signal:AbortSignal){
    const [analyses,delivery]=await Promise.all([
      api.frameAnalyses?.(id,request.request_id,signal).catch(e=>{if(e instanceof NetworkError && e.status===503)return null;throw e;}),
      api.reminderStatus?.(id,request.request_id,signal),
    ]);
    if(signal.aborted)return;
    setAILoaded(true);setAIEnabled(Boolean(analyses));setJobs(analyses?.jobs||[]);setAIWorker(Boolean(analyses?.worker.running));
    setReminders(delivery||null);setError('');
  }
  useEffect(()=>{
    const c=new AbortController();active.current=c;let timer:ReturnType<typeof setTimeout>;
    setJobs([]);setReminders(null);setAIEnabled(false);setAILoaded(false);setFrame('');setDetection('');setAnimal('');setConfirmed(false);setError('');
    async function poll(){try{await refresh(c.signal);}catch(e){if(!c.signal.aborted)failure(e);}
      if(!c.signal.aborted)timer=setTimeout(()=>void poll(),5000);}
    void poll();return()=>{c.abort();clearTimeout(timer);};
  },[api,id,request.request_id]);
  useEffect(()=>{
    if(selectedEvidenceId!==undefined && (!selectedEvidenceId || request.evidence?.some(e=>e.evidence_id===selectedEvidenceId))){
      setFrame(selectedEvidenceId);setDetectorFile(null);setDetectorConfirmed(false);setDetection('');setAnimal('');setConfirmed(false);
      key.current=crypto.randomUUID();
    }
  },[selectedEvidenceId]);
  async function action(fn:(s:AbortSignal)=>Promise<unknown>){
    if(lock.current || !active.current || active.current.signal.aborted)return;
    const s=active.current.signal;lock.current=true;setBusy(true);setError('');
    try{await fn(s);if(!s.aborted){setConfirmed(false);await onChanged();await refresh(s);}}
    catch(e){if(!s.aborted)failure(e);}
    finally{lock.current=false;if(!s.aborted)setBusy(false);}
  }
  const detected=jobs.find(j=>j.analysis_id===detection && j.evidence_id===frame && j.status==='completed' && j.stage==='detect');
  const canAnalyze=canManage && ['in_progress','evidence_ready'].includes(request.status);
  function queue(stage:'detect'|'assess'){
    if(!confirmed)return;
    const operationKey=key.current;
    void action(async s=>{
      await api.queueFrameAnalysis!(id,request.request_id,frame,{revision:request.revision,confirmed:true,request_key:operationKey,
        stage,...(stage==='assess'?{detection_job_id:detection,animal_index:Number(animal)}:{})},s);
      key.current=crypto.randomUUID();
    });
  }
  if(!api.frameAnalyses && !api.reminderStatus)return null;
  return <section aria-label="Observation follow-up" className="lj-panel" style={{marginTop:20}}>
    {error && <p role="alert">{error}</p>}
    {!aiEnabled && <p className="lj-muted">{api.frameAnalyses&&!aiLoaded?'Checking AI analysis availability…':'AI analysis is unavailable here. Review the original evidence manually; no AI finding has been applied.'}</p>}
    {aiEnabled && <>
      <h3>Analyze saved evidence</h3>
      <p>AI screening is advisory. A coordinator must review it before making a case decision.</p>
      {!aiWorker && <p className="lj-notice">The analysis worker is not reporting ready. Queued jobs will wait for it.</p>}
      {canAnalyze && <>
        <label>Saved frame<select value={frame} onChange={e=>{setFrame(e.target.value);setDetectorFile(null);setDetectorConfirmed(false);if(e.target.value)onEvidenceSelected?.(e.target.value);setDetection('');setAnimal('');setConfirmed(false);key.current=crypto.randomUUID();}}>
          <option value="">Choose saved evidence</option>{request.evidence?.map(e=><option key={e.evidence_id} value={e.evidence_id}>{e.description}</option>)}
        </select></label>
        <label style={{flexDirection:'row'}}><input type="checkbox" style={{minWidth:0}} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I confirm sending this saved frame for advisory AI analysis.</label>
        <button disabled={busy||!frame||!confirmed} onClick={()=>queue('detect')}>Detect animals in this frame</button>
        <label>Completed detection<select value={detection} onChange={e=>{setDetection(e.target.value);setAnimal('');setConfirmed(false);key.current=crypto.randomUUID();}}>
          <option value="">Choose a detection result</option>{jobs.filter(j=>j.stage==='detect'&&j.evidence_id===frame&&j.status==='completed').map(j=><option key={j.analysis_id} value={j.analysis_id}>{new Date(j.created_at).toLocaleString()} · {j.result?.detections?.length??0} animals detected</option>)}
        </select></label>
        {detected && <label>Animal to assess<select value={animal} onChange={e=>{setAnimal(e.target.value);setConfirmed(false);key.current=crypto.randomUUID();}}>
          <option value="">Choose the animal</option>{detected.result?.detections?.map((d,i)=><option key={i} value={i}>Animal {i+1}{d.description?' · '+d.description:(d.label?' · '+d.label:'')}</option>)}
        </select></label>}
        <button disabled={busy||!confirmed||!detected||animal===''} onClick={()=>queue('assess')}>Assess selected animal</button>
      </>}
      {canAnalyze && api.attachDetectorResult && <details>
        <summary>Use teammate detector results</summary>
        <p>Choose a saved frame above. Export its input metadata and use the exact original image. Import the detector JSON for that frame; this does not call Gemini.</p>
        <button type="button" disabled={busy||!frame||!api.detectorInput} onClick={()=>void action(async signal=>{
          const input=await api.detectorInput!(id,request.request_id,frame,signal);
          if(signal.aborted)return;
          const url=URL.createObjectURL(new Blob([JSON.stringify(input,null,2)],{type:'application/json'}));
          const link=document.createElement('a');link.href=url;link.download='detector-input-'+frame+'.json';link.click();
          setTimeout(()=>URL.revokeObjectURL(url),1000);
        })}>Export selected frame metadata</button>
        <button type="button" disabled={busy||!frame} onClick={()=>void action(async signal=>{
          const image=await api.photo(id,request.request_id,frame,signal);
          if(signal.aborted)return;
          const url=URL.createObjectURL(image);const link=document.createElement('a');
          link.href=url;link.download='evidence-'+frame+(image.type==='image/png'?'.png':image.type==='image/webp'?'.webp':'.jpg');link.click();
          setTimeout(()=>URL.revokeObjectURL(url),1000);
        })}>Download selected original image</button>
        <label>Detector result JSON<input type="file" accept="application/json,.json" onChange={e=>{setDetectorFile(e.target.files?.[0]||null);setDetectorConfirmed(false);}}/></label>
        <label style={{flexDirection:'row'}}><input type="checkbox" style={{minWidth:0}} checked={detectorConfirmed} onChange={e=>setDetectorConfirmed(e.target.checked)}/>I confirm this detector output belongs to the selected original frame.</label>
        <button type="button" disabled={busy||!frame||!detectorFile||!detectorConfirmed} onClick={()=>{
          const file=detectorFile;if(!file)return;
          const operationKey=key.current;
          void action(async signal=>{
            if(file.size>128*1024)throw new Error('Detector JSON must be under 128 KiB.');
            const result:unknown=JSON.parse(await file.text());
            if(signal.aborted)return;
            await api.attachDetectorResult!(id,request.request_id,frame,{revision:request.revision,confirmed:true,request_key:operationKey,result},signal);
            key.current=crypto.randomUUID();setDetectorFile(null);setDetectorConfirmed(false);
          });
        }}>Attach detector results</button>
      </details>}
      {!request.evidence?.length && <p className="lj-muted">Save a frame before requesting analysis.</p>}
      {jobs.map(j=><article className="lj-panel" key={j.analysis_id}>
        <h4>{j.provider==='external_detector'?'Imported detector result':j.stage==='detect'?'Animal detection':'AI advisory finding'} · {j.status}</h4>
        <p className="lj-muted">{request.evidence?.find(e=>e.evidence_id===j.evidence_id)?.description||'Saved case evidence'} · {new Date(j.created_at).toLocaleString()}</p>
        {j.result?.model && <p className="lj-muted">{j.result.model}{j.result.model_version?' · '+j.result.model_version:''}</p>}
        {j.provider==='external_detector' && j.status==='failed' && <p>Detector processing failed. Rerun it and attach a new result; this is not evidence that no animal was present.</p>}
        {j.error_code && <p>{j.error_code.replaceAll('_',' ')}. No case finding was applied.</p>}
        {j.stage==='detect'&&j.status==='completed' && <p>{j.result?.detections?.length?j.result.detections.length+' possible animals detected. Choose the intended animal before assessment.':'No animal was detected. This does not establish absence; review the frame manually.'}</p>}
        {j.result?.identity_summary && <p>{j.result.identity_summary.name} · identification confidence {typeof j.result.identity_summary.confidence==='number'?Math.round(j.result.identity_summary.confidence*100)+'%':'unknown'}</p>}
        {j.result?.assessment?.injury?.summary && <p>{j.result.assessment.injury.summary}</p>}
        {j.result?.assessment?.severity_level && <p>Advisory severity: {j.result.assessment.severity_level}. Confirm through evidence review.</p>}
        {j.result?.limitations && <details><summary>Evidence limits</summary><ul>{j.result.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul></details>}
        {canAnalyze && j.status==='failed' && j.provider!=='external_detector' && <button className="secondary" disabled={busy} onClick={()=>void action(s=>api.queueFrameAnalysis!(id,request.request_id,j.evidence_id,
          {revision:request.revision,confirmed:true,request_key:j.request_key,stage:j.stage,detection_job_id:j.detection_job_id,animal_index:j.animal_index},s))}>Retry failed analysis</button>}
      </article>)}
    </>}
    {reminders && <>
      <h3>Background monitoring reminders</h3>
      {!reminders.enabled?<p>Background delivery is disabled.</p>:<>
        {!reminders.destination_configured && <p className="lj-notice">The lead organization delivery destination is not configured. Alerts are not being sent.</p>}
        {!reminders.worker.running && <p className="lj-notice">The reminder worker is not reporting ready. Alerts may be delayed.</p>}
        <p className="lj-muted">Delivery continues independently of this page while the background worker is running. Delivered means accepted by the destination, not read or acknowledged.</p>
      </>}
      {reminders.items.map(item=><p key={item.notification_id}>{item.kind} · <strong>{item.status}</strong> · {item.attempts} delivery attempts
        {canManage&&item.status==='failed'&&<button disabled={busy} className="secondary" onClick={()=>void action(s=>api.retryReminder!(id,request.request_id,{revision:request.revision,confirmed:true,notification_id:item.notification_id},s))}>Retry reminder</button>}
      </p>)}
    </>}
  </section>;
}
