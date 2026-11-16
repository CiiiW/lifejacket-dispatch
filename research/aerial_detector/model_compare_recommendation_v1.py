from pathlib import Path
import json,sys,statistics,shutil,nbformat
A=Path.home()/'lifejacket-dispatch/research/aerial_detector';sys.path.insert(0,str(A))
R=Path.home()/'aerial-data/model-comparison-v1'
from role_proposal_composer_v1 import compose
from model_compare_archive_v1 import metrics as match_metrics
import dmd
plan=json.loads((R/'plan.json').read_text())
pred={name:{r['key']:r for r in json.loads((R/(name+'-predictions.json')).read_text())} for name in ['dmd','yolo_world']}
packets=[]
for item in plan['items']:
 packet=compose(pred['dmd'][item['key']]['tiled_plus_full'],pred['yolo_world'][item['key']]['full'])
 packets.append({'key':item['key'],'source':item['source'],'source_sha256':item['source_sha256'],'overview_required':True,**packet})
by={p['key']:p for p in packets};scores=[]
for cohort,cid in [('noaa_seal',1),('coco_context',0),('coco_context',1),('coco_context',2)]:
 tp=fp=fn=0
 for item in [i for i in plan['items'] if i['cohort']==cohort]:
  boxes=[dmd.Box(**b) for b in by[item['key']]['boxes'] if b['class_id']==cid]
  truth=[dmd.Box(**b) for b in item['references'] if b['class_id']==cid]
  a,b,c=match_metrics(boxes,truth,[dmd.Box(**b) for b in item['ignore']]);tp+=a;fp+=b;fn+=c
 scores.append({'cohort':cohort,'class_id':cid,'tp':tp,'fp':fp,'fn':fn,'reference_boxes':tp+fn})
assert next(s for s in scores if s['cohort']=='noaa_seal')['tp']==10
video=json.loads((R/'video-diagnostics.json').read_text());fourk={i['key'] for i in plan['items'] if i['cohort']=='video_diagnostic' and i['size'][0]>=3840}
runtime=[{'model':model,**{method:statistics.median(v['seconds'] for v in video if v['model']==model and v['method']==method and v['key'] in fourk) for method in ['full','tiled_plus_full']}} for model in plan['models']]
report=json.loads((R/'report.json').read_text());report['role_composite']={'scope':'Development composition of cached predictions; no new inference or end-to-end Gemini validation.','animal_branch':'DMD full+tiles','context_branch':'YOLO-World full-frame','metrics':scores}
report['fourk_runtime']=runtime
report['recommendation']='Keep DMD animal proposals for now; prototype YOLO-World person/vehicle context as a separate branch. Improve crop diversity and short temporal evidence; validate marine co-occurrence before deployment.'
(R/'report.json').write_text(json.dumps(report,indent=2))
(R/'role-composite-packets.json').write_text(json.dumps(packets,indent=2))
(R/'role-composite-metrics.json').write_text(json.dumps(scores,indent=2))
lead="""## Recommendation: separate animal detection from context detection

Our existing **DroneMegaDetector remains the strongest seal proposer in this pilot**. At confidence 0.3 with full-frame plus tiles, it matched **10/14** labeled seals; Grounding DINO Tiny matched **2/14**, YOLO-World v2 **0/14**, and YOLOE-26s **6/14**. Unmatched animal proposals were 23, 37, 18 and 86 respectively. This is a small previously inspected regression set, not a held-out benchmark.

**YOLO-World is more promising for the context branch:** on eight labeled COCO controls, full-frame inference matched **23/30 people and 5/6 vehicles**, versus DMD's **11/30 and 0/6**. These are general-image controls; aerial seal-plus-human retention still needs validation.

I built an **offline role-separated proposal prototype**: DMD supplies animal candidates; YOLO-World supplies person/vehicle candidates. Its composed outputs preserve 10/14 seal matches and the 23/30 person, 5/6 vehicle matches on these same inputs. It always requires animal confirmation before context display. Person overlap is a review hint, not a reason to delete an animal proposal. Gemini was not called in this experiment.

YOLO-World's whole-frame median was **0.064 seconds** on eight sampled 4K frames from two clips. DMD's full-plus-tile median was **2.080 seconds** on those frames; the animal branch remains the speed bottleneck. Separate-run timings do not establish combined live throughput.

**Next layer design to validate:** preserve the full overview, select diverse native-resolution animal crops, and verify short crop sequences with Gemini. Keep uncertain candidates available for review. A model swap alone did not solve small-seal detection, false animal proposals, or the crop-budget problem. No production integration, fine-tuning or deployment.

"""
p=R/'README.md';body=p.read_text()
if body.startswith('## Recommendation:'):body=body[body.index('# Alternative detector comparison'):]
body=body.replace('| Model | Whole-frame median / sampled 4K frame | Full+tiles median |','| Model | Whole-frame median / sampled video frame | Full+tiles median |')
body=body.replace('## Practical video runtime','## Practical video runtime (mixed 1080p and 4K inputs)')
text=lead+body+"\n## 4K-only runtime subset\n\n| Model | Full frame | Full+tiles |\n|---|---:|---:|\n"
for row in runtime:text+=f"| {row['model']} | {row['full']:.3f} s | {row['tiled_plus_full']:.3f} s |\n"
text+="\nEight 4K samples from two clips. The earlier mixed-resolution table includes eight 1080p samples as well.\n"
p.write_text(text)
path=A/'notebooks/16_alternative_detector_comparison.ipynb';nb=nbformat.read(path,as_version=4);nb.cells[0].source=text
nbformat.write(nb,path)
dest=A/'results/model-comparison-v1'
for p in R.glob('*.json'):shutil.copy2(p,dest/p.name)
shutil.copy2(R/'README.md',dest/'README.md')
print(json.dumps({'scores':scores,'fourk_runtime':runtime},indent=2))
