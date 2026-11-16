"""Extend the frozen aerial sample grid through each complete source clip; reuse exact prior inputs."""
from pathlib import Path
from dataclasses import asdict
import json,sys,time,gc,os,traceback
os.environ['YOLO_CONFIG_DIR']=str(Path.home()/'aerial-data/model-comparison-v1/yolo-config')
import cv2,torch
from PIL import Image
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from tile_inference import tile_windows,to_source,merge_boxes
from role_proposal_composer_v1 import compose
D=Path.home()/'aerial-data';R=D/'context-video-v1';P=D/'aerial-patrol-v1'
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def state(phase,**kw):v={'phase':phase,**kw};save('detector-status.json',v);print(json.dumps(v),flush=True)
def main():
 assert not (R/'predictions.json').exists()
 plan=json.loads((R/'plan.json').read_text());old=json.loads((P/'observations.json').read_text());idx={(r['source'],r['sample_index']):r for r in old};frames=[]
 for s in plan['sources']:
  assert dmd.file_sha256(s['path'])==s['sha256']
  cap=cv2.VideoCapture(s['path']);assert cap.isOpened();fps=cap.get(cv2.CAP_PROP_FPS);n=0;sample=0;next_index=0
  while True:
   ok,f=cap.read()
   if not ok:break
   if n==next_index:
    key=(s['source'],sample)
    if key in idx:
     r={k:v for k,v in idx[key].items() if k not in ['evidence','crop_yes','scene_yes','scheduled_review','baseline_gate','combined_gate']}
     assert r['frame_index']==n and dmd.file_sha256(r['path'])==r['sha256'];r['reused_from_study18']=True
    else:
     im=Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB));p=R/'frames'/f"{s['source']}-{sample:03}.jpg";p.parent.mkdir(exist_ok=True);im.save(p,quality=95)
     r={'source':s['source'],'sample_index':sample,'frame_index':n,'seconds':n/fps,'source_seconds':n/fps,'path':str(p),'sha256':dmd.file_sha256(p),'size':list(im.size),'reused_from_study18':False}
    frames.append(r);sample+=1;next_index=round(sample/2*fps)
   n+=1
  cap.release();assert n==s['decoded_frames']
 save('frame-manifest.json',[{k:r[k] for k in ['source','sample_index','frame_index','seconds','path','sha256','size','reused_from_study18']} for r in frames])
 todo=[r for r in frames if not r['reused_from_study18']];assert len(frames)>96 and len(todo)<60
 torch.set_num_threads(4);from rfdetr import RFDETRMedium
 weights=D/'weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth';assert dmd.file_sha256(weights)==plan['dmd_sha256']
 m=RFDETRMedium(pretrain_weights=str(weights),resolution=1280,num_classes=3)
 for i,r in enumerate(todo,1):
  im=Image.open(r['path']).convert('RGB');torch.cuda.synchronize();t=time.perf_counter();raw=dmd.to_boxes(m.predict(im,threshold=.05));tile=[]
  for win in tile_windows(*im.size,1280,100):tile.extend(to_source(dmd.to_boxes(m.predict(im.crop(win),threshold=.05)),win,im.size))
  r['full_predictions']=[asdict(b) for b in raw if b.score>=.3];r['merged_predictions']=[asdict(b) for b in merge_boxes(raw+tile,.3,.5)]
  torch.cuda.synchronize();r['animal_detector_seconds']=time.perf_counter()-t;state('animal',ready=i,total=len(todo))
 del m;gc.collect();torch.cuda.empty_cache()
 from ultralytics import YOLOWorld
 weight=D/'model-comparison-v1/yolov8s-worldv2.pt';assert dmd.file_sha256(weight)==plan['context_weights_sha256']
 m=YOLOWorld(str(weight));m.set_classes(plan['vocabulary'])
 for i,r in enumerate(todo,1):
  im=Image.open(r['path']).convert('RGB');torch.cuda.synchronize();t=time.perf_counter();rr=m.predict(im,imgsz=1280,conf=.3,iou=.5,device=0,verbose=False,max_det=300)[0];boxes=[]
  if rr.boxes is not None:
   for xy,score,cid in zip(rr.boxes.xyxy.cpu().tolist(),rr.boxes.conf.cpu().tolist(),rr.boxes.cls.cpu().tolist()):boxes.append(asdict(dmd.Box(*map(float,xy),plan['class_mapping'][int(cid)],float(score))))
  r['world_full_predictions']=boxes;r['combined_packet']=compose(r['merged_predictions'],boxes);torch.cuda.synchronize();r['context_detector_seconds']=time.perf_counter()-t
  state('context',ready=i,total=len(todo))
 save('predictions.json',frames);state('completed',total=len(frames),reused=96,new=len(todo))
if __name__=='__main__':
 try:main()
 except Exception as e:state('failed',error=str(e)[:1000]);traceback.print_exc();raise
