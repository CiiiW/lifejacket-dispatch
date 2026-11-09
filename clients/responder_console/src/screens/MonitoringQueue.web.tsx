import {useEffect,useState} from 'react';
import {type DroneApi,type MonitoringItem,networkErrorMessage} from '../lib/networkApi';

export function MonitoringQueue({api,onOpen,revision=0}:{api:DroneApi;onOpen:(caseId:string,requestId:string)=>void;revision?:number}) {
  const [items,setItems]=useState<MonitoringItem[]>([]);
  const [offset,setOffset]=useState(0);
  const [total,setTotal]=useState(0);
  const [refresh,setRefresh]=useState(0);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    if (!api.monitoringQueue) return;
    const c=new AbortController();
    setBusy(true);setItems([]);setError('');
    void api.monitoringQueue(offset,c.signal).then(data=>{
      if (!c.signal.aborted) {setItems(data.items);setTotal(data.total);}
    }).catch(e=>{if(!c.signal.aborted){setItems([]);setTotal(0);setError(networkErrorMessage(e));}})
      .finally(()=>{if(!c.signal.aborted)setBusy(false);});
    const timer=window.setInterval(()=>setRefresh(v=>v+1),30000);
    return ()=>{c.abort();clearInterval(timer);};
  },[api,offset,refresh,revision]);
  if (!api.monitoringQueue) return null;
  return <section className="lj-panel" aria-label="Monitoring queue">
    <h2>Monitoring follow-ups</h2>
    <p className="lj-muted">Participating cases · due soon means within 24 hours. Review times are set by the coordinator.</p>
    {error && <p role="alert" className="lj-error">{error}</p>}
    <button className="secondary" disabled={busy} onClick={()=>setRefresh(v=>v+1)}>Refresh monitoring</button>
    {busy && <p role="status">Loading monitoring…</p>}
    {!busy && !error && !items.length && <p>No monitoring follow-ups on this page.</p>}
    {items.map(item=><button className="lj-case" key={item.request_id} onClick={()=>onOpen(item.case_id,item.request_id)} style={{marginTop:12}}>
      <strong>{item.queue_status.replaceAll('_',' ')} · {item.objective}</strong>
      <span className="lj-meta">Case {item.case_id} · {item.execution_kind.replaceAll('_',' ')} · {item.request_status.replaceAll('_',' ')}</span>
      <span className="lj-meta">{item.next_review_at?new Date(item.next_review_at).toLocaleString():'Review time needed'}</span>
    </button>)}
    <nav className="lj-pagination" aria-label="Monitoring pages">
      <button className="secondary" disabled={busy||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-50))}>Previous monitoring</button>
      <span>{total} follow-ups</span>
      <button className="secondary" disabled={busy||offset+50>=total} onClick={()=>setOffset(v=>v+50)}>Next monitoring</button>
    </nav>
  </section>;
}
