"""Per-sample exact-class context verification on complete cached aerial clips."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json,sys,time,shutil,hashlib,traceback
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import video_patrol_review_v1 as crop
import independent_scene_review_v1 as scene
from context_video_policy_v1 import AnimalEvidence,classify_context,check_policy
D=Path.home()/'aerial-data';R=D/'context-video-v1';P=D/'aerial-patrol-v1';AR=R/'animal-review';CR=R/'context-review'
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def state(phase,**kw):v={'phase':phase,**kw};save('review-status.json',v);print(json.dumps(v),flush=True)
def main():
 assert not (R/'observations.json').exists()
 deadline=time.monotonic()+1200
 while not (R/'predictions.json').exists():
  if time.monotonic()>deadline:raise RuntimeError('Detector wait timeout')
  p=R/'detector-status.json'
  if p.exists() and json.loads(p.read_text())['phase']=='failed':raise RuntimeError(p.read_text())
  time.sleep(2)
 frames=json.loads((R/'predictions.json').read_text());plan=json.loads((R/'plan.json').read_text())
 AR.mkdir(exist_ok=True);CR.mkdir(exist_ok=True)
 for folder in ['calls','scene-calls','verification-inputs','scene-inputs']:
  if (P/folder).exists():shutil.copytree(P/folder,AR/folder,dirs_exist_ok=True)
 crop.ROOT=AR;scene.ROOT=AR
 selected=[f for f in frames if f['sample_index']%6==0];tasks=[(mode,f) for f in selected for mode in ['crop','scene']]
 def cache_path(mode,f):return AR/('calls' if mode=='crop' else 'scene-calls')/(f"{f['source']}-{f['sample_index']:03}.json")
 new=sum(not cache_path(m,f).exists() for m,f in tasks);assert new<=plan['max_new_animal_requests']
 save('animal-review-plan.json',{'trial_sha256':hashlib.sha256((R/'plan.json').read_bytes()).hexdigest(),'tasks':[{'mode':m,'source':f['source'],'sample_index':f['sample_index'],'sha256':f['sha256'],'reused':cache_path(m,f).exists()} for m,f in tasks],'new_requests':new,'reused_requests':len(tasks)-new})
 def call(task):
  m,f=task;reused=cache_path(m,f).exists();t=time.perf_counter()
  result=crop.verify(f) if m=='crop' else scene.call({**f,'study_source':f['source']})
  return {'mode':m,'reused':reused,'wall_seconds':time.perf_counter()-t,'review':result}
 state('animal_review',new_requests=new,reused=len(tasks)-new)
 with ThreadPoolExecutor(max_workers=2) as pool:
  animal=[]
  for result in pool.map(call,tasks):animal.append(result);state('animal_review',completed=len(animal),total=len(tasks))
 save('animal-reviews.json',animal)
 ci={(x['review']['source'],x['review']['sample_index']):x['review'] for x in animal if x['mode']=='crop'}
 si={(x['review']['source'],x['review']['sample_index']):x['review'] for x in animal if x['mode']=='scene'}
 old=AnimalEvidence(False);clear=AnimalEvidence(True);rows=[]
 for f in frames:
  key=(f['source'],f['sample_index']);a=old.update(f,ci.get(key),si.get(key));b=clear.update(f,ci.get(key),si.get(key))
  rows.append({**f,'old_animal_state':a,'clear_animal_state':b,'cohort':'aerial'})
 ground=json.loads((D/'combined-gemini-v1/observations.json').read_text())
 for f in ground:
  rows.append({**f,'source':'ground_rescue','cohort':'ground_retention_regression',
   'old_animal_state':{'gate':f['combined_gate']},'clear_animal_state':{'gate':f['combined_gate']}})
 # Every eligible raw context box is reviewed on its own frame; no propagated acceptance.
 tasks=[];tasks_by_frame={}
 for f in rows:
  if not (f['old_animal_state']['gate']['context_visible'] or f['clear_animal_state']['gate']['context_visible']):continue
  boxes=[b for b in f['combined_packet']['boxes'] if b['class_id'] in [0,2]]
  for batch in range(0,len(boxes),3):
   subset=boxes[batch:batch+3]
   item={'frame_source':f['source'],'sample_index':f['sample_index'],'frame_sha256':f['sha256'],'frame_path':f['path'],'seconds':f['seconds'],'source_seconds':f['source_seconds'],'batch':batch//3,'boxes':subset}
   tasks.append(item)
 assert len(tasks)<=plan['max_context_requests'],len(tasks)
 save('context-review-plan.json',{'created_at':datetime.now(timezone.utc).isoformat(),'tasks':tasks,'requests':len(tasks),'acceptance':'Per-region exact class agreement only; no temporal reuse. No animal/ground-truth labels passed to classifier.','driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'policy_sha256':hashlib.sha256((A/'context_video_policy_v1.py').read_bytes()).hexdigest()})
 crop.ROOT=CR
 def context_call(item):
  pseudo={'source':f"{item['frame_source']}-context-b{item['batch']:02}",'sample_index':item['sample_index'],'seconds':item['seconds'],'path':item['frame_path'],'merged_predictions':[{**b,'class_id':1} for b in item['boxes']]}
  t=time.perf_counter();result=crop.verify(pseudo)
  return {**item,'review':result,'wall_seconds':time.perf_counter()-t,'checks':classify_context(item['boxes'],result)}
 state('context_review',planned=len(tasks))
 with ThreadPoolExecutor(max_workers=2) as pool:
  results=[]
  for result in pool.map(context_call,tasks):results.append(result);state('context_review',completed=len(results),total=len(tasks),last_status=result['review']['status'])
 save('context-reviews.json',results)
 lookup={}
 for r in results:lookup.setdefault((r['frame_source'],r['sample_index']),[]).extend(r['checks'])
 for f in rows:
  checks=lookup.get((f['source'],f['sample_index']),[]);f['context_checks']=checks
  accepted=[c['box'] for c in checks if c['accepted']]
  f['verified_context_boxes']=accepted
  for name,gate in [('context_verified',f['old_animal_state']['gate']),('context_verified_clear',f['clear_animal_state']['gate'])]:
   f[name]={'context_visible':gate['context_visible'],'shown_persons':sum(b['class_id']==0 for b in accepted) if gate['context_visible'] else 0,'shown_vehicles':sum(b['class_id']==2 for b in accepted) if gate['context_visible'] else 0}
 save('observations.json',rows);save('policy-checks.json',check_policy());state('completed',frames=len(frames),ground_frames=len(ground),new_animal_calls=new,context_calls=len(tasks))
if __name__=='__main__':
 try:main()
 except Exception as e:state('failed',error=str(e)[:1600]);traceback.print_exc();raise
