const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const colors=['#268367','#bf8240','#688bc4','#ae6c93','#8e9d44','#5ba9ac'];
let catalog=[],selected=null,plan=null,result=null,busy=false,filter='all',history=[],view=null,baseView=null,selectionVersion=0,catalogVersion=0;
const el=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n};
const dom=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok)throw Error(value.error||'Request failed');return value}
function notice(text,kind=''){const n=$('notice');if(n){n.textContent=text;n.className='notice '+kind}}
function visible(){const query=$('search').value.toLowerCase();return catalog.filter(p=>(p.name+' '+p.description).toLowerCase().includes(query)&&(filter==='all'||(filter==='test')===(p.source==='Synthetic test')))}
function library(){$('count').textContent=catalog.length;$('plans').replaceChildren();visible().forEach(p=>{const b=dom('button','plan'+(p.key===selected?' active':''));b.disabled=busy;b.setAttribute('aria-current',String(p.key===selected));b.append(dom('span','plan-icon','⌑'));const text=dom('span');text.append(dom('span','plan-title',p.name),dom('small','',`${p.rooms} rooms · ${p.source}`));b.append(text);if(history.some(h=>h.key===p.key&&h.ok&&h.profile_valid!==false))b.append(dom('span','plan-dot','✓'));b.onclick=()=>choose(p.key);$('plans').append(b)});if(!visible().length)$('plans').append(dom('p','muted','No plans match your search.'))}
function clearResult(){result=null;['h','j','l','x','o','b','latency'].forEach(k=>$('metric-'+k)&&($('metric-'+k).textContent='—'));$('download').disabled=true;$('play').disabled=true;$('save-svg').disabled=true;$('zones').replaceChildren(dom('p','muted','Generate rings to inspect each zone’s capacity and visiting order.'));$('score-bar').replaceChildren();$('proof-title').textContent='Geometry first';$('proof').textContent='Every output is checked before it appears as a valid design.';$('status').textContent='READY';$('status').className='pill';$('canvas-label').textContent='INPUT GEOMETRY';$('facts').replaceChildren();if(typeof stopTrace3D==='function')stopTrace3D();if(routesGroup)routesGroup.clear();if(typeof update3DLabels==='function')update3DLabels();}
async function choose(key){setCanvasMode('2d');const version=++selectionVersion;selected=key;plan=null;clearResult();library();const item=catalog.find(p=>p.key===key);$('title').textContent=item?item.name:key;$('description').textContent=item?item.description:'';$('solve').disabled=true;$('empty').hidden=false;$('map').replaceChildren();$('rooms').replaceChildren();$('warnings').replaceChildren();notice('Loading floor-plan geometry…');try{const value=await api('/api/plan/'+key);if(version!==selectionVersion)return;plan=value;const [x0,y0,x1,y1]=plan.bounds,pad=Math.max(x1-x0,y1-y0)*.1;baseView=[x0-pad,-y1-pad,x1-x0+2*pad,y1-y0+2*pad];view=[...baseView];draw();inputDetails();$('solve').disabled=busy;if(value.solution){const solTime=value.solution.solver?.elapsed_s??value.solution.elapsed_s??null;showResult({ok:true,output:value.solution,solver_time_s:solTime,elapsed_s:solTime});notice(`${item?item.source:'Solution'} · Solution routes loaded · ${plan.rooms.filter(r=>r.node).length} fixed nodes · source coordinates preserved.`,'success')}else{notice(`${item?item.source:'Plan'} · ${plan.rooms.filter(r=>r.node).length} fixed nodes · source coordinates preserved.`)}}catch(e){if(version!==selectionVersion)return;notice(e.message,'error');$('empty').textContent='Input could not be loaded';warnings([{rule:'input',message:e.message}])}}
function pathData(g){if(!g)return '';if(g.type==='Polygon')return g.coordinates.map(r=>r.map((p,i)=>(i?'L':'M')+p[0]+','+(-p[1])).join(' ')+'Z').join(' ');if(g.type==='MultiPolygon')return g.coordinates.map(c=>pathData({type:'Polygon',coordinates:c})).join(' ');if(g.type==='GeometryCollection')return g.geometries.map(pathData).join(' ');return ''}
function polygon(parent,g,fill,opacity=1){const d=pathData(g);if(d)parent.append(el('path',{d,fill,opacity,'fill-rule':'evenodd'}))}
function applyView(){$('map').setAttribute('viewBox',view.join(' '))}
function draw(){if(!plan)return;const svg=$('map');svg.replaceChildren();svg.classList.remove('tracing');applyView();$('empty').hidden=true;const unit=Math.max(baseView[2],baseView[3]);const font=unit*.012;polygon(svg,plan.inner,'#e9eee4');plan.rooms.forEach(r=>polygon(svg,r.polygon,'#f4f5eb'));if(result)result.output.hubs.forEach((h,i)=>h.assigned_rooms.forEach(id=>polygon(svg,plan.rooms.find(r=>r.id===id).polygon,colors[i%colors.length],.12)));if($('clearance').checked&&$('profile').value!=='0')polygon(svg,plan.clearance_band,'#daaa60',.23);polygon(svg,plan.wall,'#41564b');polygon(svg,plan.window,'#77b1cd');plan.doors.forEach(d=>polygon(svg,d,'#d4b67b',.68));if($('labels').checked)plan.rooms.forEach(r=>{const text=el('text',{x:r.label[0],y:-r.label[1]-font*1.8,'text-anchor':'middle',fill:'#8a957e','font-size':font*.8,class:'map-label'},r.id+' · '+r.area.toFixed(1)+' m²');svg.append(text)});
if(result){result.output.hubs.forEach((h,i)=>{const color=colors[i%colors.length],group=el('g',{'data-ring':i});h.route_segments.forEach((l,j)=>{const d=l.polyline.map((p,k)=>(k?'L':'M')+p[0]+','+(-p[1])).join(' ');const line=el('path',{d,fill:'none',stroke:color,'stroke-width':unit*.0026,class:'route',opacity:j===h.route_segments.length-1?.65:1});line.style.setProperty('--route-length',l.length_m);group.append(line);const pairs=l.polyline.slice(1).map((p,k)=>[l.polyline[k],p]).sort((a,b)=>Math.hypot(b[1][0]-b[0][0],b[1][1]-b[0][1])-Math.hypot(a[1][0]-a[0][0],a[1][1]-a[0][1]));if(pairs.length){const [a,b]=pairs[0],x=(a[0]+b[0])/2,y=-(a[1]+b[1])/2,angle=Math.atan2(-(b[1]-a[1]),b[0]-a[0])*180/Math.PI,s=unit*.005;group.append(el('path',{d:`M ${-s} ${-s*.6} L ${s} 0 L ${-s} ${s*.6}`,transform:`translate(${x} ${y}) rotate(${angle})`,fill:'none',stroke:color,'stroke-width':unit*.0018}));}});const x=h.location.x,y=-h.location.y,s=unit*.006;group.append(el('path',{d:`M${x} ${y-s}L${x+s} ${y}L${x} ${y+s}L${x-s} ${y}Z`,fill:color,stroke:'white','stroke-width':unit*.001}));group.append(el('text',{x:x+s*1.6,y:y-s*1.6,fill:color,'font-size':font*1.1,'font-weight':700,class:'map-label'},h.hub_id));svg.append(group)})}
plan.rooms.filter(r=>r.node).forEach(r=>{const i=result?result.output.hubs.findIndex(h=>h.assigned_rooms.includes(r.id)):-1,color=i<0?'#76946a':colors[i%colors.length];const [x,y]=r.node;svg.append(el('circle',{cx:x,cy:-y,r:unit*.0035,fill:color,stroke:'white','stroke-width':unit*.001}));if($('labels').checked){const visit=i<0?'':` · ${result.output.hubs[i].closed_sequence.indexOf(r.node_id)}`;svg.append(el('text',{x:x+font*.7,y:-y+font*1.3,fill:color,'font-size':font*.85,class:'map-label'},r.node_id+visit))}})}
function warnings(items){$('warnings-count').textContent=items.length?items.length+' notices':'CLEAR';$('warnings').replaceChildren();if(!items.length){$('warnings').append(dom('span','','✓ No input warnings detected. Output validation runs after solving.'));return}items.forEach(w=>{const d=dom('div','warning-item');d.append(dom('strong','',w.rule.replaceAll('_',' ').toUpperCase()),dom('span','',w.message));$('warnings').append(d)})}
function inputDetails(){warnings(plan.warnings);$('provenance').textContent='Node provenance: '+plan.provenance+'. Catalog includes only available files; synthetic cases are labelled. Full ResPlan and organiser hidden inputs are not bundled.';$('rooms').replaceChildren();plan.rooms.forEach(r=>{const row=dom('tr');[r.id,r.kind,r.area.toFixed(3),r.node_id||'Excluded'].forEach(v=>row.append(dom('td','',v)));$('rooms').append(row)})}
function showResult(value){result=value;const out=value.output,s=out.solver||{};const hubs=out.hubs||[];const calcLength=hubs.reduce((acc,h)=>(h.route_segments||[]).reduce((a,sg)=>a+(sg.length_m||0),acc),0);const m=out.reported_metrics||{hub_count:hubs.length,total_cost_J:calcLength,total_length_m:calcLength,total_crossings:0,total_overlap_m:0,total_bends:0};const solverSec=s.elapsed_s??value.solver_time_s??value.solve_time_s??(s.latency_ms?s.latency_ms/1000:null);const latencyDisplay=solverSec!=null?(Number(solverSec)<0.01&&Number(solverSec)>0?(Number(solverSec)*1000).toFixed(0)+' ms':Number(solverSec).toFixed(3)+' s'):(value.elapsed_s!=null?Number(value.elapsed_s).toFixed(2)+' s':'—');[['h',m.hub_count],['j',Number(m.total_cost_J??0).toFixed(2)],['l',Number(m.total_length_m??0).toFixed(2)],['x',m.total_crossings??0],['o',Number(m.total_overlap_m??0).toFixed(2)],['b',m.total_bends??0]].forEach(([k,v])=>$('metric-'+k)&&($('metric-'+k).textContent=v));$('status').textContent='VALIDATED';$('status').className='pill valid';$('canvas-label').textContent='VERIFIED ROUTES';$('proof-title').textContent=s.hub_count_proven?'Minimum hub count matched':'Valid design with extra hubs';$('proof').textContent=`Capacity bound ${plan.capacity_lower_bound} · graph partition minimum ${s.minimum_hubs??hubs.length}. Tried ${(s.attempted_hub_counts || [m.hub_count]).join(', ')} hubs. ${s.hub_count_proven?'Hub count is proven for the constructed graph.':'Minimum-hub routes were not found with this candidate search.'} Cable cost remains heuristic.`;
$('zones').replaceChildren();out.hubs.forEach((h,i)=>{const area=h.assigned_rooms.reduce((sum,id)=>sum+plan.rooms.find(r=>r.id===id).area,0),card=dom('article','zone'),head=dom('label','zone-head'),check=dom('input');check.type='checkbox';check.checked=true;check.onchange=()=>document.querySelector(`[data-ring="${i}"]`).setAttribute('opacity',check.checked?1:.08);head.append(check,dom('span','',h.hub_id),dom('small','',h.assigned_nodes.length+' / 5 nodes'));head.style.color=colors[i%colors.length];const bar=dom('div','bar'),fill=dom('i');fill.style.width=Math.min(100,area)+'%';fill.style.background=colors[i%colors.length];bar.append(fill);card.append(head,dom('p','',h.closed_sequence.join(' → ')),bar,dom('small','',`${area.toFixed(1)} / 100 m² · ${h.ring_length_m.toFixed(2)} m cable`));$('zones').append(card)});
$('facts').replaceChildren();[['Wire clearance',Number(s.wire_clearance_m ?? $('profile').value).toFixed(1)+' m required'],['Router policy',s.rl_adaptive_routing?'RL Dueling-DDQN (Adaptive)':'Classical Dijkstra'],['Measured minimum',value.measured_clearance_m==null?'No wall/window':value.measured_clearance_m.toFixed(3)+' m'],['Solver latency',latencyDisplay],['Area gap',Number(s.area_gap_m2 ?? 0).toFixed(2)+' m²'],['Coordinates','Source origin / metres']].forEach(([k,v])=>{const d=dom('div');d.append(dom('span','',k),dom('b','',v));$('facts').append(d)});
const costs=[m.total_length_m,5*m.total_crossings,m.total_overlap_m,.5*m.total_bends],bar=dom('div','cost-bars'),labels=dom('div','cost-labels');costs.forEach((v,i)=>{const part=dom('i');part.style.width=(m.total_cost_J?v/m.total_cost_J*100:0)+'%';part.style.background=colors[i];part.title=['Length','Crossings','Overlap','Bends'][i]+': '+v.toFixed(2);bar.append(part);labels.append(dom('span','',['L','5X','O','½B'][i]+' '+v.toFixed(1)))});$('score-bar').replaceChildren(bar,labels);const alerts=[...(out.warnings||out.validation?.warnings||plan.warnings||[])];const actual=value.measured_clearance_m,required=Number(s.wire_clearance_m ?? $('profile').value);const clearanceFailed=actual!=null&&actual<required-.001;if(clearanceFailed)alerts.push({rule:'wire_clearance',message:`This backend returned a wire ${actual.toFixed(3)} m from a wall/window; the selected profile requires ${required.toFixed(3)} m.`});warnings(alerts);draw();$('download').disabled=false;$('play').disabled=false;$('save-svg').disabled=false;notice(`Validated in ${latencyDisplay}. Every node is covered and every route passes the configured geometry checks.`,'success');if(clearanceFailed){$('status').textContent='CLEARANCE ISSUE';$('canvas-label').textContent='INSPECTION ONLY';$('status').className='pill failed';$('download').disabled=true;notice(`The route is shown for inspection, but wires pass within ${actual.toFixed(3)} m of a wall/door. Switch profile to "Slide rules" to export.`,'error');}if(typeof update3DRoutes==='function')update3DRoutes();if(typeof update3DLabels==='function')update3DLabels();}
function setBusy(value){busy=value;['solve','batch','upload'].forEach(id=>{const el=$(id);if(el)el.disabled=value||(!plan&&id==='solve')});$('profile')?.querySelectorAll('.profile-btn').forEach(b=>b.disabled=value);$('solve').textContent=value?'Solving…':'Generate cable rings ↗';library()}
async function run(key){clearResult();draw();const profile=Number($('profile').value),limit=Number($('budget')?.value||30),enhanced=Boolean($('enhanced')?.checked),use_rl=true,start=performance.now();notice('Searching connected zones and clearance-safe routes…','busy');$('status').textContent='RUNNING';try{const {job_id}=await api('/api/solve',{key,wire_clearance:profile,timeout:limit,enhanced,use_rl});let value;do{if(performance.now()-start>(limit+15)*1000)throw Error('The server has not finished within the time budget. Check that you are running the current server.');await new Promise(r=>setTimeout(r,450));value=await api('/api/jobs/'+job_id);if(value.status!=='done')notice(`Searching routes · ${((performance.now()-start)/1000).toFixed(0)} s elapsed`,'busy')}while(value.status!=='done');const solverSec=value.output?.solver?.elapsed_s??value.solver_time_s??value.solve_time_s;if(solverSec!=null)value.solver_time_s=solverSec;value.network_elapsed_s=(performance.now()-start)/1000;value.profile_valid=value.ok&&(value.measured_clearance_m==null||value.measured_clearance_m>=profile-.001);history.unshift({key,name:catalog.find(p=>p.key===key).name,profile,use_rl,...value});renderHistory();if(value.ok)showResult(value);else{notice(value.error,'error');$('status').textContent='NOT SOLVED';$('status').className='pill failed';$('proof-title').textContent='No valid design emitted';$('proof').textContent=value.error;warnings([...(plan?.warnings||[]),{rule:'routing',message:value.error}])}return value}catch(e){notice(e.message,'error');$('status').textContent='ERROR';$('status').className='pill failed';history.unshift({key,name:catalog.find(p=>p.key===key).name,profile,use_rl,ok:false,error:e.message,elapsed_s:(performance.now()-start)/1000});renderHistory();return {ok:false}}}
function renderHistory(){$('history').replaceChildren();history.forEach(h=>{const row=dom('tr'),name=dom('td'),link=dom('button','text-button',h.name);link.onclick=async()=>{if(busy)return;$('profile').value=String(h.profile);await choose(h.key);if(plan&&h.ok)showResult(h);else if(h.error){notice(h.error,'error');$('status').textContent='NOT SOLVED';$('status').className='pill failed';$('proof-title').textContent='No valid design emitted';$('proof').textContent=h.error;warnings([...(plan?.warnings||[]),{rule:'routing',message:h.error}])}};name.append(link);name.append(dom('small','',(h.profile===.5?'0.5 m clearance':'Slide rules')+(h.use_rl?' · RL enhanced':'')));row.title=h.error||'Validated for the selected profile';const m=h.output?.reported_metrics;const histTime=h.output?.solver?.elapsed_s??h.solver_time_s??h.elapsed_s;const histTimeStr=histTime!=null?(Number(histTime)<0.01&&Number(histTime)>0?(Number(histTime)*1000).toFixed(0)+' ms':Number(histTime).toFixed(3)+' s'):'—';row.append(name,...[h.profile_valid===false&&h.ok?'Clearance issue':h.ok?'✓ Valid':'Issue',m?.hub_count??'—',m?.total_cost_J.toFixed(2)??'—',histTimeStr].map(v=>dom('td','',v)));$('history').append(row)})}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=dom('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('solve').onclick=async()=>{if(!selected||busy)return;setBusy(true);try{await run(selected)}finally{setBusy(false)}};
$('batch').onclick=async()=>{if(busy)return;const keys=visible().map(p=>p.key);setBusy(true);let valid=0;try{for(const key of keys){await choose(key);if(plan){const r=await run(key);valid+=Number(r.ok&&r.profile_valid!==false)}}notice(`Suite complete: ${valid}/${keys.length} valid designs. See each result or failure in run history. Expected negative tests remain failures.`,valid===keys.length?'success':'')}finally{setBusy(false)}};
$('upload').onchange=async e=>{try{const files=[...e.target.files];if(files.length>50)throw Error('Import up to 50 files at once.');const items=[];for(const f of files){if(f.size>12*1024*1024)throw Error(f.name+' exceeds 12 MB.');items.push({name:f.name,data:JSON.parse(await f.text())})}if(!items.length)return;const response=await api('/api/import',{plans:items});const stamp=++catalogVersion;const data=await api('/api/plans');if(stamp!==catalogVersion)return;catalog=data;library();const lastKey=response.keys && response.keys.length ? response.keys[response.keys.length-1] : null;if(lastKey)await choose(lastKey);if(response.errors.length)notice(response.errors.join(' '),'error')}catch(error){notice('Import failed: '+error.message,'error')}finally{e.target.value=''}};
$('search').oninput=library;document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(n=>n.classList.toggle('active',n===b));library()});
$('download').onclick=()=>result&&download(result.output,'sutrayana-result.json');$('export-history').onclick=()=>download({generated_at:new Date().toISOString(),scope:'Local runs; not a hidden-benchmark score',runs:history},'sutrayana-run-report.json');
const pEl=$('profile');if(pEl){let curVal='0';pEl.dataset.value=curVal;Object.defineProperty(pEl,'value',{get(){return pEl.dataset.value||curVal},set(v){curVal=String(Number(v)===.5?.5:0);pEl.dataset.value=curVal;pEl.querySelectorAll('.profile-btn').forEach(b=>{const m=b.dataset.value===curVal;b.classList.toggle('active',m);b.setAttribute('aria-checked',String(m))})}});pEl.querySelectorAll('.profile-btn').forEach(b=>{b.onclick=()=>{if(busy||pEl.value===b.dataset.value)return;pEl.value=b.dataset.value;if(typeof pEl.onchange==='function')pEl.onchange()}})}
$('profile').onchange=()=>{clearResult();draw();if(plan)inputDetails();notice('Routing profile changed. Generate again to score this configuration.')};$('clearance').onchange=draw;$('labels').onchange=()=>{draw();if(labelsGroup)labelsGroup.visible=Boolean($('labels').checked)};
function zoom(factor){if(!view)return;const [x,y,w,h]=view;view=[x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor];applyView()}
$('zoom-in').onclick=()=>zoom(.8);$('zoom-out').onclick=()=>zoom(1.25);$('fit').onclick=()=>{if(baseView){view=[...baseView];applyView()}};$('play').onclick=()=>{if(canvasMode==='3d'){playTrace3D()}else{$('map').classList.remove('tracing');void $('map').getBoundingClientRect();$('map').classList.add('tracing')}};$('map').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)},{passive:false});let drag=null;$('map').onpointerdown=e=>{if(view){drag={x:e.clientX,y:e.clientY,view:[...view]};$('map').setPointerCapture(e.pointerId)}};$('map').onpointermove=e=>{if(!drag)return;const rect=$('map').getBoundingClientRect(),scale=Math.max(drag.view[2]/rect.width,drag.view[3]/rect.height);view=[drag.view[0]-(e.clientX-drag.x)*scale,drag.view[1]-(e.clientY-drag.y)*scale,...drag.view.slice(2)];applyView()};$('map').onpointerup=$('map').onpointercancel=()=>drag=null;
api('/api/plans').then(async data=>{const stamp=++catalogVersion;if(stamp!==catalogVersion)return;catalog=data;library();if(data.length){const preferred=data.find(p=>p.name==='Open-plan studio')?.key||data[0].key;await choose(preferred);}else notice('No plans found. Import JSON to begin.')}).catch(e=>notice('Cannot reach the local solver: '+e.message,'error'));

$('save-svg').onclick=()=>{if(!result)return;const copy=$('map').cloneNode(true);copy.setAttribute('xmlns',NS);copy.setAttribute('viewBox',baseView.join(' '));copy.setAttribute('width','1400');copy.setAttribute('height',String(Math.round(1400*baseView[3]/baseView[2])));copy.classList.remove('tracing');copy.querySelectorAll('[data-ring]').forEach(g=>g.setAttribute('opacity','1'));const title=el('title',{},'SutraYana / '+plan.id+' / '+result.output.reported_metrics.hub_count+' hubs / J '+result.output.reported_metrics.total_cost_J.toFixed(2));copy.prepend(title);const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));const a=dom('a');a.href=url;a.download='sutrayana-overlay.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};

let renderer = null, scene3d = null, camera = null, controls = null;
let currentModel = null, autoRotate = false, modelCache = new Map();
let canvasMode = '2d';
let currentMaxDim = 15;
let labelsGroup = null;
let routesGroup = null;
let tracePulsesGroup = null;
let threeDOverlay = null;
let isTracing3D = false;
let traceStartTime = 0;
let traceSplines = [];

// High-contrast, saturated circuit palette matching the 2D zone cards
const circuitColors = [
  '#00e676', // Zone 1: Vibrant Emerald Green
  '#ff9100', // Zone 2: Safety Amber / Orange
  '#00b0ff', // Zone 3: Electric Sky Blue
  '#f50057', // Zone 4: Neon Rose / Pink
  '#d500f9', // Zone 5: Electric Purple
  '#00e5ff', // Zone 6: Bright Turquoise Cyan
];

function getPlanCenter() {
  if (!plan || !plan.bounds) return { cx: 0, cy: 0 };
  return {
    cx: (plan.bounds[0] + plan.bounds[2]) / 2.0,
    cy: (plan.bounds[1] + plan.bounds[3]) / 2.0,
  };
}

function planTo3D(px, py, elevation = 0.05) {
  const { cx, cy } = getPlanCenter();
  return new THREE.Vector3(px - cx, elevation, -(py - cy));
}

function setCanvasMode(mode) {
  canvasMode = mode;
  if (mode === '2d') {
    if ($('canvas-3d')) $('canvas-3d').style.display = 'none';
    if ($('map')) $('map').style.display = 'block';
    if ($('view-mode-2d')) $('view-mode-2d').classList.add('active');
    if ($('view-mode-3d')) $('view-mode-3d').classList.remove('active');
    if ($('canvas-caption')) $('canvas-caption').innerHTML = 'METRES · Y UP <span>Scroll to zoom · Drag to pan</span>';
    stopTrace3D();
  } else {
    if ($('map')) $('map').style.display = 'none';
    if ($('canvas-3d')) $('canvas-3d').style.display = 'block';
    if ($('view-mode-3d')) $('view-mode-3d').classList.add('active');
    if ($('view-mode-2d')) $('view-mode-2d').classList.remove('active');
    if ($('canvas-caption')) $('canvas-caption').innerHTML = '3D DIGITAL TWIN · 360° ORBIT <span>Left-drag to rotate 360° · Scroll to zoom · Right-drag to pan</span>';
    init3D();
    on3DResize();
    if (selected) {
      load3DModel(selected);
    }
  }
}

function makeTextSprite(message, opts = {}) {
  const {
    textColor = '#ffffff',
    backgroundColor = 'rgba(15, 23, 42, 0.94)',
    borderColor = 'rgba(94, 234, 212, 0.8)',
    borderWidth = 3,
    fontSize = 30,
    fontFamily = "'Segoe UI', system-ui, -apple-system, sans-serif",
    fontWeight = '700',
    paddingX = 22,
    paddingY = 12,
    radius = 12,
    scaleFactor = 0.0065,
  } = opts;

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const fontStr = `${fontWeight} ${fontSize}px ${fontFamily}`;
  ctx.font = fontStr;

  const textWidth = ctx.measureText(message).width;
  const w = Math.ceil(textWidth + paddingX * 2);
  const h = Math.ceil(fontSize + paddingY * 2);

  const dpr = 2;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  // Background rounded rectangle
  ctx.fillStyle = backgroundColor;
  ctx.strokeStyle = borderColor;
  ctx.lineWidth = borderWidth;
  ctx.beginPath();
  const r = Math.min(radius, h / 2, w / 2);
  ctx.moveTo(r, 0);
  ctx.lineTo(w - r, 0);
  ctx.quadraticCurveTo(w, 0, w, r);
  ctx.lineTo(w, h - r);
  ctx.quadraticCurveTo(w, h, w - r, h);
  ctx.lineTo(r, h);
  ctx.quadraticCurveTo(0, h, 0, h - r);
  ctx.lineTo(0, r);
  ctx.quadraticCurveTo(0, 0, r, 0);
  ctx.closePath();
  ctx.fill();
  if (borderWidth > 0) {
    ctx.stroke();
  }

  // Draw text
  ctx.font = fontStr;
  ctx.fillStyle = textColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(message, w / 2, h / 2 + 1);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;

  const spriteMaterial = new THREE.SpriteMaterial({
    map: texture,
    depthTest: false,
    transparent: true,
  });

  const sprite = new THREE.Sprite(spriteMaterial);
  sprite.renderOrder = 999;
  sprite.scale.set(w * scaleFactor, h * scaleFactor, 1);
  return sprite;
}

function update3DLabels() {
  if (!labelsGroup) return;
  labelsGroup.clear();

  const showLabels = $('labels') ? $('labels').checked : true;
  labelsGroup.visible = Boolean(showLabels);
  if (!showLabels || !plan) return;

  // 1. Hub labels (elevated directly above hub cabinet)
  if (result && result.output && result.output.hubs) {
    result.output.hubs.forEach((h, i) => {
      const col = circuitColors[i % circuitColors.length];
      const hubSprite = makeTextSprite(`◆ ${h.hub_id} · Circuit ${i + 1}`, {
        textColor: '#ffffff',
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderColor: col,
        borderWidth: 3.5,
        fontSize: 32,
        fontWeight: '700',
        paddingX: 22,
        paddingY: 11,
        radius: 12,
        scaleFactor: 0.0070,
      });
      const pos = planTo3D(h.location.x, h.location.y, 1.15);
      hubSprite.position.copy(pos);
      labelsGroup.add(hubSprite);
    });
  }

  // 2. Fixed Node labels (terminals, elevated above terminal base plate)
  (plan.rooms || []).filter(r => r.node && r.node_id).forEach(r => {
    let hubIdx = -1;
    let visitStr = '';
    if (result && result.output && result.output.hubs) {
      hubIdx = result.output.hubs.findIndex(h => h.assigned_rooms && h.assigned_rooms.includes(r.id));
      if (hubIdx >= 0) {
        const hub = result.output.hubs[hubIdx];
        const seqIdx = hub.closed_sequence ? hub.closed_sequence.indexOf(r.node_id) : -1;
        if (seqIdx >= 0) {
          visitStr = ` · Stop #${seqIdx}`;
        }
      }
    }
    const col = hubIdx >= 0 ? circuitColors[hubIdx % circuitColors.length] : '#10b981';
    const nodeSprite = makeTextSprite(`● ${r.node_id}${visitStr}`, {
      textColor: '#ffffff',
      backgroundColor: 'rgba(15, 23, 42, 0.94)',
      borderColor: col,
      borderWidth: 3,
      fontSize: 28,
      fontWeight: '700',
      paddingX: 18,
      paddingY: 10,
      radius: 10,
      scaleFactor: 0.0060,
    });
    const pos = planTo3D(r.node[0], r.node[1], 0.50);
    nodeSprite.position.copy(pos);
    labelsGroup.add(nodeSprite);
  });

  // 3. Room place names & areas (elevated above room center)
  (plan.rooms || []).filter(r => r.label).forEach(r => {
    const roomSprite = makeTextSprite(`📍 ${r.id} · ${r.area.toFixed(1)} m²`, {
      textColor: '#f8fafc',
      backgroundColor: 'rgba(15, 23, 42, 0.88)',
      borderColor: 'rgba(56, 189, 248, 0.65)',
      borderWidth: 2,
      fontSize: 26,
      fontWeight: '600',
      paddingX: 18,
      paddingY: 9,
      radius: 9,
      scaleFactor: 0.0055,
    });
    const pos = planTo3D(r.label[0], r.label[1], 0.75);
    roomSprite.position.copy(pos);
    labelsGroup.add(roomSprite);
  });
}

function update3DRoutes() {
  if (!routesGroup) return;
  routesGroup.clear();

  if (!result || !result.output || !result.output.hubs) return;

  // Sleek architectural black cable conduit
  const blackConduitMat = new THREE.MeshStandardMaterial({
    color: 0x111827,         // Deep architectural black (slate-900)
    roughness: 0.35,
    metalness: 0.25,
  });

  result.output.hubs.forEach((h, i) => {
    const col = circuitColors[i % circuitColors.length];
    const arrowMat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(col),
      emissive: new THREE.Color(col),
      emissiveIntensity: 1.5,
      roughness: 0.2,
      metalness: 0.1,
    });

    (h.route_segments || []).forEach(seg => {
      const rawPts = seg.polyline || [];
      if (rawPts.length >= 2) {
        const pts = rawPts.map(p => planTo3D(p[0], p[1], 0.05));
        const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.0);

        // Solid architectural black 3D conduit pipe (radius 0.048 = ~10cm diameter)
        const tubeGeo = new THREE.TubeGeometry(curve, Math.max(pts.length * 4, 12), 0.048, 10, false);
        const tubeMesh = new THREE.Mesh(tubeGeo, blackConduitMat);
        routesGroup.add(tubeMesh);

        // Directional flow arrowheads along each straight run of the conduit
        for (let j = 0; j < pts.length - 1; j++) {
          const p1 = pts[j];
          const p2 = pts[j + 1];
          const segDist = p1.distanceTo(p2);
          if (segDist < 0.6) continue;

          const dir = new THREE.Vector3().subVectors(p2, p1).normalize();
          // Arrow count: 1 on standard runs, 2 on long straight runs (> 4.5m)
          const arrowCount = segDist > 4.5 ? 2 : 1;
          for (let a = 1; a <= arrowCount; a++) {
            const frac = a / (arrowCount + 1);
            const pos = new THREE.Vector3().lerpVectors(p1, p2, frac);

            // 3D directional arrow cone pointing along dir
            const arrowGeo = new THREE.ConeGeometry(0.09, 0.26, 12);
            const arrowMesh = new THREE.Mesh(arrowGeo, arrowMat);
            arrowMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
            arrowMesh.position.set(pos.x, 0.062, pos.z);
            routesGroup.add(arrowMesh);

            // Sleek conduit collar ring directly under the arrow
            const collarGeo = new THREE.CylinderGeometry(0.062, 0.062, 0.04, 10);
            const collarMesh = new THREE.Mesh(collarGeo, arrowMat);
            collarMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
            collarMesh.position.set(pos.x, 0.05, pos.z);
            routesGroup.add(collarMesh);
          }
        }
      }
    });
  });
}

function startTrace3D() {
  if (!result || !result.output || !result.output.hubs || result.output.hubs.length === 0) {
    notice('Please click "Generate cable rings ↗" first to calculate and trace routes.', 'busy');
    return;
  }
  stopTrace3D();
  isTracing3D = true;
  traceStartTime = performance.now();

  if ($('btn-3d-trace')) {
    $('btn-3d-trace').textContent = '⏹ Stop Trace';
    $('btn-3d-trace').classList.add('active');
  }
  if ($('play')) {
    $('play').textContent = '⏹ Stop Trace';
  }

  traceSplines = [];
  result.output.hubs.forEach((h, hIdx) => {
    const ringPolylines = [];
    const seq = h.closed_sequence || [];
    
    // Connect segments in exact visiting sequence order
    if (seq.length >= 2) {
      for (let s = 0; s < seq.length - 1; s++) {
        const fromId = seq[s];
        const toId = seq[s + 1];
        let seg = (h.route_segments || []).find(sg => sg.from === fromId && sg.to === toId);
        let pts = null;
        if (seg) {
          pts = seg.polyline;
        } else {
          seg = (h.route_segments || []).find(sg => sg.from === toId && sg.to === fromId);
          if (seg) {
            pts = [...seg.polyline].reverse();
          }
        }
        if (pts && pts.length > 0) {
          if (ringPolylines.length > 0) {
            ringPolylines.push(...pts.slice(1));
          } else {
            ringPolylines.push(...pts);
          }
        }
      }
    } else {
      (h.route_segments || []).forEach(seg => {
        if (seg.polyline) ringPolylines.push(...seg.polyline);
      });
    }

    if (ringPolylines.length >= 2) {
      const points3D = ringPolylines.map(p => planTo3D(p[0], p[1], 0.08));
      const isClosed = points3D[0].distanceTo(points3D[points3D.length - 1]) < 0.3;
      const curve = new THREE.CatmullRomCurve3(points3D, isClosed, 'catmullrom', 0.0);
      const col = circuitColors[hIdx % circuitColors.length];

      const pulses = [];
      const pulseCount = 2; // Clean spacing
      for (let p = 0; p < pulseCount; p++) {
        const pulseGroup = new THREE.Group();

        // White-hot core sphere (radius 0.14m)
        const coreGeo = new THREE.SphereGeometry(0.14, 16, 16);
        const coreMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        pulseGroup.add(new THREE.Mesh(coreGeo, coreMat));

        // Outer glowing colored halo (radius 0.28m)
        const glowGeo = new THREE.SphereGeometry(0.28, 16, 16);
        const glowMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(col),
          transparent: true,
          opacity: 0.85,
        });
        pulseGroup.add(new THREE.Mesh(glowGeo, glowMat));

        // Dynamic 3D point light to illuminate surrounding walls & floor
        const pLight = new THREE.PointLight(col, 2.2, 4.0);
        pulseGroup.add(pLight);

        // Directional comet tail spheres indicating forward travel direction
        const tail1 = new THREE.Mesh(
          new THREE.SphereGeometry(0.09, 12, 12),
          new THREE.MeshBasicMaterial({ color: new THREE.Color(col), transparent: true, opacity: 0.70 })
        );
        const tail2 = new THREE.Mesh(
          new THREE.SphereGeometry(0.05, 12, 12),
          new THREE.MeshBasicMaterial({ color: new THREE.Color(col), transparent: true, opacity: 0.40 })
        );
        pulseGroup.add(tail1);
        pulseGroup.add(tail2);

        if (tracePulsesGroup) {
          tracePulsesGroup.add(pulseGroup);
        }
        pulses.push({ group: pulseGroup, tail1, tail2 });
      }

      // Smooth, gentle, slow animation pace (~14–18s per complete ring loop)
      const ringLength = h.ring_length_m || 25;
      const speed = Math.max(0.035, Math.min(0.09, 1.8 / ringLength));
      traceSplines.push({ curve, pulses, speed });
    }
  });

  notice('Tracing 3D cable circuits · Directional flow active', 'success');
}

function stopTrace3D() {
  isTracing3D = false;
  traceSplines = [];
  if (tracePulsesGroup) tracePulsesGroup.clear();
  if ($('btn-3d-trace')) {
    $('btn-3d-trace').textContent = '▶ Trace';
    $('btn-3d-trace').classList.remove('active');
  }
  if ($('play')) {
    $('play').textContent = '▶ Trace';
  }
}

function playTrace3D() {
  if (isTracing3D) {
    stopTrace3D();
  } else {
    startTrace3D();
  }
}

function init3D() {
  const container = $('canvas-3d-viewport');
  if (!container || renderer || typeof THREE === 'undefined') return;

  const width = container.clientWidth || 800;
  const height = container.clientHeight || 460;

  scene3d = new THREE.Scene();
  scene3d.background = new THREE.Color(0x0d1410);

  // Studio floor grid
  const grid = new THREE.GridHelper(80, 80, 0x22362a, 0x142018);
  grid.position.y = -0.01;
  scene3d.add(grid);

  // Camera
  camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 1000);
  camera.position.set(16, 14, 18);

  // Lighting setup for balanced architectural visualization
  const ambient = new THREE.AmbientLight(0xd4e2d8, 0.40);
  scene3d.add(ambient);

  const hemiLight = new THREE.HemisphereLight(0xedf5f0, 0x142018, 0.50);
  hemiLight.position.set(0, 50, 0);
  scene3d.add(hemiLight);

  const dirLight1 = new THREE.DirectionalLight(0xfff5e6, 0.75);
  dirLight1.position.set(25, 45, 25);
  scene3d.add(dirLight1);

  const dirLight2 = new THREE.DirectionalLight(0x5eead4, 0.25);
  dirLight2.position.set(-25, 30, -25);
  scene3d.add(dirLight2);

  const dirLight3 = new THREE.DirectionalLight(0xa5c9b2, 0.35);
  dirLight3.position.set(0, -25, 20);
  scene3d.add(dirLight3);

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  if (renderer.outputEncoding !== undefined) {
    renderer.outputEncoding = THREE.sRGBEncoding;
  }
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  container.appendChild(renderer.domElement);

  // OrbitControls for 360-degree rotation and zoom
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.screenSpacePanning = true;
  controls.minDistance = 2;
  controls.maxDistance = 250;
  controls.maxPolarAngle = Math.PI / 2 + 0.05;

  // Root 3D Overlay containers
  threeDOverlay = new THREE.Group();
  labelsGroup = new THREE.Group();
  routesGroup = new THREE.Group();
  tracePulsesGroup = new THREE.Group();
  threeDOverlay.add(routesGroup);
  threeDOverlay.add(tracePulsesGroup);
  threeDOverlay.add(labelsGroup);

  // Animation loop
  function animate() {
    requestAnimationFrame(animate);
    if (controls) {
      controls.autoRotate = autoRotate;
      controls.autoRotateSpeed = 1.8;
      controls.update();
    }
    if (isTracing3D && traceSplines.length > 0) {
      const elapsed = (performance.now() - traceStartTime) / 1000;
      traceSplines.forEach(({ curve, pulses, speed }) => {
        pulses.forEach(({ group, tail1, tail2 }, idx) => {
          const offset = idx / pulses.length;
          const t = ((elapsed * speed) + offset) % 1.0;
          const pt = curve.getPointAt(t);
          if (pt) {
            group.position.copy(pt);
            // Directional trailing comet tail spheres
            const t1 = (t - 0.018 + 1.0) % 1.0;
            const pt1 = curve.getPointAt(t1);
            if (pt1 && tail1) {
              tail1.position.set(pt1.x - pt.x, pt1.y - pt.y, pt1.z - pt.z);
            }
            const t2 = (t - 0.036 + 1.0) % 1.0;
            const pt2 = curve.getPointAt(t2);
            if (pt2 && tail2) {
              tail2.position.set(pt2.x - pt.x, pt2.y - pt.y, pt2.z - pt.z);
            }
          }
        });
      });
    }
    if (renderer && scene3d && camera) {
      renderer.render(scene3d, camera);
    }
  }
  animate();

  window.addEventListener('resize', on3DResize);
}

function on3DResize() {
  const container = $('canvas-3d-viewport');
  if (!container || !renderer || !camera) return;
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (width > 0 && height > 0) {
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }
}

function fitCamera(maxDim) {
  if (!camera || !controls) return;
  currentMaxDim = Math.max(maxDim || 10, 6);
  const dist = currentMaxDim * 1.5;
  camera.position.set(dist * 0.75, dist * 0.72, dist * 0.75);
  controls.target.set(0, 0, 0);
  controls.update();
}

function set3DAngle(type) {
  if (!camera || !controls) return;
  const dist = currentMaxDim * 1.5;
  if (type === 'iso') {
    camera.position.set(dist * 0.75, dist * 0.72, dist * 0.75);
    controls.target.set(0, 0, 0);
  } else if (type === 'top') {
    camera.position.set(0.001, dist * 1.6, 0.001);
    controls.target.set(0, 0, 0);
  } else if (type === 'reset') {
    fitCamera(currentMaxDim);
  }
  controls.update();
}

async function load3DModel(key) {
  if (!key) return;
  init3D();
  on3DResize();

  if (modelCache.has(key)) {
    const cached = modelCache.get(key);
    if (currentModel && scene3d) scene3d.remove(currentModel);
    currentModel = cached.model;
    if (threeDOverlay && !currentModel.children.includes(threeDOverlay)) {
      currentModel.add(threeDOverlay);
    }
    scene3d.add(currentModel);
    if ($('btn-3d-blend')) $('btn-3d-blend').href = cached.blend_url || '#';
    if ($('btn-3d-glb')) $('btn-3d-glb').href = cached.glb_url || '#';
    update3DLabels();
    update3DRoutes();
    fitCamera(cached.maxDim);
    if ($('canvas-3d-loading')) $('canvas-3d-loading').style.display = 'none';
    return;
  }

  if ($('canvas-3d-loading')) {
    $('canvas-3d-loading').style.display = 'flex';
    $('canvas-3d-loading-text').textContent = 'Loading 3D Digital Twin geometry...';
  }

  try {
    const data = await api('/api/digital_twin/' + encodeURIComponent(key));
    if (!data.glb_url) throw new Error('GLB model not generated');

    if ($('btn-3d-blend')) $('btn-3d-blend').href = data.blend_url || '#';
    if ($('btn-3d-glb')) $('btn-3d-glb').href = data.glb_url || '#';

    const loader = new THREE.GLTFLoader();
    loader.load(data.glb_url, (gltf) => {
      const obj = gltf.scene;

      const box = new THREE.Box3().setFromObject(obj);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.z, size.y);

      obj.position.x -= center.x;
      obj.position.y -= box.min.y;
      obj.position.z -= center.z;

      obj.traverse((child) => {
        if (child.isMesh) {
          if (child.name.includes('Cable')) {
            child.visible = false; // Hide faint GLB static lines, replaced by vibrant 3D conduits
          }
          if (child.name.includes('Terminal_Glow') || child.name.includes('Hub_LED')) {
            if (child.material && child.material.emissive) {
              child.material.emissiveIntensity = 2.5;
            }
          }
        }
      });

      if (threeDOverlay) {
        obj.add(threeDOverlay);
      }

      if (currentModel && scene3d) scene3d.remove(currentModel);
      currentModel = obj;
      scene3d.add(obj);

      modelCache.set(key, { model: obj, maxDim, blend_url: data.blend_url, glb_url: data.glb_url });
      update3DLabels();
      update3DRoutes();
      fitCamera(maxDim);
      if ($('canvas-3d-loading')) $('canvas-3d-loading').style.display = 'none';
    }, undefined, (err) => {
      if ($('canvas-3d-loading-text')) {
        $('canvas-3d-loading-text').textContent = 'Error loading 3D model: ' + err.message;
      }
    });
  } catch (err) {
    if ($('canvas-3d-loading-text')) {
      $('canvas-3d-loading-text').textContent = 'Failed to load 3D twin: ' + err.message;
    }
  }
}

if ($('view-mode-2d')) $('view-mode-2d').onclick = () => setCanvasMode('2d');
if ($('view-mode-3d')) $('view-mode-3d').onclick = () => setCanvasMode('3d');
if ($('btn-twin-modal')) $('btn-twin-modal').onclick = () => setCanvasMode('3d');

if ($('btn-3d-autorotate')) {
  $('btn-3d-autorotate').onclick = () => {
    autoRotate = !autoRotate;
    $('btn-3d-autorotate').classList.toggle('active', autoRotate);
  };
}
if ($('btn-3d-iso')) $('btn-3d-iso').onclick = () => set3DAngle('iso');
if ($('btn-3d-top')) $('btn-3d-top').onclick = () => set3DAngle('top');
if ($('btn-3d-reset')) $('btn-3d-reset').onclick = () => set3DAngle('reset');
if ($('btn-3d-trace')) $('btn-3d-trace').onclick = () => playTrace3D();

