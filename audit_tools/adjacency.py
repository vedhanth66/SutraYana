import math, itertools
from shapely import affinity
from validate import geoms, ELIG

def rooms_m(raw, truth):
    out={}
    for t in ELIG+("bathroom","balcony"):
        for j,p in enumerate(geoms(raw.get(t))):
            s=1/truth["scale"]; out[f"{t}{j}"]=(t, affinity.scale(p,s,s,origin=(0,0)))
    return out

def true_edges(raw, truth, open_min=0.5, touch=0.02):
    R=rooms_m(raw,truth); E={}
    s=1/truth["scale"]
    for dp in geoms(raw.get("door")):
        dp=affinity.scale(dp,s,s,origin=(0,0))
        near=[r for r,(t,p) in R.items() if dp.distance(p)<=0.05]
        for a,b in itertools.combinations(sorted(near),2): E[(a,b)]="door"
    ids=sorted(R)
    for a,b in itertools.combinations(ids,2):
        if R[a][1].distance(R[b][1])<=touch:
            shared=R[a][1].buffer(touch).intersection(R[b][1].buffer(touch))
            if shared.length/2>=open_min and (a,b) not in E: E[(a,b)]="open"
    return E, R

def min_partition(elig_ids, adj, area, maxA=100.0, maxN=5):
    """Exact: smallest k such that eligible rooms split into k connected zones obeying both caps."""
    import networkx as nx
    G=nx.Graph(); G.add_nodes_from(elig_ids); G.add_edges_from(adj)
    n=len(elig_ids)
    def ok(S):
        if len(S)>maxN or sum(area[r] for r in S)>maxA+1e-9: return False
        return nx.is_connected(G.subgraph(S))
    ids=list(elig_ids); best=[None]
    def rec(rest,k,cur):
        if not rest: return cur if k==0 else None
        if k==0: return None
        first=rest[0]; others=rest[1:]
        for r in range(len(others)+1):
            for combo in itertools.combinations(others,r):
                S=(first,)+combo
                if ok(S):
                    rem=[x for x in others if x not in combo]
                    res=rec(rem,k-1,cur+[S])
                    if res: return res
        return None
    for k in range(1,n+1):
        res=rec(ids,k,[])
        if res: return k,res
    return None,None
