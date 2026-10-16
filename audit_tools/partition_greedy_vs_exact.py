import sys,pickle,json,collections,math,random,time,itertools
sys.path.insert(0,"/home/claude/audit")
import networkx as nx
from validate import *; from adjacency import *
d=pickle.load(open(__import__("os").environ.get("RESPLAN_PKL","ResPlan/ResPlan/ResPlan.pkl"),"rb"))
def greedy_partition(elig,adj,area):
    G=nx.Graph(); G.add_nodes_from(elig); G.add_edges_from(adj)
    un=set(elig); zones=[]
    while un:
        sub=G.subgraph(un); seed=max(sorted(un),key=lambda r:(sub.degree(r),area[r]))
        z={seed}; un.discard(seed); a=area[seed]
        while len(z)<5:
            fr=[n for r in z for n in G.neighbors(r) if n in un and a+area[n]<=100]
            if not fr: break
            n=max(sorted(set(fr)),key=lambda r:(sub.degree(r),-area[r])); z.add(n); un.discard(n); a+=area[n]
        zones.append(z)
    return zones
random.seed(11); idx=random.sample(range(17000),400)
c=collections.Counter(); t0=time.time()
for i in idx:
    raw=d[i]; truth=build_truth(raw); E,R=true_edges(raw,truth)
    elig=[r for r,(t,p) in R.items() if t in ELIG]; area={r:R[r][1].area for r in elig}
    adj=[e for e in E if e[0] in elig and e[1] in elig]
    if not elig: continue
    lb=max(math.ceil(sum(area.values())/100-1e-9),math.ceil(len(elig)/5),1)
    k,_=min_partition(elig,adj,area); g=len(greedy_partition(elig,adj,area))
    if k is None: c["no_feasible"]+=1; continue
    c["plans"]+=1; c["greedy==LB"]+= g==lb; c["exact==LB"]+= k==lb; c["greedy>exact"]+= g>k; c["greedy>exact_by2+"]+= g>k+1; c["exact>LB"]+= k>lb
    c["exact_hubs"]+=k; c["greedy_hubs"]+=g
print(dict(c),"time",round(time.time()-t0))
