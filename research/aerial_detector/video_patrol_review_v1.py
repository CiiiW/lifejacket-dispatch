"""Video scene-context smoke test with actual scheduled Gemini checks and separate fixtures."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
import sys,json,time,traceback,statistics,hashlib,shutil,csv
from PIL import Image,ImageDraw
AERIAL=Path(__file__).resolve().parent;sys.path.insert(0,str(AERIAL))
import dmd
import gemini_handoff_v1 as g
import gemini_ontology_regression_v2 as ontology
from patrol_memory import PatrolMemory,check_policy
ROOT=Path.home()/'aerial-data/video-patrol-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,v):
 p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
 temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(v,indent=2));temp.replace(p)
def state(phase,**kw):
 r={'phase':phase,'updated_at':datetime.now(timezone.utc).isoformat(),**kw};save('review-status.json',r);print(json.dumps(r),flush=True)
def verify(frame):
 key=f"{frame['source']}-{frame['sample_index']:03}";out=ROOT/'calls'/f'{key}.json'
 if out.exists():return json.loads(out.read_text())
 client=g.MeteredClient(max_retries=1,temperature=.1);client.usage={}
 folder=ROOT/'verification-inputs'/key;folder.mkdir(parents=True,exist_ok=True)
 with Image.open(frame['path']) as im:image=im.convert('RGB')
 overview=image.copy();overview.thumbnail((2048,2048));overview_path=folder/'context.jpg';overview.save(overview_path,quality=95)
 proposals=[dmd.Box(**b) for b in frame['merged_predictions'] if b['class_id']==1][:3]
 images=[g.ImageInput(data=overview_path.read_bytes())];regions=[]
 for n,b in enumerate(proposals,1):
  w,h=image.size;cw=max(256,(b.x2-b.x1)*2);ch=max(256,(b.y2-b.y1)*2)
  x0=max(0,int((b.x1+b.x2-cw)/2));y0=max(0,int((b.y1+b.y2-ch)/2))
  x1=min(w,int((b.x1+b.x2+cw)/2+1));y1=min(h,int((b.y1+b.y2+ch)/2+1))
  crop=image.crop((x0,y0,x1,y1));crop.thumbnail((1280,1280));path=folder/f'region-{n}.jpg';crop.save(path,quality=95)
  target=[round(1000*(b.y1-y0)/(y1-y0)),round(1000*(b.x1-x0)/(x1-x0)),round(1000*(b.y2-y0)/(y1-y0)),round(1000*(b.x2-x0)/(x1-x0))]
  regions.append({'region_id':f'R{n:02}','target_yxyx_1000':[max(0,min(1000,v)) for v in target]})
  images.append(g.ImageInput(data=path.read_bytes()))
 started=time.perf_counter()
 try:
  if regions:
   prompt=ontology.prompt({'selected_proposals':regions})
   response=client.generate_json(prompt,ontology.SCHEMA,images=images,temperature=.1,system_instruction=ontology.SYSTEM)
   data=response.data;rows=data.get('regions',[])
   ids=[r['region_id'] for r in rows]
   assert len(ids)==len(set(ids))==len(regions) and set(ids)=={r['region_id'] for r in regions}
   confirmed=any(r['subject_class']=='animal' for r in rows)
   needs_review=any(r['subject_class']=='uncertain' for r in rows)
   method='proposal_crops'
  else:
   agent=g.DetectionAgent(client);result=agent.run(images=images);prompt=agent.last_prompt
   data=result.model_dump(mode='json')
   confirmed=any(a['kind']=='mammal' for a in data['animals'])
   needs_review=False;method='independent_whole_scene'
  row={'key':key,'source':frame['source'],'sample_index':frame['sample_index'],'seconds':frame['seconds'],
   'status':'success','method':method,'data':data,'animal_confirmed':confirmed,'uncertain':needs_review,
   'usage':client.usage,'model_version':client.model_version,'seconds_processing':time.perf_counter()-started,
   'prompt':prompt,'input_sha256':[hashlib.sha256(i.data).hexdigest() for i in images]}
 except Exception as exc:
  row={'key':key,'source':frame['source'],'sample_index':frame['sample_index'],'seconds':frame['seconds'],
    'status':'failed','animal_confirmed':False,'uncertain':True,'usage':client.usage,
    'error':str(exc)[:1000],'seconds_processing':time.perf_counter()-started}
 save(str(out.relative_to(ROOT)),row);return row
def main():
 assert not (ROOT/'report.json').exists(),'Completed; use new directory'
 state('waiting_for_detector')
 while not (ROOT/'predictions.json').exists():
  p=ROOT/'status.json'
  if p.exists() and json.loads(p.read_text())['phase']=='failed':raise RuntimeError('Video preparation failed')
  time.sleep(2)
 frames=json.loads((ROOT/'predictions.json').read_text());plan=json.loads((ROOT/'plan.json').read_text())
 selected=[r for r in frames if r['sample_index']%6==0]
 assert len(selected)<=8
 save('review-plan.json',{'created_at':datetime.now(timezone.utc).isoformat(),
   'model':g.settings.llm_model,'temperature':.1,'thinking_budget':g.settings.llm_thinking_budget,
   'schema':ontology.SCHEMA,'system':ontology.SYSTEM,'max_requests':8,
   'schedule':[{'source':r['source'],'sample_index':r['sample_index'],'seconds':r['seconds']} for r in selected],
   'role':'Operational non-human-animal confirmation, not urgency or injury assessment',
   'plan_sha256':sha(ROOT/'plan.json')})
 state('gemini',planned_requests=len(selected))
 with ThreadPoolExecutor(max_workers=2) as pool:
  futures=[pool.submit(verify,r) for r in selected]
  reviews=[]
  for f in as_completed(futures):
   review=f.result();reviews.append(review)
   state('gemini',completed_requests=len(reviews),planned_requests=len(selected),last_status=review['status'])
 indexed={(r['source'],r['sample_index']):r for r in reviews}
 observations=[]
 # Memory is exercised across the explicit clip boundary; it must reset.
 reviewed_memory=PatrolMemory();naive_memory=PatrolMemory()
 for frame in frames:
  p=frame['merged_predictions'];candidate=any(b['class_id']==1 for b in p)
  persons=sum(b['class_id']==0 for b in p);vehicles=sum(b['class_id']==2 for b in p)
  review=indexed.get((frame['source'],frame['sample_index']))
  confirmed=bool(review and review['status']=='success' and review['animal_confirmed'])
  checked=reviewed_memory.update(frame['source'],frame['seconds'],animal_candidate=candidate,
   animal_confirmed=confirmed,persons=persons,vehicles=vehicles,
   review_failed=bool(review and (review['status']=='failed' or review['uncertain'])))
  naive=naive_memory.update(frame['source'],frame['seconds'],animal_candidate=candidate,
   animal_confirmed=candidate,persons=persons,vehicles=vehicles)
  observations.append({**frame,'animal_candidate':candidate,'person_boxes':persons,'vehicle_boxes':vehicles,
    'scheduled_review':review is not None,'animal_confirmed_at_sample':confirmed,
    'reviewed_gate':checked,'detector_only_gate':naive})
 save('observations.json',observations);save('reviews.json',reviews)
 summary=[]
 for source in ['seal','people_vehicles']:
  rows=[r for r in observations if r['source']==source];calls=[r for r in reviews if r['source']==source]
  summary.append({'source':source,'sampled_frames':len(rows),
   'whole_frame_animal_proposal_frames':sum(any(b['class_id']==1 for b in r['full_predictions']) for r in rows),
   'tiled_animal_proposal_frames':sum(r['animal_candidate'] for r in rows),
   'frames_with_raw_person_or_vehicle_boxes':sum(bool(r['person_boxes'] or r['vehicle_boxes']) for r in rows),
   'naive_gate_open_frames':sum(r['detector_only_gate']['context_visible'] for r in rows),
   'reviewed_gate_open_frames':sum(r['reviewed_gate']['context_visible'] for r in rows),
   'naive_context_shown_frames':sum(bool(r['detector_only_gate']['shown_persons'] or r['detector_only_gate']['shown_vehicles']) for r in rows),
   'reviewed_context_shown_frames':sum(bool(r['reviewed_gate']['shown_persons'] or r['reviewed_gate']['shown_vehicles']) for r in rows),
   'candidate_episodes':sum(r['reviewed_gate']['new_candidate_episode'] for r in rows),
   'scheduled_reviews':len(calls),'animal_confirmations':sum(r['animal_confirmed'] for r in calls),
   'median_detector_seconds':statistics.median(r['seconds_processing'] for r in rows)})
 # Explicitly synthetic temporal fault tests, separate from model performance.
 fixtures=check_policy()
 m=PatrolMemory()
 short=[]
 for n in range(7):
  t=n*.5
  result=m.update('dropout-fixture',t,animal_candidate=not 1.5<=t<=2.5,
     animal_confirmed=t==0,persons=2,vehicles=1)
  if 1.5<=t<=2.5:short.append(result['context_visible'])
 assert all(short)
 fixtures.append({'case':'injected_1_second_detector_gap_preserves_recent_context','passed':True})
 reset=m.update('new-scene-fixture',0.,persons=2,vehicles=1)
 assert not reset['context_visible'] and not reset['shown_persons'] and not reset['shown_vehicles']
 fixtures.append({'case':'explicit_clip_scene_transition_drops_stale_context','passed':True})
 save('policy-fixtures.json',fixtures)
 # Reduced-resolution previews are for review only, never model inputs.
 previews=[]
 for source in ['seal','people_vehicles']:
  movie=[]
  for row in [v for v in observations if v['source']==source]:
   with Image.open(row['path']) as handle:image=handle.convert('RGB')
   image.thumbnail((960,540));scale=image.width/row['size'][0]
   draw=ImageDraw.Draw(image)
   for b in row['merged_predictions']:
    color={0:'#46c5ff',1:'#75ed89',2:'#ffc268'}[b['class_id']]
    draw.rectangle((b['x1']*scale,b['y1']*scale,b['x2']*scale,b['y2']*scale),outline=color,width=2)
   draw.rectangle((0,0,image.width,44),fill='#102633')
   draw.text((8,6),f"{source} | {row['seconds']:.2f}s | candidates {sum(b['class_id']==1 for b in row['merged_predictions'])}",fill='white')
   draw.text((8,24),f"raw context boxes: person {row['person_boxes']}, vehicle {row['vehicle_boxes']} | reviewed context gate: {row['reviewed_gate']['context_visible']}",fill='white')
   movie.append(image)
  out=ROOT/f'review-{source}.gif'
  movie[0].save(out,save_all=True,append_images=movie[1:],duration=500,loop=0,optimize=True);previews.append(str(out))
 report={'experiment':'video-patrol-v1','scope':plan['scope'],'video_integrity':json.loads((ROOT/'video-integrity.json').read_text()),
  'summary':summary,'model':g.settings.llm_model,'requests':len(reviews),'failed_requests':sum(r['status']=='failed' for r in reviews),
  'usage':g.usage_sum(reviews),'policy_fixtures':fixtures,'previews':previews,
  'sampling_fps':2.,'hold_seconds':3.,'episode_idle_seconds':8.,
  'limitations':['Two short stock aerial clips are a smoke test, not representative rescue/DJI field validation.',
   'No independent bounding-box or track ground truth is supplied. Proposal counts are not accuracy or unique-animal counts.',
   'People/vehicle clip is a visually screened control, not an exhaustive wildlife-absence annotation.',
   'Both clips decoded completely. Only first 12 seal seconds and first 10 people/vehicle seconds are sampled at 2 FPS.',
   'Gemini checks are scheduled every three seconds with up to three candidate crops, or an independent whole-scene check if no animal proposal exists.',
   'Only explicit non-human-animal confirmation opens the reviewed context gate; uncertainty keeps evidence for review.',
   'Known clip IDs provide scene boundaries. Automatic within-video shot-change detection is not implemented or validated.',
   'Dropouts, false candidates, hold expiry and context-count fixtures are synthetic logic tests, not naturally measured occlusions.',
   'Episode IDs group scene/time evidence, not animal identities, unique-animal counts or incidents.',
   'No app integration, automatic alerts, flight control, dispatch, urgency/injury assessment or production deployment.']}
 save('report.json',report)
 with (ROOT/'summary.csv').open('w',newline='') as h:
  writer=csv.DictWriter(h,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
 bundle=AERIAL/'results/video-patrol-v1';bundle.mkdir(parents=True,exist_ok=True)
 for name in ['plan.json','review-plan.json','video-source.json','negative-source.json','local-video-check.json','video-integrity.json','frame-manifest.json','predictions.json','observations.json','reviews.json','policy-fixtures.json','summary.csv','report.json']:
  shutil.copy2(ROOT/name,bundle/name)
 state('completed',sampled_frames=len(frames),requests=len(reviews),policy_fixtures=len(fixtures))
 print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as exc:state('failed',error=str(exc));traceback.print_exc();raise
