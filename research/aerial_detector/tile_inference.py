"""Native-resolution tile geometry and class-wise cross-pass merging.
No annotation locations are used to choose tiles. RF-DETR's individual passes
do not need NMS; merging separate overlapping passes does.
"""
from dataclasses import replace

def axis_starts(length, size=1280, overlap=100):
    if length <= 0 or size <= 0 or not 0 <= overlap < size:
        raise ValueError("Invalid image, tile size or overlap")
    if length <= size:
        return [0]
    starts=list(range(0,length-size+1,size-overlap))
    if starts[-1] != length-size:
        starts.append(length-size)
    return starts

def tile_windows(width,height,size=1280,overlap=100):
    return [(x,y,min(x+size,width),min(y+size,height))
            for y in axis_starts(height,size,overlap)
            for x in axis_starts(width,size,overlap)]

def to_source(boxes,window,image_size):
    x,y,_,_=window
    width,height=image_size
    out=[]
    for b in boxes:
        x1=max(0.,min(float(width),b.x1+x))
        x2=max(0.,min(float(width),b.x2+x))
        y1=max(0.,min(float(height),b.y1+y))
        y2=max(0.,min(float(height),b.y2+y))
        if x2>x1 and y2>y1:
            out.append(replace(b,x1=x1,y1=y1,x2=x2,y2=y2))
    return out

def merge_boxes(boxes,confidence=.3,iou_threshold=.5):
    """Class-aware greedy NMS across tile/full passes, in source coordinates."""
    import numpy as np
    if not 0<=confidence<=1 or not 0<=iou_threshold<=1:
        raise ValueError("Invalid merge thresholds")
    kept=[]
    for kind in sorted({b.class_id for b in boxes}):
        rows=sorted([b for b in boxes if b.class_id==kind and b.score>=confidence],
                    key=lambda b:-b.score)
        if not rows:
            continue
        coords=np.asarray([[b.x1,b.y1,b.x2,b.y2] for b in rows],dtype=np.float64)
        areas=np.maximum(0,coords[:,2]-coords[:,0])*np.maximum(0,coords[:,3]-coords[:,1])
        order=np.arange(len(rows))
        while len(order):
            i=int(order[0]);kept.append(rows[i])
            rest=order[1:]
            if not len(rest):
                break
            left=np.maximum(coords[i,:2],coords[rest,:2])
            right=np.minimum(coords[i,2:],coords[rest,2:])
            extent=np.maximum(0,right-left)
            inter=extent[:,0]*extent[:,1]
            union=areas[i]+areas[rest]-inter
            overlap=np.divide(inter,union,out=np.zeros_like(inter),where=union>0)
            order=rest[overlap<=iou_threshold]
    return sorted(kept,key=lambda b:-b.score)

def check_geometry():
    from dmd import Box
    # Awkward image dimensions, images smaller than a tile, and exact multiples.
    for width,height in [(6576,4384),(640,427),(1280,1280),(2360,2461),(1,1)]:
        xs=axis_starts(width);ys=axis_starts(height)
        assert xs[0]==ys[0]==0
        assert xs[-1]+min(1280,width)==width
        assert ys[-1]+min(1280,height)==height
        assert all(b-a<=1280 for a,b in zip(xs,xs[1:]))
        assert all(b-a<=1280 for a,b in zip(ys,ys[1:]))
        assert len(set(tile_windows(width,height)))==len(xs)*len(ys)
    # Same source animal appears in two overlapping tiles, plus a second class.
    a=to_source([Box(1200,10,1270,80,1,.9)],(0,0,1280,1280),(2500,1280))[0]
    b=to_source([Box(20,10,90,80,1,.8)],(1180,0,2460,1280),(2500,1280))[0]
    assert (a.x1,a.y1,a.x2,a.y2)==(b.x1,b.y1,b.x2,b.y2)
    c=Box(a.x1,a.y1,a.x2,a.y2,0,.85)
    merged=merge_boxes([b,c,a])
    assert len(merged)==2 and {v.class_id for v in merged}=={0,1}
    assert next(v for v in merged if v.class_id==1).score==.9
    clipped=to_source([Box(-10,-5,40,30,1,.8)],(0,0,1280,1280),(20,20))[0]
    assert (clipped.x1,clipped.y1,clipped.x2,clipped.y2)==(0.,0.,20.,20.)
    try:axis_starts(100,1280,1280)
    except ValueError:pass
    else:raise AssertionError("Invalid overlap accepted")
    return {"coverage_and_boundaries":"passed","coordinate_remap":"passed",
            "cross_tile_duplicate_merge":"passed","class_separation":"passed"}
