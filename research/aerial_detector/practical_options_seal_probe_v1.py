"""Whole-versus-native single-image stress check on the existing annotated NOAA8 subset."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys,json,time,copy,traceback
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import practical_options_review_v1 as p
D=Path.home()/'aerial-data';R=p.R;Q=R/'seal-probe';Q.mkdir(exist_ok=True)
def main():
 assert not (Q/'reviews.json').exists()
 source=json.loads((D/'model-comparison-v1/plan.json').read_text());pred={r['key']:r for r in json.loads((D/'model-comparison-v1/dmd-predictions.json').read_text())}
 tasks=[];refs=[]
 for item in [r for r in source['items'] if r['cohort']=='noaa_seal']:
  assert p.sha(item['source'])==item['source_sha256']
  key='seal_probe_'+item['key'];boxes=[b for b in pred[item['key']]['tiled_plus_full'] if b['score']>=.3]
  f={'source':key,'sample_index':0,'seconds':0.,'source_seconds':0.,'path':item['source'],'sha256':item['source_sha256'],'size':item['size'],'merged_predictions':boxes,'combined_packet':{'boxes':[]}}
  refs.append(item)
  group={'key':key,'source':key,'single_index':0,'burst_indices':[0]}
  for mode in ['single_whole','single_native']:
   manifest,images=p.prepare(group,mode,{(key,0):f});tasks.append({'key':key,'reference_key':item['key'],'mode':mode,'manifest':manifest,'images':images})
 assert len(tasks)==16
 plan={'scope':'Development stress check on8 previously inspected annotated NOAA aerial images containing14 seal references. Presence decisions only; not independent box/species accuracy. Reference boxes never passed to the model.',
  'reviewer_sha256':p.sha(A/'practical_options_review_v1.py'),'probe_code_sha256':p.sha(__file__),'max_requests':16,'references':refs,'tasks':tasks}
 (Q/'plan.json').write_text(json.dumps(plan,indent=2))
 def call(item):
  mapping=copy.deepcopy(item['manifest'])
  for f in mapping:
   for k in ['source_sha256','sample_index','seconds','source_seconds']:f.pop(k,None)
   f['images']=[{'image_id':im['image_id'],'role':im['role']} for im in f['images']]
   for c in f['context_regions']:c.pop('box',None)
  prompt=p.PROMPT+'\nImage order: '+json.dumps([i['image_id'] for i in item['images']])+'\nFrame/target mapping: '+json.dumps(mapping)
  client=p.g.MeteredClient(max_retries=1,temperature=.1);client.usage={};start=time.perf_counter()
  try:
   data=client.generate_json(prompt,p.SCHEMA,images=[p.g.ImageInput(data=Path(i['path']).read_bytes()) for i in item['images']],temperature=.1,system_instruction=p.SYSTEM).data
   assert len(data['frames'])==1 and data['frames'][0]['frame_id']=='F1'
   assert set(data['frames'][0]['evidence_image_ids'])<={i['image_id'] for i in item['images']}
   row={'key':item['key'],'reference_key':item['reference_key'],'mode':item['mode'],'status':'success','data':data,'wall_seconds':time.perf_counter()-start,'usage':client.usage,'input_sha256':[im['sha256'] for im in item['images']],'model_version':client.model_version,'prompt':prompt}
  except Exception as e:row={'key':item['key'],'reference_key':item['reference_key'],'mode':item['mode'],'status':'failed','error':str(e)[:1200],'usage':client.usage,'wall_seconds':time.perf_counter()-start}
  folder=Q/'calls'/item['mode'];folder.mkdir(parents=True,exist_ok=True);(folder/(item['key']+'.json')).write_text(json.dumps(row,indent=2));return row
 with ThreadPoolExecutor(max_workers=2) as pool:
  out=[]
  for row in pool.map(call,tasks):out.append(row);print(row['mode'],row['reference_key'],row['status'],flush=True)
 (Q/'reviews.json').write_text(json.dumps(out,indent=2))
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
