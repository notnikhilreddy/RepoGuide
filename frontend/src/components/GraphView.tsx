import {useEffect,useMemo,useRef,useState} from 'react';
import {Background,Controls,MiniMap,ReactFlow,MarkerType,type Edge,type Node,type NodeMouseHandler} from '@xyflow/react';
import {Activity,ArrowRight,Braces,Expand,Filter,GitFork,Pause,Play,Search} from 'lucide-react';
import type {GraphData,GraphNode,Repo} from '../lib/types';
import {api} from '../lib/api';
import {Empty,ErrorPanel,Loading,PaneTitle} from './Shared';

function positionGraph(data:GraphData,visible:Set<string>):Node[]{
  const byFile=new Map<string,GraphNode[]>();
  data.nodes.filter(n=>visible.has(n.id)).forEach(node=>{
    const list=byFile.get(node.file_path)||[];list.push(node);byFile.set(node.file_path,list);
  });
  const files=[...byFile.keys()].sort();
  const columns=Math.max(1,Math.ceil(Math.sqrt(files.length||1)));
  const groups=Array.from({length:Math.ceil(files.length/columns)},(_,row)=>files.slice(row*columns,(row+1)*columns));
  const heights=groups.map(row=>Math.max(190,...row.map(f=>(byFile.get(f)?.length||1)*72+45)));
  const offsets=heights.map((_,i)=>heights.slice(0,i).reduce((sum,h)=>sum+h+35,0));
  return files.flatMap((file,group)=>{
    const list=byFile.get(file)||[]; const row=Math.floor(group/columns);
    return list.map((n,i)=>({id:n.id,type:'default',position:{x:(group%columns)*310,
      y:offsets[row]+i*72},
      data:{label:<div className="graph-node-inner"><span className="graph-node-kind">{n.kind}</span><strong title={n.label}>{n.label.split('.').slice(-2).join('.')}</strong><small title={file}>{file.split('/').slice(-2).join('/')}</small></div>},
      className:'code-graph-node',draggable:false,connectable:false,selectable:true,
      style:{width:245}}));
  });
}
export function GraphView({repo,onFile}:{repo:Repo;onFile:(path:string,line?:number)=>void}){
  const [data,setData]=useState<GraphData|null>(null);const [error,setError]=useState('');
  const [query,setQuery]=useState('');const [kind,setKind]=useState('all');
  const [selected,setSelected]=useState<string|null>(null);const [playing,setPlaying]=useState(false);
  const [step,setStep]=useState(0);const [traceNodes,setTraceNodes]=useState<string[]>([]);
  const [showOnlyConnected,setShowOnlyConnected]=useState(false);
  useEffect(()=>{let ok=true;api.graph(repo.id,1500).then(x=>{if(ok)setData(x)}).catch(e=>{if(ok)setError(String(e))});return()=>{ok=false}},[repo.id]);
  const byId=useMemo(()=>new Map((data?.nodes||[]).map(n=>[n.id,n])),[data]);
  const adjacency=useMemo(()=>{
    const map=new Map<string,string[]>();
    data?.edges.forEach(e=>{if(e.target){const prev=map.get(e.source)||[];prev.push(e.target);map.set(e.source,prev)}});
    return map;
  },[data]);
  const path=useMemo(()=>{
    if(!selected)return [];
    const queue=[selected],visited=new Set([selected]),order:string[]=[];
    while(queue.length&&order.length<40){const current=queue.shift()!;order.push(current);
      for(const next of adjacency.get(current)||[]){if(!visited.has(next)){visited.add(next);queue.push(next)}}}
    return order;
  },[selected,adjacency]);
  useEffect(()=>{setTraceNodes([]);setStep(0);setPlaying(false)},[selected]);
  useEffect(()=>{if(!playing)return;const timer=window.setInterval(()=>{setStep(i=>{
    if(i>=path.length){setPlaying(false);return i}setTraceNodes(path.slice(0,i+1));return i+1;
  })},550);return()=>window.clearInterval(timer)},[playing,path]);
  const filtered=useMemo(()=>{
    const base=(data?.nodes||[]).filter(n=>(kind==='all'||n.kind===kind)&&`${n.label} ${n.file_path}`.toLowerCase().includes(query.toLowerCase()));
    const ids=new Set(base.map(x=>x.id));
    if(showOnlyConnected&&selected){return new Set([...ids].filter(id=>id===selected||
      (data?.edges||[]).some(e=>(e.source===selected&&e.target===id)||(e.target===selected&&e.source===id))))}
    return ids;
  },[data,query,kind,showOnlyConnected,selected]);
  const active=new Set(traceNodes);
  const nodes=useMemo(()=>positionGraph(data||{nodes:[],edges:[]},filtered).map(n=>({...n,
    className:'code-graph-node '+(selected===n.id?'selected-node ':'')+(active.has(n.id)?'visited-node':''),
  })),[data,filtered,selected,traceNodes]);
  const edges:Edge[]=useMemo(()=>data?.edges.filter(e=>e.target&&filtered.has(e.source)&&filtered.has(e.target))
    .map(e => {const lit = active.has(e.source) && e.target !== null && active.has(e.target);
      return {id:e.id,source:e.source,target:e.target!,label:e.kind==='contains'?undefined:e.kind,
        animated:lit,style:{stroke:lit?'#6bbcb4':'#506071',strokeWidth:lit?2.6:1.2,opacity:lit?1:.64},
        labelStyle:{fill:'#98a8b9',fontSize:10},markerEnd:{type:MarkerType.ArrowClosed,width:12,height:12,color:lit?'#6bbcb4':'#506071'},
        type:'smoothstep'};
    })||[],[data,filtered,traceNodes]);
  const chosen=selected?byId.get(selected):undefined;
  const nodeSelect:NodeMouseHandler=(_,node)=>setSelected(node.id);
  const kinds=useMemo(()=>[...new Set((data?.nodes||[]).map(n=>n.kind))].sort(),[data]);
  return <div className="page graph-page entrance"><PaneTitle eyebrow="STRUCTURAL INTELLIGENCE" title="Architecture graph" detail="Trace resolved code relationships. Highlighted edges reflect real parsed links—not a synthetic animation." right={<span className="tiny-count">{data?.nodes.length||0} symbols · {data?.edges.filter(x=>x.resolved).length||0} resolved edges</span>}/>
    {error?<ErrorPanel message={error}/>:!data?<Loading label="Loading code relationships…"/>:data.nodes.length===0?<Empty title="No graph data" description="Index or refresh a repository to extract symbols and call relationships."/>:<>
      <div className="graph-controls"><div className="searchbox"><Search size={16}/><input placeholder="Search symbols or files…" value={query} onChange={e=>setQuery(e.target.value)}/></div>
        <div className="filter-box"><Filter size={15}/><select value={kind} onChange={e=>setKind(e.target.value)}><option value="all">All kinds</option>{kinds.map(x=><option key={x} value={x}>{x}</option>)}</select></div>
        <label className="switch-label"><input type="checkbox" checked={showOnlyConnected} onChange={e=>setShowOnlyConnected(e.target.checked)}/> Neighbors only</label>
        <button className="subtle-btn" disabled={!selected||path.length<2} onClick={()=>{if(step>=path.length){setStep(0);setTraceNodes([])}setPlaying(v=>!v)}}>{playing?<Pause size={15}/>:<Play size={15}/>} {playing?'Pause trace':'Trace flow'}</button>
        <span className="trace-progress">{step&&path.length?`${Math.min(step,path.length)}/${path.length} visited`:''}</span>
      </div>
      <div className="graph-workspace"><div className="graph-canvas"><ReactFlow nodes={nodes} edges={edges} onNodeClick={nodeSelect} fitView minZoom={.15} maxZoom={1.8} nodesDraggable={false} nodesConnectable={false} proOptions={{hideAttribution:true}}><Background gap={20} size={1} color="var(--graph-grid)"/><Controls showInteractive={false}/><MiniMap pannable zoomable nodeColor="var(--accent-muted)" style={{background:'var(--surface)'}}/></ReactFlow><div className="canvas-help"><GitFork size={13}/> Click a node to inspect · Trace follows outgoing resolved calls</div></div>
        <aside className="graph-inspector"><div className="section-heading"><h3>Symbol inspector</h3><Activity size={16}/></div>{!chosen?<Empty title="Select a symbol" description="Inspect definition, location and outgoing relationships."/>:<>
          <span className="chip">{chosen.kind}</span><h3 className="inspector-name">{chosen.label}</h3><div className="mono-muted">{chosen.file_path}</div>
          <div className="inspector-stats"><div><span>Outgoing</span><strong>{data.edges.filter(x=>x.source===chosen.id).length}</strong></div><div><span>Incoming</span><strong>{data.edges.filter(x=>x.target===chosen.id).length}</strong></div></div>
          <button className="primary-btn block" onClick={()=>onFile(chosen.file_path,chosen.start_line)}><Braces size={16}/> Open in explorer <ArrowRight size={15}/></button>
          <div className="inspector-divider"/><div className="field-label">OUTGOING CONNECTIONS</div>
          {data.edges.filter(x=>x.source===chosen.id).slice(0,25).map(e=><button className="connection-row" key={e.id} onClick={()=>e.target&&setSelected(e.target)} disabled={!e.target}><GitFork size={13}/><span title={e.target_name}>{e.target_name}</span><small>{e.kind}</small></button>)}
          {data.edges.filter(x=>x.source===chosen.id).length===0&&<p className="micro-muted">No outgoing relationships extracted.</p>}
        </>}</aside></div>
      <div className="footnote">Static analysis is conservative. Dynamic dispatch and unresolved calls may be absent. For very large repositories, this view samples up to 1,500 stored edges.</div>
    </>}
  </div>
}
