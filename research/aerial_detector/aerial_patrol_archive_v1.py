"""Audit and render fixed aerial detector -> Gemini -> context-gate trial."""
from pathlib import Path
import json,sys,time,shutil,statistics,traceback
from PIL import Image,ImageDraw,ImageFont
import nbformat
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from evidence_gate_v1 import EvidenceGate,check_gate
from patrol_memory import PatrolMemory,check_policy
R=Path.home()/'aerial-data/aerial-patrol-v1'
sha=dmd.file_sha256
def save(n,x):(R/n).write_text(json.dumps(x,indent=2))
def main():
 deadline=time.monotonic()+1200
 while not (R/'report.json').exists():
  if time.monotonic()>deadline:raise RuntimeError('Review wait timeout')
  time.sleep(2)
 plan=json.loads((R/'trial-plan.json').read_text());rp=json.loads((R/'review-plan.json').read_text())
 report=json.loads((R/'report.json').read_text());rows=json.loads((R/'observations.json').read_text())
 cr=json.loads((R/'crop-reviews.json').read_text());sr=json.loads((R/'scene-reviews.json').read_text())
 ci={(r['source'],r['sample_index']):r for r in cr};si={(r['source'],r['sample_index']):r for r in sr}
 audit={
 'all_four_sources_decoded':all(s['complete'] for s in plan['sources']),
 'source_sha256_verified':all(sha(s['path'])==s['sha256'] for s in plan['sources']),
 'frame_hashes_verified':len(rows)==96 and all(sha(r['path'])==r['sha256'] for r in rows),
 'frozen_code_verified':all(sha(A/n)==v for n,v in plan['code_hashes'].items()),
 'review_plan_verified':sha(R/'trial-plan.json')==rp['trial_plan_sha256'] and sha(A/'aerial_patrol_review_v1.py')==rp['review_code_sha256'],
 'dmd_weights_verified':sha(Path.home()/'aerial-data/weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth')==plan['dmd_sha256'],
 'context_weights_verified':sha(Path.home()/'aerial-data/model-comparison-v1/yolov8s-worldv2.pt')==plan['context_weights_sha256'],
 'crop_image_hashes_verified':all([sha(p) for p in [R/'verification-inputs'/v['key']/'context.jpg']+sorted((R/'verification-inputs'/v['key']).glob('region-*.jpg'))]==v['input_sha256'] for v in cr if v['status']=='success'),
 'scene_image_hashes_verified':all(sha(R/'scene-inputs'/(v['key']+'.jpg'))==v['input_sha256'] for v in sr if v['status']=='success'),
 'same_animal_proposals':all([b for b in r['merged_predictions'] if b['class_id']==1]==[b for b in r['combined_packet']['boxes'] if b['class_id']==1] for r in rows),
 'no_automatic_dispatch':all(not r[a+'_gate']['automatic_incident_or_dispatch'] for r in rows for a in ['baseline','combined'])
 }
 eg=EvidenceGate();bm=PatrolMemory();cm=PatrolMemory();replay=True
 last_source=None
 for r in rows:
  if r['source']!=last_source:
   eg=EvidenceGate();bm=PatrolMemory();cm=PatrolMemory();last_source=r['source']
  key=(r['source'],r['sample_index']);c=ci.get(key);s=si.get(key)
  e=eg.update(r['source'],r['seconds'],scheduled=r['scheduled_review'],crop_yes=r['crop_yes'],scene_yes=r['scene_yes'])
  replay &= e==r['evidence']
  failed=bool(c and (c['status']!='success' or c['uncertain'])) or bool(s and (s['status']!='success' or s['data']['nonhuman_animal_visible']=='uncertain'))
  for arm,boxes,m in [('baseline',r['merged_predictions'],bm),('combined',r['combined_packet']['boxes'],cm)]:
   x=m.update(r['source'],r['seconds'],animal_candidate=any(b['class_id']==1 for b in r['merged_predictions']),animal_confirmed=e['confirmed'],persons=sum(b['class_id']==0 for b in boxes),vehicles=sum(b['class_id']==2 for b in boxes),review_failed=failed)
   replay &= x==r[arm+'_gate']
 audit['full_paired_state_replay']=bool(replay)
 assert all(audit.values()),audit
 checks=check_gate()+check_policy();save('policy-checks.json',checks);save('audit.json',audit)
 checkpoints=[]
 for r in rows:
  if not r['scheduled_review']:continue
  key=(r['source'],r['sample_index'])
  checkpoints.append({'source':r['source'],'seconds':r['seconds'],'crop_yes':r['crop_yes'],'scene_yes':r['scene_yes'],
    'gate_open':r['combined_gate']['context_visible'],'scene_data':si[key].get('data'),'crop_data':ci[key].get('data'),
    'crop_status':ci[key]['status'],'scene_status':si[key]['status']})
 save('checkpoint-output.json',checkpoints)
 timing=[]
 for source in dict.fromkeys(r['source'] for r in rows):
  rr=[r for r in rows if r['source']==source]
  calls=[r for r in cr+sr if r['source']==source]
  timing.append({'source':source,'median_animal_detector_seconds':statistics.median(r['animal_detector_seconds'] for r in rr),
   'median_context_detector_seconds':statistics.median(r['context_detector_seconds'] for r in rr),
   'median_gemini_request_wall_seconds':statistics.median(r['wall_seconds'] for r in calls),
   'max_gemini_request_wall_seconds':max(r['wall_seconds'] for r in calls)})
 report.update(audit=audit,policy_checks_passed=len(checks),timing=timing,
  visibility_annotation='No exhaustive frame-level animal visibility or box annotations. Gate-open counts are evidence persistence/proposal diagnostics, never video recall.',
  entry_exit_scope='Source changes and expiration are checked by replay and policy fixtures. Natural animal disappearance and automatic shot-cut detection are not validated.',
  source_screening=plan['manual_screening'])
 save('report.json',report)
 font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',16)
 small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
 def render(r):
  im=Image.open(r['path']).convert('RGB');w,h=im.size;im=im.resize((960,540))
  canvas=Image.new('RGB',(960,620),'#12202b');canvas.paste(im,(0,60));draw=ImageDraw.Draw(canvas)
  gate=r['combined_gate'];opened=gate['context_visible'];sx=960/w;sy=540/h
  draw.text((12,8),f"{r['source']} | source {r['seconds']:.2f}s | animal evidence {'ACTIVE' if opened else 'PENDING'}",fill='#92f0aa' if opened else '#ffcf66',font=font)
  draw.text((12,32),f"Context proposals shown: people {gate['shown_persons']} | vehicles {gate['shown_vehicles']}",fill='white',font=font)
  animals=sorted([b for b in r['merged_predictions'] if b['class_id']==1],key=lambda b:b['score'],reverse=True)[:3]
  boxes=[(b,'#ffdf45','animal proposal') for b in animals]
  if opened:
   boxes += [(b,'#00e5ff' if b['class_id']==0 else '#ff9633','person proposal' if b['class_id']==0 else 'vehicle proposal') for b in r['combined_packet']['boxes'] if b['class_id'] in [0,2]]
  for b,color,label in boxes:
   xy=[b['x1']*sx,b['y1']*sy+60,b['x2']*sx,b['y2']*sy+60]
   draw.rectangle(xy,outline=color,width=2);text=label+f" {b['score']:.2f}"
   y=max(60,xy[1]-17);draw.rectangle((xy[0],y,min(959,xy[0]+len(text)*8),y+17),fill='#10202b')
   draw.text((xy[0],y),text,fill=color,font=small)
  draw.text((12,603),'Research overlay: yellow = unverified top-3 animal proposals; cyan/orange = gated context.',fill='white',font=small)
  return canvas
 for source in dict.fromkeys(r['source'] for r in rows):
  rr=[r for r in rows if r['source']==source];ims=[render(r) for r in rr]
  ims[0].save(R/(source+'-combined.gif'),save_all=True,append_images=ims[1:],duration=500,loop=0,optimize=False)
  ims[12].save(R/(source+'-checkpoint.jpg'),quality=92)
  with Image.open(R/(source+'-combined.gif')) as test:assert test.n_frames==24
 dest=A/'results/aerial-patrol-v1';dest.mkdir(exist_ok=True,parents=True)
 for n in ['trial-plan.json','review-plan.json','sources.json','control-source.json','frame-manifest.json','paired-predictions.json','crop-reviews.json','scene-reviews.json','observations.json','report.json','audit.json','policy-checks.json','checkpoint-output.json']:shutil.copy2(R/n,dest/n)
 lines=['# Aerial videos: combined detector → Gemini','',
 'Four newly reviewed public aerial clips, fixed settings, first 12 seconds at 2 FPS. Both arms share identical DMD animal proposals and actual Gemini decisions. Only the context detector differs.','',
 '| Clip | Samples | Animal evidence active | People shown, base → combined | Vehicles shown, base → combined |',
 '|---|---:|---:|---:|---:|']
 for r in report['summary']:
  lines.append(f"| {r['source']} | {r['samples']} | {r['gate_open_samples']} | {r['baseline_persons_shown_samples']} → {r['combined_persons_shown_samples']} | {r['baseline_vehicles_shown_samples']} → {r['combined_vehicles_shown_samples']} |")
 lines+=['','**These are sampled-frame proposal/display counts, not accuracy or recall.** Animal presence can be held for three seconds; natural exits are not annotated.',
 f"**{report['requests']} actual Gemini requests; {report['failed_requests']} failed.** All {len(audit)} integrity/state-replay checks and {len(checks)} policy fixtures passed.",
 '', '## What the overlays mean','',
 'Yellow boxes show the raw top-three animal proposals selected for review, including false proposals. Gemini verifies animal presence, not the correctness of every yellow box. Cyan person and orange vehicle proposals are shown only while the animal-evidence gate is active. A platform is not automatically a vehicle, and birds are outside this DMD animal ontology.',
 '', '## Coverage and remaining gap','',
 'Platform and rocky-islet screening showed clear pinnipeds; the surf animal is small and intermittently obscured by waves. The crowded-beach screening showed people/umbrellas with no mammal identified, but absence is not exhaustively annotated.',
 '**No verified marine-animal-plus-human/vehicle aerial positive was found in these clips.** This trial tests aerial animal evidence and false context activation; it cannot establish marine co-occurrence retention. It is neither DJI capture validation nor a rescue-need classifier.',
 '', '## Fixed settings and timing','',
 'DMD full-frame + native 1280 tiles, 100-pixel overlap, score 0.3 and merge IoU 0.5. YOLO-World full-frame context uses the frozen 21-name vocabulary. Gemini reviews at samples 0, 6, 12 and 18: max three native crops plus overview, and a separate scene check. Gate accepts same-check agreement or two consecutive scene confirmations within four seconds; same-scene evidence hold is three seconds. Both reviewers use the same Gemini model and may hallucinate together.',
 'Source-time replay applies completed reviews at their source timestamps. Measured API/detector timing is archived, but this is not real-time streaming throughput. Automatic scene-cut detection and natural disappearance timing remain untested; known source changes and expiry are covered by state replay/fixtures.',
 '', '## Sources','']
 for s in plan['sources']:lines.append(f"- [{s['source']}]({s['page']}) — {s['credit']}; {s['size'][0]}×{s['size'][1]}, {s['duration']:.2f}s, fully decoded. Derivative overlays are sampled/resized.")
 lines+=['','No model weights/prompts changed, no production integration or deployment, and no automatic incident/dispatch.']
 md='\n'.join(lines);(R/'README.md').write_text(md);(dest/'README.md').write_text(md)
 nb=nbformat.v4.new_notebook();old=nbformat.read(A/'notebooks/17_combined_detector_gemini.ipynb',as_version=4);nb.metadata=old.metadata
 nb.cells=[nbformat.v4.new_markdown_cell(md),nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/aerial-patrol-v1'\naudit=json.loads((R/'audit.json').read_text())\nassert all(audit.values())\nprint('All integrity and paired-state checks passed.')\nprint(json.dumps(json.loads((R/'report.json').read_text())['timing'],indent=2))")]
 for s in plan['sources']:
  source=s['source'];nb.cells += [nbformat.v4.new_markdown_cell('## '+source+' — combined aerial replay'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-combined.gif'))!r}))")]
 nb.cells+=[nbformat.v4.new_markdown_cell("## Reproduce and inspect\nScripts: aerial_patrol_prepare_v1.py, aerial_control_prepare_v1.py, aerial_patrol_infer_v1.py, aerial_patrol_review_v1.py and aerial_patrol_archive_v1.py. Frozen plan, code/weight hashes, all predictions and review decisions are under results/aerial-patrol-v1. Native sources and exact Gemini images are cached under ~/aerial-data/aerial-patrol-v1. Rerunning inference/review can incur GPU/API usage; notebook cells only display cached outputs.")]
 nbformat.write(nb,A/'notebooks/18_aerial_patrol_validation.ipynb')
 print(json.dumps(report,indent=2),flush=True);print('Saved notebook18',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
