from pathlib import Path
import subprocess,json
A=Path.home()/'lifejacket-dispatch/research/aerial_detector';R=Path.home()/'aerial-data/model-comparison-v1'
python=(R/'env-ready.txt').read_text().strip()
codes={}
for name in ['dmd','grounding_dino','yolo_world','yoloe26']:
 with (R/(name+'.log')).open('w') as h:
  result=subprocess.run([python,'-u',str(A/'model_compare_infer_v1.py'),name],cwd=R,stdout=h,stderr=subprocess.STDOUT)
 codes[name]=result.returncode
 (R/'controller-status.json').write_text(json.dumps(codes))
print(codes,flush=True)
