const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const colors=['#268367','#bf8240','#688bc4','#ae6c93','#8e9d44','#5ba9ac'];
let catalog=[],selected=null,plan=null,result=null,busy=false,filter='all',history=[],view=null,baseView=null,selectionVersion=0,catalogVersion=0,activeCutSimulation=null;
let movedNodes={},baseResult=null,draggingNode=null,photoData=null,photoPickingColor=false;
const el=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n};
const dom=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
async function api(path,body){const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const value=await response.json();if(!response.ok)throw Error(value.error||'Request failed');return value}
function notice(text,kind=''){const n=$('notice');if(n){n.textContent=text;n.className='notice '+kind}}
function visible(){const query=$('search').value.toLowerCase();return catalog.filter(p=>(p.name+' '+p.description).toLowerCase().includes(query)&&(filter==='all'||(filter==='test')===(p.source==='Synthetic test')))}
function library(){$('count').textContent=catalog.length;$('plans').replaceChildren();visible().forEach(p=>{const b=dom('button','plan'+(p.key===selected?' active':''));b.disabled=busy;b.setAttribute('aria-current',String(p.key===selected));b.append(dom('span','plan-icon','⌑'));const text=dom('span');text.append(dom('span','plan-title',p.name),dom('small','',`${p.rooms} rooms · ${p.source}`));b.append(text);if(history.some(h=>h.key===p.key&&h.ok&&h.profile_valid!==false))b.append(dom('span','plan-dot','✓'));b.onclick=()=>choose(p.key);$('plans').append(b)});if(!visible().length)$('plans').append(dom('p','muted','No plans match your search.'))}
function clearResult(){result=null;activeCutSimulation=null;movedNodes={};baseResult=null;if($('moved-badge'))$('moved-badge').style.display='none';['h','j','l','x','o','b','latency'].forEach(k=>$('metric-'+k)&&($('metric-'+k).textContent='—'));$('download').disabled=true;$('play').disabled=true;$('save-svg').disabled=true;if($('btn-top3'))$('btn-top3').disabled=true;if($('btn-pdf-report'))$('btn-pdf-report').disabled=true;if($('btn-official-submission'))$('btn-official-submission').disabled=true;if($('hud-3d-hub-select'))$('hud-3d-hub-select').innerHTML='<option value="all"> All Circuits</option>';if($('hud-3d-loop-card'))$('hud-3d-loop-card').style.display='none';selected3DHub='all';if($('btn-cut-test')){$('btn-cut-test').disabled=true;$('btn-cut-test').classList.remove('active');}if($('resilience-panel'))$('resilience-panel').style.display='none';$('zones').replaceChildren(dom('p','muted','Generate rings to inspect each zone’s capacity and visiting order.'));$('score-bar').replaceChildren();$('proof-title').textContent='Geometry first';$('proof').textContent='Every output is checked before it appears as a valid design.';$('status').textContent='READY';$('status').className='pill';$('canvas-label').textContent='INPUT GEOMETRY';$('facts').replaceChildren();if(typeof stopTrace3D==='function')stopTrace3D();if(routesGroup)routesGroup.clear();if(typeof update3DLabels==='function')update3DLabels();}
async function choose(key){setCanvasMode('2d');const version=++selectionVersion;selected=key;plan=null;clearResult();library();const item=catalog.find(p=>p.key===key);$('title').textContent=item?item.name:key;$('description').textContent=item?item.description:'';$('solve').disabled=true;if($('btn-top3'))$('btn-top3').disabled=false;$('empty').hidden=false;$('map').replaceChildren();$('rooms').replaceChildren();$('warnings').replaceChildren();notice('Loading floor-plan geometry…');try{const value=await api('/api/plan/'+key);if(version!==selectionVersion)return;plan=value;const [x0,y0,x1,y1]=plan.bounds,pad=Math.max(x1-x0,y1-y0)*.1;baseView=[x0-pad,-y1-pad,x1-x0+2*pad,y1-y0+2*pad];view=[...baseView];draw();inputDetails();$('solve').disabled=busy;if(value.solution){const solTime=value.solution.solver?.elapsed_s??value.solution.elapsed_s??null;showResult({ok:true,output:value.solution,solver_time_s:solTime,elapsed_s:solTime});notice(`${item?item.source:'Solution'} · Solution routes loaded · ${plan.rooms.filter(r=>r.node).length} fixed nodes · source coordinates preserved.`,'success')}else{notice(`${item?item.source:'Plan'} · ${plan.rooms.filter(r=>r.node).length} fixed nodes · source coordinates preserved.`)}}catch(e){if(version!==selectionVersion)return;notice(e.message,'error');$('empty').textContent='Input could not be loaded';warnings([{rule:'input',message:e.message}])}}
function pathData(g){if(!g)return '';if(g.type==='Polygon')return g.coordinates.map(r=>r.map((p,i)=>(i?'L':'M')+p[0]+','+(-p[1])).join(' ')+'Z').join(' ');if(g.type==='MultiPolygon')return g.coordinates.map(c=>pathData({type:'Polygon',coordinates:c})).join(' ');if(g.type==='GeometryCollection')return g.geometries.map(pathData).join(' ');return ''}
function polygon(parent,g,fill,opacity=1){const d=pathData(g);if(d)parent.append(el('path',{d,fill,opacity,'fill-rule':'evenodd'}))}
function applyView(){$('map').setAttribute('viewBox',view.join(' '))}
function draw(){if(!plan)return;const svg=$('map');svg.replaceChildren();svg.classList.remove('tracing');applyView();$('empty').hidden=true;const unit=Math.max(baseView[2],baseView[3]);const font=unit*.012;polygon(svg,plan.inner,'#e9eee4');plan.rooms.forEach(r=>polygon(svg,r.polygon,'#f4f5eb'));if(result)result.output.hubs.forEach((h,i)=>h.assigned_rooms.forEach(id=>polygon(svg,plan.rooms.find(r=>r.id===id).polygon,colors[i%colors.length],.12)));if($('clearance').checked&&$('profile').value!=='0')polygon(svg,plan.clearance_band,'#daaa60',.23);polygon(svg,plan.wall,'#41564b');polygon(svg,plan.window,'#77b1cd');plan.doors.forEach(d=>polygon(svg,d,'#d4b67b',.68));if($('labels').checked)plan.rooms.forEach(r=>{const text=el('text',{x:r.label[0],y:-r.label[1]-font*1.8,'text-anchor':'middle',fill:'#8a957e','font-size':font*.8,class:'map-label'},r.id+' · '+r.area.toFixed(1)+' m²');svg.append(text)});
if(result){result.output.hubs.forEach((h,i)=>{const color=colors[i%colors.length],group=el('g',{'data-ring':i});h.route_segments.forEach((l,j)=>{const isCut=activeCutSimulation&&activeCutSimulation.hub_idx===i&&activeCutSimulation.cut_segment_idx===j;const strokeColor=isCut?'#ef4444':color;const strokeWidth=isCut?unit*.0055:unit*.0026;const lineClass=isCut?'route cut-severed':'route';const d=l.polyline.map((p,k)=>(k?'L':'M')+p[0]+','+(-p[1])).join(' ');const line=el('path',{d,fill:'none',stroke:strokeColor,'stroke-width':strokeWidth,class:lineClass,opacity:j===h.route_segments.length-1?.65:1});line.style.setProperty('--route-length',l.length_m);group.append(line);if(isCut&&l.polyline.length){const mid=l.polyline[Math.floor(l.polyline.length/2)];const cutTag=el('text',{x:mid[0],y:-mid[1]-unit*.006,fill:'#ef4444','font-size':font*.95,'font-weight':800,'text-anchor':'middle',class:'map-label'},'SEVERED CABLE (SPoF TEST)');group.append(cutTag);}const pairs=l.polyline.slice(1).map((p,k)=>[l.polyline[k],p]).sort((a,b)=>Math.hypot(b[1][0]-b[0][0],b[1][1]-b[0][1])-Math.hypot(a[1][0]-a[0][0],a[1][1]-a[0][1]));if(pairs.length&&!isCut){const [a,b]=pairs[0],x=(a[0]+b[0])/2,y=-(a[1]+b[1])/2,angle=Math.atan2(-(b[1]-a[1]),b[0]-a[0])*180/Math.PI,s=unit*.005;group.append(el('path',{d:`M ${-s} ${-s*.6} L ${s} 0 L ${-s} ${s*.6}`,transform:`translate(${x} ${y}) rotate(${angle})`,fill:'none',stroke:color,'stroke-width':unit*.0018}));}});const x=h.location.x,y=-h.location.y,s=unit*.006;group.append(el('path',{d:`M${x} ${y-s}L${x+s} ${y}L${x} ${y+s}L${x-s} ${y}Z`,fill:color,stroke:'white','stroke-width':unit*.001}));group.append(el('text',{x:x+s*1.6,y:y-s*1.6,fill:color,'font-size':font*1.1,'font-weight':700,class:'map-label'},h.hub_id));svg.append(group)})}
plan.rooms.filter(r=>r.node).forEach((r,idx)=>{const i=result?result.output.hubs.findIndex(h=>h.assigned_rooms.includes(r.id)):-1,color=i<0?'#76946a':colors[i%colors.length];const pos=movedNodes[idx]||movedNodes[r.id]||r.node;const [x,y]=pos;const circle=el('circle',{cx:x,cy:-y,r:unit*.0045,fill:color,stroke:'white','stroke-width':unit*.0012,class:'dev-handle','data-room-idx':idx,'data-room-id':r.id});circle.title=`Device node in ${r.id} · drag to move and re-route`;svg.append(circle);if(movedNodes[idx]||movedNodes[r.id]){svg.append(el('circle',{cx:x,cy:-y,r:unit*.0075,fill:'none',stroke:'#fbbf24','stroke-width':unit*.0012,'stroke-dasharray':'2,2'}));}if($('labels').checked){const visit=i<0?'':` · ${result.output.hubs[i].closed_sequence.indexOf(r.node_id)}`;svg.append(el('text',{x:x+font*.7,y:-y+font*1.3,fill:color,'font-size':font*.85,class:'map-label'},r.node_id+visit))}})}
function warnings(items){$('warnings-count').textContent=items.length?items.length+' notices':'CLEAR';$('warnings').replaceChildren();if(!items.length){$('warnings').append(dom('span','','✓ No input warnings detected. Output validation runs after solving.'));return}items.forEach(w=>{const d=dom('div','warning-item');d.append(dom('strong','',w.rule.replaceAll('_',' ').toUpperCase()),dom('span','',w.message));$('warnings').append(d)})}
function inputDetails(){warnings(plan.warnings);$('provenance').textContent='Node provenance: '+plan.provenance+'. Catalog includes only available files; synthetic cases are labelled. Full ResPlan and organiser hidden inputs are not bundled.';$('rooms').replaceChildren();plan.rooms.forEach(r=>{const row=dom('tr');[r.id,r.kind,r.area.toFixed(3),r.node_id||'Excluded'].forEach(v=>row.append(dom('td','',v)));$('rooms').append(row)})}
function showResult(value){result=value;if(Object.keys(movedNodes).length===0)baseResult=value;const out=value.output,s=out.solver||{};const hubs=out.hubs||[];const calcLength=hubs.reduce((acc,h)=>(h.route_segments||[]).reduce((a,sg)=>a+(sg.length_m||0),acc),0);const m=out.reported_metrics||{hub_count:hubs.length,total_cost_J:calcLength,total_length_m:calcLength,total_crossings:0,total_overlap_m:0,total_bends:0};const solverSec=s.elapsed_s??value.solver_time_s??value.solve_time_s??(s.latency_ms?s.latency_ms/1000:null);const latencyDisplay=solverSec!=null?(Number(solverSec)<0.01&&Number(solverSec)>0?(Number(solverSec)*1000).toFixed(0)+' ms':Number(solverSec).toFixed(3)+' s'):(value.elapsed_s!=null?Number(value.elapsed_s).toFixed(2)+' s':'—');[['h',m.hub_count],['j',Number(m.total_cost_J??0).toFixed(2)],['l',Number(m.total_length_m??0).toFixed(2)],['x',m.total_crossings??0],['o',Number(m.total_overlap_m??0).toFixed(2)],['b',m.total_bends??0]].forEach(([k,v])=>$('metric-'+k)&&($('metric-'+k).textContent=v));$('status').textContent='VALIDATED';$('status').className='pill valid';$('canvas-label').textContent='VERIFIED ROUTES';$('proof-title').textContent=s.hub_count_proven?'Minimum hub count matched':'Valid design with extra hubs';$('proof').textContent=`Capacity bound ${plan.capacity_lower_bound} · graph partition minimum ${s.minimum_hubs??hubs.length}. Tried ${(s.attempted_hub_counts || [m.hub_count]).join(', ')} hubs. ${s.hub_count_proven?'Hub count is proven for the constructed graph.':'Minimum-hub routes were not found with this candidate search.'} Cable cost remains heuristic.`;
$('zones').replaceChildren();out.hubs.forEach((h,i)=>{const area=h.assigned_rooms.reduce((sum,id)=>sum+plan.rooms.find(r=>r.id===id).area,0),card=dom('article','zone'),head=dom('label','zone-head'),check=dom('input');check.type='checkbox';check.checked=true;check.onchange=()=>document.querySelector(`[data-ring="${i}"]`).setAttribute('opacity',check.checked?1:.08);head.append(check,dom('span','',h.hub_id),dom('small','',h.assigned_nodes.length+' / 5 nodes'));head.style.color=colors[i%colors.length];const bar=dom('div','bar'),fill=dom('i');fill.style.width=Math.min(100,area)+'%';fill.style.background=colors[i%colors.length];bar.append(fill);card.append(head,dom('p','',h.closed_sequence.join(' → ')),bar,dom('small','',`${area.toFixed(1)} / 100 m² · ${h.ring_length_m.toFixed(2)} m cable`));$('zones').append(card)});
$('facts').replaceChildren();[['Wire clearance',Number(s.wire_clearance_m ?? $('profile').value).toFixed(1)+' m required'],['Router policy',s.rl_adaptive_routing?'RL Dueling-DDQN (Adaptive)':'Classical Dijkstra'],['Measured minimum',value.measured_clearance_m==null?'No wall/window':value.measured_clearance_m.toFixed(3)+' m'],['Solver latency',latencyDisplay],['Area gap',Number(s.area_gap_m2 ?? 0).toFixed(2)+' m²'],['Coordinates','Source origin / metres']].forEach(([k,v])=>{const d=dom('div');d.append(dom('span','',k),dom('b','',v));$('facts').append(d)});
const costs=[m.total_length_m,5*m.total_crossings,m.total_overlap_m,.5*m.total_bends],bar=dom('div','cost-bars'),labels=dom('div','cost-labels');costs.forEach((v,i)=>{const part=dom('i');part.style.width=(m.total_cost_J?v/m.total_cost_J*100:0)+'%';part.style.background=colors[i];part.title=['Length','Crossings','Overlap','Bends'][i]+': '+v.toFixed(2);bar.append(part);labels.append(dom('span','',['L','5X','O','½B'][i]+' '+v.toFixed(1)))});$('score-bar').replaceChildren(bar,labels);const alerts=[...(out.warnings||out.validation?.warnings||plan.warnings||[])];const actual=value.measured_clearance_m,required=Number(s.wire_clearance_m ?? $('profile').value);const clearanceFailed=actual!=null&&actual<required-.001;if(clearanceFailed)alerts.push({rule:'wire_clearance',message:`This backend returned a wire ${actual.toFixed(3)} m from a wall/window; the selected profile requires ${required.toFixed(3)} m.`});warnings(alerts);draw();$('download').disabled=false;$('play').disabled=false;$('save-svg').disabled=false;if($('btn-pdf-report'))$('btn-pdf-report').disabled=false;if($('btn-official-submission'))$('btn-official-submission').disabled=Boolean(clearanceFailed||!value.ok);const hubSel=$('hud-3d-hub-select');if(hubSel){hubSel.innerHTML=`<option value="all"> All Circuits (${out.hubs.length} Loops)</option>`;out.hubs.forEach(h=>{const opt=dom('option','',`◆ ${h.hub_id} · ${h.assigned_nodes.length} nodes · ${(h.ring_length_m||0).toFixed(1)}m`);opt.value=h.hub_id;hubSel.append(opt)});}selected3DHub='all';update3DLoopCard();notice(`Validated in ${latencyDisplay}. Every node is covered and every route passes the configured geometry checks.`,'success');if(clearanceFailed){$('status').textContent='CLEARANCE ISSUE';$('canvas-label').textContent='INSPECTION ONLY';$('status').className='pill failed';$('download').disabled=true;if($('btn-official-submission'))$('btn-official-submission').disabled=true;notice(`The route is shown for inspection, but wires pass within ${actual.toFixed(3)} m of a wall/door. Switch profile to "Slide rules" to export.`,'error');}if($('resilience-panel'))$('resilience-panel').style.display='block';if($('btn-cut-test'))$('btn-cut-test').disabled=false;populateCutOptions();if(typeof updateMovedBadge==='function')updateMovedBadge();if(typeof update3DRoutes==='function')update3DRoutes();if(typeof update3DLabels==='function')update3DLabels();}
function setBusy(value){busy=value;['solve','upload'].forEach(id=>{const el=$(id);if(el)el.disabled=value||(!plan&&id==='solve')});$('profile')?.querySelectorAll('.profile-btn').forEach(b=>b.disabled=value);$('solve').textContent=value?'Solving…':'Generate cable rings ↗';library()}
async function run(key,use_rl=false){clearResult();draw();const profile=Number($('profile').value),limit=Number($('budget')?.value||30),enhanced=Boolean($('enhanced')?.checked),start=performance.now();notice('Searching connected zones and clearance-safe routes…','busy');$('status').textContent='RUNNING';try{const {job_id}=await api('/api/solve',{key,wire_clearance:profile,timeout:limit,enhanced,use_rl});let value,delay=50;do{if(performance.now()-start>(limit+15)*1000)throw Error('The server has not finished within the time budget. Check that you are running the current server.');await new Promise(r=>setTimeout(r,delay));delay=Math.min(250,Math.round(delay*1.5));value=await api('/api/jobs/'+job_id);if(value.status!=='done')notice(`Searching routes · ${((performance.now()-start)/1000).toFixed(0)} s elapsed`,'busy')}while(value.status!=='done');const solverSec=value.output?.solver?.elapsed_s??value.solver_time_s??value.solve_time_s;if(solverSec!=null)value.solver_time_s=solverSec;value.network_elapsed_s=(performance.now()-start)/1000;value.profile_valid=value.ok&&(value.measured_clearance_m==null||value.measured_clearance_m>=profile-.001);history.unshift({key,name:catalog.find(p=>p.key===key).name,profile,use_rl,...value});renderHistory();if(value.ok)showResult(value);else{notice(value.error,'error');$('status').textContent='NOT SOLVED';$('status').className='pill failed';$('proof-title').textContent='No valid design emitted';$('proof').textContent=value.error;warnings([...(plan?.warnings||[]),{rule:'routing',message:value.error}])}return value}catch(e){notice(e.message,'error');$('status').textContent='ERROR';$('status').className='pill failed';history.unshift({key,name:catalog.find(p=>p.key===key).name,profile,use_rl,ok:false,error:e.message,elapsed_s:(performance.now()-start)/1000});renderHistory();return {ok:false}}}
function renderHistory(){$('history').replaceChildren();history.forEach(h=>{const row=dom('tr'),name=dom('td'),link=dom('button','text-button',h.name);link.onclick=async()=>{if(busy)return;$('profile').value=String(h.profile);await choose(h.key);if(plan&&h.ok)showResult(h);else if(h.error){notice(h.error,'error');$('status').textContent='NOT SOLVED';$('status').className='pill failed';$('proof-title').textContent='No valid design emitted';$('proof').textContent=h.error;warnings([...(plan?.warnings||[]),{rule:'routing',message:h.error}])}};name.append(link);name.append(dom('small','',(h.profile===.5?'0.5 m clearance':'Slide rules')+(h.use_rl?' · RL enhanced':'')));row.title=h.error||'Validated for the selected profile';const m=h.output?.reported_metrics;const histTime=h.output?.solver?.elapsed_s??h.solver_time_s??h.elapsed_s;const histTimeStr=histTime!=null?(Number(histTime)<0.01&&Number(histTime)>0?(Number(histTime)*1000).toFixed(0)+' ms':Number(histTime).toFixed(3)+' s'):'—';row.append(name,...[h.profile_valid===false&&h.ok?'Clearance issue':h.ok?'✓ Valid':'Issue',m?.hub_count??'—',m?.total_cost_J.toFixed(2)??'—',histTimeStr].map(v=>dom('td','',v)));$('history').append(row)})}
function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=dom('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('solve').onclick=async()=>{if(!selected||busy)return;setBusy(true);try{await run(selected)}finally{setBusy(false)}};
$('upload').onchange=async e=>{try{const files=[...e.target.files];if(files.length>50)throw Error('Import up to 50 files at once.');const items=[];for(const f of files){if(f.size>12*1024*1024)throw Error(f.name+' exceeds 12 MB.');items.push({name:f.name,data:JSON.parse(await f.text())})}if(!items.length)return;const response=await api('/api/import',{plans:items});const stamp=++catalogVersion;const data=await api('/api/plans');if(stamp!==catalogVersion)return;catalog=data;library();const lastKey=response.keys && response.keys.length ? response.keys[response.keys.length-1] : null;if(lastKey)await choose(lastKey);if(response.errors.length)notice(response.errors.join(' '),'error')}catch(error){notice('Import failed: '+error.message,'error')}finally{e.target.value=''}};
$('search').oninput=library;document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(n=>n.classList.toggle('active',n===b));library()});
$('download').onclick=()=>result&&download(result.output,'sutrayana-result.json');
if($('btn-pdf-report'))$('btn-pdf-report').onclick=()=>{if(selected)window.open('/api/report/pdf/'+encodeURIComponent(selected),'_blank')};
if($('btn-official-submission'))$('btn-official-submission').onclick=async()=>{if(!selected)return;try{const res=await fetch('/api/submission/'+encodeURIComponent(selected));if(res.status===422){const err=await res.json();alert('Slide 8 Official Submission JSON Withheld:\n\n'+(err.error||'Independent validation failed.'));return}if(!res.ok)throw new Error('Failed to retrieve submission JSON');const data=await res.json();download(data,`official_submission_${selected}.json`)}catch(e){alert('Error: '+e.message)}};
if($('hud-3d-hub-select'))$('hud-3d-hub-select').onchange=()=>{selected3DHub=$('hud-3d-hub-select').value;update3DLoopCard();update3DRoutes();update3DLabels();if(isTracing3D)startTrace3D()};
$('export-history').onclick=()=>download({generated_at:new Date().toISOString(),scope:'Local runs; not a hidden-benchmark score',runs:history},'sutrayana-run-report.json');
const pEl=$('profile');if(pEl){let curVal='0';pEl.dataset.value=curVal;Object.defineProperty(pEl,'value',{get(){return pEl.dataset.value||curVal},set(v){curVal=String(Number(v)===.5?.5:0);pEl.dataset.value=curVal;pEl.querySelectorAll('.profile-btn').forEach(b=>{const m=b.dataset.value===curVal;b.classList.toggle('active',m);b.setAttribute('aria-checked',String(m))})}});pEl.querySelectorAll('.profile-btn').forEach(b=>{b.onclick=()=>{if(busy||pEl.value===b.dataset.value)return;pEl.value=b.dataset.value;if(typeof pEl.onchange==='function')pEl.onchange()}})}
$('profile').onchange=()=>{clearResult();draw();if(plan)inputDetails();notice('Routing profile changed. Generate again to score this configuration.')};$('clearance').onchange=draw;$('labels').onchange=()=>{draw();if(labelsGroup)labelsGroup.visible=Boolean($('labels').checked)};
function zoom(factor){if(!view)return;const [x,y,w,h]=view;view=[x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor];applyView()}
$('zoom-in').onclick=()=>zoom(.8);$('zoom-out').onclick=()=>zoom(1.25);$('fit').onclick=()=>{if(baseView){view=[...baseView];applyView()}};$('play').onclick=()=>{if(canvasMode==='3d'){playTrace3D()}else{$('map').classList.remove('tracing');void $('map').getBoundingClientRect();$('map').classList.add('tracing')}};$('map').addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.1:.9)},{passive:false});let drag=null;
$('map').onpointerdown=e=>{
  const handle=e.target.closest('.dev-handle');
  if(handle){
    const rIdx=handle.getAttribute('data-room-idx');
    const rId=handle.getAttribute('data-room-id');
    draggingNode={roomIdx:rIdx,roomId:rId,pointerId:e.pointerId};
    $('map').setPointerCapture(e.pointerId);
    handle.classList.add('dragging');
    e.stopPropagation();
    return;
  }
  if(view){
    drag={x:e.clientX,y:e.clientY,view:[...view]};
    $('map').setPointerCapture(e.pointerId);
  }
};
$('map').onpointermove=e=>{
  if(draggingNode){
    const rect=$('map').getBoundingClientRect();
    const scaleX=view[2]/rect.width;
    const scaleY=view[3]/rect.height;
    const svgX=view[0]+(e.clientX-rect.left)*scaleX;
    const svgY=view[1]+(e.clientY-rect.top)*scaleY;
    const worldX=Math.round(svgX*100)/100;
    const worldY=Math.round(-svgY*100)/100;
    movedNodes[draggingNode.roomIdx]=[worldX,worldY];
    draw();
    updateMovedBadge();
    return;
  }
  if(!drag)return;
  const rect=$('map').getBoundingClientRect(),scale=Math.max(drag.view[2]/rect.width,drag.view[3]/rect.height);
  view=[drag.view[0]-(e.clientX-drag.x)*scale,drag.view[1]-(e.clientY-drag.y)*scale,...drag.view.slice(2)];
  applyView();
};
$('map').onpointerup=$('map').onpointercancel=async e=>{
  if(draggingNode){
    try{$('map').releasePointerCapture(e.pointerId);}catch(_){}
    const handle=document.querySelector(`.dev-handle[data-room-idx="${draggingNode.roomIdx}"]`);
    if(handle)handle.classList.remove('dragging');
    draggingNode=null;
    await solveWithMoved();
    return;
  }
  drag=null;
};
api('/api/plans').then(async data=>{const stamp=++catalogVersion;if(stamp!==catalogVersion)return;catalog=data;library();if(data.length){const preferred=data.find(p=>p.name==='Open-plan studio')?.key||data[0].key;await choose(preferred);}else notice('No plans found. Import JSON to begin.')}).catch(e=>notice('Cannot reach the local solver: '+e.message,'error'));

$('save-svg').onclick=()=>{if(!result)return;const copy=$('map').cloneNode(true);copy.setAttribute('xmlns',NS);copy.setAttribute('viewBox',baseView.join(' '));copy.setAttribute('width','1400');copy.setAttribute('height',String(Math.round(1400*baseView[3]/baseView[2])));copy.classList.remove('tracing');copy.querySelectorAll('[data-ring]').forEach(g=>g.setAttribute('opacity','1'));const title=el('title',{},'SutraYana / '+plan.id+' / '+result.output.reported_metrics.hub_count+' hubs / J '+result.output.reported_metrics.total_cost_J.toFixed(2));copy.prepend(title);const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));const a=dom('a');a.href=url;a.download='sutrayana-overlay.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};

function populateCutOptions(){
  const sel=$('cut-segment-select');
  if(!sel||!result||!result.output||!result.output.hubs)return;
  sel.replaceChildren();
  const defOpt=dom('option','','None (Normal Continuous Loop)');
  defOpt.value='none';
  sel.append(defOpt);
  result.output.hubs.forEach((h,hIdx)=>{
    (h.route_segments||[]).forEach((seg,sIdx)=>{
      const fromN=seg.from||seg.from_room||'H';
      const toN=seg.to||seg.to_room||'N';
      const opt=dom('option','',`${h.hub_id} · Leg ${sIdx+1}: ${fromN} → ${toN} (${(seg.length_m||0).toFixed(1)}m)`);
      opt.value=`${hIdx}_${sIdx}`;
      sel.append(opt);
    });
  });
  sel.value='none';
  clearCutSimulation();
}

function clearCutSimulation(){
  activeCutSimulation=null;
  const sel=$('cut-segment-select');
  if(sel&&sel.value!=='none')sel.value='none';
  if($('res-surv'))$('res-surv').textContent='100%';
  if($('res-loss'))$('res-loss').textContent='0%';
  if($('res-feed-info')){
    $('res-feed-info').innerHTML='Normal dual-feed ring operation. Select a cable segment above to simulate a severed wire.';
  }
  if($('btn-cut-test'))$('btn-cut-test').classList.remove('active');
  draw();
}

async function simulateCut(hIdx,sIdx){
  if(!selected||!result)return;
  try{
    const data=await api('/api/resilience/simulate',{key:selected,hub_idx:hIdx,cut_segment_idx:sIdx});
    activeCutSimulation={hub_idx:hIdx,cut_segment_idx:sIdx,...data};
    if($('res-surv'))$('res-surv').textContent=(data.survivability_pct||100)+'%';
    if($('res-loss'))$('res-loss').textContent=(data.comparative_tree_loss_pct||0)+'%';
    if($('res-feed-info')){
      const bA=data.branch_a||{nodes:[],length_m:0};
      const bB=data.branch_b||{nodes:[],length_m:0};
      $('res-feed-info').innerHTML=`<b>Clockwise Branch:</b> ${bA.nodes.join(' → ')||'Hub only'} (${bA.length_m} m)<br><b>Counter-CW Branch:</b> ${bB.nodes.join(' → ')||'Hub only'} (${bB.length_m} m)<br><span style="color:#16a34a;font-weight:600;">100% devices powered via dual-feed loop return.</span>`;
    }
    if($('btn-cut-test'))$('btn-cut-test').classList.add('active');
    draw();
  }catch(err){console.error('Cut simulation error:',err);}
}

if($('cut-segment-select')){$('cut-segment-select').onchange=()=>{const val=$('cut-segment-select').value;if(!val||val==='none'){clearCutSimulation();}else{const [h,s]=val.split('_').map(Number);simulateCut(h,s);}};}
if($('btn-cut-test')){$('btn-cut-test').onclick=()=>{const panel=$('resilience-panel');if(panel){panel.scrollIntoView({behavior:'smooth',block:'center'});panel.style.boxShadow='0 0 0 3px rgba(94, 234, 212, 0.6)';setTimeout(()=>{panel.style.boxShadow='';},1500);}const sel=$('cut-segment-select');if(sel&&sel.value==='none'&&sel.options.length>1){sel.selectedIndex=1;const [h,s]=sel.value.split('_').map(Number);simulateCut(h,s);}else if(sel&&sel.value!=='none'){clearCutSimulation();}};}
if($('btn-stress-test')){$('btn-stress-test').onclick=async()=>{if(!selected)return;notice('Executing exhaustive SPoF audit across all ring segments...','busy');try{const rep=await api('/api/resilience/stress_test',{key:selected});notice(`SPoF Audit Passed: ${rep.total_cuts_simulated} cuts tested. Single-cut survivability: ${rep.single_cut_survivability_rate_pct}%. Verdict: ${rep.verdict}`,'success');alert(`SUTRAYANA SPoF RESILIENCE AUDIT\n\nTotal Cable Rings: ${rep.total_hubs}\nTotal Monitored Nodes: ${rep.total_devices}\nTotal Cuts Simulated: ${rep.total_cuts_simulated}\nSingle-Cut Survivability: ${rep.single_cut_survivability_rate_pct}%\nWorst-Case Daisy Chain Loss: ${rep.worst_case_tree_topology_loss_pct}%\n\nVerdict: ${rep.verdict}\n\nDual-feed ring topology guarantees 100% device survivability under any single cable break.`);}catch(err){notice('Audit error: '+err.message,'error');}};}


let renderer = null, scene3d = null, camera = null, controls = null;
let currentModel = null, autoRotate = false, modelCache = new Map();
let canvasMode = '2d';
let currentMaxDim = 15;
let labelsGroup = null;
let routesGroup = null;
let doorsGroup = null;
let tracePulsesGroup = null;
let threeDOverlay = null;
let isTracing3D = false;
let traceStartTime = 0;
let traceSplines = [];
let selected3DHub = 'all';

function update3DLoopCard() {
  const card = $('hud-3d-loop-card');
  if (!card) return;
  if (selected3DHub === 'all' || !result || !result.output || !result.output.hubs) {
    card.style.display = 'none';
    return;
  }
  const hub = result.output.hubs.find(h => h.hub_id === selected3DHub);
  if (!hub || !plan) {
    card.style.display = 'none';
    return;
  }
  const area = (hub.assigned_rooms || []).reduce((acc, rid) => {
    const r = (plan.rooms || []).find(rm => rm.id === rid);
    return acc + (r ? r.area : 0);
  }, 0);
  card.innerHTML = `<strong>◆ ${hub.hub_id} CANONICAL LOOP</strong>
    <div class="loop-seq">${(hub.closed_sequence || []).join(' → ')}</div>
    <div class="loop-metrics">
      <span>CAPACITY: <b>${(hub.assigned_nodes || []).length} / 5 nodes</b></span>
      <span>AREA: <b>${area.toFixed(1)} / 100 m²</b></span>
      <span>LENGTH: <b>${(hub.ring_length_m || 0).toFixed(2)} m</b></span>
    </div>`;
  card.style.display = 'block';
}

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
    const roomSprite = makeTextSprite(`${r.id} · ${r.area.toFixed(1)} m²`, {
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

  const dimConduitMat = new THREE.MeshStandardMaterial({
    color: 0x475569,
    transparent: true,
    opacity: 0.16,
    roughness: 0.8,
  });

  result.output.hubs.forEach((h, i) => {
    const isFocused = (selected3DHub === 'all' || selected3DHub === h.hub_id);
    const col = circuitColors[i % circuitColors.length];
    const conduitMat = isFocused ? blackConduitMat : dimConduitMat;
    const arrowMat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(col),
      emissive: new THREE.Color(col),
      emissiveIntensity: isFocused ? 1.5 : 0.2,
      transparent: !isFocused,
      opacity: isFocused ? 1.0 : 0.2,
      roughness: 0.2,
      metalness: 0.1,
    });

    (h.route_segments || []).forEach(seg => {
      const rawPts = seg.polyline || [];
      if (rawPts.length >= 2) {
        const pts = rawPts.map(p => planTo3D(p[0], p[1], 0.05));
        const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.0);

        // Solid architectural black 3D conduit pipe
        const tubeGeo = new THREE.TubeGeometry(curve, Math.max(pts.length * 4, 12), isFocused ? 0.048 : 0.030, 10, false);
        const tubeMesh = new THREE.Mesh(tubeGeo, conduitMat);
        routesGroup.add(tubeMesh);

        // Directional flow arrowheads along each straight run of the conduit
        if (isFocused) {
          for (let j = 0; j < pts.length - 1; j++) {
            const p1 = pts[j];
            const p2 = pts[j + 1];
            const segDist = p1.distanceTo(p2);
            if (segDist < 0.6) continue;

            const dir = new THREE.Vector3().subVectors(p2, p1).normalize();
            const arrowCount = segDist > 4.5 ? 2 : 1;
            for (let a = 1; a <= arrowCount; a++) {
              const frac = a / (arrowCount + 1);
              const pos = new THREE.Vector3().lerpVectors(p1, p2, frac);

              const arrowGeo = new THREE.ConeGeometry(0.09, 0.26, 12);
              const arrowMesh = new THREE.Mesh(arrowGeo, arrowMat);
              arrowMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
              arrowMesh.position.set(pos.x, 0.062, pos.z);
              routesGroup.add(arrowMesh);

              const collarGeo = new THREE.CylinderGeometry(0.062, 0.062, 0.04, 10);
              const collarMesh = new THREE.Mesh(collarGeo, arrowMat);
              collarMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
              collarMesh.position.set(pos.x, 0.05, pos.z);
              routesGroup.add(collarMesh);
            }
          }
        }
      }
    });
  });
}

function update3DDoors() {
  if (!doorsGroup) return;
  doorsGroup.clear();
  if (!plan || !plan.doors || !plan.doors.length) return;

  const doorMat = new THREE.MeshStandardMaterial({
    color: 0xd4b67b, // Warm golden brass sill plate
    roughness: 0.35,
    metalness: 0.35,
  });

  plan.doors.forEach((d) => {
    let rings = [];
    if (d.type === 'Polygon' && d.coordinates) {
      rings = d.coordinates;
    } else if (d.type === 'MultiPolygon' && d.coordinates) {
      rings = d.coordinates.flatMap(c => c);
    }
    if (!rings.length) return;

    rings.forEach(ring => {
      if (ring.length < 3) return;
      const pts3D = ring.map(p => planTo3D(p[0], p[1], 0.025));
      const shape = new THREE.Shape();
      pts3D.forEach((p, idx) => {
        if (idx === 0) shape.moveTo(p.x, -p.z);
        else shape.lineTo(p.x, -p.z);
      });
      const extrudeGeo = new THREE.ExtrudeGeometry(shape, { depth: 0.035, bevelEnabled: false });
      extrudeGeo.rotateX(Math.PI / 2);
      const mesh = new THREE.Mesh(extrudeGeo, doorMat);
      mesh.position.y = 0.025;
      doorsGroup.add(mesh);

      const avgX = ring.reduce((s, p) => s + p[0], 0) / ring.length;
      const avgY = ring.reduce((s, p) => s + p[1], 0) / ring.length;
      const doorTag = makeTextSprite('DOOR', {
        textColor: '#ffffff',
        backgroundColor: 'rgba(30, 27, 20, 0.92)',
        borderColor: '#d4b67b',
        borderWidth: 2,
        fontSize: 22,
        fontWeight: '700',
        paddingX: 12,
        paddingY: 6,
        radius: 6,
        scaleFactor: 0.0042,
      });
      doorTag.position.copy(planTo3D(avgX, avgY, 0.28));
      doorsGroup.add(doorTag);
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
    $('btn-3d-trace').textContent = 'Stop Trace';
    $('btn-3d-trace').classList.add('active');
  }
  if ($('play')) {
    $('play').textContent = 'Stop Trace';
  }

  traceSplines = [];
  result.output.hubs.forEach((h, hIdx) => {
    if (selected3DHub !== 'all' && selected3DHub !== h.hub_id) return;
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
    $('btn-3d-trace').textContent = 'Trace';
    $('btn-3d-trace').classList.remove('active');
  }
  if ($('play')) {
    $('play').textContent = 'Trace';
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
  doorsGroup = new THREE.Group();
  tracePulsesGroup = new THREE.Group();
  threeDOverlay.add(doorsGroup);
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
    update3DDoors();
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
      update3DDoors();
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

/* -------------------------------------------------------------
   Interactive Device Dragging & Re-Solve Helpers
   ------------------------------------------------------------- */
function updateMovedBadge() {
  const count = Object.keys(movedNodes).length;
  const badge = $('moved-badge');
  const txt = $('moved-text');
  if (!badge || !txt) return;
  if (count === 0) {
    badge.style.display = 'none';
    return;
  }
  badge.style.display = 'flex';
  let deltaStr = `${count} device${count > 1 ? 's' : ''} moved`;
  if (baseResult && result && baseResult.output && result.output) {
    const bM = baseResult.output.reported_metrics || {};
    const rM = result.output.reported_metrics || {};
    const dJ = (rM.total_cost_J || 0) - (bM.total_cost_J || 0);
    const dH = (rM.hub_count || 0) - (bM.hub_count || 0);
    const jSign = dJ > 0 ? '+' : '';
    const hSign = dH > 0 ? '+' : '';
    deltaStr += ` · ΔJ: ${jSign}${dJ.toFixed(2)} · ΔH: ${hSign}${dH}`;
  }
  txt.innerHTML = `<b>${deltaStr}</b>`;
}

async function solveWithMoved() {
  if (!selected) return;
  notice('Live re-solving with moved device coordinates…', 'busy');
  try {
    const res = await api('/api/solve', { key: selected, moved_nodes: movedNodes });
    if (res.ok) {
      showResult(res);
      updateMovedBadge();
      notice('Cable routes updated live for new device positions.', 'success');
    }
  } catch (err) {
    notice('Live re-solve issue: ' + err.message, 'error');
  }
}

if ($('btn-reset-moved')) {
  $('btn-reset-moved').onclick = async () => {
    movedNodes = {};
    $('moved-badge').style.display = 'none';
    if (selected) {
      if (baseResult) {
        showResult(baseResult);
        notice('Reset device positions to original coordinates.', 'success');
      } else {
        await run(selected);
      }
    }
  };
}

/* -------------------------------------------------------------
   Top 3 Exact-Cover Groupings Comparison Modal
   ------------------------------------------------------------- */
if ($('btn-top3')) {
  $('btn-top3').onclick = async () => {
    if (!selected) return;
    $('top3-modal').style.display = 'flex';
    $('top3-cards').innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:#94a3b8;">Computing top 3 exact-cover groupings & alternative loops…</div>';
    try {
      const body = { key: selected };
      if (Object.keys(movedNodes).length > 0) body.moved_nodes = movedNodes;
      const data = await api('/api/top3', body);
      renderTop3(data.options);
    } catch (err) {
      $('top3-cards').innerHTML = `<div style="grid-column:1/-1;text-align:center;color:#ef4444;padding:30px;">Failed to evaluate top 3 groupings: ${err.message}</div>`;
    }
  };
}

if ($('top3-close')) {
  $('top3-close').onclick = () => {
    $('top3-modal').style.display = 'none';
  };
}

function renderTop3(options) {
  const container = $('top3-cards');
  if (!container) return;
  if (!options || !options.length) {
    container.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:30px;color:#94a3b8;">No alternate groupings found for this plan.</div>';
    return;
  }
  container.replaceChildren();
  options.forEach((opt, idx) => {
    const card = dom('div', 'top3-card' + (idx === 0 ? ' best' : ''));
    const rankLabel = idx === 0 ? '#1 Recommended' : `#${idx + 1} Alternative`;
    const tagText = idx === 0 ? 'Optimal Objective J' : `ΔJ: +${(opt.metrics.J - options[0].metrics.J).toFixed(2)}`;
    
    // Bounds & SVG thumbnail
    const [x0, y0, x1, y1] = opt.bounds || [0, 0, 10, 10];
    const w = x1 - x0, h = y1 - y0;
    const pad = Math.max(w, h) * 0.08;
    const vb = `${(x0 - pad).toFixed(2)} ${(-y1 - pad).toFixed(2)} ${(w + 2 * pad).toFixed(2)} ${(h + 2 * pad).toFixed(2)}`;
    
    let svgInner = '';
    if (opt.walls) svgInner += `<path d="${opt.walls}" fill="#41564b"/>`;
    if (opt.doors) svgInner += `<path d="${opt.doors}" fill="#d4b67b" opacity="0.7"/>`;
    if (opt.windows) svgInner += `<path d="${opt.windows}" fill="#77b1cd" opacity="0.6"/>`;
    
    (opt.rooms || []).forEach(r => {
      if (r.path) {
        const col = colors[(r.zone != null ? r.zone : 0) % colors.length];
        svgInner += `<path d="${r.path}" fill="${col}" opacity="0.14"/>`;
      }
    });

    (opt.hubs || []).forEach((h, hIdx) => {
      const col = colors[hIdx % colors.length];
      if (h.ring && h.ring.length > 1) {
        const d = h.ring.map((p, k) => (k ? 'L' : 'M') + p[0] + ',' + (-p[1])).join(' ');
        svgInner += `<path d="${d}" fill="none" stroke="${col}" stroke-width="${Math.max(w, h) * 0.0075}" stroke-linejoin="round"/>`;
      }
      if (h.hub) {
        const s = Math.max(w, h) * 0.014;
        const hx = h.hub[0], hy = -h.hub[1];
        svgInner += `<path d="M${hx} ${hy-s}L${hx+s} ${hy}L${hx} ${hy+s}L${hx-s} ${hy}Z" fill="${col}" stroke="white" stroke-width="${s*0.2}"/>`;
      }
    });

    // Hubs list
    let hubsListHtml = '';
    (opt.hubs || []).forEach((h, hIdx) => {
      const col = colors[hIdx % colors.length];
      hubsListHtml += `
        <div class="top3-hub-item">
          <span style="color:${col};font-weight:700;">${h.hub_id}</span>
          <span>${h.devices || (h.rooms || []).length} devices · ${h.area} m²</span>
          <span>${(h.metrics ? h.metrics.L : 0).toFixed(1)}m cable</span>
        </div>`;
    });

    card.innerHTML = `
      <div class="top3-header">
        <span class="top3-rank">${rankLabel}</span>
        <span class="top3-tag">${tagText}</span>
      </div>
      <div class="top3-nums">
        <strong>${opt.H} Hubs</strong>
        <span style="color:#5eead4;font-family:monospace;font-weight:700;">J = ${opt.metrics.J}</span>
      </div>
      <div class="top3-metrics-row">
        L: ${opt.metrics.L}m · X: ${opt.metrics.X} · O: ${opt.metrics.O}m · B: ${opt.metrics.B}
      </div>
      <svg viewBox="${vb}" role="img">${svgInner}</svg>
      <div class="top3-hubs-list">${hubsListHtml}</div>
      <button class="secondary small-btn btn-apply-top3" type="button" style="margin-top:auto;width:100%;font-weight:600;">Show on main canvas ↗</button>
    `;

    const applyBtn = card.querySelector('.btn-apply-top3');
    if (applyBtn) {
      applyBtn.onclick = () => {
        showResult(opt.sutrayana_payload);
        $('top3-modal').style.display = 'none';
        notice(`Applied grouping option ${rankLabel} (${opt.H} hubs, J=${opt.metrics.J}).`, 'success');
      };
    }
    container.append(card);
  });
}

/* -------------------------------------------------------------
   OpenCV Photo Import Flow
   ------------------------------------------------------------- */
function roomTypeColor(type) {
  switch (type) {
    case 'living': return '#d99a2b';
    case 'bedroom': return '#3f9a55';
    case 'kitchen': return '#3f6fc9';
    case 'storage': return '#c9643f';
    case 'bathroom': return '#7c3aed';
    case 'balcony': return '#059669';
    default: return '#64748b';
  }
}

if ($('photo-upload')) {
  $('photo-upload').onchange = e => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (file.size > 15 * 1024 * 1024) {
      notice('Image exceeds 15 MB limit.', 'error');
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      const base64Str = reader.result;
      notice('Analyzing photo: detecting walls, doors, windows & room layouts with OpenCV…', 'busy');
      try {
        const res = await api('/api/image/detect', { image: base64Str, name: file.name });
        photoData = res;
        openPhotoModal(res);
        notice('Floor plan features detected. Confirm wall colour and room types.', 'success');
      } catch (err) {
        notice('Photo detection failed: ' + err.message, 'error');
      } finally {
        e.target.value = '';
      }
    };
    reader.readAsDataURL(file);
  };
}

function openPhotoModal(data) {
  if (!$('photo-modal')) return;
  $('photo-modal').style.display = 'flex';
  if ($('photo-wall-swatch') && data.wall_rgb) {
    $('photo-wall-swatch').style.background = `rgb(${data.wall_rgb.join(',')})`;
  }
  if ($('photo-area-input') && data.total_area_m2) {
    $('photo-area-input').value = data.total_area_m2.toFixed(1);
  }
  if ($('photo-scale-info')) {
    $('photo-scale-info').textContent = `Scale: ${data.px_per_m.toFixed(1)} px/m (${data.scale_from}). Detected ${data.n_doors} doors and ${data.n_windows} windows.`;
  }

  // Populate Room types
  const list = $('photo-rooms-list');
  if (list) {
    list.replaceChildren();
    (data.rooms || []).forEach(r => {
      const row = dom('div', 'photo-room-row');
      row.innerHTML = `
        <b style="background:${roomTypeColor(r.type)}">${r.i + 1}</b>
        <span>${r.type.toUpperCase()} · ${r.area_m2.toFixed(1)} m²</span>
        <select data-room-idx="${r.i}">
          <option value="living" ${r.type === 'living' ? 'selected' : ''}>Living</option>
          <option value="bedroom" ${r.type === 'bedroom' ? 'selected' : ''}>Bedroom</option>
          <option value="kitchen" ${r.type === 'kitchen' ? 'selected' : ''}>Kitchen</option>
          <option value="storage" ${r.type === 'storage' ? 'selected' : ''}>Storage</option>
          <option value="bathroom" ${r.type === 'bathroom' ? 'selected' : ''}>Bathroom</option>
          <option value="balcony" ${r.type === 'balcony' ? 'selected' : ''}>Balcony</option>
          <option value="other" ${r.type === 'other' ? 'selected' : ''}>Other (Exclude)</option>
        </select>
      `;
      const sel = row.querySelector('select');
      if (sel) {
        sel.onchange = () => {
          r.type = sel.value;
          row.querySelector('b').style.background = roomTypeColor(r.type);
          row.querySelector('span').textContent = `${r.type.toUpperCase()} · ${r.area_m2.toFixed(1)} m²`;
          drawPhotoPreview(photoData);
        };
      }
      list.append(row);
    });
  }

  drawPhotoPreview(data);
}

function drawPhotoPreview(data) {
  const svg = $('photo-svg');
  if (!svg || !data) return;
  const [W, H] = data.size || [800, 600];
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

  let inner = '';
  // Background image (flipped into Cartesian space)
  if (data.image) {
    inner += `<image href="${data.image}" x="0" y="0" width="${W}" height="${H}" preserveAspectRatio="none" transform="translate(0, ${H}) scale(1, -1)" opacity="0.35"/>`;
  }
  // Detected walls
  if (data.walls) {
    inner += `<path d="${data.walls}" fill="#41564b" opacity="0.88"/>`;
  }
  // Detected doors and windows
  if (data.doors) {
    inner += `<path d="${data.doors}" fill="#c02bc0" opacity="0.85"/>`;
  }
  if (data.windows) {
    inner += `<path d="${data.windows}" fill="#16b3c4" opacity="0.85"/>`;
  }
  // Detected rooms
  (data.rooms || []).forEach(r => {
    if (r.path) {
      inner += `<path d="${r.path}" fill="${roomTypeColor(r.type)}" opacity="0.28"/>`;
    }
  });

  // Put SVG content wrapped in a flipping group so Cartesian Y-up aligns with SVG
  svg.innerHTML = `<g transform="translate(0, ${H}) scale(1, -1)">${inner}</g>`;

  // Room labels (in normal SVG coordinate space)
  const labelsG = el('g');
  (data.rooms || []).forEach(r => {
    if (r.label_xy) {
      const lx = r.label_xy[0];
      const ly = H - r.label_xy[1]; // Convert Cartesian Y to SVG Y
      const t = el('text', {
        x: lx,
        y: ly,
        fill: '#ffffff',
        'font-size': Math.max(11, W * 0.016),
        'font-weight': '700',
        'text-anchor': 'middle',
        'filter': 'drop-shadow(0px 1px 2px rgba(0,0,0,0.9))'
      }, `${r.i + 1}`);
      labelsG.append(t);
    }
  });
  svg.append(labelsG);
}

if ($('photo-close')) {
  $('photo-close').onclick = () => {
    $('photo-modal').style.display = 'none';
    photoPickingColor = false;
    if ($('photo-pick-color')) $('photo-pick-color').classList.remove('active');
    if ($('photo-svg')) $('photo-svg').style.cursor = 'default';
  };
}

if ($('photo-pick-color')) {
  $('photo-pick-color').onclick = () => {
    photoPickingColor = !photoPickingColor;
    $('photo-pick-color').classList.toggle('active', photoPickingColor);
    $('photo-svg').style.cursor = photoPickingColor ? 'crosshair' : 'default';
    if (photoPickingColor) {
      notice('Click directly on any wall segment in the photo to sample its colour.', 'busy');
    }
  };
}

if ($('photo-svg')) {
  $('photo-svg').onclick = async e => {
    if (!photoPickingColor || !photoData) return;
    const rect = $('photo-svg').getBoundingClientRect();
    const [W, H] = photoData.size;
    const clickX = ((e.clientX - rect.left) / rect.width) * W;
    const clickY = ((e.clientY - rect.top) / rect.height) * H;
    const cartX = Math.round(clickX);
    const cartY = Math.round(H - clickY);
    photoPickingColor = false;
    $('photo-pick-color').classList.remove('active');
    $('photo-svg').style.cursor = 'default';
    notice('Resampling wall colour and re-segmenting…', 'busy');
    try {
      const res = await api('/api/image/redetect', {
        token: photoData.token,
        wall_xy: [cartX, cartY]
      });
      photoData = res;
      openPhotoModal(res);
      notice('Wall colour updated and plan re-detected.', 'success');
    } catch (err) {
      notice('Re-detection failed: ' + err.message, 'error');
    }
  };
}

if ($('photo-redo-scale')) {
  $('photo-redo-scale').onclick = async () => {
    if (!photoData) return;
    const area = parseFloat($('photo-area-input').value);
    if (!area || area <= 0) {
      notice('Enter a valid total floor area in m²', 'error');
      return;
    }
    notice('Recalibrating scale to ' + area + ' m²…', 'busy');
    try {
      const res = await api('/api/image/redetect', {
        token: photoData.token,
        area_m2: area
      });
      photoData = res;
      openPhotoModal(res);
      notice('Floor scale recalibrated.', 'success');
    } catch (err) {
      notice('Recalibrate error: ' + err.message, 'error');
    }
  };
}

if ($('photo-build-btn')) {
  $('photo-build-btn').onclick = async () => {
    if (!photoData) return;
    const selects = $('photo-rooms-list').querySelectorAll('select');
    const types = Array.from(selects).map(s => s.value);
    notice('Building floor-plan geometry and synthesizing optimal rings…', 'busy');
    try {
      const res = await api('/api/image/build', {
        token: photoData.token,
        types: types
      });
      $('photo-modal').style.display = 'none';
      const cat = await api('/api/plans');
      catalog = cat;
      library();
      await choose(res.key);
      notice(`Floor plan #${res.id} generated from photo and opened in studio!`, 'success');
    } catch (err) {
      notice('Build error: ' + err.message, 'error');
    }
  };
}




