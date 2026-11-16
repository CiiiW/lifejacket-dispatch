"""Research-only same-scene patrol evidence memory. No flight or dispatch actions."""
from dataclasses import dataclass,field
import math
@dataclass
class PatrolMemory:
    hold_seconds:float=3.
    episode_idle_seconds:float=8.
    scene:str|None=None
    last_time:float|None=None
    last_candidate:float|None=None
    last_confirmed:float|None=None
    episode_id:str|None=None
    episode_counter:int=0
    def __post_init__(self):
        if not 0<self.hold_seconds<=self.episode_idle_seconds:
            raise ValueError('Invalid evidence windows')
    def update(self,scene,seconds,*,animal_candidate=False,animal_confirmed=False,persons=0,vehicles=0,review_failed=False):
        if not isinstance(scene,str) or not scene:raise ValueError('Scene is required')
        if not math.isfinite(seconds) or seconds<0:raise ValueError('Invalid timestamp')
        if type(animal_candidate) is not bool or type(animal_confirmed) is not bool:raise TypeError('Evidence flags must be booleans from the caller')
        if type(persons) is not int or type(vehicles) is not int or min(persons,vehicles)<0:raise ValueError('Invalid context counts')
        changed=scene!=self.scene
        if changed:
            self.scene=scene;self.last_time=None;self.last_candidate=None;self.last_confirmed=None;self.episode_id=None
        if self.last_time is not None and seconds<self.last_time:raise ValueError('Time moved backward within a scene')
        self.last_time=seconds
        if self.last_candidate is not None and seconds-self.last_candidate>self.episode_idle_seconds:self.episode_id=None
        evidence=animal_candidate or animal_confirmed
        new_episode=False
        if evidence:
            if self.episode_id is None:
                self.episode_counter+=1;self.episode_id=f'{scene}:episode-{self.episode_counter}';new_episode=True
            self.last_candidate=seconds
        if animal_confirmed:self.last_confirmed=seconds
        age=seconds-self.last_confirmed if self.last_confirmed is not None else None
        visible=age is not None and age<=self.hold_seconds
        return {'scene':scene,'seconds':seconds,'scene_reset':changed,'episode_id':self.episode_id,
          'new_candidate_episode':new_episode,'context_visible':visible,
          'shown_persons':persons if visible else 0,'shown_vehicles':vehicles if visible else 0,
          'confirmed_evidence_age_seconds':age,'review_needed':review_failed or (animal_candidate and not visible),
          'automatic_incident_or_dispatch':False}
def check_policy():
    rows=[]
    def record(name,condition):
        assert condition,name
        rows.append({'case':name,'passed':True})
    m=PatrolMemory()
    r=m.update('A',0.,persons=3,vehicles=2)
    record('person_vehicle_only_hidden',not r['context_visible'] and r['shown_persons']==r['shown_vehicles']==0)
    r=m.update('A',.5,animal_candidate=True,persons=3,vehicles=2)
    episode=r['episode_id']
    record('raw_candidate_is_not_confirmation',not r['context_visible'] and r['review_needed'])
    r=m.update('A',1.,animal_confirmed=True,persons=3,vehicles=2)
    record('independent_confirmation_opens_context',r['context_visible'] and r['shown_persons']==3 and r['shown_vehicles']==2)
    r=m.update('A',2.5,persons=3,vehicles=2,review_failed=True)
    record('short_dropout_or_review_failure_keeps_recent_context',r['context_visible'] and r['review_needed'])
    r=m.update('A',4.,persons=3)
    record('hold_boundary_is_inclusive',r['context_visible'])
    r=m.update('A',4.001,persons=3)
    record('stale_confirmation_expires',not r['context_visible'] and r['shown_persons']==0)
    r=m.update('A',5.,animal_candidate=True,animal_confirmed=True)
    record('repeated_sighting_reuses_episode',not r['new_candidate_episode'] and r['episode_id']==episode)
    r=m.update('B',0.,persons=4,vehicles=1)
    record('scene_change_clears_previous_animal_evidence',not r['context_visible'] and r['episode_id'] is None)
    for t in [.5,1.]:
        r=m.update('B',t,animal_candidate=True,persons=4,vehicles=1)
    record('persistent_false_candidates_still_do_not_open_context',not r['context_visible'])
    try:m.update('B',.75)
    except ValueError:record('backward_scene_time_rejected',True)
    else:raise AssertionError('Backward time accepted')
    try:m.update('B',1.5,animal_confirmed='person')
    except TypeError:record('class_label_cannot_be_used_as_boolean_confirmation',True)
    else:raise AssertionError('Class string accepted as confirmation')
    before=m.episode_id
    r=m.update('B',10.,animal_candidate=True)
    record('expired_episode_gets_new_identifier',r['new_candidate_episode'] and r['episode_id']!=before)
    record('policy_never_creates_dispatch',not r['automatic_incident_or_dispatch'])
    return rows
