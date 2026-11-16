"""Locked aerial-video paired detector benchmark; no tuning or production integration."""
from pathlib import Path
from dataclasses import asdict
import sys,json,time,gc,os,traceback,statistics
os.environ['YOLO_CONFIG_DIR']=str(Path.home()/'aerial-data/model-comparison-v1/yolo-config')
import cv2,torch
from PIL import Image
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from tile_inference import tile_windows,to_source,merge_boxes
from role_proposal_composer_v1 import compose
R=Path.home()/'aerial-data/aerial-patrol-v1'
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def status(phase,**kw):
 v={'phase':phase,**kw};save('detector-status.json',v);print(json.dumps(v),flush=True)
def main():
 assert not (R/'paired-predictions.json').exists()
 plan=json.loads((R/'trial-plan.json').read_text());frames=[]
 for source in plan['sources']:
  assert dmd.file_sha256(source['path'])==source['sha256']
  cap=cv2.VideoCapture(source['path']);fps=cap.get(cv2.CAP_PROP_FPS);n=0;sample=0;next_index=0
  while True:
   ok,f=cap.read()
   if not ok:break
   if n==next_index and sample<24:
    im=Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB));p=R/'frames'/f"{source['source']}-{sample:03}.jpg";p.parent.mkdir(exist_ok=True);im.save(p,quality=95)
    frames.append({'source':source['source'],'sample_index':sample,'frame_index':n,'seconds':n/fps,'source_seconds':n/fps,'path':str(p),'sha256':dmd.file_sha256(p),'size':list(im.size)})
    sample+=1;next_index=round(sample/2*fps)
   n+=1
  cap.release();assert n==source['decoded_frames'];assert sample==24
 assert len(frames)==96;save('frame-manifest.json',frames)
 assert all(dmd.file_sha256(f['path'])==f['sha256'] for f in frames)
 torch.set_num_threads(4)
 from rfdetr import RFDETRMedium
 weights=Path.home()/'aerial-data/weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth'
 assert dmd.file_sha256(weights)==plan['dmd_sha256']
 model=RFDETRMedium(pretrain_weights=str(weights),resolution=1280,num_classes=3)
 for i,f in enumerate(frames,1):
  im=Image.open(f['path']).convert('RGB');torch.cuda.synchronize();start=time.perf_counter()
  raw=dmd.to_boxes(model.predict(im,threshold=.05));tile=[]
  for win in tile_windows(*im.size,1280,100):tile.extend(to_source(dmd.to_boxes(model.predict(im.crop(win),threshold=.05)),win,im.size))
  f['full_predictions']=[asdict(b) for b in raw if b.score>=.3];f['merged_predictions']=[asdict(b) for b in merge_boxes(raw+tile,.3,.5)]
  torch.cuda.synchronize();f['animal_detector_seconds']=time.perf_counter()-start
  status('animal_inference',ready=i,total=len(frames))
 del model;gc.collect();torch.cuda.empty_cache()
 from ultralytics import YOLOWorld
 bench=Path.home()/'aerial-data/model-comparison-v1'
 assert dmd.file_sha256(bench/'yolov8s-worldv2.pt')==plan['context_weights_sha256']
 model=YOLOWorld(str(bench/'yolov8s-worldv2.pt'));model.set_classes(plan['vocabulary'])
 for i,f in enumerate(frames,1):
  im=Image.open(f['path']).convert('RGB');torch.cuda.synchronize();start=time.perf_counter()
  result=model.predict(im,imgsz=1280,conf=.3,iou=.5,device=0,verbose=False,max_det=300)[0];context=[]
  if result.boxes is not None:
   for xy,score,cid in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
    context.append(asdict(dmd.Box(*map(float,xy),plan['class_mapping'][int(cid)],float(score))))
  f['world_full_predictions']=context;f['combined_packet']=compose(f['merged_predictions'],context)
  torch.cuda.synchronize();f['context_detector_seconds']=time.perf_counter()-start
  status('context_inference',ready=i,total=len(frames))
 save('paired-predictions.json',frames);status('completed',frames=len(frames))
if __name__=='__main__':
 try:main()
 except Exception as e:status('failed',error=str(e)[:1000]);traceback.print_exc();raise
