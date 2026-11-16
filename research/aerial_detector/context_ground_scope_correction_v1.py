"""Correct ground regression cohort after an accidental inclusion of study17's controls.
No requests, detector outputs, accepted region decisions or aerial rows are changed.
"""
from pathlib import Path
import json,hashlib,shutil
D=Path.home()/'aerial-data';R=D/'context-video-v1'
p=R/'observations.json';backup=R/'observations-before-ground-scope-correction.json'
if not backup.exists():shutil.copy2(p,backup)
raw=json.loads(backup.read_text());ref=json.loads((D/'combined-gemini-v1/observations.json').read_text())
valid={r['sha256'] for r in ref if r['source']=='rescue'}
rows=[r for r in raw if r['cohort']=='aerial' or r['sha256'] in valid]
assert sum(r['cohort']=='aerial' for r in rows)==141
assert sum(r['cohort']!='aerial' for r in rows)==24
assert len({(r['source'],r['sample_index']) for r in rows})==len(rows)
before=[r for r in raw if r['cohort']=='aerial'];after=[r for r in rows if r['cohort']=='aerial'];assert before==after
eligible=[r for r in rows if r['old_animal_state']['gate']['context_visible'] or r['clear_animal_state']['gate']['context_visible']]
assert len({(r['source'],r['sample_index']) for r in eligible})==len(eligible)
note={'scope':'Postprocessing correction only: the ground reference file contains24 release rows and41 old negative-control rows. The completed verifier had renamed every reference row ground_rescue. The41 closed-gate rows generated no requests but duplicated positive frame keys in later lookup/summary. They are removed by exact release-frame SHA256 membership.',
 'raw_observations_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'removed_closed_gate_rows':len(raw)-len(rows),'no_model_calls_repeated':True,'aerial_rows_unchanged':True}
assert all(not r['old_animal_state']['gate']['context_visible'] and not r['clear_animal_state']['gate']['context_visible'] for r in raw if r not in rows)
p.write_text(json.dumps(rows,indent=2));note['corrected_observations_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
(R/'ground-scope-correction.json').write_text(json.dumps(note,indent=2))
print(json.dumps(note,indent=2))
