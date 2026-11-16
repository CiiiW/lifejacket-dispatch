"""Post-hoc diagnostic context-box classification, separate from locked aerial trial."""
from pathlib import Path
import json,sys,time,traceback,hashlib
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A))
import video_patrol_review_v1 as reviewer
R=Path.home()/'aerial-data/aerial-patrol-v1';Q=R/'context-ablation';Q.mkdir(exist_ok=True)
reviewer.ROOT=Q
rows=json.loads((R/'observations.json').read_text());examples=[]
for source,kind in [('surf',0),('rocks',2)]:
 r=next(r for r in rows if r['source']==source and r['combined_gate']['context_visible'] and any(b['class_id']==kind for b in r['combined_packet']['boxes']))
 boxes=sorted([b for b in r['combined_packet']['boxes'] if b['class_id']==kind],key=lambda b:b['score'],reverse=True)[:3]
 examples.append((r,boxes))
ground=json.loads((Path.home()/'aerial-data/combined-gemini-v1/observations.json').read_text())
r=next(r for r in ground if r['source']=='rescue' and r['sample_index']==12)
people=sorted([b for b in r['combined_packet']['boxes'] if b['class_id']==0],key=lambda b:b['score'],reverse=True)[:2]
vehicle=sorted([b for b in r['combined_packet']['boxes'] if b['class_id']==2],key=lambda b:b['score'],reverse=True)[:1]
examples.append((r,people+vehicle))
plan={'scope':'Post-hoc diagnostic on two selected aerial failure frames and one previously inspected ground-level seal+person+truck frame. No held-out result or production adoption.',
 'max_requests':3,'classifier':'Existing neutral region ontology, no new expected labels passed to Gemini. Input boxes are routed to its region-selection API; original proposed classes retained only for output comparison.',
 'acceptance':'Keep a person/vehicle proposal only if its region classification agrees with that proposed class; animal/background/uncertain/failed classifications do not confirm context.',
 'frames':[{'source':r['source'],'sample_index':r['sample_index'],'sha256':r['sha256'],'proposals':boxes} for r,boxes in examples],
 'reviewer_code_sha256':hashlib.sha256((A/'video_patrol_review_v1.py').read_bytes()).hexdigest()}
assert not (Q/'plan.json').exists()
(Q/'plan.json').write_text(json.dumps(plan,indent=2));out=[]
for r,boxes in examples:
 f={**r,'source':'context-'+r['source'],'merged_predictions':[{**b,'class_id':1} for b in boxes]}
 result=reviewer.verify(f)
 subjects={v['region_id']:v['subject_class'] for v in result.get('data',{}).get('regions',[])}
 checks=[]
 for i,b in enumerate(boxes,1):
  expected={0:'person',2:'vehicle'}[b['class_id']];actual=subjects.get(f'R{i:02}','failed')
  checks.append({'proposed_class':expected,'reviewed_class':actual,'retained':result['status']=='success' and expected==actual,'box':b})
 out.append({'source':r['source'],'seconds':r['seconds'],'status':result['status'],'checks':checks,'full_review':result})
 print(json.dumps({k:v for k,v in out[-1].items() if k!='full_review'},indent=2),flush=True)
(Q/'report.json').write_text(json.dumps({'scope':plan['scope'],'new_requests':3,'results':out},indent=2))
