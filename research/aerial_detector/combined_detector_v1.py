"""Paired baseline/context-branch inference on locked sources; no model tuning."""
from pathlib import Path
from dataclasses import asdict
import sys,json,time,hashlib,gc,os,traceback
os.environ['YOLO_CONFIG_DIR']=str(Path.home()/'aerial-data/model-comparison-v1/yolo-config')
import cv2,torch
from PIL import Image
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from tile_inference import tile_windows,to_source,merge_boxes
from role_proposal_composer_v1 import compose
R=Path.home()/'aerial-data/combined-gemini-v1'
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def status(phase,**kw):
 s={'phase':phase,**kw};save('detector-status.json',s);print(json.dumps(s),flush=True)
def main():
 assert not (R/'paired-predictions.json').exists()
 plan=json.loads((R/'trial-plan.json').read_text());source=json.loads((R/'r7-source.json').read_text())
 assert dmd.file_sha256(source['path'])==source['sha256']
 cap=cv2.VideoCapture(source['path']);assert cap.isOpened();fps=cap.get(cv2.CAP_PROP_FPS)
 frames=[];n=0;sample=0;start=plan['source_window'][0];end=plan['source_window'][1];next_index=round(start*fps)
 while True:
  ok,f=cap.read()
  if not ok:break
  if n==next_index and n/fps<end:
   p=R/'frames'/f'rescue-{sample:03}.jpg';p.parent.mkdir(exist_ok=True)
   im=Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB));im.save(p,quality=95)
   frames.append({'source':'rescue','sample_index':sample,'frame_index':n,'seconds':n/fps-start,'source_seconds':n/fps,
    'path':str(p),'sha256':dmd.file_sha256(p),'size':list(im.size),'baseline_reused':False})
   sample+=1;next_index=round((start+sample/2)*fps)
  n+=1
 cap.release();assert n==source['decoded_frames']
 for control in plan['controls']:
  for old in json.loads(Path(control['observations']).read_text()):
   if old['source']!=control['source']:continue
   row={k:old[k] for k in ['source','sample_index','frame_index','seconds','path','sha256','size','merged_predictions','full_predictions']}
   row['source_seconds']=row['seconds'];row['baseline_reused']=True;frames.append(row)
 assert len(frames)==65
 assert all(dmd.file_sha256(f['path'])==f['sha256'] for f in frames)
 save('frame-manifest.json',frames)
 torch.set_num_threads(4);from rfdetr import RFDETRMedium
 weights=Path.home()/'aerial-data/weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth'
 assert dmd.file_sha256(weights)==plan['dmd_sha256']
 model=RFDETRMedium(pretrain_weights=str(weights),resolution=1280,num_classes=3)
 for i,f in enumerate([f for f in frames if not f['baseline_reused']],1):
  im=Image.open(f['path']).convert('RGB');raw=dmd.to_boxes(model.predict(im,threshold=.05));tile=[]
  for win in tile_windows(*im.size,1280,100):tile.extend(to_source(dmd.to_boxes(model.predict(im.crop(win),threshold=.05)),win,im.size))
  f['full_predictions']=[asdict(b) for b in raw if b.score>=.3]
  f['merged_predictions']=[asdict(b) for b in merge_boxes(raw+tile,.3,.5)]
  status('animal_inference',ready=i,total=24)
 del model;gc.collect();torch.cuda.empty_cache()
 from ultralytics import YOLOWorld
 bench=Path.home()/'aerial-data/model-comparison-v1';model=YOLOWorld(str(bench/'yolov8s-worldv2.pt'));model.set_classes(plan['vocabulary'])
 for i,f in enumerate(frames,1):
  im=Image.open(f['path']).convert('RGB');result=model.predict(im,imgsz=1280,conf=.3,iou=.5,device=0,verbose=False,max_det=300)[0]
  context=[]
  if result.boxes is not None:
   for xy,score,cid in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
    label=plan['class_mapping'][int(cid)]
    context.append(asdict(dmd.Box(*map(float,xy),label,float(score))))
  f['world_full_predictions']=context
  f['combined_packet']=compose(f['merged_predictions'],context)
  status('context_inference',ready=i,total=len(frames))
 save('paired-predictions.json',frames);status('completed',frames=len(frames))
if __name__=='__main__':
 try:main()
 except Exception as exc:status('failed',error=str(exc)[:1200]);traceback.print_exc();raise
