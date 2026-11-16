from pathlib import Path
import requests,json,re,hashlib,cv2
from urllib.parse import urljoin
from PIL import Image,ImageDraw
R=Path.home()/'aerial-data/combined-gemini-v1';R.mkdir(parents=True,exist_ok=True)
MASTER=(R/'r7-media-url.txt').read_text().strip()

session=requests.Session()
def get(url):
 response=session.get(url,timeout=(20,60));response.raise_for_status();return response.content
master=get(MASTER).decode()
(R/'r7-master.m3u8').write_text(master)
lines=master.splitlines();variants=[]
for i,line in enumerate(lines):
 if line.startswith('#EXT-X-STREAM-INF'):
  match=re.search(r'RESOLUTION=(\d+)x(\d+)',line)
  if match:
   uri=next(v.strip() for v in lines[i+1:] if v.strip() and not v.startswith('#'))
   variants.append((int(match[1])*int(match[2]),urljoin(MASTER,uri)))
assert variants
playlist_url=max(variants)[1];playlist=get(playlist_url).decode()
(R/'r7-rendition.m3u8').write_text(playlist)
assert not any(line.startswith('#EXT-X-KEY') and 'METHOD=NONE' not in line for line in playlist.splitlines())
duration=sum(float(re.search(r'#EXTINF:([0-9.]+)',line)[1]) for line in playlist.splitlines() if line.startswith('#EXTINF:'))
match=re.search(r'#EXT-X-MAP:.*URI="([^"]+)"',playlist);parts=[]
if match:parts.append(urljoin(playlist_url,match[1]))
parts += [urljoin(playlist_url,line.strip()) for line in playlist.splitlines() if line.strip() and not line.startswith('#')]
payloads=[];records=[];total=0
for i,url in enumerate(parts):
 payload=get(url);total+=len(payload);assert total<=100*1024*1024
 p=R/f'r7-part-{i:03}.bin';p.write_bytes(payload)
 records.append({'index':i,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()});payloads.append(payload)
 print('segment',i,len(payload),flush=True)
p=R/'r7-release.mp4';p.write_bytes(b''.join(payloads))
cap=cv2.VideoCapture(str(p));assert cap.isOpened()
fps=cap.get(cv2.CAP_PROP_FPS);assert fps>0
count=0;views=[];targets={round(i*(duration-.2)/7*fps) for i in range(8)}
while True:
 ok,f=cap.read()
 if not ok:break
 if count in targets:
  im=Image.fromarray(cv2.cvtColor(f,cv2.COLOR_BGR2RGB));im.thumbnail((480,270))
  tile=Image.new('RGB',(480,300),'#102633');tile.paste(im,((480-im.width)//2,24));ImageDraw.Draw(tile).text((6,5),f'NOAA R7AF b-roll {count/fps:.2f}s',fill='white');views.append(tile)
 count+=1
cap.release();assert abs(count/fps-duration)<.5
canvas=Image.new('RGB',(1920,600),'#102633')
for i,tile in enumerate(views):canvas.paste(tile,((i%4)*480,(i//4)*300))
canvas.save(R/'r7-contact.jpg',quality=94)
source={'id':'noaa_r7af','path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,
 'source_page':'https://videos.fisheries.noaa.gov/detail/videos/b-roll:-seals-and-sea-lions/video/6297080580001/b-roll:-release-of-hawaiian-monk-seal-r7af',
 'player_page':'https://players.brightcove.net/659677166001/default_default/index.html?videoId=6297080580001',
 'author':'NOAA Fisheries and partners','credit':'NOAA Fisheries and Hawaii Marine Animal Response; source b-roll slate credits apply.',
 'media_note':'Complete public video rendition downloaded as clear fMP4 video segments and concatenated; no audio used. Frames sampled and overlays added for research.',
 'fps':fps,'decoded_frames':count,'duration_seconds':count/fps,'playlist_duration_seconds':duration,'complete':True,'segments':records}
(R/'r7-source.json').write_text(json.dumps(source,indent=2))
print('NOAA complete',count,fps,duration,flush=True)
