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
        cards = "".join(f'<div class="metric"><span>{label}</span><strong>{value}</strong></div>' for label,value in [
            ("Hubs",str(m["hub_count"])),("Objective J",f'{m["total_cost_J"]:.2f}'),("Cable length",f'{m["total_length_m"]:.2f} m'),
            ("Crossings",str(m["total_crossings"])),("Overlap",f'{m["total_overlap_m"]:.2f} m'),("Bends",str(m["total_bends"]))])
        hubs = ""
        for i,h in enumerate(output["hubs"]):
            area = sum(plan.rooms[r].area for r in h["assigned_rooms"])
            hubs += f'<article class="hub"><label><input type="checkbox" checked data-ring="{i}"><b style="color:{COLORS[i%len(COLORS)]}">{html.escape(h["hub_id"])}</b><span>{area:.1f} / 100 m² · {len(h["assigned_nodes"])} / 5 nodes</span></label><p>{html.escape(" → ".join(h["closed_sequence"]))}</p><small>{html.escape(", ".join(h["assigned_rooms"]))}</small><div class="bar"><i style="width:{area}%;background:{COLORS[i%len(COLORS)]}"></i></div></article>'
        data = json.dumps(output,ensure_ascii=True).replace("<","\\u003c")
        status = "Validated geometry" if report["valid"] else "Validation failed"
        document = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SutraYana · Cable ring review</title><style>
*{box-sizing:border-box}body{margin:0;background:#f0f3ef;color:#203c30;font:15px system-ui,sans-serif}header{padding:28px 4vw;background:#173e32;color:white;display:flex;justify-content:space-between;align-items:center}h1{font-size:25px;margin:0;letter-spacing:-1px}header p{margin:6px 0 0;color:#bad2c4;font-size:13px}.badge{padding:8px 14px;background:#d6f5dd;color:#215c39;border-radius:30px;font-size:12px;font-weight:700}main{padding:25px 4vw;max-width:1700px;margin:auto}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:22px}.metric{background:white;border:1px solid #dce4dc;border-radius:12px;padding:17px}.metric span{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#64796b}.metric strong{font-size:26px;display:block;margin-top:8px;font-weight:600}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:22px}.drawing,aside{background:#fafbf9;border:1px solid #dce4dc;border-radius:16px;overflow:hidden}.drawing{position:relative;overflow:auto}.drawing svg{width:100%;height:auto;display:block}aside{padding:22px;height:fit-content}h2{font-size:16px;margin:0 0 8px}.muted,small{color:#748477;font-size:12px;line-height:1.6}.hub{padding:20px 0;border-bottom:1px solid #dfe7df}.hub label{display:flex;gap:8px;align-items:center;cursor:pointer}.hub label span{margin-left:auto;font-size:11px;color:#64796b}.hub p{font-size:13px;line-height:1.8;margin:10px 0 4px}.bar{height:4px;border-radius:3px;background:#e5ebe4;margin-top:12px}.bar i{display:block;height:100%;border-radius:3px}button{background:#173e32;color:white;border:0;padding:12px 15px;border-radius:8px;cursor:pointer;font:inherit;font-size:12px;margin:12px 5px 0 0}button:hover{background:#28634e}.legend{display:flex;gap:16px;padding:16px 22px;border-top:1px solid #dfe7df;font-size:11px;color:#617369;flex-wrap:wrap}.legend i{width:12px;height:9px;display:inline-block;margin-right:5px}.foot{font-size:12px;line-height:1.8;color:#6c7c70;margin-top:24px}details{margin-top:22px;font-size:12px}summary{cursor:pointer;font-weight:600}pre{overflow:auto;background:#edf1eb;padding:12px;max-height:260px;font-size:10px}@media(max-width:1000px){.workspace{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:500px){.metrics{grid-template-columns:repeat(2,1fr)}header{gap:16px}.badge{font-size:10px}.metric strong{font-size:22px}}@media print{button,input{display:none}header{background:white;color:#173e32}.workspace{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(6,1fr)}aside{break-inside:avoid}}
</style></head><body><header><div><h1>SutraYana<span style="font-weight:300;color:#b4d0bf"> / Cable rings</span></h1><p>Geometry you can inspect. Results you can verify.</p></div><div class="badge">STATUS</div></header><main><section class="metrics">CARDS</section><div class="workspace"><section class="drawing">DRAWING<div class="legend"><span><i style="background:#35443e"></i>Wall</span><span><i style="background:#71b9de"></i>Window</span><span><i style="background:#e9cb81"></i>Door</span><span>◆ Hub · ● Fixed node · → Cable direction</span></div></section><aside><h2>Connected zones</h2><p class="muted">Toggle a ring to inspect its route. Node labels show the visiting order.</p>HUBS<button id="download">Download result JSON</button><button id="print">Print review</button><details><summary>Validation & search details</summary><pre id="validation"></pre></details><p class="foot">Fewest hubs first. Then J = L + 5X + O + 0.5B.<br>Hub count is proven for the configured connectivity rule. Cable cost uses finite candidate search.<br><br>Research prototype for the Cable Ring Challenge. Open-passage threshold: OPENMIN m. Excluded rooms do not connect zones.</p></aside></div><p class="foot">Input coordinates are converted once to metres with lower-left origin. Every route edge is checked against inner − wall − window. Fixed input nodes are preserved.</p></main><script type="application/json" id="result">DATA</script><script>
const data=JSON.parse(document.getElementById('result').textContent);document.getElementById('validation').textContent=JSON.stringify({validation:data.validation,solver:data.solver},null,2);document.querySelectorAll('[data-ring]').forEach(el=>el.addEventListener('change',()=>document.querySelectorAll('[id^="ring-'+el.dataset.ring+'-"]').forEach(g=>g.style.opacity=el.checked?'1':'0')));document.getElementById('print').onclick=()=>window.print();document.getElementById('download').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='sutrayana-result.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
</script></body></html>'''
        for key,value in [("STATUS",status),("CARDS",cards),("DRAWING",svg),("HUBS",hubs),("OPENMIN",str(plan.open_min)),("DATA",data)]:
            document = document.replace(key,value)
        if not report["valid"]:
            document = document.replace('<div class="badge">','<div class="badge" style="background:#fde5e5;color:#b32727">')
        Path(html_path).parent.mkdir(parents=True,exist_ok=True)
        Path(html_path).write_text(document,encoding="utf-8")
    plt.close(fig)
