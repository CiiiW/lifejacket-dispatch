import {useEffect,useRef,useState} from 'react';
import {type DroneApi,type DroneRequest,type ObservationComparison as Comparison,networkErrorMessage} from '../lib/networkApi';

export function ObservationComparison({api,id,request,rows}:{
 api:DroneApi;id:string;request:DroneRequest;rows:DroneRequest[];
}) {
 const [previous,setPrevious]=useState(request.previous_request_id||'');
 const [data,setData]=useState<Comparison|null>(null);
 const [images,setImages]=useState<Record<string,string>>({});
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 const urls=useRef<string[]>([]);
 const controller=useRef<AbortController|null>(null);
 useEffect(()=>{
   if(!api.comparison)return;
   const c=new AbortController();controller.current=c;
   urls.current.forEach(URL.revokeObjectURL);urls.current=[];setImages({});setData(null);setError('');setLoading(true);
   void api.comparison(id,request.request_id,previous||undefined,c.signal).then(value=>{
     if(!c.signal.aborted)setData(value);
   }).catch(e=>{if(!c.signal.aborted)setError(networkErrorMessage(e));})
     .finally(()=>{if(!c.signal.aborted)setLoading(false);});
   return ()=>{c.abort();urls.current.forEach(URL.revokeObjectURL);urls.current=[];};
 },[api,id,request.request_id,request.revision,previous]);
 if(!api.comparison)return null;
 const observation=(row:DroneRequest|null,title:string)=><section className="lj-panel">
   <h4>{title}</h4>
   {row?<><p>{row.objective}</p><p>{row.execution_kind.replaceAll('_',' ')} · {row.status.replaceAll('_',' ')}</p>
   <p>{row.review_note||'No reviewed finding recorded.'}</p>
   <p className="lj-id">Request {row.request_id}</p>
   {!row.evidence?.length&&<p>No image evidence attached.</p>}
   {row.evidence?.map(e=><article key={e.evidence_id}>
     <p>{e.description}</p><p className="lj-muted">Capture: {e.captured_at?new Date(e.captured_at).toLocaleString():'unknown'} · {e.source_kind.replaceAll('_',' ')} · {e.rights_note}</p>
     <button type="button" className="secondary" onClick={()=>{
       const signal=controller.current?.signal;if(!signal||signal.aborted)return;
       void api.photo(id,row.request_id,e.evidence_id,signal).then(blob=>{
         if(!signal.aborted){const url=URL.createObjectURL(blob);urls.current.push(url);setImages(v=>({...v,[e.evidence_id]:url}));}
       }).catch(err=>{if(!signal.aborted)setError(networkErrorMessage(err));});
     }}>Load comparison image</button>
     {images[e.evidence_id]&&<img alt={title+' evidence: '+e.description} src={images[e.evidence_id]} style={{maxWidth:'100%',marginTop:12}}/>}
   </article>)}</>:<p>No earlier observation selected.</p>}
 </section>;
 return <section aria-label="Observation comparison" style={{marginTop:24}}>
   <h3>Compare observations</h3>
   <label>Earlier observation<select value={previous} onChange={e=>setPrevious(e.target.value)}>
     <option value="">Linked previous observation, if available</option>
     {request.previous_request_id&&!rows.some(r=>r.request_id===request.previous_request_id)&&<option value={request.previous_request_id}>Linked previous request</option>}
     {rows.filter(r=>r.request_id!==request.request_id).map(r=><option key={r.request_id} value={r.request_id}>{r.objective} · {r.status.replaceAll('_',' ')}</option>)}
   </select></label>
   {error&&<p role="alert" className="lj-error">{error}</p>}
   {loading&&<p role="status">Loading comparison…</p>}
   {data&&<>
     <h4>Stored intake assessment</h4>
     <p>{data.intake.species_common_name||data.intake.animal_group||'Animal unidentified'} · severity {data.intake.severity_level||'unknown'} · injury {data.intake.injury_present===null?'unknown':data.intake.injury_present?'reported':'not reported'} · entanglement {data.intake.entanglement_present===null?'unknown':data.intake.entanglement_present?'reported':'not reported'}</p>
     <div className="lj-grid">{observation(data.previous,'Earlier observation')}{observation(data.current,'Current observation')}</div>
   </>}
   <p className="lj-muted">Compare capture times and sources before judging changes. Recorded samples are demonstration evidence. This view makes no automatic worsening or recovery assessment. Intake shows the current stored assessment; it is not a historical snapshot or the reporter transcript.</p>
 </section>;
}
