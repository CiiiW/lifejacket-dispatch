"""Research proposal composition only. Context display still requires animal confirmation."""
import dmd
def compose(animal_predictions,context_predictions,threshold=.3):
 animals=[b for b in animal_predictions if b['class_id']==1 and b['score']>=threshold]
 context=[b for b in context_predictions if b['class_id'] in (0,2) and b['score']>=threshold]
 persons=[dmd.Box(**b) for b in context if b['class_id']==0]
 pairs=[]
 for box in animals:
  overlap=max((dmd.iou(dmd.Box(**box),p) for p in persons),default=0.)
  pairs.append((dict(box),{'branch':'animal','model':'dmd','person_overlap_iou':overlap,'note':'Overlap is a review hint; never automatically deletes or relabels an animal proposal.'}))
 pairs += [(dict(b),{'branch':'context','model':'yolo_world'}) for b in context]
 pairs.sort(key=lambda p:-p[0]['score'])
 return {'boxes':[p[0] for p in pairs],'provenance':[p[1] for p in pairs],
 'context_display_requires_animal_confirmation':True,'automatic_incident_or_dispatch':False}
