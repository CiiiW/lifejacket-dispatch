"""Exploratory GPU benchmark. Fixed manifest/prompt; no Gemini calls."""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
from datetime import datetime,timezone
import os,sys,json,time,hashlib,traceback,importlib.metadata
os.environ['YOLO_CONFIG_DIR']=str(Path.home()/'aerial-data/model-comparison-v1/yolo-config')
os.environ['HF_HUB_DISABLE_XET']='1'
import torch
from PIL import Image
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from tile_inference import tile_windows,to_source,merge_boxes
R=Path.home()/'aerial-data/model-comparison-v1'
def save(n,x):
 p=R/n;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,indent=2,default=str));tmp.replace(p)
def state(model,phase,**kw):
 v={'model':model,'phase':phase,'at':datetime.now(timezone.utc).isoformat(),**kw};save(model+'-status.json',v);print(json.dumps(v),flush=True)
def main(name):
 plan=json.loads((R/'plan.json').read_text());assert not (R/(name+'-predictions.json')).exists()
 torch.set_num_threads(4);assert torch.cuda.is_available()
 vocab=plan['vocabulary'];mapping=plan['class_mapping'];label_counts=Counter();unknown=Counter()
 meta={'model':name,'gpu':torch.cuda.get_device_name(0),'plan_sha256':dmd.file_sha256(R/'plan.json'),'versions':{n:importlib.metadata.version(n) for n in ['torch','torchvision','transformers']}}
 state(name,'loading')
 if name=='dmd':
  from rfdetr import RFDETRMedium
  weights=Path.home()/'aerial-data/weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth'
  assert dmd.file_sha256(weights)==plan['baseline_sha256']
  model=RFDETRMedium(pretrain_weights=str(weights),resolution=1280,num_classes=3)
  meta.update(weights_sha256=dmd.file_sha256(weights))
  def infer(im):return dmd.to_boxes(model.predict(im,threshold=plan['raw_floor']))
 elif name in ['yolo_world','yoloe26']:
  from ultralytics import YOLOWorld,YOLOE
  model=YOLOWorld('yolov8s-worldv2.pt') if name=='yolo_world' else YOLOE('yoloe-26s-seg.pt');model.set_classes(vocab)
  meta.update(weights_sha256=dmd.file_sha256(Path(model.ckpt_path)),ultralytics=importlib.metadata.version('ultralytics'),vocabulary=vocab)
  def infer(im):
   result=model.predict(im,imgsz=1280,conf=plan['raw_floor'],iou=.5,device=0,verbose=False,max_det=300)[0]
   out=[]
   if result.boxes is None:return out
   for xy,score,cid in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
    idx=int(cid);label_counts[vocab[idx]]+=1;out.append(dmd.Box(*map(float,xy),mapping[idx],float(score)))
   return out
 elif name=='grounding_dino':
  from transformers import AutoProcessor,AutoModelForZeroShotObjectDetection
  from huggingface_hub import hf_hub_download
  repo='IDEA-Research/grounding-dino-tiny'
  cfg=Path(hf_hub_download(repo,'config.json'));revision=cfg.parent.name
  processor=AutoProcessor.from_pretrained(repo,revision=revision);model=AutoModelForZeroShotObjectDetection.from_pretrained(repo,revision=revision,use_safetensors=True).to('cuda').eval()
  text='. '.join(vocab)+'.'
  assert cfg.exists()
  meta.update(repo=repo,revision=revision,weight_hashes={p.name:dmd.file_sha256(p) for p in cfg.parent.glob('*.safetensors')},prompt=text,processor_size=processor.image_processor.size)
  def classify(label):
   if isinstance(label,int) and 0<=label<len(mapping):return mapping[label]
   label=str(label).lower().strip();found={mapping[i] for i,v in enumerate(vocab) if v in label}
   if len(found)==1:return found.pop()
   unknown[label]+=1;return 3
  def infer(im):
   inputs=processor(images=im,text=text,return_tensors='pt').to('cuda')
   with torch.inference_mode():outputs=model(**inputs)
   result=processor.post_process_grounded_object_detection(outputs,inputs.input_ids,threshold=plan['raw_floor'],text_threshold=plan['grounding_dino_text_threshold'],target_sizes=[im.size[::-1]])[0]
   labels=result.get('text_labels',result.get('labels'))
   out=[]
   for xy,score,label in zip(result['boxes'].cpu().tolist(),result['scores'].cpu().tolist(),labels):
    if hasattr(label,'item'):label=label.item()
    label_counts[str(label)]+=1;out.append(dmd.Box(*map(float,xy),classify(label),float(score)))
   return out
 else:raise ValueError(name)
 image=Image.open(plan['items'][0]['source']).convert('RGB')
 infer(image.crop((0,0,1280,1280)));torch.cuda.synchronize()
 records=[]
 for i,item in enumerate(plan['items'],1):
  assert dmd.file_sha256(item['source'])==item['source_sha256']
  with Image.open(item['source']) as h:im=h.convert('RGB')
  torch.cuda.synchronize();t=time.perf_counter();full_raw=infer(im);torch.cuda.synchronize();full_time=time.perf_counter()-t
  windows=tile_windows(*im.size,plan['tile_size'],plan['overlap'])
  torch.cuda.synchronize();t=time.perf_counter();tile_raw=[]
  for win in windows:tile_raw.extend(to_source(infer(im.crop(win)),win,im.size))
  torch.cuda.synchronize();tiles_time=time.perf_counter()-t
  t=time.perf_counter()
  full=merge_boxes(full_raw,plan['raw_floor'],plan['merge_iou'])
  combined=merge_boxes(full_raw+tile_raw,plan['raw_floor'],plan['merge_iou'])
  merge_time=time.perf_counter()-t
  record={'key':item['key'],'source_sha256':item['source_sha256'],'full':[asdict(b) for b in full],'tiled_plus_full':[asdict(b) for b in combined],'full_seconds':full_time,'tiled_plus_full_seconds':full_time+tiles_time+merge_time,'tiles':len(windows)}
  records.append(record);save(name+'-progress.json',records);state(name,'inference',images_ready=i,images_total=len(plan['items']))
 meta.update(label_counts=dict(label_counts),unmapped_labels=dict(unknown),timing='Synchronized warm GPU prediction/crop/merge; excludes file decode, loading, downloads and one warmup.')
 save(name+'-metadata.json',meta);save(name+'-predictions.json',records);state(name,'completed',images=len(records))
if __name__=='__main__':
 name=sys.argv[1]
 try:main(name)
 except Exception as exc:state(name,'failed',error=str(exc)[:1500]);traceback.print_exc();raise
