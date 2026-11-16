from pathlib import Path
import json,shutil,nbformat,hashlib
R=Path.home()/'aerial-data/aerial-patrol-v1';A=Path.home()/'lifejacket-dispatch/research/aerial_detector';dest=A/'results/aerial-patrol-v1'
report=json.loads((R/'report.json').read_text());ab=json.loads((R/'context-ablation/report.json').read_text());cut=json.loads((R/'hard-cut-regression.json').read_text())
for r in ab['results']:r['source_seconds']=r['seconds']+12 if r['source']=='rescue' else r['seconds']
context_audit={}
Q=R/'context-ablation'
context_audit['all_three_requests_succeeded']=all(r['status']=='success' for r in ab['results'])
context_audit['all_review_image_hashes_verified']=all([hashlib.sha256(p.read_bytes()).hexdigest() for p in [Q/'verification-inputs'/r['full_review']['key']/'context.jpg']+sorted((Q/'verification-inputs'/r['full_review']['key']).glob('region-*.jpg'))]==r['full_review']['input_sha256'] for r in ab['results'])
assert all(context_audit.values())
ab['audit']=context_audit
(Q/'report.json').write_text(json.dumps(ab,indent=2))
report['hard_cut_regression']={mode:{k:v for k,v in arm.items() if k!='rows'} for mode,arm in cut['arms'].items()}
report['context_box_diagnostic']={'scope':ab['scope'],'requests':3,'aerial_failure_proposals_rejected':sum(not c['retained'] for r in ab['results'] if r['source']!='rescue' for c in r['checks']),'ground_positive_proposals_retained':sum(c['retained'] for r in ab['results'] if r['source']=='rescue' for c in r['checks']),'audit':context_audit}
report['manual_context_error_examples']=[{'source':'surf','source_seconds':5.52,'proposed_class':'person','manual_visual_subject':'Surfacing nonhuman animal; no human body in this target crop.'},{'source':'rocks','source_seconds':4.004,'proposed_class':'vehicle','manual_visual_subject':'Rock carrying pinnipeds; no vehicle in this target crop.'}]
report['recommendation']='Do not promote context branch as-is. Validate proposed context boxes as well as animal presence, add reliable scene-boundary/negative-evidence handling, and evaluate latency. Marine-human/vehicle aerial co-occurrence retention remains untested.'
report['plan_metadata_note']=json.loads((R/'trial-plan-notes.json').read_text())['note']
(R/'report.json').write_text(json.dumps(report,indent=2));shutil.copy2(R/'report.json',dest/'report.json')
for n in ['hard-cut-regression.json','trial-plan-notes.json']:shutil.copy2(R/n,dest/n)
(dest/'context-ablation').mkdir(exist_ok=True)
for n in ['plan.json','report.json']:shutil.copy2(Q/n,dest/'context-ablation'/n)
p=A/'notebooks/18_aerial_patrol_validation.ipynb';nb=nbformat.read(p,as_version=4)
original=nb.cells[0].source
coverage=original[original.index('## What the overlays mean'):]
lead="""# Drone-video test: animal gate works, context needs verification

**The combined prototype is not ready to promote.** The aerial test exposed context errors that the animal-presence gate cannot catch: a sea lion was proposed as a person, and a rock carrying pinnipeds was proposed as a vehicle.

Four newly reviewed aerial clips, 24 sampled frames each (first 12 seconds at 2 FPS), with the previous settings frozen. This is aerial stock footage, not a DJI field recording.

| Clip | Animal gate active | Person frames | Vehicle frames |
|---|---:|---:|---:|
| Platform | 24/24 | 0 | 0 |
| Surf | 13/24 | 2 | 0 |
| Rocks | 24/24 | 0 | 8 |
| Beach control | 0/24 | 0 | 0 |

**Gate-open/display counts are not accuracy, recall or unique-object counts.** Surf visibility varies with wave occlusion. The two unexpected context types above were visually checked at native-resolution crops; their examples are shown below.

**Main trial: 96 frames, 32 Gemini requests, zero failed requests.** All 12 integrity/state-replay checks and 23 policy fixtures passed. Both detector arms shared the same DMD animal proposals and actual Gemini decisions. Full baseline/combined counts are in report.json.

## Two failure modes and the next prototype

1. **Animal presence does not validate context boxes.** A separate, post-hoc three-request crop check rejected the inspected false person and vehicle proposals, while retaining two person proposals and one truck proposal in the earlier ground-level seal-release frame. These five proposals across three selected frames are a diagnostic, not held-out evidence or full-video context filtering. This check has not been applied to the 96-frame replays.
2. **Stale evidence survives a hard cut.** An explicitly synthetic cut from platform animals to the actual beach-control frames left context displayed for six control frames (source offsets 0–2.5025 seconds) without a cut reset. Providing the known scene reset reduced this to zero. Automatic cut detection is not implemented; this checks the reset hook, not natural animal exits.

The next candidate should verify **both animal evidence and the proposed person/vehicle crops**, and clear evidence on reliable scene transitions. It needs new aerial co-occurrence validation before promotion.

## Timing is still a limitation

The 4K tiled DMD pass took roughly **2.0 seconds per analyzed frame** on the Tesla T4. The 1080p clips took about 0.67–0.68 seconds. YOLO-World context took about 0.03–0.06 seconds; individual Gemini requests had medians of about 2.6–3.7 seconds. The 2-FPS replay therefore does not demonstrate a live 2-FPS pipeline.

"""
nb.cells[0].source=lead+coverage
# Keep visual diagnostics separate from the frozen combined replay.
extra=[nbformat.v4.new_markdown_cell("## Native crops of the false context proposals\nThese show the two selected failure examples before context verification. The original replay retains them; the post-hoc classifier rejects them.")]
for source in ['surf','rocks']:
 extra += [nbformat.v4.new_markdown_cell('### '+source+' — context target crop'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-context-roi.jpg'))!r}))")]
base_cells=nb.cells[:2]
for source in ['raft','surf','rocks','crowded_beach']:
 base_cells += [nbformat.v4.new_markdown_cell('## '+source+' — combined aerial replay'),nbformat.v4.new_code_cell(f"display(Image(filename={str(R/(source+'-combined.gif'))!r}))")]
nb.cells=base_cells[:2]+extra+base_cells[2:]
nb.cells += [nbformat.v4.new_markdown_cell("## Separate context-crop diagnostic and injected-cut result\nThree additional Gemini requests; no failed calls. Cached decisions and crop hashes are archived. The ground-level positive is a retention sanity check only; it does not fill the marine co-occurrence drone gap."),
nbformat.v4.new_code_cell("ab=json.loads((R/'context-ablation/report.json').read_text())\nfor r in ab['results']:\n print(r['source'], 'source second',r['source_seconds'],[(c['proposed_class'],c['reviewed_class'],c['retained']) for c in r['checks']])\ncut=json.loads((R/'hard-cut-regression.json').read_text())\nprint({m:{k:v for k,v in a.items() if k!='rows'} for m,a in cut['arms'].items()})")]
nbformat.write(nb,p)
(R/'README.md').write_text(nb.cells[0].source);(dest/'README.md').write_text(nb.cells[0].source)
print('Saved notebook18 findings, error crops, separate diagnostic and cut regression.')
print(json.dumps(report['context_box_diagnostic'],indent=2))
