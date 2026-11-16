"""Actual Gemini animal verification shared by paired context branches."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json,sys,time,traceback,statistics,shutil
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import video_patrol_review_v1 as crop
import independent_scene_review_v1 as scene
from evidence_gate_v1 import EvidenceGate
from patrol_memory import PatrolMemory
R=Path.home()/'aerial-data/aerial-patrol-v1';crop.ROOT=R;scene.ROOT=R
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def main():
 assert not (R/'report.json').exists()
 while not (R/'paired-predictions.json').exists():
  p=R/'detector-status.json'
  if p.exists() and json.loads(p.read_text())['phase']=='failed':raise RuntimeError(p.read_text())
  time.sleep(2)
 frames=json.loads((R/'paired-predictions.json').read_text());selected=[f for f in frames if f['sample_index']%6==0]
 assert len(selected)==16
 tasks=[(mode,f) for f in selected for mode in ['crop','scene']]
 def call(task):
  request_start=time.perf_counter()
  mode,f=task
  result=crop.verify(f) if mode=='crop' else scene.call({**f,'study_source':f['source']})
  result['wall_seconds']=time.perf_counter()-request_start
  print(mode,result['key'],result['status'],flush=True);return mode,result
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(call,tasks))
 cr=[r for m,r in results if m=='crop'];sr=[r for m,r in results if m=='scene']
 save('crop-reviews.json',cr);save('scene-reviews.json',sr)
 ci={(r['source'],r['sample_index']):r for r in cr};si={(r['source'],r['sample_index']):r for r in sr}
 out=[];summary=[]
 for source in dict.fromkeys(f['source'] for f in frames):
  eg=EvidenceGate();baseline=PatrolMemory();combined=PatrolMemory()
  for f in [f for f in frames if f['source']==source]:
   key=(source,f['sample_index']);c=ci.get(key);s=si.get(key)
   cy=bool(c and c['status']=='success' and c['animal_confirmed']);sy=bool(s and s['status']=='success' and s['data']['nonhuman_animal_visible']=='yes')
   cf=bool(c and (c['status']!='success' or c['uncertain']));sf=bool(s and (s['status']!='success' or s['data']['nonhuman_animal_visible']=='uncertain'))
   evidence=eg.update(source,f['seconds'],scheduled=bool(c or s),crop_yes=cy,scene_yes=sy)
   candidate=any(b['class_id']==1 for b in f['merged_predictions'])
   counts={}
   for arm,boxes,mem in [('baseline',f['merged_predictions'],baseline),('combined',f['combined_packet']['boxes'],combined)]:
    persons=sum(b['class_id']==0 for b in boxes);vehicles=sum(b['class_id']==2 for b in boxes)
    counts[arm]=mem.update(source,f['seconds'],animal_candidate=candidate,animal_confirmed=evidence['confirmed'],persons=persons,vehicles=vehicles,review_failed=cf or sf)
   assert counts['baseline']['context_visible']==counts['combined']['context_visible']
   out.append({**f,'crop_yes':cy,'scene_yes':sy,'scheduled_review':bool(c or s),'evidence':evidence,'baseline_gate':counts['baseline'],'combined_gate':counts['combined']})
  rows=[o for o in out if o['source']==source];checks=[r for r in cr if r['source']==source];scs=[r for r in sr if r['source']==source]
  active=[r for r in rows if r['combined_gate']['context_visible']]
  summary.append({'source':source,'samples':len(rows),'scheduled_checks':len(checks),
   'crop_animal_confirmations':sum(r['status']=='success' and r['animal_confirmed'] for r in checks),
   'scene_animal_confirmations':sum(r['status']=='success' and r['data']['nonhuman_animal_visible']=='yes' for r in scs),
   'gate_open_samples':len(active),'first_gate_source_seconds':active[0]['source_seconds'] if active else None,
   **{arm+'_'+kind+'_shown_samples':sum(bool(r[arm+'_gate']['shown_'+kind]) for r in rows) for arm in ['baseline','combined'] for kind in ['persons','vehicles']},
   **{arm+'_any_context_shown_samples':sum(bool(r[arm+'_gate']['shown_persons'] or r[arm+'_gate']['shown_vehicles']) for r in rows) for arm in ['baseline','combined']}})
 save('observations.json',out)
 report={'scope':'Fixed paired pipeline on four new aerial stock clips: platform pinnipeds, surf animal, rocky-islet pinnipeds, and crowded-beach control. Not DJI field or annotated-box accuracy validation.',
 'summary':summary,'requests':len(results),'failed_requests':sum(r['status']!='success' for _,r in results),'usage':crop.g.usage_sum([r for _,r in results]),
 'paired_design':'Identical DMD animal proposals and identical Gemini image inputs/decisions for both arms. Only context detections differ: DMD baseline versus YOLO-World full-frame context.',
 'gate':'Frozen same-check crop+scene agreement OR two consecutive scene yes checks within four seconds, then existing three-second source-scene hold.',
 'limits':['All four sources are aerial views newly reviewed in this study; source equipment/altitude and model pretraining overlap are not independently known.',
 'Only one newly reviewed crowded-beach control; screening cannot prove exhaustive animal absence. No verified marine-plus-person/vehicle co-occurrence positive in these clips.',
 'Context shown means gated detector proposals; no exhaustive bounding-box or identity truth and no validation of each displayed box.',
 'Source-time replay excludes model/API scheduling latency. Native-video shot cuts and current animal disappearance timestamps are not annotated.',
 'Animal confirmation is non-human mammal presence, not injury, urgency, danger or rescue need. No automatic incident/dispatch.',
 'No production integration or deployment; training weights and prompts unchanged.']}
 save('report.json',report)
 dest=A/'results/aerial-patrol-v1';dest.mkdir(parents=True,exist_ok=True)
 for name in ['trial-plan.json','sources.json','control-source.json','frame-manifest.json','paired-predictions.json','crop-reviews.json','scene-reviews.json','observations.json','report.json']:shutil.copy2(R/name,dest/name)
 print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
