"""Independent validator written from the problem statement (not from the team's code)."""
import math, itertools
from shapely.geometry import LineString, Point, MultiPoint
from shapely.ops import unary_union
from shapely import affinity
from collections import defaultdict

ELIG = ("living","bedroom","kitchen","storage")

def geoms(g):
    if g is None or g.is_empty: return []
    return list(g.geoms) if hasattr(g,"geoms") else [g]

def build_truth(raw):
    """Ground truth from the RAW ResPlan record, in metres."""
    scale = math.sqrt(raw["inner"].area / raw["area"])
    s = 1.0/scale
    sc = lambda g: affinity.scale(g, s, s, origin=(0,0))
    inner = sc(raw["inner"])
    wall = sc(raw["wall"]) if raw.get("wall") is not None else None
    win = sc(raw["window"]) if raw.get("window") is not None else None
    barrier = unary_union([g for g in (wall, win) if g is not None and not g.is_empty])
    free = inner.difference(barrier)
    rooms = {}
    for t in ELIG:
        for p in geoms(raw.get(t)):
            rooms.setdefault(t, []).append(sc(p))
    return dict(scale=scale, inner=inner, wall=wall, win=win, free=free, rooms=rooms,
                door=sc(raw["door"]) if raw.get("door") is not None else None)

def seg_len(a,b): return math.hypot(b[0]-a[0], b[1]-a[1])

def ring_polyline(h):
    pts=[]
    for sg in h["route_segments"]:
        for p in sg["polyline"]:
            if not pts or seg_len(pts[-1],p)>1e-9: pts.append(tuple(p))
    return pts

def check_output(out, truth, rooms_meta):
    """rooms_meta: {room_id: dict(area_m2, node(x,y) in metres)} for eligible rooms"""
    errs=[]
    free_tol = truth["free"].buffer(0.002)       # 2 mm tolerance
    hubs = out["hubs"]
    # coverage / exactly-one-hub
    seen=defaultdict(int)
    for h in hubs:
        for r in h["assigned_rooms"]: seen[r]+=1
    for r in rooms_meta:
        if seen[r]!=1: errs.append(f"COVERAGE room {r} assigned {seen[r]}x")
    # capacity
    for h in hubs:
        a=sum(rooms_meta[r]["area"] for r in h["assigned_rooms"] if r in rooms_meta)
        if a>100+1e-6: errs.append(f"CAPACITY {h['hub_id']} area {a:.1f}")
        if len(h["assigned_rooms"])>5: errs.append(f"CAPACITY {h['hub_id']} nodes {len(h['assigned_rooms'])}")
    # sequence: closed, each assigned node exactly once
    for h in hubs:
        seq=h["closed_sequence"]
        if seq[0]!=h["hub_id"] or seq[-1]!=h["hub_id"]: errs.append(f"SEQ {h['hub_id']} not closed at own hub")
        mid=seq[1:-1]
        if sorted(mid)!=sorted(h["assigned_nodes"]):
            errs.append(f"SEQ {h['hub_id']} visits {sorted(mid)} but assigned {sorted(h['assigned_nodes'])}")
    # geometry
    all_segs=[]
    for h in hubs:
        pl=ring_polyline(h)
        if len(pl)<2: errs.append(f"GEOM {h['hub_id']} empty polyline"); continue
        if seg_len(pl[0],pl[-1])>1e-3: errs.append(f"GEOM {h['hub_id']} ring not closed")
        loc=(h["location"]["x"],h["location"]["y"])
        if seg_len(loc,pl[0])>1e-3: errs.append(f"GEOM {h['hub_id']} location != polyline start")
        for a,b in zip(pl,pl[1:]):
            if abs(a[0]-b[0])>1e-6 and abs(a[1]-b[1])>1e-6: errs.append(f"AXIS {h['hub_id']} diagonal"); break
        for a,b in zip(pl,pl[1:]):
            ls=LineString([a,b])
            if not free_tol.contains(ls):
                bad=ls.difference(free_tol).length
                errs.append(f"FREESPACE {h['hub_id']} {bad:.3f} m of cable outside inner-wall-window"); break
        # node visits: polyline passes within 2mm of every node point
        for r in h["assigned_rooms"]:
            if r in rooms_meta:
                nd=Point(rooms_meta[r]["node"])
                if LineString(pl).distance(nd)>2e-3: errs.append(f"NODE {h['hub_id']} misses node of {r}")
        # hub point inside an assigned eligible room, >=0.5 m from walls
        hp=Point(loc)
        inroom=False
        for r in h["assigned_rooms"]:
            for pg in truth["rooms"].get(rooms_meta[r]["type"],[]):
                if pg.contains(hp): inroom=True; clr=hp.distance(pg.boundary)
        if not inroom: errs.append(f"HUBPT {h['hub_id']} not inside an assigned eligible room")
        elif clr<0.5-1e-3: errs.append(f"HUBPT {h['hub_id']} only {clr:.2f} m from room edge (<0.5)")
        for a,b in zip(pl,pl[1:]): all_segs.append((h["hub_id"],a,b))
    return errs, all_segs

def global_metrics(hubs_polylines, tol=1e-3):
    """Recompute L,B,O,X over ALL rings (incl. between rings and T-touches)."""
    L=0;B=0;segs=[]
    nodeish=set()
    for pid,pl in hubs_polylines.items():
        pl=[p for i,p in enumerate(pl) if i==0 or seg_len(pl[i-1],p)>tol]
        for a,b in zip(pl,pl[1:]): L+=seg_len(a,b); segs.append((pid,a,b))
        d=[]
        for a,b in zip(pl,pl[1:]):
            d.append(("H" if abs(b[1]-a[1])<tol else "V", 1 if (b[0]-a[0]+b[1]-a[1])>0 else -1))
        for i in range(len(d)):
            p,q=d[i-1],d[i]
            if p!=q: B+=1          # turn or reversal both count once
    # overlap
    O=0.0; by=defaultdict(list)
    for pid,a,b in segs:
        if abs(a[1]-b[1])<tol: by[("H",round(a[1]/tol))].append((min(a[0],b[0]),max(a[0],b[0])))
        else: by[("V",round(a[0]/tol))].append((min(a[1],b[1]),max(a[1],b[1])))
    for k,iv in by.items():
        ev=[]
        for lo,hi in iv: ev+= [(lo,1),(hi,-1)]
        ev.sort(key=lambda e:(e[0],-e[1])); cov=0;px=None
        for x,dd in ev:
            if px is not None and cov>=2 and x>px: O+=(cov-1)*(x-px)
            cov+=dd; px=x
    # crossings: distinct points where two different legs meet (interior of at least one) away from nodes/hubs
    pts=set()
    S=[(a,b) for _,a,b in segs]
    for i in range(len(S)):
        for j in range(i+1,len(S)):
            l1=LineString(S[i]); l2=LineString(S[j])
            if l1.intersects(l2):
                x=l1.intersection(l2)
                if x.geom_type=="Point": pts.add((round(x.x/tol),round(x.y/tol)))
    return dict(L=L,B=B,O=O,pts_touch=len(pts))
