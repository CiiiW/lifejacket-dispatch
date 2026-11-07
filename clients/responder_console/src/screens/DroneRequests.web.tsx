import { DroneStreamPanel } from './DroneStreamPanel.web';
import { ObservationComparison } from './ObservationComparison.web';
import { useEffect, useRef, useState } from 'react';
import { type DroneApi, type DroneRequest, type DroneSuggestion, networkErrorMessage } from '../lib/networkApi';

const label = (s: string) => s.replaceAll('_', ' ');
const confidenceText = (value: number | null) => value === null ? 'Unknown' : Number((value*100).toFixed(2))+'%';
export function DroneRequests({ api, id, initialRequestId, onMonitoringChange }: { api: DroneApi; id: string; initialRequestId?:string; onMonitoringChange?:()=>void }) {
  const [rows, setRows] = useState<DroneRequest[]>([]);
  const [confidence, setConfidence] = useState<{animal_group:number|null;condition:number|null}|null>(null);
  const [suggestions, setSuggestions] = useState<DroneSuggestion[]>([]);
  const [suggestionId, setSuggestionId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [canCreate, setCanCreate] = useState(false);
  const [selected, setSelected] = useState<DroneRequest | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [monitoringAction, setMonitoringAction] = useState('continue');
  const [monitoringReason, setMonitoringReason] = useState('');
  const [monitoringTime, setMonitoringTime] = useState('');
  const [monitoringConfirmed, setMonitoringConfirmed] = useState(false);
  const [purpose, setPurpose] = useState('verification');
  const [mode, setMode] = useState('recorded_demo');
  const [objective, setObjective] = useState('');
  const [reason, setReason] = useState('');
  const [escalation, setEscalation] = useState('');
  const [reviewTime, setReviewTime] = useState('');
  const [followUp, setFollowUp] = useState('');
  const [target, setTarget] = useState('');
  const [note, setNote] = useState('');
  const [operator, setOperator] = useState('');
  const [outcome, setOutcome] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState('');
  const [rights, setRights] = useState('');
  const [capture, setCapture] = useState('');
  const [offset, setOffset] = useState('');
  const [image, setImage] = useState('');
  const controller = useRef<AbortController | null>(null);
  const lock = useRef(false);
  const key = useRef(crypto.randomUUID());
  const preview = useRef('');
  async function load(signal: AbortSignal, requestId?: string) {
    const list = await api.list(id, signal);
    const detail = requestId ? await api.detail(id, requestId, signal) : null;
    if (!signal.aborted) {
      setRows(list.requests); setConfidence(list.confidence_summary ?? null); setSuggestions(list.suggestions ?? []); setCanCreate(list.can_create); setSelected(detail);
      setTarget(''); setNote(''); setOutcome(''); setConfirmed(false); setMonitoringReason(''); setMonitoringTime(''); setMonitoringConfirmed(false);
    }
  }
  useEffect(() => {
    const c = new AbortController(); controller.current = c;
    setRows([]); setConfidence(null); setSuggestions([]); setSelected(null); setCanCreate(false);
    void load(c.signal, initialRequestId).catch(e => { if (!c.signal.aborted) setError(networkErrorMessage(e)); });
    return () => { c.abort(); if (preview.current) URL.revokeObjectURL(preview.current); };
  }, [api, id, initialRequestId]);
  async function act(fn: (signal: AbortSignal) => Promise<string | void>) {
    if (lock.current || !controller.current || controller.current.signal.aborted) return;
    lock.current = true; setBusy(true); setError('');
    const signal = controller.current.signal;
    try {
      const requestId = await fn(signal);
      await load(signal, requestId || selected?.request_id);
      if (!signal.aborted) onMonitoringChange?.();
    } catch (e) {
      if (!signal.aborted) {
        setError(networkErrorMessage(e)); setCanCreate(false); setRows([]); setConfidence(null); setSuggestions([]); setSelected(null);
        if (preview.current) URL.revokeObjectURL(preview.current);
        preview.current = ''; setImage('');
      }
    } finally { lock.current = false; if (!signal.aborted) setBusy(false); }
  }
  return <section aria-label="Case drone requests" style={{borderTop:'1px solid #ffffff25', marginTop:24,paddingTop:24}}>
    <h2>Drone observation requests</h2>
    <p className="lj-muted">Collect evidence for this case: clarify an uncertainty or monitor a change.</p>
    {error && <p role="alert" className="lj-error">{error}</p>}
    <button className="secondary" disabled={busy} onClick={() => void act(async () => undefined)}>Refresh drone requests</button>
    {confidence && <p className="lj-muted">Confidence: animal group {confidenceText(confidence.animal_group)} · condition {confidenceText(confidence.condition)}</p>}
    {suggestions.map(s=><aside className="lj-panel" key={s.suggestion_id} aria-label="Automatic drone request suggestion" style={{marginTop:16}}>
      <div className="lj-eyebrow">Suggested from current intake</div><h3>{s.title}</h3>
      <p>{s.reason}</p>
      <ul>{s.signals.map(signal=><li key={signal.code}>{signal.label}: <strong>{signal.code==='photo_evidence_gap'?'Additional view requested':confidenceText(signal.confidence)}</strong>{signal.confidence !== null && <> · below {Number((s.threshold*100).toFixed(2))}%</>}</li>)}</ul>
      <p className={s.urgent_parallel_review?'lj-notice lj-error':'lj-muted'}>{s.response_note}</p>
      <p className="lj-muted">{s.signals.some(signal=>signal.code==='photo_evidence_gap')
      ?'The intake requested another photo. Review this evidence gap even when confidence is high.'
      :'Provisional threshold. Check whether an additional view would help.'}</p>
      {canCreate && <button disabled={busy} onClick={()=>{
        setPurpose('verification');setSuggestionId(s.suggestion_id);setObjective(s.objective);
        setReason(s.reason);setEscalation(s.escalation_criteria);setCreateOpen(true);
        key.current=crypto.randomUUID();
      }}>Review suggested request</button>}
    </aside>)}
    {canCreate && <details open={createOpen} onToggle={e=>setCreateOpen(e.currentTarget.open)} style={{marginTop:16}}><summary>Create observation request</summary>
      <form aria-label="Create drone request" onSubmit={e => {
        e.preventDefault();
        void act(async signal => {
          const row = await api.create(id, {purpose, objective, reason, execution_kind:mode,
            escalation_criteria:escalation, request_key:key.current, suggestion_id:suggestionId,
            next_review_at:reviewTime ? new Date(reviewTime).toISOString() : null}, signal);
          key.current = crypto.randomUUID();setSuggestionId(null);setCreateOpen(false); setObjective(''); setReason(''); setEscalation('');
          return row.request_id;
        });
      }}>
        <label>Purpose<select disabled={Boolean(suggestionId)} value={purpose} onChange={e=>setPurpose(e.target.value)}>
          <option value="verification">Verification</option><option value="monitoring">Monitoring</option>
        </select></label>
        <label>Evidence collection<select value={mode} onChange={e=>setMode(e.target.value)}>
          <option value="recorded_demo">Recorded footage demo</option><option value="operator_flight">Operator flight · Mini 2</option>
        </select></label>
        {suggestionId && <p className="lj-notice">Review and edit this draft before creating the request. <button type="button" className="secondary" onClick={()=>setSuggestionId(null)}>Use as manual request instead</button></p>}
        {mode==='recorded_demo' && <p className="lj-muted">Sample-footage demos do not resolve operational suggestions.</p>}
        <label>Question to answer<input required maxLength={1000} value={objective} onChange={e=>setObjective(e.target.value)}/></label>
        <label>Why more evidence is needed<input required maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label>
        <label>Escalate if<input required maxLength={1000} value={escalation} onChange={e=>setEscalation(e.target.value)}/></label>
        <label>Next review · your local time<input type="datetime-local" required={purpose==='monitoring'} value={reviewTime} onChange={e=>setReviewTime(e.target.value)} onInput={e=>setReviewTime(e.currentTarget.value)}/></label>
        <button disabled={busy || !objective.trim() || !reason.trim() || !escalation.trim() || (purpose==='monitoring' && !reviewTime)}>Create request</button>
      </form>
    </details>}
    {!rows.length && !error && <p className="lj-muted">No observation requests yet.</p>}
    <div className="lj-cases" style={{marginTop:16}}>
      {rows.map(row=><button key={row.request_id} className="lj-case" aria-pressed={selected?.request_id===row.request_id}
        disabled={busy} onClick={()=>{setImage(''); if(preview.current)URL.revokeObjectURL(preview.current);preview.current='';void act(async () => row.request_id);}}>
        <strong>{row.objective}</strong><span className="lj-meta">{label(row.purpose)} · {label(row.status)} · {label(row.execution_kind)}</span>
      </button>)}
    </div>
    {selected && <article style={{marginTop:20}}>
      <span className="lj-pill">{label(selected.status)}</span>
      <h3>{selected.objective}</h3><p>{selected.reason}</p>
      {selected.execution_kind==='recorded_demo' && <p className="lj-notice">Demonstration using recorded sample footage. No requested flight is claimed.</p>}
      <dl><dt>Operator</dt><dd>{selected.operator || 'Unassigned'}</dd>
        <dt>Escalate if</dt><dd>{selected.escalation_criteria}</dd>
        <dt>Next review</dt><dd>{selected.next_review_at ? new Date(selected.next_review_at).toLocaleString() : 'Not scheduled'}</dd>
        <dt>Reported location</dt><dd>{selected.target_location.latitude ?? 'Unknown'}, {selected.target_location.longitude ?? 'Unknown'}</dd>
      </dl>
      {selected.allowed_transitions.length>0 && <form aria-label="Update drone request" onSubmit={e=>{
        e.preventDefault(); if (!confirmed) return;
        void act(async signal => {
          await api.change(id, selected.request_id, {revision:selected.revision, status:target, confirmed:true,
            note, ...(target==='approved'?{operator}:{}),
            feasibility_confirmed:target==='in_progress' && selected.execution_kind==='operator_flight',
            ...(target==='reviewed'?{outcome,next_review_at:followUp?new Date(followUp).toISOString():null}: {})}, signal);
          return selected.request_id;
        });
      }}>
        <label>Next step<select required value={target} onChange={e=>{setTarget(e.target.value);setConfirmed(false);}}>
          <option value="">Choose a step</option>{selected.allowed_transitions.map(t=><option key={t} value={t}>{label(t)}</option>)}
        </select></label>
        {target==='approved' && <label>Responsible operator<input required value={operator} maxLength={120} onChange={e=>setOperator(e.target.value)}/></label>}
        {target==='reviewed' && <label>Evidence outcome<select required value={outcome} onChange={e=>setOutcome(e.target.value)}>
          <option value="">Choose outcome</option><option value="answered">Question answered</option>
          <option value="still_uncertain">Still uncertain</option><option value="escalation_needed">Escalation needed</option>
        </select></label>}
        {target==='reviewed' && <label>Next observation review · your local time<input type="datetime-local" value={followUp} onChange={e=>setFollowUp(e.target.value)} onInput={e=>setFollowUp(e.currentTarget.value)}/></label>}
        <label>{target==='reviewed'?'Reassessment finding':'Update note'}<input required value={note} maxLength={2000} onChange={e=>setNote(e.target.value)}/></label>
        <label style={{flexDirection:'row'}}><input type="checkbox" style={{minWidth:0}} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
          {target==='in_progress' && selected.execution_kind==='operator_flight' ? 'Operator confirmed site permission, weather, range and battery feasibility.' :
            target==='reviewed' ? 'I reviewed the evidence and confirm this finding.' : 'I confirm this request update.'}
        </label>
        <button disabled={busy || !target || !confirmed || !note.trim()}>Record update</button>
      </form>}
      {selected.status==='in_progress' && canCreate && <form aria-label="Attach drone evidence" onSubmit={e=>{
        e.preventDefault(); if (!file) return;
        void act(async signal=>{
          const data=new FormData();
          data.set('metadata',JSON.stringify({revision:selected.revision,
            source_kind:selected.execution_kind==='recorded_demo'?'sample_footage':'operator_capture',
            source_url:source||null, rights_note:rights, description:note,
            captured_at:capture?new Date(capture).toISOString():null,
            frame_offset_seconds:offset?Number(offset):null}));
          data.set('photo',file);
          await api.upload(id,selected.request_id,data,signal); setFile(null);
          return selected.request_id;
        });
      }}>
        <h3>Attach a photo or extracted video frame</h3>
        <label>Image<input required type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>setFile(e.target.files?.[0]||null)}/></label>
        <label>Source URL<input type="url" required={selected.execution_kind==='recorded_demo'} value={source} onChange={e=>setSource(e.target.value)}/></label>
        <label>Credits and reuse terms<input required value={rights} onChange={e=>setRights(e.target.value)}/></label>
        <label>Evidence description<input required value={note} onChange={e=>setNote(e.target.value)}/></label>
        <label>Actual capture time · leave unknown if unavailable<input type="datetime-local" required={selected.execution_kind==='operator_flight'} value={capture} onChange={e=>setCapture(e.target.value)} onInput={e=>setCapture(e.currentTarget.value)}/></label>
        <label>Video offset · seconds<input type="number" min="0" step="any" value={offset} onChange={e=>setOffset(e.target.value)}/></label>
        <button disabled={busy || !file || !note.trim() || !rights.trim()}>Attach evidence</button>
      </form>}
      {!!selected.evidence?.length && <><h3>Case evidence</h3>{selected.evidence.map(e=><div key={e.evidence_id} className="lj-panel">
        <p>{e.description}</p><small>{label(e.source_kind)} · capture time {e.captured_at || 'unknown'} · offset {e.frame_offset_seconds ?? 'unknown'}</small>
        {e.received_at && <p className="lj-muted">Saved from an observation stream · received {new Date(e.received_at).toLocaleString()}. Camera capture time remains unknown.</p>}
        <p>{e.rights_note}</p>{e.source_url && <a href={e.source_url} target="_blank" rel="noreferrer" style={{color:'#48cae4'}}>Source</a>}
        <button className="secondary" disabled={busy} onClick={()=>void act(async signal=>{
          const blob=await api.photo(id,selected.request_id,e.evidence_id,signal);
          if (!signal.aborted) {if(preview.current)URL.revokeObjectURL(preview.current);
            preview.current=URL.createObjectURL(blob);setImage(preview.current);}
          return selected.request_id;
        })}>View evidence</button>
      </div>)}</>}
      {image && <img src={image} alt="Selected request evidence" style={{maxWidth:'100%',borderRadius:8}}/>}
      {selected.outcome && <p className="lj-notice"><strong>{label(selected.outcome)}</strong>: {selected.review_note}</p>}
      {selected.previous_request_id && <p className="lj-id">Follow-up of {selected.previous_request_id}</p>}
      {selected.monitoring_decision && <p className="lj-notice">Monitoring decision: {label(selected.monitoring_decision.action)} · {selected.monitoring_decision.reason}
        {selected.monitoring_decision.next_request_id && <button className="secondary" disabled={busy} onClick={()=>void act(async()=>selected.monitoring_decision!.next_request_id!)}>Open follow-up request</button>}
      </p>}
      {canCreate && api.monitoringDecision && !selected.monitoring_decision &&
        (selected.purpose==='monitoring' || selected.next_review_at) &&
        ['reviewed','failed','declined','cancelled'].includes(selected.status) &&
        <form aria-label="Monitoring decision" onSubmit={e=>{
          e.preventDefault();
          if (!monitoringConfirmed) return;
          void act(async signal=>{
            await api.monitoringDecision!(id,selected.request_id,{
              revision:selected.revision,confirmed:true,action:monitoringAction,
              reason:monitoringReason,
              next_review_at:monitoringAction==='continue'?new Date(monitoringTime).toISOString():null,
            },signal);
            return selected.request_id;
          });
        }}>
          <h3>Monitoring follow-through</h3>
          <label>Decision<select value={monitoringAction} onChange={e=>{setMonitoringAction(e.target.value);setMonitoringConfirmed(false);}}>
            <option value="continue">Continue monitoring</option><option value="escalate">Escalate for coordinator action</option><option value="finish">Finish monitoring</option>
          </select></label>
          {monitoringAction==='continue' && <label>Next review · your local time<input type="datetime-local" required value={monitoringTime} onChange={e=>setMonitoringTime(e.target.value)} onInput={e=>setMonitoringTime(e.currentTarget.value)}/></label>}
          <label>Decision reason<input required maxLength={2000} value={monitoringReason} onChange={e=>setMonitoringReason(e.target.value)}/></label>
          <label style={{flexDirection:'row'}}><input type="checkbox" style={{minWidth:0}} checked={monitoringConfirmed} onChange={e=>setMonitoringConfirmed(e.target.checked)}/>I confirm this monitoring decision.</label>
          <button disabled={busy || !monitoringConfirmed || !monitoringReason.trim()}>Record monitoring decision</button>
          <p className="lj-muted">Continue creates a follow-up awaiting approval. Escalation requires coordinator action. Finishing monitoring does not close the rescue case.</p>
        </form>}
      <DroneStreamPanel key={'stream-'+selected.request_id} api={api} id={id} request={selected}
        onChanged={()=>act(async()=>selected.request_id)} onUnavailable={failure=>{
          setError(networkErrorMessage(failure));setRows([]);setSelected(null);setCanCreate(false);
          setSuggestions([]);setConfidence(null);setImage('');
          if(preview.current)URL.revokeObjectURL(preview.current);preview.current='';
        }}/>
      <ObservationComparison key={'comparison-'+selected.request_id} api={api} id={id} request={selected} rows={rows} onUnavailable={failure=>{
        setError(networkErrorMessage(failure));setRows([]);setSelected(null);setCanCreate(false);setSuggestions([]);setConfidence(null);
        if(preview.current)URL.revokeObjectURL(preview.current);
        preview.current='';setImage('');
      }}/>
      <details><summary>Request history</summary><ol>{selected.events?.map(e=><li key={e.revision}>{label(e.kind)} · {new Date(e.recorded_at).toLocaleString()} · {e.actor_user_id}{e.note ? ': '+e.note:''}</li>)}</ol></details>
      <p className="lj-muted">Findings are saved as a case addendum. Rescue status and the original intake assessment remain separately reviewed.</p>
    </article>}
  </section>;
}
