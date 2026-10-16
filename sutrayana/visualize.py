"""Presentation overlay and a portable offline review dashboard."""
import html
import io
import json
import os
from pathlib import Path
import tempfile
os.environ.setdefault("MPLCONFIGDIR",tempfile.gettempdir())
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from .model import parts
from .validation import validate

COLORS = ["#007f78", "#bf5b2e", "#6453b8", "#b53869", "#2e74ad"]


def render(plan,output,image_path=None,html_path=None):
    report = validate(plan,output)
    fig,ax = plt.subplots(figsize=(11,9),layout="constrained")
    fig.patch.set_facecolor("#fafbf9")
    ax.set_facecolor("#fafbf9")
    def polygon(g,color,alpha=1,edge="none",gid=None):
        for p in parts(g):
            if p.geom_type != "Polygon":
                continue
            from shapely.geometry.polygon import orient
            p = orient(p,sign=1)
            vertices,codes = [],[]
            for ring in [p.exterior]+list(p.interiors):
                pts = list(ring.coords)
                vertices.extend(pts)
                codes.extend([MplPath.MOVETO]+[MplPath.LINETO]*(len(pts)-2)+[MplPath.CLOSEPOLY])
            patch = PathPatch(MplPath(vertices,codes),facecolor=color,edgecolor=edge,alpha=alpha,lw=.6)
            if gid:
                patch.set_gid(gid)
            ax.add_patch(patch)
    polygon(plan.inner,"#e9ede9")
    for room in plan.rooms.values():
        polygon(room.polygon,"#f1f3ef",edge="#c6cec7")
    for i,h in enumerate(output["hubs"]):
        color = COLORS[i%len(COLORS)]
        for rid in h["assigned_rooms"]:
            polygon(plan.rooms[rid].polygon,color,.13,gid=f"zone-{i}-{rid}")
    polygon(plan.wall,"#35443e")
    polygon(plan.window,"#71b9de")
    for door in plan.doors:
        polygon(door,"#e9cb81",.8)
    for rid,r in plan.rooms.items():
        p = r.polygon.representative_point()
        ax.text(p.x,p.y+.30,f"{rid}\n{r.area:.1f} m²",fontsize=6.5,ha="center",va="bottom",color="#53655c")
    for i,h in enumerate(output["hubs"]):
        color = COLORS[i%len(COLORS)]
        if any(e["message"].startswith(h["hub_id"]+":") for e in report["errors"]):
            color = "#d32626"
        for j,leg in enumerate(h["route_segments"]):
            xy = leg["polyline"]
            line, = ax.plot(*zip(*xy),color=color,lw=1.7,alpha=.9,zorder=4)
            line.set_gid(f"ring-{i}-{j}")
            # Mark direction on a substantial segment without obscuring a doorway.
            segments = list(zip(xy,xy[1:]))
            if segments:
                a,b = max(segments,key=lambda s:abs(s[1][0]-s[0][0])+abs(s[1][1]-s[0][1]))
                start = (.55*a[0]+.45*b[0],.55*a[1]+.45*b[1])
                end = (.45*a[0]+.55*b[0],.45*a[1]+.55*b[1])
                ann = ax.annotate("",xy=end,xytext=start,arrowprops=dict(arrowstyle="->",color=color,lw=1.4),zorder=5)
                ann.set_gid(f"ring-{i}-arrow-{j}")
        for visit,nid in enumerate(h["closed_sequence"][1:-1],1):
            r = next(r for r in plan.eligible.values() if r.node_id == nid)
            ax.scatter(*r.node,s=24,c=color,edgecolors="white",linewidths=.8,zorder=6)
            ax.annotate(f"{nid} · {visit}",r.node,xytext=(6,-12),textcoords="offset points",fontsize=7,fontweight="bold",color=color,zorder=7)
        hp = h["location"]
        ax.scatter(hp["x"],hp["y"],s=80,marker="D",c=color,edgecolors="white",linewidths=1,zorder=8)
        ax.annotate(h["hub_id"],(hp["x"],hp["y"]),xytext=(7,7),textcoords="offset points",color=color,fontsize=9,fontweight="bold",zorder=9)
    if not report["valid"]:
        ax.text(.02,.98,"VALIDATION FAILED",transform=ax.transAxes,va="top",color="#c62828",weight="bold")
        for h in output["hubs"]:
            for leg in h["route_segments"]:
                from shapely.geometry import LineString
                bad = LineString(leg["polyline"]).difference(plan.free)
                for line in parts(bad):
                    if hasattr(line,"coords") and line.geom_type == "LineString":
                        ax.plot(*line.xy,color="#e02020",lw=4,zorder=10)
    m = output["reported_metrics"]
    ax.set_title(f"SutraYana / Plan {plan.id}\n{m['hub_count']} hubs    {m['total_length_m']:.2f} m cable    J {m['total_cost_J']:.2f}",loc="left",fontsize=13,color="#243d32",pad=18)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_xlabel("Metres · origin lower-left",color="#617369",fontsize=8)
    ax.set_ylabel("Metres",color="#617369",fontsize=8)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color("#d3dcd5")
    ax.tick_params(colors="#617369",labelsize=8)
    ax.grid(alpha=.1)
    if image_path:
        Path(image_path).parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(image_path,dpi=180)
    if html_path:
        stream = io.StringIO()
        fig.savefig(stream,format="svg")
        svg = stream.getvalue()
        svg = svg[svg.index("<svg"):]
        latency_val = output.get("solver", {}).get("elapsed_s") or output.get("solver_time_s")
        if latency_val is not None:
            latency_str = f'{latency_val * 1000:.0f} ms' if 0 < latency_val < 0.01 else f'{latency_val:.3f} s'
        else:
            latency_str = '—'
        cards = "".join(f'<div class="metric"><span>{label}</span><strong id="{mid}">{value}</strong></div>' for label,value,mid in [
            ("Hubs",str(m["hub_count"]),"metric-h"),
            ("Objective J",f'{m["total_cost_J"]:.2f}',"metric-j"),
            ("Cable length",f'{m["total_length_m"]:.2f} m',"metric-l"),
            ("Crossings",str(m["total_crossings"]),"metric-x"),
            ("Overlap",f'{m["total_overlap_m"]:.2f} m',"metric-o"),
            ("Bends",str(m["total_bends"]),"metric-b"),
            ("Latency",latency_str,"metric-latency")])
        hubs = ""
        for i,h in enumerate(output["hubs"]):
            area = round(sum(plan.rooms[r].area for r in h["assigned_rooms"]), 2)
            h["assigned_area_m2"] = area
            color = COLORS[i%len(COLORS)]
            hubs += f'<article class="hub"><label><input type="checkbox" checked data-ring="{i}"><b style="color:{color}">{html.escape(h["hub_id"])}</b><span>{area:.1f} / 100 m² · {len(h["assigned_nodes"])} / 5 nodes</span></label><p>{html.escape(" → ".join(h["closed_sequence"]))}</p><small>{html.escape(", ".join(h["assigned_rooms"]))}</small><div class="bar"><i style="width:{min(100, area)}%;background:{color}"></i></div></article>'
        data = json.dumps(output,ensure_ascii=True).replace("<","\\u003c")
        status = "Validated geometry" if report["valid"] else "Validation failed"
        document = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SutraYana · Cable ring review</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6f3;color:#1e362d;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}header{padding:24px 4vw;background:#173e32;color:white;display:flex;justify-content:space-between;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,0.06)}h1{font-size:24px;margin:0;letter-spacing:-0.5px;font-weight:700}header p{margin:4px 0 0;color:#b7cebf;font-size:13px}.badge{padding:6px 14px;background:#d6f5dd;color:#1a5632;border-radius:999px;font-size:12px;font-weight:600;display:inline-flex;align-items:center;gap:6px}.badge::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor}main{padding:24px 4vw;max-width:1700px;margin:auto}.metrics{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin-bottom:22px}.metric{background:#ffffff;border:1px solid #dce4dc;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,0.02);transition:transform 0.15s ease,box-shadow 0.15s ease}.metric:hover{transform:translateY(-1px);box-shadow:0 4px 8px rgba(0,0,0,0.04)}.metric span{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;color:#627768}.metric strong{font-size:24px;display:block;margin-top:8px;font-weight:700;color:#1a3328}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px}.drawing,aside{background:#fafbf9;border:1px solid #dce4dc;border-radius:16px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.02)}.drawing{position:relative;overflow:auto;display:flex;flex-direction:column}.drawing svg{width:100%;height:auto;display:block}aside{padding:22px;height:fit-content}h2{font-size:16px;font-weight:700;margin:0 0 6px;color:#173e32}.muted,small{color:#6f8072;font-size:12px;line-height:1.5}.hub{padding:18px 0;border-bottom:1px solid #dfe7df}.hub label{display:flex;gap:8px;align-items:center;cursor:pointer;user-select:none}.hub label input[type="checkbox"]{cursor:pointer;accent-color:#173e32;width:15px;height:15px}.hub label b{font-size:14px}.hub label span{margin-left:auto;font-size:11px;font-weight:500;color:#64796b}.hub p{font-size:12.5px;line-height:1.7;margin:8px 0 4px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;color:#274438}.hub small{display:block;font-size:11.5px;color:#6e7f73}.bar{height:5px;border-radius:3px;background:#e3eae2;margin-top:10px;overflow:hidden}.bar i{display:block;height:100%;border-radius:3px;transition:width 0.3s ease}.btn-group{display:flex;gap:8px;margin-top:16px}button{background:#173e32;color:white;border:0;padding:11px 16px;border-radius:8px;cursor:pointer;font:inherit;font-size:12px;font-weight:600;margin:12px 6px 0 0;transition:background 0.15s ease}button:hover{background:#235d4b}button.secondary{background:#e6ece4;color:#173e32}button.secondary:hover{background:#d4ded1}.legend{display:flex;gap:16px;padding:14px 20px;border-top:1px solid #dfe7df;font-size:11px;color:#5d7065;flex-wrap:wrap;align-items:center;background:#ffffff}.legend span{display:inline-flex;align-items:center}.legend i{width:12px;height:9px;display:inline-block;margin-right:6px;border-radius:2px}.foot{font-size:11.5px;line-height:1.7;color:#6b7d70;margin-top:20px}details{margin-top:20px;font-size:12px;border-top:1px solid #dfe7df;padding-top:14px}summary{cursor:pointer;font-weight:600;color:#204135;user-select:none}summary:hover{color:#112920}pre{overflow:auto;background:#edf1eb;padding:12px;border-radius:6px;max-height:260px;font-size:10.5px;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;margin-top:10px;color:#213a2f}@media(max-width:1200px){.metrics{grid-template-columns:repeat(4,1fr)}}@media(max-width:1000px){.workspace{grid-template-columns:1fr}}@media(max-width:600px){.metrics{grid-template-columns:repeat(2,1fr)}header{flex-direction:column;align-items:flex-start;gap:12px}.badge{font-size:11px}.metric strong{font-size:20px}}@media print{button,input{display:none!important}header{background:white;color:#173e32;padding:12px 0}.workspace{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(7,1fr)}aside{break-inside:avoid;border:none;padding:0}}
</style></head><body><header><div><h1>SutraYana<span style="font-weight:300;color:#b4d0bf"> / Cable rings</span></h1><p>Geometry you can inspect. Results you can verify.</p></div><div class="badge" id="status-badge">STATUS</div></header><main><section class="metrics" id="metrics-panel">CARDS</section><div class="workspace"><section class="drawing">DRAWING<div class="legend"><span><i style="background:#35443e"></i>Wall</span><span><i style="background:#71b9de"></i>Window</span><span><i style="background:#e9cb81"></i>Door</span><span>◆ Hub · ● Fixed node · → Cable direction</span></div></section><aside><h2>Connected zones</h2><p class="muted">Toggle a ring to inspect its route. Node labels show the visiting order.</p><div id="hubs-container">HUBS</div><button id="download">Download result JSON</button><button id="print">Print review</button><details><summary>Validation & search details</summary><pre id="validation"></pre></details><p class="foot">Fewest hubs first. Then J = L + 5X + O + 0.5B.<br>Hub count is proven for the configured connectivity rule. Cable cost uses finite candidate search.<br><br>Research prototype for the Cable Ring Challenge. Open-passage threshold: OPENMIN m. Excluded rooms do not connect zones.</p></aside></div><p class="foot">Input coordinates are converted once to metres with lower-left origin. Every route edge is checked against inner − wall − window. Fixed input nodes are preserved.</p></main><script type="application/json" id="result">DATA</script><script>
(function(){
  const resultEl=document.getElementById('result');
  if(!resultEl)return;
  try{
    const data=JSON.parse(resultEl.textContent);
    const m=data.reported_metrics||{};
    const solver=data.solver||{};
    const val=data.validation||{};

    // Dynamic metrics hydration
    const setTxt=(id,v)=>{const el=document.getElementById(id);if(el&&v!=null)el.textContent=v;};
    setTxt('metric-h',m.hub_count??(data.hubs?data.hubs.length:'—'));
    setTxt('metric-j',m.total_cost_J!=null?Number(m.total_cost_J).toFixed(2):'—');
    setTxt('metric-l',m.total_length_m!=null?Number(m.total_length_m).toFixed(2)+' m':'—');
    setTxt('metric-x',m.total_crossings??0);
    setTxt('metric-o',m.total_overlap_m!=null?Number(m.total_overlap_m).toFixed(2)+' m':'0.00 m');
    setTxt('metric-b',m.total_bends??0);

    const solverSec=solver.elapsed_s??data.solver_time_s??data.solve_time_s;
    const latStr=solverSec!=null?(Number(solverSec)<0.01&&Number(solverSec)>0?(Number(solverSec)*1000).toFixed(0)+' ms':Number(solverSec).toFixed(3)+' s'):'—';
    setTxt('metric-latency',latStr);

    const valPre=document.getElementById('validation');
    if(valPre)valPre.textContent=JSON.stringify({validation:val,solver:solver},null,2);

    document.querySelectorAll('[data-ring]').forEach(el=>{
      el.addEventListener('change',()=>{
        const r=el.dataset.ring,vis=el.checked;
        document.querySelectorAll('[id^="ring-'+r+'-"]').forEach(g=>g.style.opacity=vis?'1':'0');
        document.querySelectorAll('[id^="zone-'+r+'-"]').forEach(g=>g.style.opacity=vis?'0.13':'0');
      });
    });

    const pBtn=document.getElementById('print');
    if(pBtn)pBtn.onclick=()=>window.print();

    const dBtn=document.getElementById('download');
    if(dBtn)dBtn.onclick=()=>{
      const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url;
      a.download=`sutrayana-${data.plan_id||'result'}.json`;
      a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
  }catch(e){console.error(e);}
})();
</script></body></html>'''
        for key,value in [("STATUS",status),("CARDS",cards),("DRAWING",svg),("HUBS",hubs),("OPENMIN",str(plan.open_min)),("DATA",data)]:
            document = document.replace(key,value)
        if not report["valid"]:
            document = document.replace('<div class="badge" id="status-badge">','<div class="badge" id="status-badge" style="background:#fde5e5;color:#b32727">')
        Path(html_path).parent.mkdir(parents=True,exist_ok=True)
        Path(html_path).write_text(document,encoding="utf-8")
    plt.close(fig)
