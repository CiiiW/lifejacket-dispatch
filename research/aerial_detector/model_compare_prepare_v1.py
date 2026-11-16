from pathlib import Path
from datetime import datetime,timezone
import json,sys,hashlib
from PIL import Image
A=Path.home()/'lifejacket-dispatch/research/aerial_detector';sys.path.insert(0,str(A))
import dmd
R=Path.home()/'aerial-data/model-comparison-v1'
assert not (R/'report.json').exists(),'Completed experiment: choose a new experiment directory before preparing inputs.'
sha=lambda p:dmd.file_sha256(p)
items=[]
old=Path.home()/'aerial-data/seal-tiling-v1'
for i in range(0,24,3):
 s=json.loads((old/'manifest.json').read_text())[i]
 p=Path.home()/'aerial-data/transfer-retention-v1/raw/noaa'/s['key']
 items.append({'key':'seal-'+str(i+1).zfill(2),'cohort':'noaa_seal','source':str(p),'source_sha256':s['source_sha256'],'size':s['source_size'],'references':s['references'],'annotated_classes':[1],'ignore':[],'prior_source_index':i+1,'flight':s['flight']})
prior=Path.home()/'aerial-data/transfer-retention-v1'
doc=json.loads((prior/'instances_val2017.json').read_text())
handoff=json.loads((Path.home()/'aerial-data/gemini-handoff-v1/manifest.json').read_text())
for s in [v for v in handoff if v['dataset']=='coco']:
 p=Path(s['source']);image_id=int(p.stem);refs=[];ignore=[]
 for ann in doc['annotations']:
  if ann['image_id']!=image_id:continue
  cid=ann['category_id']
  label=0 if cid==1 else 2 if cid in [2,3,4,5,6,7,8,9] else 1 if cid in [16,17,18,19,20,21,22,23,24] else None
  if label is None:continue
  b=dmd.Box.from_xywh(ann['bbox'],label)
  from dataclasses import asdict
  (ignore if ann.get('iscrowd') else refs).append(asdict(b))
 with Image.open(p) as im:size=list(im.size)
 items.append({'key':'coco-'+p.stem,'cohort':'coco_context','source':str(p),'source_sha256':sha(p),'size':size,'references':refs,'annotated_classes':[0,1,2],'ignore':ignore})
for folder,source in [('strict-fresh-v1','dog_walk'),('marine-validation-v1','beach_people'),('mixed-scene-v1','mixed'),('marine-validation-extra-v1','ocean_rocks_candidate')]:
 rows=json.loads((Path.home()/'aerial-data'/folder/'observations.json').read_text())
 for s in [v for v in rows if v['source']==source and v['sample_index'] in [0,6,12,18]]:
  items.append({'key':source+'-'+str(s['sample_index']).zfill(3),'cohort':'video_diagnostic','source':s['path'],'source_sha256':s['sha256'],'size':s['size'],'references':[],'annotated_classes':[],'ignore':[],'video_source':source,'seconds':s['seconds']})
assert len(items)==32
assert all(sha(s['source'])==s['source_sha256'] for s in items)
vocab=['seal','sea lion','sea otter','dog','horse','cat','sheep','cow','elephant','bear','zebra','giraffe','person','bicycle','car','motorcycle','airplane','bus','train','truck','boat']
mapping=[1]*12+[0]+[2]*8
plan={'created_at':datetime.now(timezone.utc).isoformat(),'scope':'Exploratory comparison on previously inspected sources; no held-out performance claim.',
'items':items,'models':['dmd','grounding_dino','yolo_world','yoloe26'],'vocabulary':vocab,'class_mapping':mapping,
'models_ids':{'dmd':'DroneMegaDetector RFDETRMedium 2026.10.04','grounding_dino':'IDEA-Research/grounding-dino-tiny','yolo_world':'yolov8s-worldv2.pt','yoloe26':'yoloe-26s-seg.pt'},
'raw_floor':.1,'primary_confidence':.3,'diagnostic_thresholds':[.1,.3,.5],'grounding_dino_text_threshold':.2,'tile_size':1280,'overlap':100,'merge_iou':.5,'match_iou':.5,
'preprocessing':'Same original images and tile geometry; each model native preprocessing. DMD1280, YOLO1280, GroundingDINO processor defaults.',
'metrics':'Per-class greedy IoU0.5, NOAA animal refs only; COCO full relevant-class refs, ignore crowd overlaps. Videos are qualitative only, not accuracy.',
'noaa_subset':'Every third image in existing 24-image manifest, chosen before new inference. Eight sources across available flights.',
'baseline_sha256':dmd.DMD_SHA256,'no_new_gemini_calls':True}
(R/'plan.json').write_text(json.dumps(plan,indent=2))
print('Locked',len(items),'sources',sum(len(s['references']) for s in items if s['cohort']=='noaa_seal'),'seal refs',sum(len(s['references']) for s in items if s['cohort']=='coco_context'),'COCO context refs')
print('SETUP',(R/'setup.log').read_text()[-1800:])
