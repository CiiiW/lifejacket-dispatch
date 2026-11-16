"""Score fixed detector comparison and build notebook16. No training or Gemini."""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import json,sys,time,statistics,shutil,traceback
from PIL import Image,ImageDraw
import nbformat
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from tile_inference import merge_boxes
R=Path.home()/'aerial-data/model-comparison-v1'
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def crowd_overlap(p,c):
 x=max(0,min(p.x2,c.x2)-max(p.x1,c.x1));y=max(0,min(p.y2,c.y2)-max(p.y1,c.y1))
 return x*y/max(p.area,1e-12)
def metrics(pred,truth,ignore):
 pred=[p for p in pred if not any(p.class_id==c.class_id and crowd_overlap(p,c)>.5 for c in ignore)]
 tp,fp,fn=dmd.match_image(pred,truth,.5)
 return tp,fp,fn
def main():
 deadline=time.monotonic()+1800
 while True:
  p=R/'controller-status.json';codes=json.loads(p.read_text()) if p.exists() else {}
  if 'yoloe26' in codes:break
  if time.monotonic()>deadline:raise RuntimeError('Benchmark wait timeout; inspect model status')
  time.sleep(3)
 plan=json.loads((R/'plan.json').read_text());items=plan['items']
 completed=[m for m in plan['models'] if (R/(m+'-predictions.json')).exists()]
 failed=[m for m in plan['models'] if m not in completed]
 data={m:{r['key']:r for r in json.loads((R/(m+'-predictions.json')).read_text())} for m in completed}
 rows=[];video=[]
 for model in completed:
  for method in ['full','tiled_plus_full']:
   for threshold in plan['diagnostic_thresholds']:
    for cohort,classes in [('noaa_seal',[1]),('coco_context',[0,1,2])]:
     for cid in classes:
      tp=fp=fn=top3=top8=0;seconds=[];images=0
      for item in [i for i in items if i['cohort']==cohort]:
       row=data[model][item['key']];pred=[dmd.Box(**b) for b in row[method] if b['class_id']==cid and b['score']>=threshold]
       pred.sort(key=lambda b:-b.score)
       truth=[dmd.Box(**b) for b in item['references'] if b['class_id']==cid]
       ignore=[dmd.Box(**b) for b in item['ignore']]
       a,b,c=metrics(pred,truth,ignore);tp+=a;fp+=b;fn+=c
       top3+=metrics(pred[:3],truth,ignore)[0];top8+=metrics(pred[:8],truth,ignore)[0]
       seconds.append(row[method+'_seconds']);images+=1
      rows.append({'model':model,'method':method,'threshold':threshold,'cohort':cohort,'class_id':cid,'tp':tp,'fp':fp,'fn':fn,
       'precision':tp/(tp+fp) if tp+fp else 0.,'recall':tp/(tp+fn) if tp+fn else None,
       'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,'top3_tp':top3,'top8_tp':top8,'images':images,'reference_boxes':tp+fn,
       'median_seconds':statistics.median(seconds)})
   for item in [i for i in items if i['cohort']=='video_diagnostic']:
    row=data[model][item['key']]
    pred=[b for b in row[method] if b['score']>=.3]
    video.append({'model':model,'method':method,'key':item['key'],'video_source':item['video_source'],
     'animal_proposals':sum(b['class_id']==1 for b in pred),'person_proposals':sum(b['class_id']==0 for b in pred),
     'vehicle_proposals':sum(b['class_id']==2 for b in pred),'unmapped_proposals':sum(b['class_id']==3 for b in pred),
     'seconds':row[method+'_seconds']})
 primary=[r for r in rows if r['threshold']==.3 and r['cohort']=='noaa_seal' and r['method']=='tiled_plus_full']
 hybrids=[]
 if 'dmd' in completed:
  for model in [m for m in completed if m!='dmd']:
   tp=fp=fn=top3=top8=0
   for item in [i for i in items if i['cohort']=='noaa_seal']:
    raw=[dmd.Box(**b) for m in ['dmd',model] for b in data[m][item['key']]['tiled_plus_full'] if b['class_id']==1]
    pred=merge_boxes(raw,.3,.5);truth=[dmd.Box(**b) for b in item['references']]
    a,b,c=metrics(pred,truth,[]);tp+=a;fp+=b;fn+=c;top3+=metrics(pred[:3],truth,[])[0];top8+=metrics(pred[:8],truth,[])[0]
   hybrids.append({'models':['dmd',model],'tp':tp,'fp':fp,'fn':fn,'top3_tp':top3,'top8_tp':top8,
    'note':'Exploratory union with raw score ranking; cross-model confidence is not calibrated.'})
 save('metrics.json',rows);save('video-diagnostics.json',video);save('hybrid-diagnostics.json',hybrids)
 audit={'source_hashes':all(dmd.file_sha256(i['source'])==i['source_sha256'] for i in items),'inputs_count':len(items),
  'completed_models':completed,'failed_models':failed,
  'prediction_manifest':all(len(data[m])==len(items) and all(data[m][i['key']]['source_sha256']==i['source_sha256'] for i in items) for m in completed),
  'plan_hashes':all(json.loads((R/(m+'-metadata.json')).read_text())['plan_sha256']==dmd.file_sha256(R/'plan.json') for m in completed)}
 assert audit['source_hashes'] and audit['prediction_manifest'] and audit['plan_hashes']
 save('audit.json',audit)
 # Fixed examples; visual crops are display-only and are not inference inputs.
 previews=[]
 selected=['seal-01','seal-10','dog_walk-006','beach_people-018']
 for key in selected:
  item=next(i for i in items if i['key']==key);source=Image.open(item['source']).convert('RGB')
  canvas=Image.new('RGB',(1200,1120),'#102633');pen=ImageDraw.Draw(canvas)
  for k,model in enumerate(completed[:4]):
   x0=(k%2)*600;y0=(k//2)*560
   pred=[dmd.Box(**b) for b in data[model][key]['tiled_plus_full'] if b['score']>=.3]
   im=source.copy();im.thumbnail((580,320));d=ImageDraw.Draw(im)
   sx=im.width/source.width;sy=im.height/source.height
   for b in [dmd.Box(**v) for v in item['references']]:
    d.rectangle((b.x1*sx,b.y1*sy,b.x2*sx,b.y2*sy),outline='white',width=2)
   for b in pred:
    d.rectangle((b.x1*sx,b.y1*sy,b.x2*sx,b.y2*sy),outline={0:'cyan',1:'lime',2:'orange',3:'gray'}[b.class_id],width=1)
   pen.text((x0+8,y0+4),model+' | '+key+' | green=animal proposals',fill='white');canvas.paste(im,(x0+8,y0+26))
   animals=sorted([p for p in pred if p.class_id==1],key=lambda b:-b.score)[:3]
   pen.text((x0+8,y0+352),'Top 3 proposed-animal crops; no Gemini verification',fill='white')
   for j,b in enumerate(animals):
    margin=max(128,(b.x2-b.x1),(b.y2-b.y1));cx=(b.x1+b.x2)/2;cy=(b.y1+b.y2)/2
    crop=source.crop((max(0,int(cx-margin)),max(0,int(cy-margin)),min(source.width,int(cx+margin)),min(source.height,int(cy+margin))))
    crop.thumbnail((185,175));canvas.paste(crop,(x0+8+j*195,y0+378))
  p=R/(key+'-comparison.jpg');canvas.save(p,quality=92);previews.append(str(p))
 report={'scope':plan['scope'],'completed_models':completed,'failed_models':failed,'primary_seal_results':primary,
  'seal_reference_boxes':sum(len(i['references']) for i in items if i['cohort']=='noaa_seal'),
  'images':len(items),'new_gemini_calls':0,'hybrids':hybrids,'previews':previews,
  'limits':['Small previously inspected cohort, not fresh test or rescue validation; NOAA8 images14 boxes and COCO8 images36 relevant refs.',
   'Videos have no independent box annotations: proposal counts and examples only, no video accuracy claim.',
   'Fixed score0.3 is not calibrated across models; the 0.1/0.3/0.5 sweep is exploratory and no tuned threshold is validated.',
   'Same native source/tile geometry, but native model preprocessing and built-in per-pass postprocessing differ.',
   'YOLOE segmentation checkpoint runs its native mask branch; runtime is practical checkpoint cost, not detection-only export speed.',
   'NOAA only animal references scored; context there is unannotated. COCO crowd overlaps ignored by detection IoA>0.5.',
   'No production integration, fine-tuning, or deployment. A replacement requires separate flight/video validation.']}
 save('report.json',report)
 text="# Alternative detector comparison\n\n"
 text+="Exploratory GPU comparison of our current DroneMegaDetector against open-vocabulary alternatives. The same locked sources and 1280-pixel tile windows were used; native model preprocessing differs. **No Gemini calls, fine-tuning or deployment.**\n\n"
 text+="## Labeled seals: full image plus tiles\n\n| Model | Matched seals / 14 | Unmatched animal proposals | Matched in top 3 | Median seconds / large NOAA image |\n|---|---:|---:|---:|---:|\n"
 for s in primary:text+=f"| {s['model']} | {s['tp']}/14 | {s['fp']} | {s['top3_tp']}/14 | {s['median_seconds']:.2f} |\n"
 text+="\nEight previously inspected NOAA sources, fourteen reference boxes. IoU0.5 matching; fixed confidence0.3. This is a small regression comparison, not held-out accuracy. Unmatched proposals are defined against available annotations. Confidence scales differ between models.\n\n"
 text+="## Person/vehicle retention on labeled COCO controls\n\n| Model | Class | Matched / references | Unmatched proposals |\n|---|---|---:|---:|\n"
 for s in rows:
  if s['threshold']==.3 and s['cohort']=='coco_context' and s['method']=='tiled_plus_full' and s['class_id'] in [0,2]:
   text+=f"| {s['model']} | {['person','animal','vehicle'][s['class_id']]} | {s['tp']}/{s['reference_boxes']} | {s['fp']} |\n"
 text+="\nThese controls test proposal retention only, before any animal-presence display gate. They are general COCO images, not aerial rescue footage.\n\n"
 text+="## Practical video runtime\n\n| Model | Whole-frame median / sampled 4K frame | Full+tiles median |\n|---|---:|---:|\n"
 for model in completed:
  full=[v['seconds'] for v in video if v['model']==model and v['method']=='full'];tile=[v['seconds'] for v in video if v['model']==model and v['method']=='tiled_plus_full']
  text+=f"| {model} | {statistics.median(full):.3f} s | {statistics.median(tile):.3f} s |\n"
 text+="\nWarm synchronized GPU timing excludes disk decode, model downloads and loading. It includes native inference, image crops and merge. It does not establish live-stream throughput or end-to-end Gemini latency.\n\n"
 if failed:text+="**Execution failures:** "+', '.join(failed)+". Check per-model logs; these are not accuracy results.\n\n"
 text+="## What this does and does not answer\n\nThe model swap must improve animal proposal coverage without flooding Gemini or losing people/vehicles. Read matched-in-top-three alongside total matches: a high-recall pool is not enough if the evidence budget excludes the true animal. Video examples show proposed-animal crops; the animals and contextual boxes in those clips are not exhaustively annotated.\n\n"
 text+="Threshold sweeps, per-class metrics, exploratory DMD+challenger unions, source hashes, weights/revisions, model versions and full predictions are archived. Hybrid confidence scores are not calibrated. No single winner should be promoted from fourteen seal boxes.\n\n"
 text+="## Sources for the model choices\n\n- [DroneMegaDetector](https://github.com/ConservationDronesAI/DroneMegaDetector)\n- [Grounding DINO](https://huggingface.co/docs/transformers/model_doc/grounding-dino)\n- [YOLO-World](https://docs.ultralytics.com/models/yolo-world/)\n- [YOLOE](https://docs.ultralytics.com/models/yoloe/)\n"
 (R/'README.md').write_text(text)
 dest=A/'results/model-comparison-v1';dest.mkdir(parents=True,exist_ok=True)
 for p in R.glob('*.json'):shutil.copy2(p,dest/p.name)
 for p in R.glob('*comparison.jpg'):shutil.copy2(p,dest/p.name)
 shutil.copy2(R/'README.md',dest/'README.md')
 template=nbformat.read(A/'notebooks/15_stricter_confirmation.ipynb',as_version=4)
 nb=nbformat.v4.new_notebook(metadata=template.metadata)
 nb.cells=[nbformat.v4.new_markdown_cell(text),nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/model-comparison-v1'\nprint((R/'audit.json').read_text())\nprint((R/'report.json').read_text())")]
 for p in previews:nb.cells+=[nbformat.v4.new_markdown_cell('## '+Path(p).stem),nbformat.v4.new_code_cell(f"display(Image(filename={p!r}))")]
 nb.cells+=[nbformat.v4.new_markdown_cell("## Reproduce\nmodel_compare_prepare_v1.py freezes the cohort; model_compare_infer_v1.py runs one detector; model_compare_archive_v1.py scores and renders. Model downloads and setup are separate from timed inference.")]
 nbformat.write(nb,A/'notebooks/16_alternative_detector_comparison.ipynb')
 print(json.dumps(report,indent=2),flush=True);print('Saved notebook16',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise

if __name__=='__main__':
 import runpy
 runpy.run_path(str(A/'model_compare_recommendation_v1.py'))
