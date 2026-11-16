from pathlib import Path
import json,requests,cv2,hashlib,traceback
from PIL import Image,ImageDraw
R=Path.home()/'aerial-data/aerial-patrol-v1';R.mkdir(exist_ok=True)
sources=[{'source':'crowded_beach','url':'https://videos.pexels.com/video-files/32726982/13953558_3840_2160_24fps.mp4','page':'https://www.pexels.com/video/aerial-view-of-beach-with-people-and-umbrellas-32726982/','credit':'8 K/Pexels'}]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for s in sources:
 try:
  p=R/(s['source']+'.mp4')
  if not p.exists():
   response=requests.get(s['url'],stream=True,timeout=(20,60));response.raise_for_status()
   temp=p.with_suffix('.part')
   with temp.open('wb') as h:
    for block in response.iter_content(1024*1024):h.write(block)
   temp.rename(p)
  cap=cv2.VideoCapture(str(p));assert cap.isOpened()
  fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));targets=[round((count-1)*i/5) for i in range(6)]
  frames=[];i=0;thumbs=[]
  while True:
   ok,f=cap.read()
   if not ok:break
   if i in targets:
    im=Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB));q=R/(s['source']+f'-screen-{i:05}.jpg');im.save(q,quality=95)
    frames.append({'frame_index':i,'seconds':i/fps,'path':str(q),'sha256':sha(q),'size':list(im.size)})
    t=im.copy();t.thumbnail((480,270));tile=Image.new('RGB',(480,295),'#101820');tile.paste(t,(0,25));ImageDraw.Draw(tile).text((8,8),f"{s['source']} {i/fps:.2f}s",fill='white');thumbs.append(tile)
   i+=1
  cap.release();assert i==count,(i,count)
  s.update(path=str(p),sha256=sha(p),fps=fps,decoded_frames=i,duration=i/fps,size=frames[0]['size'],complete=True,screening=frames)
  contact=Image.new('RGB',(1440,590))
  for j,t in enumerate(thumbs):contact.paste(t,((j%3)*480,(j//3)*295))
  contact.save(R/(s['source']+'-contact.jpg'),quality=90)
  print(s['source'],s['size'],i/fps,'complete',flush=True)
 except Exception as e:s['error']=str(e);traceback.print_exc()
 (R/'control-source.json').write_text(json.dumps(sources,indent=2))
print('Source preparation finished',flush=True)
