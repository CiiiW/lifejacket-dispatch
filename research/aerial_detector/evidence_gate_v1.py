"""Research evidence gate. Both review arms use the same Gemini model, not independent models."""
import math
class EvidenceGate:
 def __init__(self,max_check_gap=4.):
  self.max_check_gap=max_check_gap;self.scene=None;self.last_time=None;self.last_check=None;self.streak=0
 def update(self,scene,seconds,*,scheduled=False,crop_yes=False,scene_yes=False):
  if not math.isfinite(seconds) or seconds<0:raise ValueError('Invalid time')
  reset=scene!=self.scene
  if reset:self.scene=scene;self.last_time=None;self.last_check=None;self.streak=0
  if self.last_time is not None and seconds<self.last_time:raise ValueError('Time moved backwards')
  self.last_time=seconds
  if not scheduled:return {'confirmed':False,'reason':'unscheduled','scene_streak':self.streak}
  if self.last_check is not None and seconds<=self.last_check:raise ValueError('Duplicate scheduled time')
  consecutive=self.last_check is not None and seconds-self.last_check<=self.max_check_gap
  self.streak=(self.streak+1 if consecutive else 1) if scene_yes else 0
  self.last_check=seconds
  agreement=bool(crop_yes and scene_yes)
  repeated=bool(scene_yes and self.streak>=2)
  return {'confirmed':agreement or repeated,'reason':'agreement' if agreement else 'repeated_scene' if repeated else 'insufficient_evidence','scene_streak':self.streak}
def check_gate():
 tests=[]
 def record(name,ok):
  assert ok,name;tests.append({'case':name,'passed':True})
 g=EvidenceGate()
 record('single_scene_yes_held',not g.update('a',0,scheduled=True,scene_yes=True)['confirmed'])
 record('consecutive_scene_yes_confirms',g.update('a',3,scheduled=True,scene_yes=True)['confirmed'])
 record('scheduled_negative_clears_streak',not g.update('a',6,scheduled=True)['confirmed'] and g.streak==0)
 record('crop_only_does_not_confirm',not g.update('a',9,scheduled=True,crop_yes=True)['confirmed'])
 record('same_check_agreement_confirms',g.update('a',12,scheduled=True,crop_yes=True,scene_yes=True)['confirmed'])
 record('new_scene_clears_streak',not g.update('b',0,scheduled=True,scene_yes=True)['confirmed'])
 record('expired_check_gap_restarts',not g.update('b',5,scheduled=True,scene_yes=True)['confirmed'])
 record('unscheduled_does_not_confirm',not g.update('b',5.5)['confirmed'])
 try:g.update('b',4)
 except ValueError:record('backward_time_rejected',True)
 else:raise AssertionError('backward time')
 try:g.update('c',float('nan'))
 except ValueError:record('nonfinite_time_rejected',True)
 else:raise AssertionError('nonfinite')
 return tests
