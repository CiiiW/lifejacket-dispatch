"""Separate visual hard-cut probe using the frozen four review methods."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys,json,time,hashlib,copy,traceback
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import practical_options_review_v1 as p
R=p.R;Q=R/'cut-probe';Q.mkdir(exist_ok=True)
def main():
 assert not (Q/'reviews.json').exists()
 rows=json.loads((R/'frames.json').read_text())
 refs=[next(r for r in rows if r['source']==s and r['sample_index']==i) for s,i in [('raft',6),('crowded_beach',0),('crowded_beach',6)]]
 idx={('cut_probe',i):{**r,'source':'cut_probe','sample_index':i,'seconds':i*3} for i,r in enumerate(refs)}
 group={'key':'cut_probe-00','source':'cut_probe','burst_indices':[0,1,2],'single_index':1};tasks=[]
 for mode in ['single_whole','single_native','burst_whole','burst_native']:
  manifest,images=p.prepare(group,mode,idx);tasks.append({'mode':mode,'manifest':manifest,'images':images})
 plan={'scope':'Injected visual cut: platform mammals followed by two crowded-beach frames. Animal/context may be associated only within the same reviewed frame. Not a natural scene-cut dataset.',
  'source_refs':[{'source':r['source'],'sample_index':r['sample_index'],'sha256':r['sha256']} for r in refs],
  'reviewer_sha256':p.sha(A/'practical_options_review_v1.py'),'probe_code_sha256':p.sha(__file__),'max_requests':4,'tasks':tasks}
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
   assert {r['frame_id'] for r in data['frames']}=={m['frame_id'] for m in item['manifest']}
   result={'mode':item['mode'],'status':'success','data':data,'wall_seconds':time.perf_counter()-start,'usage':client.usage,'input_sha256':[im['sha256'] for im in item['images']],'model_version':client.model_version,'prompt':prompt}
  except Exception as e:result={'mode':item['mode'],'status':'failed','error':str(e)[:1000],'wall_seconds':time.perf_counter()-start,'usage':client.usage}
  (Q/(item['mode']+'.json')).write_text(json.dumps(result,indent=2));return result
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(call,tasks))
 (Q/'reviews.json').write_text(json.dumps(results,indent=2));print(json.dumps([{'mode':r['mode'],'status':r['status']} for r in results]),flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
