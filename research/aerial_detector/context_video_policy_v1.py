"""Experimental animal-evidence clearing and exact-class context acceptance; no app integration."""
from evidence_gate_v1 import EvidenceGate
from patrol_memory import PatrolMemory
class AnimalEvidence:
 def __init__(self,clear_negatives=False):self.eg=EvidenceGate();self.memory=PatrolMemory();self.clear_negatives=clear_negatives
 def update(self,frame,crop=None,scene=None):
  cy=bool(crop and crop['status']=='success' and crop['animal_confirmed'])
  sy=bool(scene and scene['status']=='success' and scene['data']['nonhuman_animal_visible']=='yes')
  dual_no=bool(crop and scene and crop['status']=='success' and not crop['uncertain'] and not crop['animal_confirmed'] and scene['status']=='success' and scene['data']['nonhuman_animal_visible']=='no')
  e=self.eg.update(frame['source'],frame['seconds'],scheduled=bool(crop or scene),crop_yes=cy,scene_yes=sy)
  cleared=bool(self.clear_negatives and dual_no)
  if cleared:self.memory.last_confirmed=None
  boxes=frame['combined_packet']['boxes']
  failed=bool(crop and (crop['status']!='success' or crop['uncertain'])) or bool(scene and (scene['status']!='success' or scene['data']['nonhuman_animal_visible']=='uncertain'))
  s=self.memory.update(frame['source'],frame['seconds'],animal_candidate=any(b['class_id']==1 for b in frame['merged_predictions']),animal_confirmed=e['confirmed'],persons=sum(b['class_id']==0 for b in boxes),vehicles=sum(b['class_id']==2 for b in boxes),review_failed=failed)
  return {'gate':s,'evidence':e,'dual_negative':dual_no,'negative_cleared':cleared,'crop_yes':cy,'scene_yes':sy}
def classify_context(boxes,result):
 subjects={r['region_id']:r['subject_class'] for r in result.get('data',{}).get('regions',[])} if result.get('status')=='success' else {}
 if subjects and (len(subjects)!=len(boxes) or set(subjects)!={f'R{i:02}' for i in range(1,len(boxes)+1)}):raise ValueError('Region mapping mismatch')
 return [{'box':b,'proposed_class':{0:'person',2:'vehicle'}[b['class_id']],'reviewed_class':subjects.get(f'R{i:02}','unreviewed'),'accepted':subjects.get(f'R{i:02}')=={0:'person',2:'vehicle'}[b['class_id']]} for i,b in enumerate(boxes,1)]
def check_policy():
 tests=[]
 f=lambda t,source='s':{'source':source,'seconds':t,'merged_predictions':[],'combined_packet':{'boxes':[{'class_id':0}]}}
 c=lambda yes,uncertain=False:{'status':'success','animal_confirmed':yes,'uncertain':uncertain}
 s=lambda yes:{'status':'success','data':{'nonhuman_animal_visible':'yes' if yes else 'no'}}
 def record(name,ok):assert ok,name;tests.append({'case':name,'passed':True})
 p=AnimalEvidence(True);p.update(f(0),c(True),s(True))
 record('single_negative_does_not_revoke',p.update(f(.5),None,s(False))['gate']['context_visible'])
 record('uncertain_crop_does_not_revoke',p.update(f(1),c(False,True),s(False))['gate']['context_visible'])
 record('dual_negative_revokes_recent_evidence',not p.update(f(1.5),c(False),s(False))['gate']['context_visible'])
 p.update(f(2),c(True),s(True))
 record('failed_review_does_not_revoke',p.update(f(2.5),{'status':'failed','uncertain':True},s(False))['gate']['context_visible'])
 record('provided_scene_change_clears',not p.update(f(0,'new'))['gate']['context_visible'])
 boxes=[{'class_id':0},{'class_id':2}]
 r={'status':'success','data':{'regions':[{'region_id':'R01','subject_class':'animal'},{'region_id':'R02','subject_class':'vehicle'}]}}
 record('class_disagreement_hidden',not classify_context(boxes,r)[0]['accepted'])
 record('matching_context_retained',classify_context(boxes,r)[1]['accepted'])
 record('failed_context_review_hides_all',not any(x['accepted'] for x in classify_context(boxes,{'status':'failed'})))
 return tests
