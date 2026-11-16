"""Small synchronized detector timing check on six representative cached native frames."""
from pathlib import Path
import json,sys,time,statistics,traceback
import torch
from PIL import Image
A=Path(__file__).resolve().parent;sys.path.insert(0,str(A));import dmd
from tile_inference import tile_windows,to_source,merge_boxes
D=Path.home()/'aerial-data';R=D/'practical-options-v1'
def main():
 rows=json.loads((R/'frames.json').read_text());chosen=[]
 for source in ['raft','surf','rocks','crowded_beach','dog_walk','parking_control']:
  rr=[r for r in rows if r['source']==source];chosen.append(rr[len(rr)//2])
 torch.set_num_threads(4);from rfdetr import RFDETRMedium
 m=RFDETRMedium(pretrain_weights=str(D/'weights/DroneMegaDetector_RFDETRMedium_2026.10.04.pth'),resolution=1280,num_classes=3)
 warm=Image.open(chosen[0]['path']).convert('RGB');m.predict(warm,threshold=.05);torch.cuda.synchronize()
 out=[]
 for f in chosen:
  im=Image.open(f['path']).convert('RGB')
  for mode in ['full','full_plus_tiles']:
   samples=[];boxes=[]
   for repeat in range(2):
    torch.cuda.synchronize();start=time.perf_counter();raw=dmd.to_boxes(m.predict(im,threshold=.05))
    if mode=='full_plus_tiles':
     for win in tile_windows(*im.size,1280,100):raw.extend(to_source(dmd.to_boxes(m.predict(im.crop(win),threshold=.05)),win,im.size))
    boxes=merge_boxes(raw,.3,.5);torch.cuda.synchronize();samples.append(time.perf_counter()-start)
   out.append({'source':f['source'],'sample_index':f['sample_index'],'sha256':f['sha256'],'size':f['size'],'mode':mode,'times_seconds':samples,'median_seconds':statistics.median(samples),'animal_proposals':sum(b.class_id==1 for b in boxes)})
   (R/'timing-status.json').write_text(json.dumps({'completed':len(out),'total':12}))
 (R/'detector-timing.json').write_text(json.dumps({'scope':'Six representative native frames, two synchronized repeats after one warm-up; model loading and source decode excluded. Small timing diagnostic, not live-stream throughput or detection accuracy.','gpu':torch.cuda.get_device_name(0),'rows':out},indent=2));print('Timing diagnostic complete',flush=True)
if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc();raise
