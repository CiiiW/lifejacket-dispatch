import {useEffect,useRef,useState} from 'react';
import {type DroneApi,type AttentionItem,networkErrorMessage} from '../lib/networkApi';

export function CoordinatorAttention({api,revision=0,onOpen,onChange}:{
 api:DroneApi;revision?:number;onOpen:(caseId:string,requestId:string)=>void;onChange:()=>void;
}) {
 const [items,setItems]=useState<AttentionItem[]>([]);
 const [total,setTotal]=useState(0);
 const [offset,setOffset]=useState(0);
 const [refresh,setRefresh]=useState(0);
 const [notes,setNotes]=useState<Record<string,string>>({});
 const [confirmed,setConfirmed]=useState<Record<string,boolean>>({});
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const [loading,setLoading]=useState(true);
 const controller=useRef<AbortController|null>(null);
 const lock=useRef(false);
 useEffect(()=>{
   if(!api.attention)return;
   const c=new AbortController();controller.current=c;
   setLoading(true);setItems([]);setError('');
   void api.attention(offset,c.signal).then(data=>{
     if(!c.signal.aborted){setItems(data.items);setTotal(data.total);}
   }).catch(e=>{if(!c.signal.aborted){setItems([]);setTotal(0);setError(networkErrorMessage(e));}})
     .finally(()=>{if(!c.signal.aborted)setLoading(false);});
   const timer=window.setInterval(()=>{if(!lock.current)setRefresh(v=>v+1);},30000);
   return ()=>{c.abort();clearInterval(timer);};
 },[api,offset,refresh,revision]);
 if(!api.attention)return null;
 return <section className="lj-panel" aria-label="Coordinator attention">
   <h2>Coordinator attention <span className="lj-pill">{total}</span></h2>
   <p className="lj-muted">Escalations and overdue review reminders remain here until acknowledged by the active lead coordinator. Checked every 30 seconds while this workspace is open.</p>
   {error&&<p role="alert" className="lj-error">{error}</p>}
   {loading&&<p role="status">Checking attention items…</p>}
   {!loading&&!error&&!items.length&&<p>No unacknowledged attention items on this page.</p>}
   <button className="secondary" disabled={busy} onClick={()=>setRefresh(v=>v+1)}>Refresh attention</button>
   {items.map(item=><article className="lj-panel" key={item.attention_key} style={{marginTop:16}}>
     <h3>{item.kind==='escalation'?'Escalation needs attention':'Overdue review reminder'}</h3>
     <p>{item.objective}</p><p>{item.reason}</p>
     <p className="lj-id">Case {item.case_id} · {item.execution_kind.replaceAll('_',' ')} · {item.since?new Date(item.since).toLocaleString():'Time unknown'}</p>
     <button className="secondary" disabled={busy} onClick={()=>onOpen(item.case_id,item.request_id)}>Open case observation</button>
     {item.can_acknowledge&&api.acknowledgeAttention&&<form aria-label={'Acknowledge '+item.kind} onSubmit={e=>{
       e.preventDefault();
       if(lock.current||!confirmed[item.attention_key]||!controller.current)return;
       lock.current=true;setBusy(true);setError('');
       const signal=controller.current.signal;
       void api.acknowledgeAttention!(item.case_id,item.request_id,{
         revision:item.revision,kind:item.kind,attention_key:item.attention_key,
         confirmed:true,note:notes[item.attention_key],
       },signal).then(()=>{
         if(!signal.aborted){setBusy(false);lock.current=false;setConfirmed({});setNotes({});setRefresh(v=>v+1);onChange();}
       }).catch(e=>{if(!signal.aborted){setError(networkErrorMessage(e));setItems([]);setTotal(0);}})
         .finally(()=>{lock.current=false;if(!signal.aborted)setBusy(false);});
     }}>
       <label>Acknowledgment note<input required maxLength={2000} value={notes[item.attention_key]||''} onChange={e=>setNotes(v=>({...v,[item.attention_key]:e.target.value}))}/></label>
       <label style={{flexDirection:'row'}}><input type="checkbox" style={{minWidth:0}} checked={confirmed[item.attention_key]||false} onChange={e=>setConfirmed(v=>({...v,[item.attention_key]:e.target.checked}))}/>I have reviewed this attention item.</label>
       <button disabled={busy||!confirmed[item.attention_key]||!notes[item.attention_key]?.trim()}>Acknowledge attention</button>
     </form>}
   </article>)}
   <p className="lj-muted">Acknowledging records receipt. It does not resolve the case, approve a flight, or change the monitoring schedule.</p>
   <nav className="lj-pagination" aria-label="Attention pages">
     <button className="secondary" disabled={busy||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-50))}>Previous attention</button>
     <button className="secondary" disabled={busy||offset+50>=total} onClick={()=>setOffset(v=>v+50)}>Next attention</button>
   </nav>
 </section>;
}
