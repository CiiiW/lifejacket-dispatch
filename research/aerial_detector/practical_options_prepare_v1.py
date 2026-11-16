"""Freeze a factorial practical-options benchmark on exact cached input bytes."""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import json,sys,hashlib,os,math,time,traceback
os.environ['YOLO_CONFIG_DIR']=str(Path.home()/'aerial-data/model-comparison-v1/yolo-config')
from PIL import Image,ImageDraw
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import dmd
D=Path.home()/'aerial-data';R=D/'practical-options-v1'
sha=dmd.file_sha256
def main():
 assert not (R/'frames.json').exists()
 rows=json.loads((D/'context-video-v1/hypothesis-observations.json').read_text())
 extras=[]
 for folder,source,newsource in [('strict-fresh-v1','dog_walk','dog_walk'),('video-patrol-v1','people_vehicles','parking_control')]:
  for f in json.loads((D/folder/'observations.json').read_text()):
   if f['source']!=source:continue
   extras.append({**{k:f[k] for k in ['sample_index','frame_index','seconds','path','sha256','size','merged_predictions','full_predictions']},
    'source':newsource,'source_seconds':f['seconds'],'cohort':'aerial_proxy' if source=='dog_walk' else 'aerial_control'})
 assert len(extras)==40
 from ultralytics import YOLOWorld
 from role_proposal_composer_v1 import compose
 oldplan=json.loads((D/'context-video-v1/plan.json').read_text())
 weight=D/'model-comparison-v1/yolov8s-worldv2.pt';assert sha(weight)==oldplan['context_weights_sha256']
 m=YOLOWorld(str(weight));m.set_classes(oldplan['vocabulary'])
 for f in extras:
  assert sha(f['path'])==f['sha256'];im=Image.open(f['path']).convert('RGB')
  rr=m.predict(im,imgsz=1280,conf=.3,iou=.5,device=0,verbose=False,max_det=300)[0];boxes=[]
  if rr.boxes is not None:
   for xy,score,cid in zip(rr.boxes.xyxy.cpu().tolist(),rr.boxes.conf.cpu().tolist(),rr.boxes.cls.cpu().tolist()):boxes.append(asdict(dmd.Box(*map(float,xy),oldplan['class_mapping'][int(cid)],float(score))))
  f['world_full_predictions']=boxes;f['combined_packet']=compose(f['merged_predictions'],boxes)
 rows+=extras;assert len(rows)==205;assert len({(f['source'],f['sample_index']) for f in rows})==len(rows)
 assert all(sha(f['path'])==f['sha256'] for f in rows)
 (R/'frames.json').write_text(json.dumps(rows,indent=2))
 groups=[]
 for source in dict.fromkeys(f['source'] for f in rows):
  ss=[f for f in rows if f['source']==source]
  for bucket in sorted({int(f['seconds']//6) for f in ss}):
   ff=[f for f in ss if int(f['seconds']//6)==bucket];chosen=[ff[0],ff[len(ff)//2],ff[-1]];unique={f['sample_index']:f for f in chosen};chosen=list(unique.values())
   groups.append({'key':f'{source}-{bucket:02}','source':source,'bucket':bucket,'start_seconds':ff[0]['seconds'],'end_seconds':ff[-1]['seconds'],
    'all_frame_keys':[f['sample_index'] for f in ff],'burst_indices':[f['sample_index'] for f in chosen],'single_index':ff[len(ff)//2]['sample_index']})
 assert len(groups)==19,len(groups)
 (R/'groups.json').write_text(json.dumps(groups,indent=2))
 # Raw source screening is distinct from future model output and from exhaustive truth.
 screens=[]
 for source in ['surf','dog_walk','parking_control']:
  ss=[f for f in rows if f['source']==source];select=[ss[0],ss[len(ss)//2],ss[-1]]
  out=Image.new('RGB',(1440,320),'#10202b')
  for j,f in enumerate(select):
   im=Image.open(f['path']).convert('RGB');im.thumbnail((480,270));out.paste(im,(j*480,35));ImageDraw.Draw(out).text((j*480+10,10),f"{source} {f['seconds']:.2f}s",fill='white')
  p=R/(source+'-screen.jpg');out.save(p,quality=93);screens.append(str(p))
 plan={'created_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
  'scope':'Development factorial comparison, same previously inspected cached clips plus cached dog-human aerial proxy and parking control. No held-out field validation.',
  'sources':dict(Counter(f['source'] for f in rows)),'groups':19,'group_seconds':6,'modes':['single_whole','single_native','burst_whole','burst_native'],
  'max_requests':76,'sample_fps':2,'frame_selection':'Middle for single; first/middle/last unique samples for burst; selected before model scoring.',
  'crop_budget':'Up to2 spatially distinct DMD animal proposals, top person and top vehicle proposal per selected frame. Whole and native modes use identical contextual target rectangles; native adds padded native crops.',
  'decision':'Review cards, no automatic incident or dispatch. Single-positive and two-frame-positive support are reported separately. Never propagate animal/context evidence to unreviewed frames.',
  'dmd_weights_sha256':oldplan['dmd_sha256'],'context_weights_sha256':oldplan['context_weights_sha256'],'context_vocabulary':oldplan['vocabulary'],
  'input_sha256':sha(R/'frames.json'),'group_sha256':sha(R/'groups.json'),'prepare_code_sha256':sha(__file__)}
 (R/'plan.json').write_text(json.dumps(plan,indent=2));print(json.dumps({'frames':len(rows),'groups':len(groups),'screens':screens,'sources':plan['sources']},indent=2),flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
