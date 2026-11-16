"""Recorded-video research workflow used by notebook 20; no app writes or dispatch.

Model workers run in their existing isolated environments. Every run is tied to
source bytes, settings, code, and checkpoint hashes. All human decisions start
empty. Context is displayed only on the exact approved source frame, never by
temporal carry-over and never because Gemini said an animal was present.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
VOCAB = ['seal', 'sea lion', 'sea otter', 'dog', 'horse', 'cat', 'sheep', 'cow',
         'elephant', 'bear', 'zebra', 'giraffe', 'person', 'bicycle', 'car',
         'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat']
MAP = [1] * 12 + [0] + [2] * 8


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False))
    temp.replace(path)


def state(run, phase, **extra):
    value = {'phase': phase, 'updated_at_unix': time.time(), **extra}
    write(Path(run) / 'status.json', value)
    print(json.dumps(value), flush=True)


def frame_uid(video_sha, frame_index, frame_sha):
    # Identical-looking frames at different timestamps are different approvals.
    return digest([video_sha, int(frame_index), frame_sha])


def prepare(video, *, output_root, dmd_weights, world_weights, sample_fps=1.,
            start_seconds=0., clip_seconds=12., max_samples=120,
            confidence=.30, group_seconds=6., max_review_calls=20,
            native_crops=False):
    import cv2
    from PIL import Image
    video = Path(video).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f'Video not found: {video}')
    for p in [dmd_weights, world_weights]:
        if not Path(p).expanduser().is_file():
            raise FileNotFoundError(f'Checkpoint not found: {p}')
    if not 0 < sample_fps <= 5 or start_seconds < 0 or group_seconds <= 0:
        raise ValueError('Use sample_fps in (0,5], nonnegative start and positive window length.')
    if clip_seconds is not None and clip_seconds <= 0:
        raise ValueError('clip_seconds must be positive or None for the entire remainder.')
    if not 0 < confidence <= 1 or max_samples < 1 or max_review_calls < 0:
        raise ValueError('Invalid confidence or budget.')
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError('Cannot decode this video.')
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not math.isfinite(fps) or fps <= 0 or total <= 0 or sample_fps > fps:
        cap.release()
        raise ValueError('Valid container frame count/FPS required; sampling cannot exceed source FPS.')
    duration = total / fps
    end = duration if clip_seconds is None else min(duration, start_seconds + clip_seconds)
    if start_seconds >= end:
        cap.release()
        raise ValueError('Requested window starts past the end of the source.')
    targets = sorted(set(round((start_seconds + k/sample_fps)*fps)
                         for k in range(math.ceil((end-start_seconds)*sample_fps))
                         if round((start_seconds+k/sample_fps)*fps) < total
                         and round((start_seconds+k/sample_fps)*fps)/fps < end))
    if len(targets) > max_samples:
        cap.release()
        raise ValueError(f'{len(targets)} samples exceed max_samples={max_samples}. '
                         'Choose a shorter preview or explicitly increase the budget.')
    if not targets:
        cap.release()
        raise ValueError('Requested window contains no sampleable source frame.')
    config = dict(video=str(video), video_sha256=sha(video), source_fps=fps,
                  container_frames=total, container_seconds=duration,
                  start_seconds=start_seconds, end_seconds=end,
                  sample_fps=sample_fps, confidence=confidence,
                  group_seconds=group_seconds, max_review_calls=max_review_calls,
                  native_crops=bool(native_crops), tile_size=1280, overlap=100,
                  merge_iou=.5, vocabulary=VOCAB, class_mapping=MAP,
                  dmd_weights=str(Path(dmd_weights).expanduser().resolve()),
                  world_weights=str(Path(world_weights).expanduser().resolve()),
                  dmd_weights_sha256=sha(Path(dmd_weights).expanduser()),
                  world_weights_sha256=sha(Path(world_weights).expanduser()),
                  code_sha256={name:sha(ROOT/name) for name in
                               ['video_review_workflow.py','dmd.py','tile_inference.py',
                                'practical_options_review_v1.py','gemini_handoff_v1.py']})
    run = Path(output_root).expanduser()/f'{video.stem}-{config["video_sha256"][:10]}-{digest(config)[:10]}'
    run.mkdir(parents=True, exist_ok=True)
    if (run/'manifest.json').exists():
        cap.release()
        manifest = read(run/'manifest.json')
        assert manifest['config'] == config, 'Run identity mismatch.'
        check_frames(run)
        return run
    (run/'frames').mkdir(exist_ok=True)
    selected = set(targets)
    rows = []
    n = 0
    # Decode sequentially: repeated random seeking is slow on high-resolution H.264.
    while n <= targets[-1]:
        ok = cap.grab()
        if not ok:
            break
        if n in selected:
            ok, array = cap.retrieve()
            if not ok:
                break
            image = Image.fromarray(cv2.cvtColor(array, cv2.COLOR_BGR2RGB))
            path = run/'frames'/f'{len(rows):06d}.jpg'
            image.save(path, quality=95)
            image_sha = sha(path)
            rows.append(dict(sample_index=len(rows), frame_index=n,
                             source_seconds=n/fps, size=list(image.size),
                             path=str(path), sha256=image_sha,
                             frame_uid=frame_uid(config['video_sha256'], n, image_sha)))
        n += 1
    cap.release()
    if not rows:
        raise ValueError('No requested samples decoded; choose another source/window.')
    manifest = dict(config=config, frames=rows, expected_samples=len(targets),
                    decoded_samples=len(rows), complete_requested_window=len(rows)==len(targets),
                    covers_whole_source=start_seconds==0 and end==duration)
    write(run/'manifest.json', manifest)
    state(run,'prepared',samples=len(rows),complete_requested_window=manifest['complete_requested_window'])
    return run


def check_frames(run):
    m = read(Path(run)/'manifest.json')
    for f in m['frames']:
        if sha(f['path']) != f['sha256']:
            raise ValueError('Saved source frame changed; create a fresh run.')
    return m


def detect(run, kind):
    import torch
    from PIL import Image
    import dmd
    from tile_inference import tile_windows, to_source, merge_boxes
    from dataclasses import asdict
    run = Path(run);m = check_frames(run);c = m['config']
    output = run/(kind+'.json')
    if output.exists():
        state(run,kind+'_cached');return
    torch.set_num_threads(4)
    if not torch.cuda.is_available():
        raise RuntimeError('This pilot is configured for a CUDA GPU. Select the GPU environment.')
    if kind == 'dmd':
        if sha(c['dmd_weights']) != c['dmd_weights_sha256']:
            raise ValueError('DMD weights changed.')
        model = dmd.load_model(weights=c['dmd_weights'], resolution=1280)
    else:
        os.environ['YOLO_CONFIG_DIR']=str(run/'yolo-config')
        from ultralytics import YOLOWorld
        if sha(c['world_weights']) != c['world_weights_sha256']:
            raise ValueError('YOLO-World weights changed.')
        model = YOLOWorld(c['world_weights']);model.set_classes(c['vocabulary'])
    rows=[]
    for position,f in enumerate(m['frames'],1):
        image=Image.open(f['path']).convert('RGB');started=time.perf_counter()
        if kind=='dmd':
            full=dmd.to_boxes(model.predict(image,threshold=.05));all_boxes=list(full)
            for window in tile_windows(*image.size,1280,100):
                found=dmd.to_boxes(model.predict(image.crop(window),threshold=.05))
                all_boxes.extend(to_source(found,window,image.size))
            proposals=[b for b in merge_boxes(all_boxes,c['confidence'],.5) if b.class_id==1]
        else:
            result=model.predict(image,imgsz=1280,conf=c['confidence'],iou=.5,
                                 device=0,verbose=False,max_det=300)[0]
            proposals=[]
            if result.boxes is not None:
                for xy,score,cls in zip(result.boxes.xyxy.cpu().tolist(),
                                        result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
                    mapped=c['class_mapping'][int(cls)]
                    if mapped in (0,2):proposals.append(dmd.Box(*xy,mapped,float(score)))
            proposals=merge_boxes(proposals,c['confidence'],.5)
        rows.append({'frame_uid':f['frame_uid'],'boxes':[asdict(b) for b in proposals],
                     'seconds':time.perf_counter()-started})
        write(run/(kind+'-progress.json'),rows)
        state(run,kind,completed=position,total=len(m['frames']))
    write(output,rows)


def paired_frames(run):
    run=Path(run);m=check_frames(run)
    animals={v['frame_uid']:v for v in read(run/'dmd.json')}
    context={v['frame_uid']:v for v in read(run/'world.json')}
    if set(animals)!=set(context) or set(animals)!={f['frame_uid'] for f in m['frames']}:
        raise ValueError('Detector stages do not refer to the same frames.')
    return [{**f,'animal_boxes':animals[f['frame_uid']]['boxes'],
             'context_boxes':context[f['frame_uid']]['boxes']} for f in m['frames']]


def windows(run):
    m=read(Path(run)/'manifest.json');c=m['config'];groups={}
    for f in paired_frames(run):
        k=int((f['source_seconds']-c['start_seconds'])/c['group_seconds'])
        groups.setdefault(k,[]).append(f)
    return [{'card_id':f'window-{k:03d}','start_seconds':rows[0]['source_seconds'],
             'end_seconds':rows[-1]['source_seconds'],'sample_count':len(rows),
             'frame':rows[len(rows)//2]} for k,rows in groups.items()]


def prepare_review(run, card):
    from PIL import Image
    from practical_options_review_v1 import crop_rect
    run=Path(run);f=card['frame'];c=read(run/'manifest.json')['config']
    folder=run/'review-inputs'/f['frame_uid'];folder.mkdir(parents=True,exist_ok=True)
    image=Image.open(f['path']).convert('RGB');w,h=image.size
    overview=image.copy();overview.thumbnail((2048,2048));p=folder/'F1-whole.jpg'
    overview.save(p,quality=95)
    images=[dict(image_id='F1-whole',path=str(p),sha256=sha(p),role='whole_frame')]
    targets=[];animal_regions=[]
    if c['native_crops']:
        for i,b in enumerate(sorted(f['animal_boxes'],key=lambda b:-b['score'])[:2],1):
            rect,target=crop_rect(b,image.size);crop=image.crop(rect);crop.thumbnail((1280,1280))
            name=f'F1-animal-{i}';p=folder/(name+'.jpg');crop.save(p,quality=95)
            images.append(dict(image_id=name,path=str(p),sha256=sha(p),role='unverified_mammal_proposal'))
            animal_regions.append(dict(image_id=name,target_yxyx_1000=target))
    for cid,label in [(0,'person'),(2,'vehicle')]:
        for i,b in enumerate(sorted([b for b in f['context_boxes'] if b['class_id']==cid],
                                   key=lambda b:-b['score'])[:2],1):
            target=dict(region_id=f'F1-{label}-{i}',proposed_class=label,box=b,
                        full_frame_target_yxyx_1000=[round(b['y1']/h*1000),round(b['x1']/w*1000),
                                                    round(b['y2']/h*1000),round(b['x2']/w*1000)])
            if c['native_crops']:
                rect,coords=crop_rect(b,image.size);crop=image.crop(rect);crop.thumbnail((1280,1280))
                name=target['region_id']+'-crop';p=folder/(name+'.jpg');crop.save(p,quality=95)
                images.append(dict(image_id=name,path=str(p),sha256=sha(p),role='unverified_context_proposal'))
                target.update(crop_image_id=name,crop_target_yxyx_1000=coords)
            targets.append(target)
    manifest=dict(frame_id='F1',frame_uid=f['frame_uid'],images=images,
                  animal_regions=animal_regions,context_regions=targets)
    write(folder/'manifest.json',manifest)
    return manifest


def validate_reply(data, manifest):
    if not isinstance(data,dict) or not isinstance(data.get('frames'),list) or len(data['frames'])!=1:
        raise ValueError('Exactly one reviewed frame is required.')
    frame=data['frames'][0]
    if frame.get('frame_id')!='F1':raise ValueError('Wrong reviewed frame.')
    for name in ['mammal_visible','people_visible','vehicles_visible']:
        if frame.get(name) not in ('yes','no','uncertain'):raise ValueError('Invalid visual verdict.')
    cited=frame.get('evidence_image_ids')
    if not isinstance(cited,list) or not set(cited)<={i['image_id'] for i in manifest['images']}:
        raise ValueError('Invalid evidence image references.')
    if frame['mammal_visible']=='yes' and (not cited or not str(frame.get('visible_mammal_features','')).strip()):
        raise ValueError('Positive mammal evidence must cite this frame and describe features.')
    checks=frame.get('context_regions')
    if not isinstance(checks,list):raise ValueError('Missing context decisions.')
    ids=[c.get('region_id') for c in checks]
    if len(ids)!=len(set(ids)) or set(ids)!={t['region_id'] for t in manifest['context_regions']}:
        raise ValueError('Missing, duplicate, or unexpected region IDs.')
    if any(c.get('proposed_class_present') not in ('yes','no','uncertain') for c in checks):
        raise ValueError('Invalid context verdict.')
    return frame


def review(run):
    import gemini_handoff_v1 as g
    from practical_options_review_v1 import SCHEMA,SYSTEM,PROMPT
    run=Path(run);m=check_frames(run);budget=m['config']['max_review_calls']
    sent=0
    for card in windows(run):
        manifest=prepare_review(run,card)
        mapping={k:v for k,v in manifest.items() if k!='frame_uid'}
        mapping['images']=[{'image_id':i['image_id'],'role':i['role']} for i in manifest['images']]
        mapping['context_regions']=[{k:v for k,v in r.items() if k!='box'} for r in manifest['context_regions']]
        prompt=PROMPT+'\nImage order: '+json.dumps([i['image_id'] for i in manifest['images']])+\
            '\nFrame/target mapping: '+json.dumps([mapping])
        client=g.MeteredClient(max_retries=1,temperature=.1);client.usage={}
        key=digest([manifest['frame_uid'],[i['sha256'] for i in manifest['images']],
                    prompt,SCHEMA,SYSTEM,client.model])
        path=run/'reviews'/(manifest['frame_uid']+'.json')
        existing=read(path) if path.exists() else None
        # Failures are retained too: a notebook rerun never silently retries a paid call.
        if existing and existing.get('input_key')==key:
            if existing['status']=='failed':break
            continue
        attempts=list((run/'reviews').glob('*.json')) if (run/'reviews').exists() else []
        if len(attempts)>=budget:
            state(run,'review_budget_reached',max_calls=budget);break
        began=time.perf_counter()
        row=dict(frame_uid=manifest['frame_uid'],input_key=key,model=client.model,
                 image_sha256=[i['sha256'] for i in manifest['images']])
        try:
            result=client.generate_json(prompt,SCHEMA,
                     images=[g.ImageInput(data=Path(i['path']).read_bytes()) for i in manifest['images']],
                     temperature=.1,system_instruction=SYSTEM)
            validate_reply(result.data,manifest)
            row.update(status='success',data=result.data,usage=client.usage,
                       model_version=getattr(client,'model_version',None))
        except Exception as exc:
            row.update(status='failed',error_type=type(exc).__name__,usage=client.usage,
                       note='Review unavailable or malformed; not evidence of animal absence.')
        row['wall_seconds']=time.perf_counter()-began;write(path,row);sent+=1
        state(run,'gemini',new_calls=sent,last_status=row['status'])
        if row['status']=='failed':break


def checked_context(run, frame):
    run=Path(run);path=run/'reviews'/(frame['frame_uid']+'.json')
    manifest_path=run/'review-inputs'/frame['frame_uid']/'manifest.json'
    if not path.exists() or not manifest_path.exists():return [],None
    row=read(path);manifest=read(manifest_path)
    if row.get('status')!='success' or row.get('frame_uid')!=frame['frame_uid']:
        return [],row
    if manifest.get('frame_uid')!=frame['frame_uid']:return [],None
    if row.get('image_sha256')!=[i['sha256'] for i in manifest['images']]:return [],None
    if any(not Path(i['path']).is_file() or sha(i['path'])!=i['sha256'] for i in manifest['images']):return [],None
    try:answer=validate_reply(row['data'],manifest)
    except (ValueError,KeyError,TypeError):return [],None
    targets={r['region_id']:r['box'] for r in manifest['context_regions']}
    accepted=[targets[r['region_id']] for r in answer['context_regions'] if r['proposed_class_present']=='yes']
    return accepted,row


def visible_context(frame, accepted, approval):
    if not approval or approval.get('decision')!='yes':return []
    if any(approval.get(k)!=frame.get(k) for k in ['frame_uid','frame_index','sha256']):return []
    return [b for b in accepted if b.get('class_id') in (0,2)]


def decisions(run):
    p=Path(run)/'human-decisions.json'
    return read(p) if p.exists() else {}


def approve(run, uid, decision):
    if decision not in ('yes','no','uncertain','clear'):raise ValueError('Invalid human decision.')
    frame=next((c['frame'] for c in windows(run) if c['frame']['frame_uid']==uid),None)
    if frame is None:raise ValueError('Only the exact selected review frame may be confirmed.')
    saved=decisions(run)
    event={k:frame[k] for k in ['frame_uid','frame_index','sha256']}
    event.update(decision=decision,at_unix=time.time(),method='explicit_notebook_reviewer_action')
    if decision=='clear':saved.pop(uid,None)
    else:saved[uid]=event
    write(Path(run)/'human-decisions.json',saved)
    with (Path(run)/'human-decision-history.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')


def draw_frame(run, frame):
    from PIL import Image,ImageDraw,ImageFont
    image=Image.open(frame['path']).convert('RGB');image.thumbnail((960,540))
    canvas=Image.new('RGB',(960,640),'#081b26');canvas.paste(image,((960-image.width)//2,70))
    left=(960-image.width)//2;sx,sy=image.width/frame['size'][0],image.height/frame['size'][1]
    accepted,row=checked_context(run,frame);approval=decisions(run).get(frame['frame_uid'])
    shown=visible_context(frame,accepted,approval);d=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('DejaVuSans.ttf',16)
    except OSError:font=ImageFont.load_default()
    for b in frame['animal_boxes']+shown:
        color='#4dd9bd' if b['class_id']==1 else '#72d9ed' if b['class_id']==0 else '#ffd081'
        xy=[left+b['x1']*sx,70+b['y1']*sy,left+b['x2']*sx,70+b['y2']*sy]
        d.rectangle(xy,outline=color,width=3)
        label='animal proposal' if b['class_id']==1 else 'person' if b['class_id']==0 else 'vehicle'
        d.text((xy[0]+2,max(70,xy[1]-19)),label,fill=color,font=font)
    status=(approval or {}).get('decision','pending')
    ai='not reviewed' if row is None else row['data']['frames'][0]['mammal_visible'] if row.get('status')=='success' else 'unavailable'
    d.text((16,12),f'Source {frame["source_seconds"]:.3f}s | human: {status} | Gemini: {ai}',font=font,fill='white')
    d.text((16,37),f'Context regions shown: {len(shown)} | exact-frame approval required | no automatic dispatch',font=font,fill='#a8bdca')
    d.text((16,620),'SAMPLED RESEARCH PREVIEW | boxes are proposals, not accuracy or unique-object counts',fill='white',font=font)
    return canvas


def build_cards(run):
    cards=[];saved=decisions(run)
    for c in windows(run):
        f=c['frame'];accepted,row=checked_context(run,f)
        advisory='not_reviewed' if row is None else row['data']['frames'][0]['mammal_visible'] if row['status']=='success' else 'unavailable'
        cards.append({k:v for k,v in c.items() if k!='frame'}|dict(
            frame_uid=f['frame_uid'],frame_index=f['frame_index'],frame_sha256=f['sha256'],
            source_seconds=f['source_seconds'],animal_proposals=len(f['animal_boxes']),
            candidate_retained=bool(f['animal_boxes']) or advisory=='yes',
            gemini_advisory=advisory,human_decision=saved.get(f['frame_uid'],{}).get('decision','pending'),
            shown_context_regions=len(visible_context(f,accepted,saved.get(f['frame_uid']))),
            automatic_incident_or_dispatch=False))
    write(Path(run)/'review-cards.json',cards)
    return cards


def export_video(run):
    run=Path(run);m=check_frames(run);frames=paired_frames(run)
    folder=run/'annotated-frames';folder.mkdir(exist_ok=True)
    for i,f in enumerate(frames):draw_frame(run,f).save(folder/f'{i:06d}.jpg',quality=90)
    ffmpeg=shutil.which('ffmpeg')
    fallback=Path.home()/'.local/share/aerial-ffmpeg/bin/ffmpeg'
    if ffmpeg is None and fallback.is_file():ffmpeg=str(fallback)
    if ffmpeg is None:raise RuntimeError('FFmpeg is required for browser-compatible H.264 export; run notebook 00 environment setup.')
    target=run/'reviewed-video.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-framerate',str(m['config']['sample_fps']),
                    '-i',str(folder/'%06d.jpg'),'-an','-c:v','libx264','-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(target)],check=True,capture_output=True)
    cards=build_cards(run)
    summary=dict(video=m['config']['video'],source_sha256=m['config']['video_sha256'],
                 requested_window=[m['config']['start_seconds'],m['config']['end_seconds']],
                 covers_whole_source=m['covers_whole_source'],
                 complete_requested_window=m['complete_requested_window'],samples=len(frames),
                 review_windows=len(cards),human_confirmed_frames=sum(c['human_decision']=='yes' for c in cards),
                 context_regions_shown=sum(c['shown_context_regions'] for c in cards),
                 gemini_statuses={k:sum(c['gemini_advisory']==k for c in cards) for k in ['yes','no','uncertain','unavailable','not_reviewed']},
                 automatic_incident_or_dispatch=False,output_video=str(target),
                 limitations='Sampled research preview; no unique-object count, ground-truth accuracy, live DJI or automatic dispatch.')
    write(run/'summary.json',summary)
    return target,summary


def review_widget(run):
    import ipywidgets as widgets
    from IPython.display import display,clear_output,HTML
    run=Path(run);cards=windows(run)
    select=widgets.Dropdown(options=[(f'{c["card_id"]} | source {c["frame"]["source_seconds"]:.3f}s',i) for i,c in enumerate(cards)],description='Review frame:',layout=widgets.Layout(width='95%'),style={'description_width':'120px'})
    output=widgets.Output()
    buttons=[widgets.Button(description=label,button_style=style,layout=widgets.Layout(width='240px')) for label,style in
             [('Animal visible in this frame','success'),('No animal visible','warning'),('Uncertain / keep for review','info'),('Clear decision','')]]
    def refresh(*args):
        f=cards[select.value]['frame'];accepted,row=checked_context(run,f)
        with output:
            clear_output(wait=True)
            display(draw_frame(run,f))
            answer=(row or {}).get('data',{}).get('frames',[{}])[0]
            display(HTML('<b>Gemini advice:</b> '+html.escape(str(answer.get('visible_mammal_features','Not reviewed / unavailable.')))+
                         '<br><b>Frame:</b> '+html.escape(f['frame_uid'][:20])+
                         '<br>Unconfirmed context stays hidden. These buttons record your actual decision on this frame.'))
    for button,decision in zip(buttons,['yes','no','uncertain','clear']):
        def clicked(_button,decision=decision):
            approve(run,cards[select.value]['frame']['frame_uid'],decision);build_cards(run);refresh()
        button.on_click(clicked)
    select.observe(refresh,names='value');refresh()
    display(widgets.VBox([select,
        widgets.HBox(buttons[:2],layout=widgets.Layout(flex_flow='row wrap')),
        widgets.HBox(buttons[2:],layout=widgets.Layout(flex_flow='row wrap')),output]))


def save_uploaded_video(name, content, folder, max_bytes=100*1024*1024):
    """Save one browser upload without overwriting another video's bytes."""
    content=bytes(content)
    if not content:raise ValueError('The selected file is empty.')
    if len(content)>max_bytes:raise ValueError('Use a clip under 100 MB, or upload via the Jupyter file browser and use its server path.')
    suffix=Path(str(name)).suffix.lower()
    if suffix not in {'.mp4','.mov','.m4v','.avi','.mkv','.webm'}:
        raise ValueError('Choose an MP4, MOV, M4V, AVI, MKV or WebM video.')
    stem=re.sub(r'[^A-Za-z0-9_.-]+','_',Path(str(name)).stem).strip('._')[:100] or 'video'
    hashed=hashlib.sha256(content).hexdigest()
    folder=Path(folder).expanduser().resolve();folder.mkdir(parents=True,exist_ok=True)
    target=folder/(hashed+'-'+stem+suffix)
    if target.exists():
        if sha(target)!=hashed:raise ValueError('An existing upload changed; choose a fresh upload directory.')
    else:
        with target.open('xb') as f:f.write(content)
    return target


def upload_widget(*, output_root, dmd_weights, world_weights,
                  python_dmd, python_world, python_gemini, on_ready=None):
    """Single-upload entry point; no run or model call starts until the button is clicked."""
    import ipywidgets as widgets
    from IPython.display import display,clear_output,HTML,Video
    from urllib.parse import quote
    upload=widgets.FileUpload(accept='.mp4,.mov,.m4v,.avi,.mkv,.webm',multiple=False,
                              description='Upload one video',layout=widgets.Layout(width='230px'))
    seconds=widgets.BoundedFloatText(value=6.,min=.5,max=120.,step=1.,description='Preview seconds:',
              style={'description_width':'130px'},layout=widgets.Layout(width='260px'))
    begin=widgets.BoundedFloatText(value=0.,min=0.,max=36000.,step=1.,description='Start at second:',
              style={'description_width':'130px'},layout=widgets.Layout(width='260px'))
    fps=widgets.Dropdown(options=[.5,1.,2.],value=1.,description='Sample FPS:',
              style={'description_width':'130px'},layout=widgets.Layout(width='260px'))
    budget=widgets.BoundedIntText(value=6,min=0,max=20,description='Gemini call cap:',
              style={'description_width':'130px'},layout=widgets.Layout(width='260px'))
    ai=widgets.Checkbox(value=True,description='Use Gemini advice')
    native=widgets.Checkbox(value=False,description='Add native proposal crops')
    run_button=widgets.Button(description='Run this video',button_style='success',disabled=True,
                              layout=widgets.Layout(width='230px'))
    refresh=widgets.Button(description='Refresh annotated video',button_style='info',disabled=True,
                           layout=widgets.Layout(width='260px'))
    message=widgets.HTML('<b>Upload one short video (under 100 MB).</b> Nothing runs until you click Run this video.')
    progress=widgets.Output();reviews=widgets.Output();player=widgets.Output()
    log=widgets.Accordion(children=[progress]);log.set_title(0,'Pipeline progress / log');log.selected_index=None
    current={'video':None,'run':None}
    controls=[upload,seconds,begin,fps,budget,ai,native]
    def uploaded(change):
        if not change['new']:return
        try:
            value=change['new']
            if isinstance(value,dict):
                if len(value)!=1:raise ValueError('Select exactly one video.')
                name,entry=next(iter(value.items()))
                name=entry.get('metadata',{}).get('name',name)
            else:
                if len(value)!=1:raise ValueError('Select exactly one video.')
                entry=value[0];name=entry['name']
            path=save_uploaded_video(name,entry['content'],Path(output_root).parent/'uploaded-videos')
            current.update(video=path,run=None);run_button.disabled=False;refresh.disabled=True
            with reviews:clear_output()
            with player:clear_output()
            message.value='<b>Ready:</b> '+html.escape(str(name))+' ('+str(round(path.stat().st_size/1e6,2))+' MB). Click <b>Run this video</b>.'
        except Exception as exc:
            run_button.disabled=True
            message.value='<b>Upload not accepted:</b> '+html.escape(str(exc))
    upload.observe(uploaded,names='value')
    def refresh_video(_=None):
        if current['run'] is None:return
        target,summary=export_video(current['run'])
        with player:
            clear_output(wait=True);display(Video(str(target),embed=True,width=960))
            display(HTML('<b>MP4:</b> '+html.escape(str(target))+'<br><b>Human-confirmed frames:</b> '+str(summary['human_confirmed_frames'])+
                         ' · <b>Context regions shown:</b> '+str(summary['context_regions_shown'])))
    refresh.on_click(refresh_video)
    def clicked(_):
        if current['video'] is None:return
        run_button.disabled=True;refresh.disabled=True;log.selected_index=0
        for control in controls:control.disabled=True
        try:
            with progress:
                clear_output()
                run=prepare(current['video'],output_root=output_root,dmd_weights=dmd_weights,
                    world_weights=world_weights,start_seconds=float(begin.value),clip_seconds=float(seconds.value),
                    sample_fps=float(fps.value),max_samples=120,confidence=.3,group_seconds=6.,
                    max_review_calls=int(budget.value),native_crops=bool(native.value))
                current['run']=run
                start(run,python_dmd=python_dmd,python_world=python_world,
                      python_gemini=python_gemini,use_gemini=bool(ai.value))
                wait(run,timeout=1200)
            if on_ready is not None:on_ready(run,current['video'])
            summary=read(run/'summary.json')
            message.value=('<b>Completed:</b> '+str(summary['samples'])+' samples; '+str(summary['review_windows'])+
                ' review window(s). Review the exact frame below; then refresh the video. '+
                ('<b>Incomplete decoding detected.</b>' if not summary['complete_requested_window'] else ''))
            with reviews:
                clear_output(wait=True);review_widget(run)
                links=[]
                for card in windows(run):
                    frame=card['frame']
                    try:relative=Path(frame['path']).resolve().relative_to(Path.home())
                    except ValueError:continue
                    url='/files/'+quote(str(relative))
                    links.append('<li><a target="_blank" rel="noopener" href="'+html.escape(url)+'">Original full-resolution frame at '+str(round(frame['source_seconds'],3))+' seconds</a></li>')
                display(HTML('<details><summary>Inspect original pixels before deciding</summary><ul>'+''.join(links)+'</ul></details>'))
            refresh.disabled=False;refresh_video();log.selected_index=None
        except Exception as exc:
            message.value='<b>Run stopped:</b> '+html.escape(str(exc))+'. Open the progress log; your source and saved evidence are retained.'
        finally:
            run_button.disabled=current['video'] is None
            for control in controls:control.disabled=False
    run_button.on_click(clicked)
    display(widgets.VBox([message,upload,
        widgets.HBox([begin,seconds],layout=widgets.Layout(flex_flow='row wrap')),
        widgets.HBox([fps,budget],layout=widgets.Layout(flex_flow='row wrap')),
        widgets.HBox([ai,native],layout=widgets.Layout(flex_flow='row wrap')),
        run_button,log,reviews,refresh,player]))
    return current


def start(run, *, python_dmd, python_world, python_gemini, use_gemini=True):
    run=Path(run)
    pid_path=run/'process.json'
    if pid_path.exists():
        pid=read(pid_path)['pid'];cmd=Path(f'/proc/{pid}/cmdline')
        if cmd.exists() and str(run).encode() in cmd.read_bytes():
            print('This run is already active:',pid);return pid
    command=[sys.executable,str(Path(__file__).resolve()),'controller',str(run),
             '--python-dmd',str(python_dmd),'--python-world',str(python_world),
             '--python-gemini',str(python_gemini)]
    if not use_gemini:command.append('--no-gemini')
    for p in [python_dmd,python_world]+([python_gemini] if use_gemini else []):
        if not Path(p).is_file():raise FileNotFoundError(f'Model environment not found: {p}')
    state(run,'queued')
    with (run/'pipeline.log').open('a') as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write(pid_path,{'pid':process.pid});print('Started pipeline:',process.pid);return process.pid


def wait(run, timeout=1200):
    run=Path(run);deadline=time.monotonic()+timeout;last=None
    while time.monotonic()<deadline:
        status=read(run/'status.json') if (run/'status.json').exists() else {'phase':'queued'}
        key=(status.get('phase'),status.get('completed'),status.get('new_calls'))
        if key!=last:print(status,flush=True);last=key
        if status['phase']=='completed':return status
        if status['phase']=='failed':raise RuntimeError('Pipeline stopped. Inspect '+status['log'])
        pid=read(run/'process.json')['pid']
        if not Path(f'/proc/{pid}').exists():raise RuntimeError('Pipeline exited before completion; inspect pipeline.log.')
        time.sleep(2)
    raise TimeoutError('Pipeline may still be running. Check its status before starting another run.')


def controller(args):
    run=Path(args.run)
    for stage,python in [('dmd',args.python_dmd),('world',args.python_world)]+([] if args.no_gemini else [('gemini',args.python_gemini)]):
        state(run,stage+'_starting')
        with (run/(stage+'.log')).open('a') as log:
            result=subprocess.run([python,str(Path(__file__).resolve()),stage,str(run)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            state(run,'failed',stage=stage,log=str(run/(stage+'.log')));return
    # Gemini failures are stored as review-needed results; detector candidates survive.
    path,summary=export_video(run)
    state(run,'completed',summary=summary)


def self_check():
    accepted=[{'class_id':0},{'class_id':2}]
    f={'frame_uid':'first','frame_index':3,'sha256':'same-pixels'}
    a={**f,'decision':'yes'}
    assert visible_context(f,accepted,None)==[]
    assert visible_context(f,accepted,a)==accepted
    assert visible_context({**f,'frame_uid':'second','frame_index':4},accepted,a)==[]
    assert visible_context(f,accepted,{**a,'decision':'no'})==[]
    assert visible_context(f,accepted,{**a,'decision':'uncertain'})==[]
    assert visible_context(f,[{'class_id':1}],a)==[]
    assert frame_uid('video',3,'pixels')!=frame_uid('video',4,'pixels')
    manifest={'images':[{'image_id':'F1-whole'}],'context_regions':[{'region_id':'F1-person-1'}]}
    reply={'frames':[{'frame_id':'F1','mammal_visible':'yes','people_visible':'yes','vehicles_visible':'no',
                     'visible_mammal_features':'flippers','evidence_image_ids':['F1-whole'],
                     'context_regions':[{'region_id':'F1-person-1','proposed_class_present':'yes'}]}]}
    validate_reply(reply,manifest)
    reply['frames'][0]['evidence_image_ids']=['OTHER-FRAME']
    try:validate_reply(reply,manifest)
    except ValueError:pass
    else:raise AssertionError('Cross-frame evidence accepted.')
    return 'PASS: unconfirmed/negative/uncertain frames hide context; exact-index approval; class guard; evidence IDs.'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage');parser.add_argument('run',nargs='?')
    parser.add_argument('--python-dmd');parser.add_argument('--python-world');parser.add_argument('--python-gemini');parser.add_argument('--no-gemini',action='store_true')
    args=parser.parse_args()
    if args.stage=='self-check':print(self_check())
    elif args.stage in ('dmd','world'):detect(args.run,args.stage)
    elif args.stage=='gemini':review(args.run)
    elif args.stage=='controller':controller(args)
    elif args.stage=='export':print(export_video(args.run)[0])
    else:raise ValueError(args.stage)


if __name__=='__main__':main()
