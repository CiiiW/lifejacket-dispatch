"""Assemble the separate class-specific A/B without changing frozen neutral results."""
from pathlib import Path
from collections import Counter
import json,sys,time,hashlib,shutil,statistics,traceback
from PIL import Image,ImageDraw,ImageFont
import nbformat
A=Path(__file__).resolve().parent;R=Path.home()/'aerial-data/context-video-v1';Q=R/'hypothesis-review'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 deadline=time.monotonic()+1800
 while not (Q/'report.json').exists() or not (A/'notebooks/19_context_verified_video.ipynb').exists():
  if time.monotonic()>deadline:raise RuntimeError('Report wait timeout')
  time.sleep(2)
 # Ensure the neutral renderer has finished before updating its notebook.
 while 'Saved notebook19' not in (R/'archive.log').read_text():
  if time.monotonic()>deadline:raise RuntimeError('Neutral render wait timeout')
  time.sleep(2)
 result=json.loads((Q/'report.json').read_text());hp=json.loads((Q/'plan.json').read_text());base=json.loads((R/'report.json').read_text());rows=json.loads((R/'observations.json').read_text());cp=json.loads((R/'context-review-plan.json').read_text())
 audit={'identical_task_plan':sha(R/'context-review-plan.json')==hp['source_context_plan_sha256'],
  'hypothesis_code_frozen':sha(A/'context_hypothesis_review_v1.py')==hp['code_sha256'],
  'request_count_complete':len(result['results'])==len(cp['tasks'])==hp['max_requests'],
  'request_images_unchanged':all([sha(p) for p in r['paths']]==r['input_sha256'] for r in result['results'])}
 lookup={}
 for r in result['results']:
  data={v['region_id']:v for v in r.get('data',{}).get('regions',[])} if r['status']=='success' else {}
  if r['status']=='success':assert set(data)=={t['region_id'] for t in r['targets']}
  for t,b in zip(r['targets'],r['boxes']):
   v=data.get(t['region_id'],{'proposed_class_present':'unreviewed','evidence':''})
   assert t['proposed_class']=={0:'person',2:'vehicle'}[b['class_id']]
   lookup.setdefault((r['frame_source'],r['sample_index']),[]).append({'box':b,'proposed_class':t['proposed_class'],'presence':v['proposed_class_present'],'accepted':v['proposed_class_present']=='yes','evidence':v['evidence']})
 for r in rows:
  r['class_specific_checks']=lookup.get((r['source'],r['sample_index']),[])
  accepted=[x['box'] for x in r['class_specific_checks'] if x['accepted']];r['class_specific_boxes']=accepted
  for suffix,state in [('',r['old_animal_state']['gate']),('_clear',r['clear_animal_state']['gate'])]:
   r['class_specific'+suffix]={'context_visible':state['context_visible'],'shown_persons':sum(b['class_id']==0 for b in accepted) if state['context_visible'] else 0,'shown_vehicles':sum(b['class_id']==2 for b in accepted) if state['context_visible'] else 0}
 audit['all_eligible_regions_covered']=all(not(r['old_animal_state']['gate']['context_visible'] or r['clear_animal_state']['gate']['context_visible']) or len(r['class_specific_checks'])==sum(b['class_id'] in [0,2] for b in r['combined_packet']['boxes']) for r in rows)
 audit['no_display_on_closed_animal_gate']=all(r['old_animal_state']['gate']['context_visible'] or not(r['class_specific']['shown_persons'] or r['class_specific']['shown_vehicles']) for r in rows)
 assert all(audit.values()),audit
 (Q/'audit.json').write_text(json.dumps(audit,indent=2));(R/'hypothesis-observations.json').write_text(json.dumps(rows,indent=2))
 summary=[]
 for source in dict.fromkeys(r['source'] for r in rows):
  rr=[r for r in rows if r['source']==source]
  summary.append({'source':source,'samples':len(rr)})
 # Explicit mapping keeps the original animal gate fixed for the verifier A/B.
 for s in summary:
  rr=[r for r in rows if r['source']==s['source']]
  for method in ['raw','exclusive','class_specific','class_specific_clear']:
   for kind in ['persons','vehicles']:
    s[method+'_'+kind+'_frames']=sum(bool((r['old_animal_state']['gate'] if method=='raw' else r['context_verified'] if method=='exclusive' else r[method])['shown_'+kind]) for r in rr)
  s['animal_gate_old_frames']=sum(r['old_animal_state']['gate']['context_visible'] for r in rr)
  s['animal_gate_clear_frames']=sum(r['clear_animal_state']['gate']['context_visible'] for r in rr)
  s['directed_region_outcomes']=dict(Counter(c['presence'] for r in rr for c in r['class_specific_checks']))
 base['class_specific_ablation']={'scope':result['scope'],'summary':summary,'new_requests':result['requests'],'failed_requests':result['failed_requests'],'usage':result['usage'],'audit':audit,
  'median_request_wall_seconds':statistics.median(r['wall_seconds'] for r in result['results']),'max_request_wall_seconds':max(r['wall_seconds'] for r in result['results'])}
 base['total_new_requests_all_phases']=base['new_animal_review_calls']+base['new_context_review_calls']+result['requests']
 base['late_beach_gate_review']={'scheduled_source_seconds':15.015,'evidence':'Crop reviewer called an ambiguous small light-colored shape a quadruped; scene reviewer answered mammal yes but its evidence described people, a car, and birds. Native crop is too small for a reliable independent mammal label here.','consequence':'Animal gate opened six later control frames. Treat this as an unresolved/unsupported trigger; do not claim clean negative specificity or a field-ready animal gate.'}
 base['recommendation']='Keep the class-specific context verifier as an experimental candidate if retention improves, but do not deploy: later beach animal trigger remains unsupported/ambiguous, aerial marine co-occurrence is missing, and API latency is material.'
 (R/'report.json').write_text(json.dumps(base,indent=2))
 names={'raft':'Platform','surf':'Surf','rocks':'Rocks','crowded_beach':'Beach control','ground_rescue':'Ground release'}
 lead=['# Full-clip test: better context checks, unresolved animal trigger','',
 '**Do not promote yet.** The later beach segment still opens the animal gate on ambiguous/contradictory evidence. Verifying context boxes cannot repair an incorrect animal trigger.','',
 '**141 aerial frames through all four complete source clips**, sampled at2FPS, plus **24 ground-release frames** as a retention regression. These are previously inspected development sources.','',
 '| Clip | Person frames: raw / exclusive / class-specific | Vehicle frames: raw / exclusive / class-specific |','|---|---:|---:|']
 for s in summary:lead.append(f"| {names[s['source']]} | {s['raw_persons_frames']} / {s['exclusive_persons_frames']} / {s['class_specific_persons_frames']} | {s['raw_vehicles_frames']} / {s['exclusive_vehicles_frames']} / {s['class_specific_vehicles_frames']} |")
 lead+=['',
 'Raw = animal-gated detector proposals. Exclusive = the original single-class crop verifier. Class-specific = asks whether the proposed person or vehicle is actually supported inside the target rectangle, allowing other objects to coexist. The table holds animal decisions fixed. **Counts are display/proposal frames, not accuracy, recall or unique-object counts.**',
 '', '## What the longer test exposed','',
 '- The surf and rock context proposals were reviewed across all eligible sampled frames, not just the earlier examples.',
 '- The exclusive classifier sometimes called a truck target “person” because responders overlapped the truck. Class-specific presence is a better formulation for overlapping objects; its full-task A/B uses exactly the same crop bytes.',
 '- At approximately15seconds of the beach clip, the crop reviewer called a tiny shape a quadruped, while the whole-scene reviewer justified a mammal “yes” with an explanation mentioning birds. Independent visual review cannot reliably identify a mammal in that tiny crop. The gate opened six frames; the prior first12seconds-only result did not cover this failure.',
 '- No verified aerial marine-animal-plus-human/vehicle positive is available here. The ground-release retention result cannot fill that gap.',
 '', '## Evidence clearing and scene changes','',
 f"The constructed hard cut left raw context visible in {base['hard_cut']['old_hold']['raw_context_shown_frames']} control frames with the old hold, versus {base['hard_cut']['dual_negative_clear']['raw_context_shown_frames']} with dual-negative clearing and {base['hard_cut']['provided_scene_reset']['raw_context_shown_frames']} with a supplied scene reset. This uses completed model decisions at source time, not live automatic cut detection.",
 'Negative clearing reduced surf animal-evidence frames from20 to19, and did not stop the later beach trigger because both reviewers answered positive there. Clearing can also drop context during real animal occlusion. Natural exit timing remains unannotated.',
 '', '## Calls, latency and verification','',
 f"New requests: **{base['new_animal_review_calls']} animal + {base['new_context_review_calls']} exclusive-context + {result['requests']} class-specific-context = {base['total_new_requests_all_phases']}**. Failed new requests across phases: {base['new_failed_animal_calls']+base['new_failed_context_calls']+result['failed_requests']}. Original32 aerial animal responses were reused.",
 f"Class-specific context requests took a median **{base['class_specific_ablation']['median_request_wall_seconds']:.2f}s** and maximum **{base['class_specific_ablation']['max_request_wall_seconds']:.2f}s**, excluding queue wait. No context approval is propagated across frames. This is offline replay; live2FPS has not been demonstrated.",
 'Source/frame/request-image/weight/code hashes, full2FPS grid coverage, per-region mappings and policy replay were audited. The ground reference was restricted by exact source-frame hashes to its24 release samples; correction lineage is archived. Logic fixtures are separate from model performance.',
 '', '## Reproduce and limits','',
 'Run context_video_infer_v1.py, context_video_review_v1.py, context_ground_scope_correction_v1.py, context_video_archive_v1.py, context_hypothesis_review_v1.py and context_video_finalize_v1.py in their documented environments. Frozen plans/results are under research/aerial_detector/results/context-video-v1; media and exact request crops are under ~/aerial-data/context-video-v1. Notebook cells only display cached artifacts.',
 'Both reviewers share a Gemini model and can make correlated mistakes. Source altitude/equipment/pretraining overlap, exhaustive boxes, identities, natural animal visibility and real-time buffering are not validated. No training, production integration, flight control, automatic incident/dispatch or deployment.',
 '', '## Sources','']
 for src in json.loads((R/'plan.json').read_text())['sources']:lead.append(f"- [{src['source']}]({src['page']}) — {src['credit']}; complete {src['duration']:.2f}s source.")
 lead.append('- Ground retention: NOAA Fisheries/Hawaii Marine Animal Response R7AF release, same segment as study17.')
 md='\n'.join(lead);(R/'README.md').write_text(md)
 font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16);small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
 def render(r,mode='class_specific'):
  im=Image.open(r['path']).convert('RGB');w,h=im.size;im=im.resize((960,540));out=Image.new('RGB',(960,620),'#10212c');out.paste(im,(0,60));dr=ImageDraw.Draw(out);gate=r['old_animal_state']['gate'];counts=r['context_verified'] if mode=='exclusive' else r['class_specific']
  dr.text((12,8),f"{names[r['source']]} | source {r['source_seconds']:.2f}s | {mode} context verifier",fill='white',font=font)
  dr.text((12,32),f"Animal evidence {'ACTIVE' if gate['context_visible'] else 'PENDING'} | people {counts['shown_persons']} | vehicles {counts['shown_vehicles']}",fill='#82efab' if gate['context_visible'] else '#ffd16c',font=font)
  boxes=r['verified_context_boxes'] if mode=='exclusive' else r['class_specific_boxes']
  if gate['context_visible']:
   for b in boxes:
    color='#00e5ff' if b['class_id']==0 else '#ff9c35';xy=[b['x1']*960/w,b['y1']*540/h+60,b['x2']*960/w,b['y2']*540/h+60];dr.rectangle(xy,outline=color,width=2)
    dr.text((xy[0],max(60,xy[1]-17)),('person' if b['class_id']==0 else 'vehicle')+' reviewed',fill=color,font=small)
  dr.text((12,603),'Research replay: animal gate unchanged. A supported context class does not prove the animal trigger is correct.',fill='white',font=small);return out
 for source in names:
  rr=[r for r in rows if r['source']==source];ims=[render(r) for r in rr];p=R/(source+'-class-specific.gif')
  ims[0].save(p,save_all=True,append_images=ims[1:],duration=500,loop=0,optimize=False)
  with Image.open(p) as im:assert im.n_frames==len(rr)
 for source,index in [('ground_rescue',0),('surf',11),('rocks',8),('crowded_beach',30)]:
  r=next(r for r in rows if r['source']==source and r['sample_index']==index);pair=Image.new('RGB',(960,1240));pair.paste(render(r,'exclusive'),(0,0));pair.paste(render(r),(0,620));pair.save(R/(source+'-ab-comparison.jpg'),quality=92)
 dest=A/'results/context-video-v1';dest.mkdir(exist_ok=True)
 for n in ['report.json','hypothesis-observations.json','ground-scope-correction.json']:shutil.copy2(R/n,dest/n)
 shutil.copytree(Q,dest/'hypothesis-review',ignore=shutil.ignore_patterns('calls'),dirs_exist_ok=True);(dest/'README.md').write_text(md)
 p=A/'notebooks/19_context_verified_video.ipynb';old=nbformat.read(p,as_version=4);nb=nbformat.v4.new_notebook();nb.metadata=old.metadata
 nb.cells=[nbformat.v4.new_markdown_cell(md),nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/context-video-v1'\nassert all(json.loads((R/'audit.json').read_text()).values())\nassert all(json.loads((R/'hypothesis-review/audit.json').read_text()).values())\nprint('Main and A/B integrity audits passed.')\nprint(json.dumps(json.loads((R/'report.json').read_text())['class_specific_ablation']['summary'],indent=2))")]
 for source in ['ground_rescue','surf','rocks','crowded_beach']:
  nb.cells += [nbformat.v4.new_markdown_cell('## '+names[source]+' — exclusive above, class-specific below'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-ab-comparison.jpg'))!r}))")]
 for source in names:
  nb.cells += [nbformat.v4.new_markdown_cell('## '+names[source]+' — full class-specific replay'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-class-specific.gif'))!r}))")]
 nb.cells += [nbformat.v4.new_markdown_cell('## Ambiguous beach-trigger evidence\nNative padded crop submitted to the animal reviewer at approximately15seconds. The scene reviewer’s mammal-positive explanation cited birds. This is unresolved evidence, not a clean negative pass.'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/'animal-review/verification-inputs/crowded_beach-030/region-1.jpg')!r}))")]
 nbformat.write(nb,p);print(json.dumps({'summary':summary,'total_new_requests':base['total_new_requests_all_phases'],'failed_class_specific':result['failed_requests'],'request_median':base['class_specific_ablation']['median_request_wall_seconds'],'request_max':base['class_specific_ablation']['max_request_wall_seconds']},indent=2),flush=True);print('Final notebook19 saved',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
