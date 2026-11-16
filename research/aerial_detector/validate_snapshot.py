#!/usr/bin/env python3
"""Validate committed research evidence offline. Never invokes a model or network."""
from pathlib import Path
import ast,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text())
def main():
 checks=[]
 def check(name,condition):
  if not condition:raise AssertionError(name)
  checks.append(name)
 manifest=load(ROOT/'publication_manifest.json')
 check('publication file hashes',all((ROOT/name).is_file() and sha(ROOT/name)==digest for name,digest in manifest['files'].items()))
 report=load(ROOT/'results/practical-options-v1/report.json')
 reviews=load(ROOT/'results/practical-options-v1/reviews.json')
 cases=[reviews]+[load(ROOT/'results/practical-options-v1'/folder/'reviews.json') for folder in ['cut-probe','seal-probe','tight-seal-probe']]
 check('104 recorded requests retained',sum(map(len,cases))==report['new_requests']==104)
 check('three unusable outputs retained',sum(r['status']!='success' for rows in cases for r in rows)==report['failed_outputs']==3)
 check('19 video windows and205 samples',len(load(ROOT/'results/practical-options-v1/groups.json'))==19 and len(load(ROOT/'results/practical-options-v1/frame-catalog.json'))==205)
 check('four review modes',set(r['mode'] for r in reviews)=={'single_whole','single_native','burst_whole','burst_native'})
 check('positive anchor denominators',all(r['anchor_positive_windows']==13 and r['screened_control_windows']==5 for r in report['video_method_summaries']))
 check('tiny seal stress preserved',len(report['seal_stress'])==3 and all(r['images']==8 and r['positive_images_confirmed']==0 for r in report['seal_stress']))
 catalog=load(ROOT/'assets/CREDITS.json')
 check('all examples credited and hashed',len(catalog)==8 and all(sha(ROOT/c['file'])==c['published_sha256'] and c['credit'] for c in catalog))
 notebooks=[ROOT/name for name in manifest['files'] if name.startswith('notebooks/') and name.endswith('.ipynb')]
 check('five compact notebooks',len(notebooks)==5)
 for p in notebooks:
  nb=load(p)
  check(p.name+' has no embedded outputs',all(c.get('outputs',[])==[] and c.get('execution_count') is None for c in nb['cells'] if c['cell_type']=='code'))
  check(p.name+' is compact',p.stat().st_size<100_000)
  for c in nb['cells']:
   text=''.join(c['source']) if isinstance(c['source'],list) else c['source']
   for match in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)',text):
    if not match[1].startswith(('http://','https://')):check(p.name+' image link '+match[1],(p.parent/match[1]).is_file())
 for p in ROOT.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
 check('Python sources parse',True)
 forbidden={'.mp4','.webm','.mov','.avi','.gif','.pt','.pth','.onnx','.engine','.zip'}
 files=[p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 check('no recordings or weights',all(p.suffix.lower() not in forbidden for p in files))
 patterns=[r'gh[pousr]_[A-Za-z0-9]{20,}',r'github_pat_[A-Za-z0-9_]{30,}',r'AIza[0-9A-Za-z_-]{30,}',r'-----BEGIN [A-Z ]*PRIVATE KEY-----',r'https?://[^/\s]+:[^/\s]+@']
 for p in files:
  if p.suffix.lower() in {'.jpg','.jpeg','.png'} or p.name==Path(__file__).name:continue
  text=p.read_text(errors='replace')
  check('secret patterns absent: '+str(p.relative_to(ROOT)),not any(re.search(pattern,text) for pattern in patterns))
 # Default standard-library-only checks finish here. Optional core behavior uses installed base dependencies.
 if '--core' in sys.argv:
  sys.path.insert(0,str(ROOT))
  from patrol_memory import check_policy
  from evidence_gate_v1 import check_gate
  from context_video_policy_v1 import check_policy as check_context
  from review_card_guard_v1 import check_guard
  behavior=check_policy()+check_gate()+check_context()+check_guard()
  check('temporal and frame-specific guard fixtures',all(row['passed'] for row in behavior))
  print('Core behavior fixtures:',len(behavior))
 print('PASS:',len(checks),'offline checks; no model calls or network.')
if __name__=='__main__':main()
