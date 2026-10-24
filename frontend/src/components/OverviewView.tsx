import {useEffect,useState} from 'react';
import {ArrowUpRight,BookOpenText,Braces,ChartNoAxesColumnIncreasing,ChevronRight,GitBranch,Layers3,Network,RefreshCw} from 'lucide-react';
import type {Overview,Repo,RepoFile} from '../lib/types';
import {api} from '../lib/api';
import {Empty,ErrorPanel,Loading,Metric,PaneTitle,Status,compact} from './Shared';
import type {View} from '../App';
export function OverviewView({repo,onOpen,onFile}:{repo:Repo;onOpen:(s:View)=>void;onFile:(path:string)=>void}){
  const [data,setData]=useState<Overview|null>(null);const [files,setFiles]=useState<RepoFile[]>([]);const [error,setError]=useState('');
  const [reload,setReload]=useState(0);
  useEffect(()=>{let active=true;Promise.all([api.overview(repo.id),api.files(repo.id)]).then(([o,f])=>{if(active){setData(o);setFiles(f)}}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[repo.id,reload]);
  return <div className="page entrance"><PaneTitle eyebrow="REPOSITORY INSIGHTS" title={repo.name.split('/').pop()||repo.name} detail={`Indexed at ${repo.commit_sha.slice(0,12)} · Read-only code intelligence`} right={<><Status status={repo.status}/><a className="subtle-btn" href={repo.url} target="_blank" rel="noreferrer"><ArrowUpRight size={14}/> GitHub</a></>}/>
    {error?<ErrorPanel message={error} retry={()=>setReload(x=>x+1)}/>:!data?<Loading label="Loading indexed repository insights…"/>:<>
    <div className="stats-grid"><Metric label="CODE CHUNKS" value={compact(data.counts.chunks)} note="Embeddable evidence"/><Metric label="SYMBOLS" value={compact(data.counts.symbols)} note="Functions, classes, methods"/><Metric label="RELATIONSHIPS" value={compact(data.counts.edges)} note="Static references"/><Metric label="DEPENDENCIES" value={compact(data.counts.dependencies)} note="Declared packages"/></div>
    <div className="overview-grid">
      <section className="panel overview-feature"><div className="panel-kicker"><Network size={16}/> CODE INTELLIGENCE</div><h3>Explore how your code connects.</h3><p>Navigate imports, function calls, and symbol relationships in a searchable interactive graph. Trace a specific execution path instead of viewing arbitrary motion.</p><div className="mini-architecture">
        <div><Braces size={16}/> API entry</div><span className="flow-connector"/><div><GitBranch size={16}/> Code graph</div><span className="flow-connector"/><div><Layers3 size={16}/> Dependencies</div>
      </div><button className="text-link" onClick={()=>onOpen('architecture')}>Open architecture <ChevronRight size={16}/></button></section>
      <section className="panel overview-feature"><div className="panel-kicker"><BookOpenText size={16}/> GROUNDED ANSWERS</div><h3>Ask the repository, not your intuition.</h3><p>Hybrid retrieval, MCP evidence, citation-linked source code and MLflow trace IDs in one workspace.</p><div className="overview-example"><span className="prompt-mark">›</span> How does a request reach the database?</div><button className="text-link" onClick={()=>onOpen('ask')}>Open assistant <ChevronRight size={16}/></button></section>
    </div>
    <div className="overview-lower"><section className="panel"><div className="section-heading"><h3>Indexed files</h3><button className="text-link" onClick={()=>onOpen('explorer')}>Browse all <ChevronRight size={14}/></button></div>
      {files.length===0?<Empty title="No files" description="No code files were found for this index."/>:<div className="file-summary-list">{files.slice(0,6).map(f=><button key={f.path} onClick={()=>onFile(f.path)}><Braces size={15}/><span title={f.path}>{f.path}</span>{!f.exact&&<small>partial</small>}<ChevronRight size={14}/></button>)}</div>}
    </section><section className="panel"><div className="section-heading"><h3>Languages & index quality</h3><button className="icon-btn" onClick={()=>setReload(x=>x+1)} title="Refresh"><RefreshCw size={15}/></button></div>
      {Object.keys(data.languages).length===0?<p className="micro-muted">No symbols classified yet.</p>:Object.entries(data.languages).sort((a,b)=>b[1]-a[1]).map(([name,count])=>{const max=Math.max(1,...Object.values(data.languages));return <div key={name} className="lang-row"><div><span>{name}</span><b>{count}</b></div><div className="lang-bar"><i style={{width:`${count/max*100}%`}}/></div></div>})}
      <div className="snapshot-status"><span className={data.has_exact_sources?'live-dot':'amber-dot'}/><div><b>{data.has_exact_sources?'Exact source snapshots available':'Legacy chunk-only index'}</b><small>{data.has_exact_sources?'Monaco can display indexed files exactly.':'Refresh the index to enable complete source files.'}</small></div></div>
    </section></div>
    <section className="panel quick-actions"><button onClick={()=>onOpen('dependencies')}><Layers3 size={18}/><span>Inspect dependencies</span><ChevronRight size={16}/></button><button onClick={()=>onOpen('evaluation')}><ChartNoAxesColumnIncreasing size={18}/><span>Run evaluation</span><ChevronRight size={16}/></button><button onClick={()=>onOpen('indexing')}><GitBranch size={18}/><span>Index another repository</span><ChevronRight size={16}/></button></section>
    </>}
  </div>
}
