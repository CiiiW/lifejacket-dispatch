"""Audit complete-video verification and render before/after replay artifacts."""
from pathlib import Path
from collections import Counter
import json,sys,time,hashlib,shutil,statistics,traceback
from PIL import Image,ImageDraw,ImageFont
import nbformat
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from context_video_policy_v1 import AnimalEvidence,classify_context,check_policy
from evidence_gate_v1 import check_gate
from patrol_memory import check_policy as check_memory
D=Path.home()/'aerial-data';R=D/'context-video-v1';sha=dmd.file_sha256
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def main():
 deadline=time.monotonic()+1800
 while not (R/'observations.json').exists():
  status=R/'review-status.json'
  if status.exists() and json.loads(status.read_text())['phase']=='failed':raise RuntimeError(status.read_text())
  if time.monotonic()>deadline:raise RuntimeError('Review wait timeout')
  time.sleep(2)
 rows=json.loads((R/'observations.json').read_text());animal=json.loads((R/'animal-reviews.json').read_text());contexts=json.loads((R/'context-reviews.json').read_text())
 plan=json.loads((R/'plan.json').read_text());phase=json.loads((R/'phase-plan.json').read_text());ap=json.loads((R/'animal-review-plan.json').read_text());cp=json.loads((R/'context-review-plan.json').read_text())
 aerial=[r for r in rows if r['cohort']=='aerial'];ground=[r for r in rows if r['cohort']!='aerial']
 def image_hashes(root,v,kind):
  if v['status']!='success':return True
  if kind=='crop':paths=[root/'verification-inputs'/v['key']/'context.jpg']+sorted((root/'verification-inputs'/v['key']).glob('region-*.jpg'));return [sha(p) for p in paths]==v['input_sha256']
  return sha(root/'scene-inputs'/(v['key']+'.jpg'))==v['input_sha256']
 audit={
 'source_hashes':all(sha(s['path'])==s['sha256'] for s in plan['sources']),
 'all_frame_hashes':all(sha(r['path'])==r['sha256'] for r in rows),
 'frozen_original_code':all(sha(A/n)==v for n,v in plan['code_hashes'].items()),
 'phase_code':all(sha(A/n)==v for n,v in phase['code_hashes'].items()),
 'trial_hash':sha(R/'plan.json')==phase['trial_sha256']==ap['trial_sha256'],
 'review_code_matches_context_plan':sha(A/'context_video_review_v1.py')==cp['driver_sha256'],
 'context_policy_matches_plan':sha(A/'context_video_policy_v1.py')==cp['policy_sha256'],
 'dmd_weights':sha(D/'weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth')==plan['dmd_sha256'],
 'context_weights':sha(D/'model-comparison-v1/yolov8s-worldv2.pt')==plan['context_weights_sha256'],
 'animal_review_input_hashes':all(image_hashes(R/'animal-review',x['review'],x['mode']) for x in animal),
 'context_review_input_hashes':all(image_hashes(R/'context-review',x['review'],'crop') for x in contexts),
 'complete_context_task_count':len(contexts)==len(cp['tasks']),
 'exact_region_mapping':all(classify_context(x['boxes'],x['review'])==x['checks'] for x in contexts),
 'no_accepted_box_without_class_agreement':all(c['accepted']==(c['proposed_class']==c['reviewed_class']) for x in contexts for c in x['checks'])
 }
 oldidx={(r['source'],r['sample_index']):r for r in json.loads((D/'aerial-patrol-v1/observations.json').read_text())}
 audit['complete_source_sample_grid']=all([r['frame_index'] for r in aerial if r['source']==s['source']]==[round(i/2*s['fps']) for i in range(1000) if round(i/2*s['fps'])<s['decoded_frames']] for s in plan['sources'])
 audit['96_prior_predictions_identical']=sum(r['reused_from_study18'] for r in aerial)==96 and all(r['merged_predictions']==oldidx[(r['source'],r['sample_index'])]['merged_predictions'] and r['combined_packet']==oldidx[(r['source'],r['sample_index'])]['combined_packet'] for r in aerial if r['reused_from_study18'])
 ci={(x['review']['source'],x['review']['sample_index']):x['review'] for x in animal if x['mode']=='crop'};si={(x['review']['source'],x['review']['sample_index']):x['review'] for x in animal if x['mode']=='scene'}
 old=AnimalEvidence(False);clear=AnimalEvidence(True);ok=True
 for r in aerial:
  key=(r['source'],r['sample_index'])
  ok &= old.update(r,ci.get(key),si.get(key))==r['old_animal_state'];ok &= clear.update(r,ci.get(key),si.get(key))==r['clear_animal_state']
 audit['both_animal_policy_replays']=bool(ok)
 audit['every_eligible_box_reviewed']=all((not(r['old_animal_state']['gate']['context_visible'] or r['clear_animal_state']['gate']['context_visible'])) or len(r['context_checks'])==sum(b['class_id'] in [0,2] for b in r['combined_packet']['boxes']) for r in rows)
 audit['display_requires_gate_and_acceptance']=all(not r[k]['shown_persons'] and not r[k]['shown_vehicles'] if not r[state]['gate']['context_visible'] else r[k]['shown_persons']==sum(c['accepted'] and c['box']['class_id']==0 for c in r['context_checks']) and r[k]['shown_vehicles']==sum(c['accepted'] and c['box']['class_id']==2 for c in r['context_checks']) for r in rows for k,state in [('context_verified','old_animal_state'),('context_verified_clear','clear_animal_state')])
 correction=json.loads((R/'ground-scope-correction.json').read_text())
 audit['ground_scope_correction_verified']=sha(R/'observations.json')==correction['corrected_observations_sha256'] and sha(R/'observations-before-ground-scope-correction.json')==correction['raw_observations_sha256'] and len(ground)==24
 audit['unique_frame_keys']=len({(r['source'],r['sample_index']) for r in rows})==len(rows)
 audit['all_context_tasks_reference_final_frames']=all(any(r['source']==t['frame_source'] and r['sample_index']==t['sample_index'] and r['sha256']==t['frame_sha256'] for r in rows) for t in cp['tasks'])
 assert all(audit.values()),audit;save('audit.json',audit)
 fixtures=check_policy()+check_gate()+check_memory();save('policy-checks.json',fixtures)
 summary=[]
 for source in dict.fromkeys(r['source'] for r in rows):
  rr=[r for r in rows if r['source']==source]
  summary.append({'source':source,'cohort':rr[0]['cohort'],'samples':len(rr),
   'old_animal_gate_frames':sum(r['old_animal_state']['gate']['context_visible'] for r in rr),
   'clearing_animal_gate_frames':sum(r['clear_animal_state']['gate']['context_visible'] for r in rr),
   'dual_negative_checks':sum(r['clear_animal_state'].get('negative_cleared',False) for r in rr),
   'raw_people_frames':sum(bool(r['old_animal_state']['gate']['shown_persons']) for r in rr),
   'raw_vehicle_frames':sum(bool(r['old_animal_state']['gate']['shown_vehicles']) for r in rr),
   'verified_people_frames':sum(bool(r['context_verified']['shown_persons']) for r in rr),
   'verified_vehicle_frames':sum(bool(r['context_verified']['shown_vehicles']) for r in rr),
   'verified_clear_people_frames':sum(bool(r['context_verified_clear']['shown_persons']) for r in rr),
   'verified_clear_vehicle_frames':sum(bool(r['context_verified_clear']['shown_vehicles']) for r in rr),
   'reviewed_proposals':sum(len(r['context_checks']) for r in rr),
   'accepted_proposals':sum(c['accepted'] for r in rr for c in r['context_checks']),
   'rejected_proposal_classes':dict(Counter(c['reviewed_class'] for r in rr for c in r['context_checks'] if not c['accepted']))})
 # Deliberately injected cut, using actual decisions. This is not natural-exit validation.
 seq=[(r,r['seconds'],'before') for r in aerial if r['source']=='raft' and r['sample_index']<=6]+[(r,3.5+r['seconds'],'after') for r in aerial if r['source']=='crowded_beach' and r['sample_index']<=12]
 cut={}
 for mode,clear_no,provide_reset in [('old_hold',False,False),('dual_negative_clear',True,False),('provided_scene_reset',False,True)]:
  policy=AnimalEvidence(clear_no);out=[]
  for r,t,segment in seq:
   key=(r['source'],r['sample_index']);f={**r,'source':segment if provide_reset else 'injected','seconds':t}
   result=policy.update(f,ci.get(key),si.get(key));out.append({'segment':segment,'replay_seconds':t,**result})
  tail=[x for x in out if x['segment']=='after']
  cut[mode]={'control_frames':len(tail),'animal_gate_open_frames':sum(x['gate']['context_visible'] for x in tail),'raw_context_shown_frames':sum(bool(x['gate']['shown_persons'] or x['gate']['shown_vehicles']) for x in tail),'rows':out}
 save('hard-cut-regression.json',{'scope':'Injected cut at3.5s combining actual reviewed platform and beach-control frames. Compares animal-evidence policies with raw context counts, not context verification or automatic cut detection. Offline reviews are applied at source time.','arms':cut})
 newanimal=[x for x in animal if not x['reused']]
 report={'scope':plan['scope'],'summary':summary,'aerial_frames':len(aerial),'ground_regression_frames':len(ground),
  'animal_review_calls_reused':sum(x['reused'] for x in animal),'new_animal_review_calls':len(newanimal),'new_context_review_calls':len(contexts),
  'new_failed_animal_calls':sum(x['review']['status']!='success' for x in newanimal),'new_failed_context_calls':sum(x['review']['status']!='success' for x in contexts),
  'new_usage':crop_usage(newanimal,contexts),'audit':audit,'policy_checks_passed':len(fixtures),
  'context_request_median_wall_seconds':statistics.median(x['wall_seconds'] for x in contexts) if contexts else None,
  'context_request_max_wall_seconds':max((x['wall_seconds'] for x in contexts),default=None),
  'context_request_sum_wall_seconds':sum(x['wall_seconds'] for x in contexts),
  'hard_cut':{m:{k:v for k,v in x.items() if k!='rows'} for m,x in cut.items()},
  'limits':['Previously inspected development sources and repeated stochastic model judgments; not held-out accuracy.',
   'No exhaustively annotated aerial marine-animal-plus-person/vehicle positive. Ground segment checks retention only in ground footage.',
   'All frames sampled at2FPS through complete source duration, not native-FPS analysis. Only every sixth sample has animal review; context acceptance is per eligible sample.',
   'No temporal reuse of context acceptance. Additional verification latency/cost is measured per request, not live-stream throughput.',
   'Animal confirmation does not establish injury, urgency or rescue need; displayed accepted proposals are not independently verified boxes or unique objects.',
   'Dual-negative clearing can suppress useful context when small or occluded animals are missed by both reviewers.',
   'Injected-cut experiment applies completed decisions at source time; online API delay and automatic cut detection are not solved.',
   'No model retraining, app integration, flight control, automatic incident/dispatch or deployment.']}
 save('report.json',report)
 font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
 small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
 def render(r,verified=True):
  im=Image.open(r['path']).convert('RGB');w,h=im.size;im=im.resize((960,540));can=Image.new('RGB',(960,620),'#11212c');can.paste(im,(0,60));dr=ImageDraw.Draw(can)
  gate=r['clear_animal_state']['gate'] if verified else r['old_animal_state']['gate'];counts=r['context_verified_clear'] if verified else gate
  dr.text((12,7),f"{r['source']} | source {r['source_seconds']:.2f}s | {'verified context + negative clearing' if verified else 'original unverified context'}",fill='white',font=font)
  dr.text((12,32),f"Animal evidence {'ACTIVE' if gate['context_visible'] else 'PENDING'} | people shown {counts['shown_persons']} | vehicles shown {counts['shown_vehicles']}",fill='#85efaa' if gate['context_visible'] else '#ffd36c',font=font)
  boxes=r['verified_context_boxes'] if verified else [b for b in r['combined_packet']['boxes'] if b['class_id'] in [0,2]]
  if gate['context_visible']:
   for b in boxes:
    color='#00e5ff' if b['class_id']==0 else '#ff9e32';xy=(b['x1']*960/w,b['y1']*540/h+60,b['x2']*960/w,b['y2']*540/h+60);dr.rectangle(xy,outline=color,width=2)
    dr.text((xy[0],max(60,xy[1]-17)),('person' if b['class_id']==0 else 'vehicle')+(' reviewed' if verified else ' proposal'),fill=color,font=small)
  dr.text((12,603),'Offline research replay. Animal presence and context classes reviewed; boxes/identities are not ground truth.',fill='white',font=small)
  return can
 for source in dict.fromkeys(r['source'] for r in rows):
  rr=[r for r in rows if r['source']==source];ims=[render(r) for r in rr]
  out=R/(source+'-verified.gif');ims[0].save(out,save_all=True,append_images=ims[1:],duration=500,loop=0,optimize=False)
  with Image.open(out) as test:assert test.n_frames==len(rr)
 for source,index in [('surf',11),('rocks',8),('ground_rescue',12)]:
  r=next(r for r in rows if r['source']==source and r['sample_index']==index);before=render(r,False);after=render(r,True)
  pair=Image.new('RGB',(960,1240));pair.paste(before,(0,0));pair.paste(after,(0,620));pair.save(R/(source+'-before-after.jpg'),quality=92)
 dest=A/'results/context-video-v1';dest.mkdir(exist_ok=True,parents=True)
 for n in ['plan.json','phase-plan.json','frame-manifest.json','predictions.json','animal-review-plan.json','animal-reviews.json','context-review-plan.json','context-reviews.json','observations.json','audit.json','policy-checks.json','hard-cut-regression.json','report.json','ground-scope-correction.json']:shutil.copy2(R/n,dest/n)
 names={'raft':'Platform','surf':'Surf','rocks':'Rocks','crowded_beach':'Beach control','ground_rescue':'Ground release'}
 md=['# Full-clip context verification: results','',
 'Complete source clips sampled at2FPS: **141 aerial frames**, plus the earlier **24-frame ground-level release segment** as a retention regression. These are inspected development sources, not held-out validation.','',
 '| Clip | Person frames: raw → verified | Vehicle frames: raw → verified |','|---|---:|---:|']
 for s in summary:md.append(f"| {names[s['source']]} | {s['raw_people_frames']} → {s['verified_people_frames']} | {s['raw_vehicle_frames']} → {s['verified_vehicle_frames']} |")
 md+=['','The table isolates context verification while keeping the old animal gate unchanged. Counts mean sampled frames with displayed proposals; **not accuracy, recall or distinct objects**. Full counts for the separate negative-clearing policy are archived.',
 f"**New calls:** {len(newanimal)} animal reviews and {len(contexts)} context reviews. Failed new calls: {report['new_failed_animal_calls']+report['new_failed_context_calls']}. The original32 aerial animal-review responses were reused without new requests.",
 '', '## What changed','',
 'Every eligible person/vehicle proposal is sent as a target crop to the existing neutral region classifier, up to three crops per request. A box is displayed only if the animal gate is open AND its reviewed class agrees exactly with its proposed person/vehicle class. Animal, background, uncertain, failed and unreviewed results stay hidden. No approval propagates across frames.',
 'A separate experimental policy clears recent animal evidence when both the crop review confidently finds no mammal and the whole-scene review says no. A single negative, uncertainty or failure does not revoke evidence. This can also suppress useful context during animal occlusion.',
 '', '## Scene carryover regression','',
 f"On the constructed cut, raw context persisted in **{cut['old_hold']['raw_context_shown_frames']}** beach-control frames with the old hold, versus **{cut['dual_negative_clear']['raw_context_shown_frames']}** with dual-negative clearing and **{cut['provided_scene_reset']['raw_context_shown_frames']}** with a supplied scene reset. This is a synthetic cut using actual decisions, not automatic cut detection or natural-exit validation.",
 '', '## Cost and limits','',
 f"Context requests took a median **{report['context_request_median_wall_seconds']:.2f}s** and maximum **{report['context_request_max_wall_seconds']:.2f}s** each, excluding queue wait. Per-frame context verification adds work; a live2FPS pipeline has not been demonstrated.",
 '**Aerial marine-animal-plus-person/vehicle retention remains unvalidated.** The ground release is a regression sanity check only. Source equipment/altitude and pretraining overlap are unknown. Natural animal exits, exhaustive box truth, tracking identities and online API delay remain untested. Both review stages use the same Gemini model and can make correlated errors.',
 'All source/input/weight/code hashes, proposal coverage, class mappings and state replays were audited. Policy fixtures are separate from model performance. No training, production integration or deployment.',
 '', '## Sources','']
 for s in plan['sources']:md.append(f"- [{s['source']}]({s['page']}) — {s['credit']}; complete {s['duration']:.2f}s source.")
 md.append('- Ground regression: NOAA Fisheries/Hawaii Marine Animal Response R7AF release; same source and segment as study17.')
 text='\n'.join(md);(R/'README.md').write_text(text);(dest/'README.md').write_text(text)
 nb=nbformat.v4.new_notebook();old=nbformat.read(A/'notebooks/18_aerial_patrol_validation.ipynb',as_version=4);nb.metadata=old.metadata
 nb.cells=[nbformat.v4.new_markdown_cell(text),nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/context-video-v1'\naudit=json.loads((R/'audit.json').read_text())\nassert all(audit.values())\nprint('All integrity, coverage and replay audits passed.')\nprint(json.dumps(json.loads((R/'report.json').read_text())['summary'],indent=2))")]
 for source in ['surf','rocks','ground_rescue']:
  nb.cells += [nbformat.v4.new_markdown_cell('## '+names[source]+' — before above, verified below'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-before-after.jpg'))!r}))")]
 for source in ['raft','surf','rocks','crowded_beach','ground_rescue']:
  nb.cells += [nbformat.v4.new_markdown_cell('## '+names[source]+' — full sampled replay'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-verified.gif'))!r}))")]
 nb.cells += [nbformat.v4.new_markdown_cell('## Reproduce\ncontext_video_infer_v1.py extends exact cached inputs; context_video_review_v1.py runs scheduled animal and every-eligible-box context reviews; context_ground_scope_correction_v1.py restricts the mixed reference file to the24 true release samples without rerunning any calls; context_video_policy_v1.py contains the experimental policies; context_video_archive_v1.py audits and renders. Native media and exact request images are cached under ~/aerial-data/context-video-v1. Reports/predictions/plans are under research/aerial_detector/results/context-video-v1. Notebook cells display cached outputs and incur no model requests.')]
 nbformat.write(nb,A/'notebooks/19_context_verified_video.ipynb');print(json.dumps(report,indent=2),flush=True);print('Saved notebook19',flush=True)
def crop_usage(animal,context):
 keys=['prompt_token_count','candidates_token_count','thoughts_token_count','total_token_count']
 return {k:sum(r['review'].get('usage',{}).get(k,0) for r in animal+context) for k in keys}
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
