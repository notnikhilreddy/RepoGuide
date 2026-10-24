import {useEffect,useMemo,useState} from 'react';
import {ArrowUpRight,Layers3,Package,Search,ShieldAlert} from 'lucide-react';
import type {Dependency,Repo} from '../lib/types';
import {api} from '../lib/api';
import {Empty,ErrorPanel,Loading,PaneTitle} from './Shared';
export function DependenciesView({repo,onFile}:{repo:Repo;onFile:(path:string)=>void}){
  const [deps,setDeps]=useState<Dependency[]>([]);const [busy,setBusy]=useState(true);const [error,setError]=useState('');
  const [query,setQuery]=useState('');const [group,setGroup]=useState('all');
  useEffect(()=>{let ok=true;api.dependencies(repo.id).then(rows=>{if(ok)setDeps(rows)}).catch(e=>{if(ok)setError(String(e))}).finally(()=>{if(ok)setBusy(false)});return()=>{ok=false}},[repo.id]);
  const groups=useMemo(()=>[...new Set(deps.map(d=>d.group))].sort(),[deps]);
  const filtered=deps.filter(d=>(group==='all'||group===d.group)&&`${d.name} ${d.spec} ${d.manifest}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="page entrance"><PaneTitle eyebrow="DEPENDENCY INTELLIGENCE" title="Dependency explorer" detail="Declared dependencies from indexed manifests, grouped by purpose and provenance." right={<span className="tiny-count">{deps.length} packages</span>}/>
    <div className="dep-summary"><div className="panel"><Package size={20}/><strong>{deps.length}</strong><span>Declared entries</span></div><div className="panel"><Layers3 size={20}/><strong>{groups.length}</strong><span>Dependency groups</span></div><div className="panel"><ShieldAlert size={20}/><strong>Unscanned</strong><span>Vulnerability data not included</span></div></div>
    <section className="panel"><div className="data-toolbar"><div className="searchbox"><Search size={15}/><input placeholder="Filter packages, versions, manifests…" value={query} onChange={e=>setQuery(e.target.value)}/></div><select value={group} onChange={e=>setGroup(e.target.value)}><option value="all">All groups</option>{groups.map(g=><option key={g}>{g}</option>)}</select></div>
      {error?<ErrorPanel message={error}/>:busy?<Loading label="Reading manifests…"/>:filtered.length===0?<Empty title="No matching packages" description="No declared dependencies match the current filter or the index is empty."/>:<div className="dependency-table"><div className="dep-head"><span>PACKAGE</span><span>DECLARATION</span><span>GROUP</span><span>SOURCE</span></div>
        {filtered.map((d,i)=><div className="dep-row" key={`${d.name}-${d.group}-${d.manifest}-${i}`}><div className="dep-package"><div className="package-logo"><Package size={15}/></div><b>{d.name}</b></div><code title={d.spec}>{d.spec}</code><span><span className="chip">{d.group}</span></span><button className="link-row" title={`Open ${d.manifest}`} onClick={()=>onFile(d.manifest)}><span>{d.manifest}</span><ArrowUpRight size={14}/></button></div>)}</div>}
    </section><div className="footnote">This view lists declarations, not necessarily resolved transitive versions. It is not a security scanner or a dependency vulnerability assessment.</div>
  </div>
}
