import assert from 'node:assert/strict';
import test from 'node:test';
import { JSDOM } from 'jsdom';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ObservationWorkspace } from '../../clients/responder_console/src/screens/ObservationWorkspace.web';
import { type DroneApi, type DroneRequest, NetworkError } from '../../clients/responder_console/src/lib/networkApi';

const request:DroneRequest={request_id:'request',case_id:'case',revision:1,status:'in_progress',purpose:'verification',execution_kind:'recorded_demo',objective:'Check the reported animal',reason:'Additional view needed',operator:'Demo operator',next_review_at:null,escalation_criteria:'Visible entanglement',target_location:{latitude:null,longitude:null},allowed_transitions:['evidence_ready'],outcome:null,evidence:[
  {evidence_id:'photo1',description:'Full body',source_kind:'sample_footage',source_url:null,captured_at:null,frame_offset_seconds:null,rights_note:'Synthetic test only',received_at:'2026-11-11T12:00:04Z',source_session_id:'stream'},
  {evidence_id:'photo2',description:'Head view',source_kind:'sample_footage',source_url:null,captured_at:null,frame_offset_seconds:null,rights_note:'Synthetic test only'},
]};

test('workspace keeps photo/AI selection together, loads private playback and clears media on case switch',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true});
  const revoked:string[]=[];let blobCount=0;
  const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;
  URL.createObjectURL=()=>`blob:private-${++blobCount}`;
  URL.revokeObjectURL=value=>revoked.push(value);
  const calls:string[]=[];
  const api={
    streams:async()=>({streams:[{stream_id:'stream',request_id:'request',status:'ended',created_at:'2026-11-11T12:00:00Z',expires_at:'2026-11-11T12:30:00Z',last_frame_at:null,frame_age_seconds:null,can_manage:false,source:{label:'Synthetic stream',source_kind:'sample_footage',source_url:null,rights_note:'Synthetic'}}]}),
    streamPreview:async()=>({stream_id:'stream',request_id:'request',status:'ended',created_at:'2026-11-11T12:00:00Z',expires_at:'2026-11-11T12:30:00Z',last_frame_at:null,frame_age_seconds:null,can_manage:false,source:{label:'Synthetic stream',source_kind:'sample_footage',source_url:null,rights_note:'Synthetic'}}),
    recordings:async()=>({enabled:true,time_note:'Server time',recordings:[{recording_id:'recording',status:'complete',started_at:'2026-11-11T12:00:00Z',updated_at:'2026-11-11T12:00:10Z',error_code:null,segments:[{segment_id:'000000',offset_seconds:0,duration_seconds:10,bytes:4,sha256:'fixture'}]}]}),
    recordingVideo:async()=>{calls.push('playback');return new Blob(['video']);},
    photo:async(_id:string,_r:string,e:string)=>{calls.push(e);return new Blob(['photo']);},
    frameAnalyses:async()=>({jobs:[],worker:{running:true}}),
  } as unknown as DroneApi;
  const root=createRoot(document.getElementById('root')!);
  const changed=async()=>{};const unavailable=()=>{throw new Error('Unexpected access failure');};
  const button=(text:string)=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent?.includes(text))!;
  try{
    await act(async()=>{root.render(<ObservationWorkspace api={api} id="case" request={request} canManage onChanged={changed} onUnavailable={unavailable}/>);});
    assert.ok(document.querySelector('[aria-label="Observation workspace"]'));
    assert.ok(document.body.textContent?.includes('Location unavailable'));
    await act(async()=>{button('Photo 1').click();});
    assert.match(document.querySelector('img')!.alt,/Full body/);
    const frame=Array.from(document.querySelectorAll('select')).find(s=>s.parentElement?.textContent?.startsWith('Saved frame'))!;
    assert.equal(frame.value,'photo1');
    assert.ok(calls.includes('photo1'));
    // Choosing a photo does not call an AI model or submit a job.
    assert.equal(button('Detect animals').disabled,true);
    await act(async()=>{button('Play 0').click();});
    assert.match(document.querySelector('video')!.src,/^blob:private-/);
    assert.ok(document.body.textContent?.includes('Approximate links'));
    await act(async()=>{button('Photo 2').click();});
    assert.equal(frame.value,'photo2');
    assert.match(document.querySelector('img')!.alt,/Head view/);
    assert.ok(revoked.length>=1);
    await act(async()=>{root.render(<ObservationWorkspace key="other" api={{photo:api.photo} as DroneApi} id="other-case" request={{...request,request_id:'other',case_id:'other-case',evidence:[]}} canManage={false} onChanged={changed} onUnavailable={unavailable}/>);});
    assert.equal(document.querySelector('img'),null);
    assert.equal(document.querySelector('video'),null);
    assert.ok(document.body.textContent?.includes('No saved evidence yet'));
  }finally{
    await act(async()=>root.unmount());dom.window.close();
    URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
  }
});

test('an obsolete photo response cannot appear after changing cases',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true});
  let finish:(b:Blob)=>void=()=>{};let accessFailures=0;
  const api={photo:async()=>new Promise<Blob>(resolve=>{finish=resolve;})} as unknown as DroneApi;
  const root=createRoot(document.getElementById('root')!);
  try{
    await act(async()=>root.render(<ObservationWorkspace key="first" api={api} id="case" request={request} canManage={false} onChanged={async()=>{}} onUnavailable={()=>accessFailures++}/>));
    await act(async()=>{(document.querySelector('[aria-label="Saved observation photos"] button') as HTMLButtonElement).click();});
    await act(async()=>root.render(<ObservationWorkspace key="next" api={api} id="next" request={{...request,request_id:'next',evidence:[]}} canManage={false} onChanged={async()=>{}} onUnavailable={()=>accessFailures++}/>));
    await act(async()=>finish(new Blob(['late private photo'])));
    assert.equal(document.querySelector('img'),null);
    assert.equal(accessFailures,0);
  }finally{await act(async()=>root.unmount());dom.window.close();}
});

test('a denied evidence read clears the image and reports lost access',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true});
  let failures=0;
  const api={photo:async()=>{throw new NetworkError(403);}} as unknown as DroneApi;
  const root=createRoot(document.getElementById('root')!);
  try{
    await act(async()=>root.render(<ObservationWorkspace api={api} id="case" request={request} canManage={false} onChanged={async()=>{}} onUnavailable={()=>failures++}/>));
    await act(async()=>{(document.querySelector('[aria-label="Saved observation photos"] button') as HTMLButtonElement).click();});
    assert.equal(document.querySelector('img'),null);
    assert.equal(failures,1);
    assert.ok(document.querySelector('[role="alert"]'));
  }finally{await act(async()=>root.unmount());dom.window.close();}
});
