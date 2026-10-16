import sys, pickle, math, json, time, os, collections, random
REPO=os.environ.get("SUTRAYANA_DIR",".")
sys.path.insert(0,REPO)
os.chdir(REPO)
PKL=os.environ.get("RESPLAN_PKL","ResPlan/ResPlan/ResPlan.pkl")
from export_resplan_to_json import extract_rooms_and_doors
from phase4_routing import run_phase4
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from validate import *
d=pickle.load(open(PKL,"rb"))
idxs=[int(x) for x in sys.argv[1:]]
res={}
for i in idxs:
    raw=d[i]; t0=time.time()
    try:
        truth=build_truth(raw)
        f=extract_rooms_and_doors(raw, plan_id=f"plan_{i}")
        sc=truth["scale"]
        meta={r["id"]:dict(type=r["type"],area=r["area"],node=(r["node"]["x"]/sc,r["node"]["y"]/sc))
              for r in f["rooms"] if r["type"] in ELIG}
        out,J,_=run_phase4(f,show_plot=False,save_img=None,resolution=0.08,output_json_path="audit_tmp_out.json",verbose=False)
        errs,segs=check_output(out,truth,meta)
        gm=global_metrics({h["hub_id"]:ring_polyline(h) for h in out["hubs"]})
        tot_area=sum(m["area"] for m in meta.values()); n=len(meta)
        lb=max(math.ceil(tot_area/100-1e-9),math.ceil(n/5),1)
        res[i]=dict(errs=errs,hubs=len(out["hubs"]),lb=lb,rep=out["reported_metrics"],gm=gm,n=n,area=tot_area,t=time.time()-t0)
    except Exception as e:
        res[i]=dict(crash=repr(e)[:200])
json.dump(res,open("audit_result_%s.json"%idxs[0],"w"),default=str)
bad=0
for i,r in res.items():
    if "crash" in r: print(i,"CRASH",r["crash"]); bad+=1; continue
    tag="OK " if not r["errs"] else "BAD"
    if r["errs"]: bad+=1
    print(i,tag,"hubs",r["hubs"],"lb",r["lb"],"n",r["n"],"area%.0f"%r["area"],"| rep J",r["rep"]["total_cost_J"],"| global L%.1f B%d O%.2f"%(r["gm"]["L"],r["gm"]["B"],r["gm"]["O"]),"|",r["errs"][:3])
print("bad",bad,"of",len(res))
