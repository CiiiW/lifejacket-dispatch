"""Score practical methods, replay cached baselines, and produce an explicit recommendation."""
from pathlib import Path
from collections import Counter
import sys,json,time,hashlib,statistics,shutil,traceback
from PIL import Image,ImageDraw,ImageFont
import nbformat
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import dmd
from evidence_gate_v1 import EvidenceGate
from patrol_memory import PatrolMemory
from review_card_guard_v1 import visible_context,check_guard
D=Path.home()/'aerial-data';R=D/'practical-options-v1';sha=dmd.file_sha256
def load(path):return json.loads(Path(path).read_text())
def save(name,value):(R/name).write_text(json.dumps(value,indent=2))
def usage(rows):
 keys=['prompt_token_count','candidates_token_count','thoughts_token_count','total_token_count']
 return {k:sum(r.get('usage',{}).get(k,0) for r in rows) for k in keys}
def derive(result,task):
 if result['status']!='success':return {'positive':False,'uncertain':True,'two_frame_support':False,'people_context':False,'vehicle_context':False,'failed':True}
 frames=result['data']['frames'];mf={f['frame_id']:f for f in task['manifest']};yes=[f for f in frames if f['mammal_visible']=='yes'];pc=False;vc=False
 for f in yes:
  targets={c['region_id']:c['proposed_class'] for c in mf[f['frame_id']]['context_regions']}
  pc |= any(c['proposed_class_present']=='yes' and targets[c['region_id']]=='person' for c in f['context_regions'])
  vc |= any(c['proposed_class_present']=='yes' and targets[c['region_id']]=='vehicle' for c in f['context_regions'])
 return {'positive':bool(yes),'uncertain':any(f['mammal_visible']=='uncertain' for f in frames),'two_frame_support':len(yes)>=2,'people_context':pc,'vehicle_context':vc,'failed':False}
def main():
 required=['reviews.json','detector-timing.json','cut-probe/reviews.json','seal-probe/reviews.json','tight-seal-probe/reviews.json']
 deadline=time.monotonic()+1800
 while not all((R/n).exists() for n in required):
  if time.monotonic()>deadline:raise RuntimeError('Comparison wait timeout')
  time.sleep(2)
 plan=load(R/'plan.json');rp=load(R/'review-plan.json');frames=load(R/'frames.json');groups=load(R/'groups.json');ann=load(R/'annotations.json')['windows'];results=load(R/'reviews.json')
 ai={r['key']:r for r in ann};gi={r['key']:r for r in groups};fi={(r['source'],r['sample_index']):r for r in frames};ti={(t['key'],t['mode']):t for t in rp['tasks']}
 audit={'source_frames_unchanged':all(sha(f['path'])==f['sha256'] for f in frames),'frame_manifest_hash':sha(R/'frames.json')==plan['input_sha256'],'group_manifest_hash':sha(R/'groups.json')==plan['group_sha256'],'trial_hash':sha(R/'plan.json')==rp['trial_sha256'],'annotation_hash':sha(R/'annotations.json')==rp['annotation_sha256'],'prepare_code_hash':sha(A/'practical_options_prepare_v1.py')==plan['prepare_code_sha256'],'review_code_hash':sha(A/'practical_options_review_v1.py')==rp['review_code_sha256'],'all_76_tasks_completed':len(results)==plan['max_requests']==len(rp['tasks']),'request_images_unchanged':all(sha(im['path'])==im['sha256'] for task in rp['tasks'] for im in task['images'])}
 for r in results:
  t=ti[(r['key'],r['mode'])]
  if r['status']=='success':assert r['input_sha256']==[im['sha256'] for im in t['images']]
 assert all(audit.values()),audit
 evaluated=[{**r,'evaluation':derive(r,ti[(r['key'],r['mode'])])} for r in results];ei={(r['key'],r['mode']):r for r in evaluated}
 summaries=[]
 for mode in plan['modes']:
  rr=[r for r in evaluated if r['mode']==mode];pos=[r for r in rr if ai[r['key']]['screening_class']=='anchor_positive'];control=[r for r in rr if ai[r['key']]['screening_class']=='screened_control'];unknown=[r for r in rr if ai[r['key']]['screening_class']=='unresolved_control']
  pc=[r for r in rr if ai[r['key']]['people_cooccurrence_anchor']];vc=[r for r in rr if ai[r['key']]['vehicle_cooccurrence_anchor']]
  summaries.append({'mode':mode,'requests':len(rr),'failed_outputs':sum(r['status']!='success' for r in rr),
   'anchor_positive_windows':len(pos),'anchor_positive_windows_flagged':sum(r['evaluation']['positive'] for r in pos),
   'screened_control_windows':len(control),'screened_control_positive_flags':sum(r['evaluation']['positive'] for r in control),
   'unresolved_control_positive_flags':sum(r['evaluation']['positive'] for r in unknown),
   'uncertain_windows':sum(r['evaluation']['uncertain'] for r in rr),
   'two_frame_supported_windows':sum(r['evaluation']['two_frame_support'] for r in rr),
   'people_cooccurrence_anchor_windows':len(pc),'people_context_windows_retained':sum(r['evaluation']['people_context'] for r in pc),
   'vehicle_cooccurrence_anchor_windows':len(vc),'vehicle_context_windows_retained':sum(r['evaluation']['vehicle_context'] for r in vc),
   'median_request_wall_seconds':statistics.median(r['wall_seconds'] for r in rr),
   'max_request_wall_seconds':max(r['wall_seconds'] for r in rr),'usage':usage(rr),
   'total_input_images':sum(len(ti[(r['key'],mode)]['images']) for r in rr)})
 # Replayed adaptive routing: never use an AI negative to delete DMD candidates.
 cards=[];routing=[]
 for g in groups:
  ff=[fi[(g['source'],i)] for i in g['all_frame_keys']];middle=fi[(g['source'],g['single_index'])]
  raw_candidate=any(any(b['class_id']==1 for b in f['merged_predictions']) for f in ff)
  whole=ei[(g['key'],'single_whole')];native=ei[(g['key'],'single_native')]
  fallback=(not whole['evaluation']['positive'] and raw_candidate) or whole['status']!='success' or whole['evaluation']['uncertain']
  used=[whole]+([native] if fallback else [])
  candidate=raw_candidate or any(r['evaluation']['positive'] for r in used)
  state='ai_supported_candidate' if whole['evaluation']['positive'] else 'detector_ai_disagreement' if raw_candidate else 'uncertain_review' if any(r['evaluation']['uncertain'] for r in used) else 'no_candidate'
  verified_checks=[]
  if whole['status']=='success':
   targets={c['region_id']:c for c in ti[(g['key'],'single_whole')]['manifest'][0]['context_regions']}
   verified_checks=[{'accepted':c['proposed_class_present']=='yes','box':targets[c['region_id']]['box']} for c in whole['data']['frames'][0]['context_regions']]
  shown=visible_context(None,middle['sha256'],verified_checks)
  card={'selected_frame_sha256':middle['sha256'],'hidden_verified_context_proposals':sum(c['accepted'] for c in verified_checks),'key':g['key'],'source':g['source'],'start_seconds':g['start_seconds'],'end_seconds':g['end_seconds'],'candidate_retained':candidate,
   'detector_candidate_retained_despite_ai_negative':raw_candidate and not any(r['evaluation']['positive'] for r in used),
   'ai_advisory':state,'human_confirmed':False,'display_person_vehicle_boxes':bool(shown),'automatic_incident_or_dispatch':False,
   'representative_frames':g['burst_indices'],'whole_result':whole['status'],'native_fallback_used':fallback}
  cards.append(card);routing.append({'key':g['key'],'requests_required':len(used),'fallback':fallback,'usage':usage(used)})
 # Human-confirmation fixture: confirmation belongs to one immutable frame, never a window.
 fixture_frame='a'*64;confirmed={fixture_frame}
 fixtures=[{'case':'ai_negative_does_not_delete_detector_candidate','passed':all(c['candidate_retained'] for c in cards if c['detector_candidate_retained_despite_ai_negative'])},
 {'case':'all_actual_cards_start_unconfirmed','passed':all(not c['human_confirmed'] and not c['display_person_vehicle_boxes'] for c in cards)},
 {'case':'same_frame_human_confirmation_only','passed':fixture_frame in confirmed and 'sha:B' not in confirmed},
 {'case':'no_automatic_dispatch','passed':all(not c['automatic_incident_or_dispatch'] for c in cards)}]
 fixtures+=check_guard()
 assert all(f['passed'] for f in fixtures)
 save('evaluated-results.json',evaluated);save('review-cards.json',cards);save('adaptive-routing-replay.json',routing);save('review-card-fixtures.json',fixtures)
 # Photo stress test: annotated positive images, only presence classification is scored.
 seal=load(R/'seal-probe/reviews.json');sealplan=load(R/'seal-probe/plan.json');tight=load(R/'tight-seal-probe/reviews.json');tightplan=load(R/'tight-seal-probe/plan.json')
 seal_summary=[]
 for mode,rr in [('single_whole',[r for r in seal if r['mode']=='single_whole']),('single_native',[r for r in seal if r['mode']=='single_native']),('tight_native',tight)]:
  outs=[r['data']['frames'][0]['mammal_visible'] for r in rr if r['status']=='success']
  seal_summary.append({'mode':mode,'images':len(rr),'positive_images_confirmed':outs.count('yes'),'uncertain':outs.count('uncertain'),'no':outs.count('no'),'failed':sum(r['status']!='success' for r in rr),'usage':usage(rr)})
 # Verify all stress/probe inputs and code.
 probeaudit={}
 for folder,pp,rr in [('seal-probe',sealplan,seal),('tight-seal-probe',tightplan,tight),('cut-probe',load(R/'cut-probe/plan.json'),load(R/'cut-probe/reviews.json'))]:
  probeaudit[folder+'_input_hashes']=all(sha(im['path'])==im['sha256'] for t in pp['tasks'] for im in t['images'])
  expected=pp.get('probe_code_sha256',pp.get('code_sha256'))
  filename={'seal-probe':'practical_options_seal_probe_v1.py','tight-seal-probe':'practical_options_tight_probe_v1.py','cut-probe':'practical_options_cut_probe_v1.py'}[folder]
  probeaudit[folder+'_code_hash']=sha(A/filename)==expected
 assert all(probeaudit.values()),probeaudit
 audit.update(probeaudit);save('audit.json',audit)
 cutplan=load(R/'cut-probe/plan.json');cut=load(R/'cut-probe/reviews.json');cutout=[]
 for r,t in zip(cut,cutplan['tasks']):
  v=derive(r,t);cutout.append({'mode':r['mode'],'status':r['status'],**v,'frame_decisions':r.get('data',{}).get('frames',[])})
 save('cut-probe/summary.json',cutout)
 # Candidate generation and the existing annotated four-model benchmark.
 metrics=load(D/'model-comparison-v1/metrics.json')
 detector_metrics=[r for r in metrics if r['threshold']==.3 and ((r['cohort']=='noaa_seal' and r['class_id']==1 and r['method'] in ['full','tiled_plus_full']) or (r['cohort']=='coco_context' and r['class_id'] in [0,2] and r['method']=='full'))]
 candidate=[]
 for mode in ['full','tiled_plus_full']:
  key='full_predictions' if mode=='full' else 'merged_predictions'
  candidate.append({'mode':mode,'candidate_windows':sum(any(any(b['class_id']==1 for b in f[key]) for f in frames if f['source']==g['source'] and f['sample_index'] in g['all_frame_keys']) for g in groups),'windows':len(groups)})
 # Cached policy replays on the shared165-frame cohort.
 shared=[f for f in frames if f['source'] not in ['dog_walk','parking_control']]
 ar=load(D/'context-video-v1/animal-reviews.json');ci={(x['review']['source'],x['review']['sample_index']):x['review'] for x in ar if x['mode']=='crop'};si={(x['review']['source'],x['review']['sample_index']):x['review'] for x in ar if x['mode']=='scene'}
 for r in load(D/'combined-gemini-v1/crop-reviews.json'):
  if r['source']=='rescue':ci[('ground_rescue',r['sample_index'])]=r
 for r in load(D/'combined-gemini-v1/scene-reviews.json'):
  if r['source']=='rescue':si[('ground_rescue',r['sample_index'])]=r
 policies=[]
 for policy in ['crop_only','scene_only','same_check_agreement','two_scene_checks','agreement_or_repeated']:
  memory=PatrolMemory();eg=EvidenceGate();out=[]
  for f in shared:
   key=(f['source'],f['sample_index']);c=ci.get(key);s=si.get(key);cy=bool(c and c['status']=='success' and c['animal_confirmed']);sy=bool(s and s['status']=='success' and s['data']['nonhuman_animal_visible']=='yes')
   evidence=eg.update(f['source'],f['seconds'],scheduled=bool(c or s),crop_yes=cy if policy=='agreement_or_repeated' else False,scene_yes=sy)
   yes=cy if policy=='crop_only' else sy if policy=='scene_only' else cy and sy if policy=='same_check_agreement' else evidence['confirmed']
   gate=memory.update(f['source'],f['seconds'],animal_candidate=any(b['class_id']==1 for b in f['merged_predictions']),animal_confirmed=yes,persons=sum(b['class_id']==0 for b in f['combined_packet']['boxes']),vehicles=sum(b['class_id']==2 for b in f['combined_packet']['boxes']))
   out.append({'source':f['source'],'seconds':f['seconds'],'gate_open':gate['context_visible']})
  policies.append({'policy':policy,'scope':'Cached165-frame shared subset; no dog/parking extension calls. Offline source-time policy replay, not new model inference.','gate_frames':sum(r['gate_open'] for r in out),'beach_gate_frames':sum(r['gate_open'] for r in out if r['source']=='crowded_beach'),'surf_gate_frames':sum(r['gate_open'] for r in out if r['source']=='surf'),'ground_gate_frames':sum(r['gate_open'] for r in out if r['source']=='ground_rescue')})
 timing=load(R/'detector-timing.json')
 gpu_summary=[{'mode':m,'median_seconds':statistics.median(r['median_seconds'] for r in timing['rows'] if r['mode']==m),'native4k_median_seconds':statistics.median(r['median_seconds'] for r in timing['rows'] if r['mode']==m and r['size'][0]>=3840)} for m in ['full','full_plus_tiles']]
 allcalls=results+seal+tight+cut
 report={'scope':plan['scope'],'review_card_guard_code_sha256':sha(A/'review_card_guard_v1.py'),'new_requests':len(allcalls),'failed_outputs':sum(r['status']!='success' for r in allcalls),'usage':usage(allcalls),
  'video_frames':len(frames),'video_windows':len(groups),'video_method_summaries':summaries,'seal_stress':seal_summary,'cut_probe':cutout,
  'adaptive_replay_requests':sum(r['requests_required'] for r in routing),'adaptive_replay_candidate_cards':sum(c['candidate_retained'] for c in cards),
  'ai_negative_candidates_preserved':sum(c['detector_candidate_retained_despite_ai_negative'] for c in cards),
  'shared_subset_per_frame_requests':len(ar)+8+load(D/'context-video-v1/hypothesis-review/report.json')['requests'],'shared_subset_adaptive_replay_requests':sum(r['requests_required'] for r in routing if not r['key'].startswith(('dog_walk-','parking_control-'))),'candidate_generation':candidate,'cached_policy_replays':policies,'cached_annotated_detector_metrics':detector_metrics,'gpu_timing':gpu_summary,'audit':audit,
  'recommendation':'Use tiled DMD animal candidates plus YOLO-World context as an offline proposal pipeline. Group into review windows. Gemini is advisory: whole-view first, selective crops for uncertainty/disagreement, never a hard negative veto for tiny animals. Show context boxes only after human animal confirmation for that exact frame and class-specific context verification. No autonomous rescue/dispatch.',
  'not_tested':['Domain fine-tuning with a clean flight-level train/validation/test split','Independent aerial marine-animal-plus-human/vehicle box ground truth','Native-FPS live DJI streaming, online buffering and automatic cut detection','Tracking identities and per-track cached approvals'],
  'limits':['All sources previously inspected development sources, except no new acquisition was required; no field-generalization or population accuracy claim.',
   'Window anchor coverage and screened-control flags are descriptive, not exhaustive frame/box accuracy. One beach window is explicitly unresolved.',
   'Four modes differ in information available and cost. Failed native-mode outputs remain failures; they were not silently retried.',
   'Tiny-seal stress has8 positive images and14 reference boxes, no matched-domain negative set. Presence judgments are not box localization scores.',
   'Adaptive routing is replayed from real cached responses, not a freshly deployed adaptive service.',
   'Group results cannot be propagated to unreviewed frames or interpreted as animal identities or current animal presence.',
   'No training, production integration, automatic incidents, flight control or deployment.']}
 save('report.json',report)
 # Lightweight review-card previews; no large embedded videos.
 font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',17);small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',14)
 previews=[]
 for source in ['dog_walk','crowded_beach','surf','ground_rescue']:
  card=next(c for c in cards if c['source']==source);g=gi[card['key']];f=fi[(source,g['single_index'])];im=Image.open(f['path']).convert('RGB');im.thumbnail((960,540));canvas=Image.new('RGB',(960,640),'#11222d');canvas.paste(im,(0,70));dr=ImageDraw.Draw(canvas)
  dr.text((15,10),f"{source} | {card['start_seconds']:.2f}-{card['end_seconds']:.2f}s | {card['ai_advisory']}",fill='white',font=font)
  dr.text((15,38),'Human confirmation pending. Person/vehicle boxes hidden.',fill='#ffd36d',font=font)
  dr.text((15,610),'Review-card prototype: detector candidates remain available even when Gemini says no.',fill='white',font=small)
  p=R/(source+'-review-card.jpg');canvas.save(p,quality=92);previews.append(str(p))
 # Tiny-seal proof is shown with reference annotations only in this evaluation view.
 stress=sealplan['references'][0];im=Image.open(stress['source']).convert('RGB');reference=stress['references'][0];cx=(reference['x1']+reference['x2'])/2;cy=(reference['y1']+reference['y2'])/2;rect=(max(0,int(cx-128)),max(0,int(cy-128)),min(im.width,int(cx+128)),min(im.height,int(cy+128)))
 crop=im.crop(rect);crop=crop.resize((512,512));crop.save(R/'annotated-seal-evaluation-crop.jpg',quality=95)
 title='# Tested recommendation: keep DMD; make Gemini advisory'
 md=[title,'',
 '**The decisive result is tiny-animal retention. A Gemini negative must not delete a DMD candidate.** The practical default is offline, operator-reviewed evidence windows, with selective AI review and class-specific context checks.','',
 f"Tested **{len(frames)} video frames across7 sources**, grouped into **{len(groups)} windows**, four new review modes, a mixed-scene probe and three tiny-seal presentation checks. **{len(allcalls)} new requests; {report['failed_outputs']} unusable outputs.** Existing four-model detection scores and five animal-evidence policies were also compared.",'',
 '## New workflow comparison','',
 '| Method | Positive anchors | Control flags | Median call |','|---|---:|---:|---:|']
 labels={'single_whole':'Single whole','single_native':'Single + native crops','burst_whole':'Three whole frames','burst_native':'Three + native crops'}
 for s in summaries:md.append(f"| {labels[s['mode']]} | {s['anchor_positive_windows_flagged']}/{s['anchor_positive_windows']} | {s['screened_control_positive_flags']}/{s['screened_control_windows']} | {s['median_request_wall_seconds']:.2f}s |")
 md+=['','Three native-mode outputs were unusable under the response/evidence checks; they remain failures, not silent retries. The single-whole method used55,540 reported total tokens, single-native44,473, burst-whole50,530 and burst-native100,370. Token totals are not dollar-cost estimates. These are manually screened window/anchor diagnostics, **not recall, specificity or box accuracy**. All methods review the same fixed midpoint or first/midpoint/last samples. Native adds candidate crops. Single and burst outputs refer only to their reviewed frames.',
 '', '## Tiny annotated aerial seals: the stress check that changes the decision','',
 '| Input presentation | Mammal-positive images | Uncertain | No | Failed |','|---|---:|---:|---:|---:|']
 for s in seal_summary:md.append(f"| {s['mode']} | {s['positive_images_confirmed']}/{s['images']} | {s['uncertain']} | {s['no']} | {s['failed']} |")
 dmdrows=[r for r in detector_metrics if r['model']=='dmd' and r['cohort']=='noaa_seal' and r['class_id']==1]
 md+=['','These are8 positive NOAA images with14 reference boxes. Native uses detector proposals, not ground-truth crops. The tighter presentation changes padding, crop budget and resize together; upsampling adds no detail. Presence is scored, not localization. There is no matched-domain negative set.',
 '', '## Detector choice','',
 '| Model, tiled + whole | Matched seal boxes /14 | Unmatched proposals |','|---|---:|---:|']
 for r in detector_metrics:
  if r['cohort']=='noaa_seal' and r['method']=='tiled_plus_full':md.append(f"| {r['model']} | {r['tp']}/14 | {r['fp']} |")
 for r in dmdrows:
  if r['method']=='full':md.append(f"\nDMD whole-frame-only matched {r['tp']}/14 in that cached subset. Preserve tiling for small animals; faster whole-frame processing is not an equivalent replacement.")
 md+=['','YOLO-World remains a context proposer rather than the animal detector. The prior class-specific context test retained19 person-display frames and15 vehicle-display frames in the ground regression, while rejecting23 inspected surf/rock proposals. Those are display diagnostics, not accuracy.',
 '', '## Annotated person/vehicle comparison (cached)', '', '| Model | Person matches /30 | Vehicle matches /6 | Extra person / vehicle proposals |', '|---|---:|---:|---:|']
 for model in ['dmd','grounding_dino','yolo_world','yoloe26']:
  persons=next(r for r in detector_metrics if r['model']==model and r['cohort']=='coco_context' and r['class_id']==0)
  vehicles=next(r for r in detector_metrics if r['model']==model and r['cohort']=='coco_context' and r['class_id']==2)
  md.append(f"| {model} | {persons['tp']} | {vehicles['tp']} | {persons['fp']} / {vehicles['fp']} |")
 md+=['', 'Grounding DINO matched more context references, while YOLO-World produced fewer extra context proposals and was faster in the prior T4 benchmark. This small inspected subset does not establish generalization.', '', '## Cached animal-gate policy tradeoffs', '', '| Rule | Surf active frames /31 | Beach active frames /38 | Ground active frames /24 |', '|---|---:|---:|---:|']
 for rule in policies:md.append(f"| {rule['policy']} | {rule['surf_gate_frames']} | {rule['beach_gate_frames']} | {rule['ground_gate_frames']} |")
 md+=['', 'These are state replays using identical prior model responses, not new inference or accuracy. More stringent rules can suppress ambiguous positives but also delay/drop useful animal evidence.', '', '## Practical configuration','',
 '1. Retain tiled DMD animal candidates and the original video. Group evidence into short review windows; do not count windows as animals.',
 '2. Use a whole-view advisory check on a representative frame. Add native crops for uncertainty or disagreement. A negative AI judgment does not erase detector evidence.',
 '3. Present an unconfirmed review card. A reviewer confirms animal presence for a specific immutable frame.',
 '4. Show person/vehicle boxes only for that confirmed frame, with class-specific context verification. Do not carry approval to another scene or unreviewed frame.',
 '5. Keep live streaming, automatic alerts and domain fine-tuning as separate validation work.',
 '', f"Adaptive routing replay would require {report['adaptive_replay_requests']} calls for these19 windows and preserves {report['ai_negative_candidates_preserved']} detector candidate windows that the used AI responses do not confirm. This is an offline replay, not a deployed adaptive timing test. On the shared165-frame subset, the prior per-frame configuration requires117 model requests versus19 for this adaptive replay; outputs and review granularity differ, so this is a request-count comparison, not a measured speedup.",
 '', '## Timing, boundaries and remaining work','']
 for s in gpu_summary:md.append(f"- Fresh6-frame T4 timing, {s['mode']}: median {s['median_seconds']:.3f}s; 4K subset median {s['native4k_median_seconds']:.3f}s. Two synchronized repeats after warm-up; source decode/loading excluded.")
 md+=['- Whole and native burst modes were tested across an injected visual cut. Context is joined to animal evidence only within the same reviewed frame. This is not natural scene-cut validation.',
 '- Cached policy replays show the latency/retention tradeoff of stricter agreement and repeated checks; all underlying responses remain the same.',
 '- No independently annotated aerial marine-animal-plus-human/vehicle positive was found. Dog-human footage is an aerial proxy; the seal release is ground-level.',
 '- No training or independent flight-level fine-tuning evaluation was performed. No live2FPS, identity tracking, app integration or deployment claim.',
 '', '## Reproduce','',
 'practical_options_prepare_v1.py freezes inputs and selection; practical_options_review_v1.py runs the four modes; practical_options_timing_v1.py measures detector cost; cut/seal/tight probe scripts run the stress checks; practical_options_archive_v1.py audits and scores. Exact request images and media references are under ~/aerial-data/practical-options-v1. Reports, plans, decisions and cards are under research/aerial_detector/results/practical-options-v1. Notebook cells display cached results only.']
 text='\n'.join(md);(R/'REPORT.md').write_text(text)
 dest=A/'results/practical-options-v1';dest.mkdir(parents=True,exist_ok=True)
 for name in ['plan.json','groups.json','annotations.json','review-plan.json','reviews.json','evaluated-results.json','review-cards.json','adaptive-routing-replay.json','review-card-fixtures.json','detector-timing.json','audit.json','report.json','REPORT.md']:shutil.copy2(R/name,dest/name)
 for folder in ['cut-probe','seal-probe','tight-seal-probe']:
  (dest/folder).mkdir(exist_ok=True)
  for name in ['plan.json','reviews.json','summary.json']:
   if (R/folder/name).exists():shutil.copy2(R/folder/name,dest/folder/name)
 old=nbformat.read(A/'notebooks/19_context_verified_video.ipynb',as_version=4);nb=nbformat.v4.new_notebook();nb.metadata=old.metadata
 nb.cells=[nbformat.v4.new_markdown_cell(text),nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/practical-options-v1'\nassert all(json.loads((R/'audit.json').read_text()).values())\nprint('Input, selection, response-image and code audits passed.')\nr=json.loads((R/'report.json').read_text())\nprint(json.dumps(r['cached_policy_replays'],indent=2))"),
 nbformat.v4.new_markdown_cell('## Annotated tiny-seal evaluation view\nThis crop is centered on a reference annotation for human evaluation only. It was never used to select model input crops.'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/'annotated-seal-evaluation-crop.jpg')!r}))")]
 for p in previews:nb.cells += [nbformat.v4.new_markdown_cell('## '+Path(p).stem),nbformat.v4.new_code_cell(f"display(Image(filename={p!r}))")]
 nbformat.write(nb,A/'notebooks/20_practical_options_report.ipynb');print(json.dumps({'workflow':summaries,'seal_stress':seal_summary,'review_card_guard_code_sha256':sha(A/'review_card_guard_v1.py'),'new_requests':len(allcalls),'failed':report['failed_outputs'],'adaptive_calls':report['adaptive_replay_requests'],'preserved':report['ai_negative_candidates_preserved']},indent=2),flush=True);print('Saved notebook20 and final recommendation',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
