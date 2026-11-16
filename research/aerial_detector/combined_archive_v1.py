"""Audit and visualize paired detector -> actual Gemini -> patrol-context outputs."""
from pathlib import Path
import sys,json,time,hashlib,shutil,statistics,traceback
from PIL import Image,ImageDraw
import nbformat
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import dmd
from evidence_gate_v1 import EvidenceGate
from patrol_memory import PatrolMemory
R=Path.home()/'aerial-data/combined-gemini-v1'
sha=lambda p:dmd.file_sha256(p)
def main():
 deadline=time.monotonic()+1200
 while not (R/'report.json').exists():
  if time.monotonic()>deadline:raise RuntimeError('Review wait timeout')
  time.sleep(2)
 plan=json.loads((R/'trial-plan.json').read_text());source=json.loads((R/'r7-source.json').read_text());report=json.loads((R/'report.json').read_text())
 rows=json.loads((R/'observations.json').read_text());cr=json.loads((R/'crop-reviews.json').read_text());sr=json.loads((R/'scene-reviews.json').read_text())
 ci={(r['source'],r['sample_index']):r for r in cr};si={(r['source'],r['sample_index']):r for r in sr}
 audit={'source_sha256_verified':sha(source['path'])==source['sha256'],
  'source_fully_decoded':source['complete'] and abs(source['decoded_frames']/source['fps']-source['playlist_duration_seconds'])<.5,
  'frame_hashes_verified':all(sha(r['path'])==r['sha256'] for r in rows),
  'frozen_code_verified':all(sha(A/n)==value for n,value in plan['code_hashes'].items()),
  'dmd_weights_verified':sha(Path.home()/'aerial-data/weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth')==plan['dmd_sha256'],
  'world_weights_verified':sha(Path.home()/'aerial-data/model-comparison-v1/yolov8s-worldv2.pt')==plan['context_weights_sha256'],
  'crop_inputs_verified':all([sha(p) for p in [R/'verification-inputs'/v['key']/'context.jpg']+sorted((R/'verification-inputs'/v['key']).glob('region-*.jpg'))]==v['input_sha256'] for v in cr if v['status']=='success'),
  'scene_inputs_verified':all(sha(R/'scene-inputs'/(v['key']+'.jpg'))==v['input_sha256'] for v in sr if v['status']=='success'),
  'same_animal_proposals':True,'paired_state_replay':True,
  'no_automatic_dispatch':all(not r[arm+'_gate']['automatic_incident_or_dispatch'] for r in rows for arm in ['baseline','combined'])}
 for r in rows:
  a=[b for b in r['merged_predictions'] if b['class_id']==1 and b['score']>=.3]
  b=[b for b in r['combined_packet']['boxes'] if b['class_id']==1]
  audit['same_animal_proposals'] &= sorted(json.dumps(v,sort_keys=True) for v in a)==sorted(json.dumps(v,sort_keys=True) for v in b)
 checkpoint_rows=[]
 for name in dict.fromkeys(r['source'] for r in rows):
  eg=EvidenceGate();mem={arm:PatrolMemory() for arm in ['baseline','combined']}
  for r in [v for v in rows if v['source']==name]:
   key=(name,r['sample_index']);c=ci.get(key);s=si.get(key)
   cy=bool(c and c['status']=='success' and c['animal_confirmed']);sy=bool(s and s['status']=='success' and s['data']['nonhuman_animal_visible']=='yes')
   cf=bool(c and (c['status']!='success' or c['uncertain']));sf=bool(s and (s['status']!='success' or s['data']['nonhuman_animal_visible']=='uncertain'))
   e=eg.update(name,r['seconds'],scheduled=bool(c or s),crop_yes=cy,scene_yes=sy)
   audit['paired_state_replay'] &= e==r['evidence']
   candidate=any(b['class_id']==1 for b in r['merged_predictions'])
   for arm,boxes in [('baseline',r['merged_predictions']),('combined',r['combined_packet']['boxes'])]:
    state=mem[arm].update(name,r['seconds'],animal_candidate=candidate,animal_confirmed=e['confirmed'],persons=sum(b['class_id']==0 for b in boxes),vehicles=sum(b['class_id']==2 for b in boxes),review_failed=cf or sf)
    audit['paired_state_replay'] &= state==r[arm+'_gate']
   if c or s:
    checkpoint_rows.append({'source':name,'source_seconds':r['source_seconds'],'crop_yes':cy,'scene_yes':sy,'gate_open':r['combined_gate']['context_visible'],
     'baseline_person_boxes_shown':r['baseline_gate']['shown_persons'],'combined_person_boxes_shown':r['combined_gate']['shown_persons'],
     'baseline_vehicle_boxes_shown':r['baseline_gate']['shown_vehicles'],'combined_vehicle_boxes_shown':r['combined_gate']['shown_vehicles'],
     'scene_data':s.get('data') if s else None})
 assert all(audit.values()),audit
 (R/'audit.json').write_text(json.dumps(audit,indent=2));(R/'checkpoint-output.json').write_text(json.dumps(checkpoint_rows,indent=2))
 previews=[]
 for name in ['rescue','beach_people','rocky_people']:
  for arm in (['baseline','combined'] if name=='rescue' else ['combined']):
   movie=[]
   for r in [v for v in rows if v['source']==name]:
    im=Image.open(r['path']).convert('RGB');im.thumbnail((640,360));d=ImageDraw.Draw(im);gate=r[arm+'_gate']
    boxes=r['merged_predictions'] if arm=='baseline' else r['combined_packet']['boxes']
    if gate['context_visible']:
     sx=im.width/r['size'][0];sy=im.height/r['size'][1]
     for b in boxes:
      if b['class_id'] not in (0,2):continue
      d.rectangle((b['x1']*sx,b['y1']*sy,b['x2']*sx,b['y2']*sy),outline='cyan' if b['class_id']==0 else 'orange',width=2)
    d.rectangle((0,0,im.width,36),fill='#102633')
    d.text((4,4),f"{arm} | {name} source {r['source_seconds']:.2f}s | animal gate {'ON' if gate['context_visible'] else 'PENDING'}",fill='white')
    d.text((4,20),f"Context proposals shown: people {gate['shown_persons']}, vehicles {gate['shown_vehicles']}",fill='white')
    if name=='rescue':
     d.rectangle((0,im.height-17,im.width,im.height),fill='#102633')
     d.text((4,im.height-14),'NOAA Fisheries / HMAR | sampled research overlays; source linked in notebook',fill='white')
    movie.append(im.quantize(colors=96,method=2))
   path=R/f'{name}-{arm}.gif';movie[0].save(path,save_all=True,append_images=movie[1:],duration=500,loop=0,optimize=False)
   with Image.open(path) as gif:assert gif.n_frames==len(movie)
   previews.append(str(path))
 positive=next(s for s in report['summary'] if s['source']=='rescue');controls=[s for s in report['summary'] if s['source']!='rescue']
 report['manual_screening_reference']={'source_seconds':18.,'observed_before_model_inference':'Monk seal, at least two responders and pickup visible in same native frame. Not exhaustive frame/box ground truth.'}
 report['paired_audit']=audit
 report['checkpoint_output_file']='checkpoint-output.json'
 (R/'report.json').write_text(json.dumps(report,indent=2))
 text="# Combined detector → Gemini: real seal-release smoke test\n\n"
 text+="A new NOAA Hawaiian monk seal release segment contains a visually verified seal, responders and pickup together. This is **ground-level 1080p footage**, not a drone test. The two coastal controls are previously inspected regression sources.\n\n"
 text+="| Source | Samples | Animal gate open | Baseline people shown | Combined people shown | Baseline vehicles shown | Combined vehicles shown |\n|---|---:|---:|---:|---:|---:|---:|\n"
 for s in report['summary']:
  text+=f"| {s['source']} | {s['samples']} | {s['gate_open_samples']} | {s['baseline_persons_shown_samples']} | {s['combined_persons_shown_samples']} | {s['baseline_vehicles_shown_samples']} | {s['combined_vehicles_shown_samples']} |\n"
 text+="\nCounts mean **sampled frames with gated detector proposals displayed**, not verified object counts or accuracy. The source has not been exhaustively annotated for all boxes, identities, visibility or animal exits.\n\n"
 text+=f"**{len(rows)} frame samples; {report['requests']} actual Gemini requests; {report['failed_requests']} request failures.** Source hashes, all Gemini image hashes, frozen code/weights, identical animal proposals and both state replays verified. No automatic incident or dispatch.\n\n"
 text+="## Fixed paired design\n\nBaseline: DMD animal and context proposals. Combined: exactly the same DMD animal proposals, with YOLO-World full-frame person/vehicle context. Both share identical actual Gemini animal judgments. This isolates the context branch, rather than confounding it with separate stochastic Gemini answers.\n\n"
 text+="Every sixth 2-FPS sample is reviewed: at most three native animal crops plus overview, and a separate independent scene check. The unchanged gate accepts same-check crop+scene agreement or two consecutive scene confirmations within four seconds; recent evidence is held for three seconds. Both reviewers use the same Gemini model and may make correlated mistakes.\n\n"
 text+="## Positive source and visual check\n\n[NOAA release b-roll for Hawaiian monk seal R7AF](https://videos.fisheries.noaa.gov/detail/videos/b-roll:-seals-and-sea-lions/video/6297080580001/b-roll:-release-of-hawaiian-monk-seal-r7af). Credit: **NOAA Fisheries and Hawaii Marine Animal Response**; opening source slate retained in cached full media. The complete 52-second video rendition decoded to 3,120 frames at 60 FPS. Only source seconds 12–24 were sampled at 2 FPS, with the window selected before model scoring to include visible co-occurrence.\n\n"
 text+="The native 18-second frame was manually screened before inference and shows the seal, responders and a pickup. Derived previews are sampled, resized and overlaid; no endorsement is implied.\n\n"
 text+="## Remaining limits\n\nThis is an offline research pipeline, not app integration or live-stream validation. Source-time replay excludes inference/API scheduling delay. No injury, urgency, danger, harassment or rescue-need inference is performed. Natural shot cuts, current animal exits and display of every individual context box remain unvalidated. A three-second evidence hold is not proof the animal remains visible on every frame.\n\n"
 text+="The independent scene checker can hallucinate animals, and both reviewers share the same model. The two negatives are repeated-call regressions rather than held-out negatives. This test alone cannot justify deployment.\n\n"
 text+="Control credits: [beach with people](https://www.pexels.com/video/people-gathering-on-the-seashore-4916420/) — Tima Miroshnichenko/Pexels; [rocky shore with people](https://www.pexels.com/video/aerial-view-of-people-on-rocky-beach-shoreline-36617003/) — Hiva Sobhani/Pexels.\n"
 (R/'README.md').write_text(text)
 dest=A/'results/combined-gemini-v1';dest.mkdir(parents=True,exist_ok=True)
 for p in R.glob('*.json'):shutil.copy2(p,dest/p.name)
 shutil.copy2(R/'README.md',dest/'README.md')
 template=nbformat.read(A/'notebooks/16_alternative_detector_comparison.ipynb',as_version=4)
 nb=nbformat.v4.new_notebook(metadata=template.metadata)
 nb.cells=[nbformat.v4.new_markdown_cell(text),
  nbformat.v4.new_code_cell("from pathlib import Path\nimport json\nfrom IPython.display import display,Image\nR=Path.home()/'aerial-data/combined-gemini-v1'\nprint((R/'audit.json').read_text())\nprint((R/'checkpoint-output.json').read_text())")]
 for p in previews:nb.cells+=[nbformat.v4.new_markdown_cell('## '+Path(p).stem),nbformat.v4.new_code_cell(f"display(Image(filename={p!r}))")]
 nb.cells+=[nbformat.v4.new_markdown_cell("## Reproduce\nScripts: combined_detector_v1.py, combined_gemini_review_v1.py, combined_archive_v1.py. Cached source media, manifests and call images are under ~/aerial-data/combined-gemini-v1. Use saved responses first; rerunning model review incurs API usage. No source usernames, expected labels or scenario descriptions are passed to Gemini.")]
 nbformat.write(nb,A/'notebooks/17_combined_detector_gemini.ipynb')
 print(json.dumps(report,indent=2),flush=True);print('Saved notebook17',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
