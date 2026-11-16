"""Final presentation ablation: tight upscaled detector crops, not reference crops."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import json,sys,time,copy,traceback
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import practical_options_review_v1 as p
D=Path.home()/'aerial-data';R=p.R;Q=R/'tight-seal-probe';Q.mkdir(exist_ok=True)
def main():
 assert not (Q/'reviews.json').exists()
 old=json.loads((R/'seal-probe/plan.json').read_text());pred={r['key']:r for r in json.loads((D/'model-comparison-v1/dmd-predictions.json').read_text())};tasks=[]
 for item in old['references']:
  folder=Q/'inputs'/item['key'];folder.mkdir(parents=True,exist_ok=True);im=Image.open(item['source']).convert('RGB');w,h=im.size
  overview=im.copy();overview.thumbnail((2048,2048));q=folder/'F1-whole.jpg';overview.save(q,quality=95)
  images=[{'image_id':'F1-whole','path':str(q),'sha256':p.sha(q),'role':'whole_frame'}];regions=[]
  boxes=sorted([b for b in pred[item['key']]['tiled_plus_full'] if b['class_id']==1 and b['score']>=.3],key=lambda b:b['score'],reverse=True)[:3]
  for j,b in enumerate(boxes,1):
   cw=max(64,1.5*(b['x2']-b['x1']));ch=max(64,1.5*(b['y2']-b['y1']));x0=max(0,int((b['x1']+b['x2']-cw)/2));y0=max(0,int((b['y1']+b['y2']-ch)/2));x1=min(w,int((b['x1']+b['x2']+cw)/2+1));y1=min(h,int((b['y1']+b['y2']+ch)/2+1))
   crop=im.crop((x0,y0,x1,y1));scale=768/max(crop.size);crop=crop.resize((max(1,round(crop.width*scale)),max(1,round(crop.height*scale))),Image.Resampling.LANCZOS)
   imageid=f'F1-animal-{j}';q=folder/(imageid+'.jpg');crop.save(q,quality=95)
   images.append({'image_id':imageid,'path':str(q),'sha256':p.sha(q),'role':'unverified_mammal_proposal_tight_resized'})
   regions.append({'image_id':imageid,'target_yxyx_1000':[round((b['y1']-y0)/(y1-y0)*1000),round((b['x1']-x0)/(x1-x0)*1000),round((b['y2']-y0)/(y1-y0)*1000),round((b['x2']-x0)/(x1-x0)*1000)],'box':b})
  tasks.append({'key':item['key'],'images':images,'regions':regions})
 plan={'scope':'Final post-hoc crop-presentation package on the same8 positive NOAA images. Detector proposals only; reference boxes never used to select crops. Crop budget3, padding1.5× with minimum64px, resized to768px long edge. Upsampling adds no new image detail. Not held-out validation.',
 'code_sha256':p.sha(__file__),'reviewer_sha256':p.sha(A/'practical_options_review_v1.py'),'max_requests':8,'tasks':tasks}
 (Q/'plan.json').write_text(json.dumps(plan,indent=2))
 def call(item):
  mapping={'frame_id':'F1','images':[{'image_id':i['image_id'],'role':i['role']} for i in item['images']],'animal_regions':[{k:v for k,v in r.items() if k!='box'} for r in item['regions']],'context_regions':[]}
  prompt=p.PROMPT+'\nSome candidate crops are resized for display; do not infer detail that is not visible.\nImage order: '+json.dumps([i['image_id'] for i in item['images']])+'\nFrame/target mapping: '+json.dumps([mapping])
  client=p.g.MeteredClient(max_retries=1,temperature=.1);client.usage={};t=time.perf_counter()
  try:
   data=client.generate_json(prompt,p.SCHEMA,images=[p.g.ImageInput(data=Path(i['path']).read_bytes()) for i in item['images']],temperature=.1,system_instruction=p.SYSTEM).data
   assert len(data['frames'])==1 and data['frames'][0]['frame_id']=='F1'
   assert set(data['frames'][0]['evidence_image_ids'])<={i['image_id'] for i in item['images']}
   result={'key':item['key'],'status':'success','data':data,'usage':client.usage,'wall_seconds':time.perf_counter()-t,'input_sha256':[i['sha256'] for i in item['images']],'model_version':client.model_version,'prompt':prompt}
  except Exception as e:result={'key':item['key'],'status':'failed','error':str(e)[:1200],'usage':client.usage,'wall_seconds':time.perf_counter()-t}
  (Q/(item['key']+'.json')).write_text(json.dumps(result,indent=2));print(item['key'],result['status'],flush=True);return result
 with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(call,tasks))
 (Q/'reviews.json').write_text(json.dumps(out,indent=2))
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
