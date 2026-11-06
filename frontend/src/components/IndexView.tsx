import { useEffect, useState } from 'react';
import { ArrowRight, Check, CircleDot, GitBranch, GitCommitHorizontal, Layers, LoaderCircle, Plus, RefreshCw, XCircle } from 'lucide-react';
import { api,hosted } from '../lib/api';
import type { Job } from '../lib/types';
import { PaneTitle, ErrorPanel } from './Shared';
const stages=[{id:'cloning',label:'Clone',icon:GitBranch},{id:'parsing',label:'Analyze',icon:Layers},{id:'embedding',label:'Embed',icon:CircleDot},{id:'persisting',label:'Persist',icon:GitCommitHorizontal}];
export function IndexView({onFinished,initialUrl="",initialJob=null}:{onFinished:(id:string)=>void;initialUrl?:string;initialJob?:Job|null}){
  const [url,setUrl]=useState(initialUrl);const [branch,setBranch]=useState('');const [force,setForce]=useState(false);
  const [job,setJob]=useState<Job|null>(initialJob);
  useEffect(()=>{if(initialJob)setJob(initialJob)},[initialJob?.id]);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  useEffect(()=>{if(initialJob)return;let live=true;if(hosted)void api.indexJobs().then(jobs=>{const latest=jobs[0];if(live&&latest){setJob(latest);if(latest.repository_url)setUrl(latest.repository_url);if(latest.branch)setBranch(latest.branch)}}).catch(()=>{});return()=>{live=false}},[]);
  useEffect(()=>{
    if(!job||job.status==='complete'||['failed','cancelled'].includes(job.status))return;
    const timer=window.setInterval(async()=>{if(document.hidden)return;try{setJob(await api.job(job.id))}catch(e){setError(e instanceof Error?e.message:'Job status unavailable')}},2500);
    return ()=>clearInterval(timer);
  },[job?.id,job?.status]);
  async function submit(e:React.FormEvent){e.preventDefault();if(!url.trim()||busy)return;
    setBusy(true);setError('');try{setJob(await api.index(url.trim(),force,branch));}catch(e){setError(e instanceof Error?e.message:'Could not start job')}finally{setBusy(false)}
  }
  const current=stages.findIndex(s=>s.id===job?.stage);
  const parsedEvent=job?.events.find(e=>e.stage==='parsing'&&e.detail.startsWith('Parsed '));
  const extracted=parsedEvent?.detail.match(/Parsed (\d+) code chunks, (\d+) symbols/);
  const chunkCount=extracted?Number(extracted[1]):0;
  const symbolCount=extracted?Number(extracted[2]):0;
  return <div className="page page-narrow entrance">
    <PaneTitle eyebrow="REPOSITORY INGESTION" title="Index a repository" detail="Build a searchable semantic and structural index. Progress reflects actual backend stages, not a simulated animation."/>
    <section className="panel index-form"><form onSubmit={submit}>
      <label className="field-label" htmlFor="giturl">Public GitHub repository URL</label>
      <div className="input-action"><GitBranch size={18}/><input id="giturl" type="url" value={url} onChange={e=>setUrl(e.target.value)} required placeholder="https://github.com/owner/repository" disabled={job?.status==='running'||job?.status==='queued'}/><button className="primary-btn" type="submit" disabled={busy||job?.status==='running'||job?.status==='queued'||!url.trim()}>{busy?<LoaderCircle size={16} className="spin"/>:<Plus size={16}/>} Index</button></div>
      <details className="index-advanced"><summary>Index options</summary><label className="field-label">Monitored branch<input aria-label="Monitored branch" value={branch} maxLength={200} onChange={e=>setBranch(e.target.value)} placeholder="Repository default branch"/></label><label className="checkbox-row"><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)}/> Reindex this commit and capture exact source snapshots <small>(may regenerate embeddings)</small></label></details>
    </form>{error&&<ErrorPanel message={error}/>}</section>
    <section className="panel index-progress"><div className="section-heading"><h3>Indexing pipeline</h3><span className="micro-muted">{job?.status||'Waiting'}</span></div>
      <div className="stage-track">{stages.map((s,i)=>{const passed=job?.status==='complete'||current>i;const active=current===i&&job?.status==='running';const Icon=s.icon;return <div key={s.id} className={'stage '+(passed?'stage-done ':'')+(active?'stage-active':'')}><div className="stage-icon">{passed?<Check size={20}/>:active?<LoaderCircle className="spin" size={19}/>:<Icon size={19}/>}</div><strong>{s.label}</strong><small>{['Git checkout','AST + symbols','Vectors','Database'][i]}</small>{i<stages.length-1&&<div className={'stage-bridge '+(passed?'lit':'')}/>}</div>})}</div>
      <div className="progress-line"><div style={{width:`${job?.percent||0}%`}}/></div>
      <div className="progress-details"><span>{job?.detail||'Enter a repository URL to begin indexing'}</span><strong>{job?.percent||0}%</strong></div>
      {job&&<div className="index-graph-live"><div className="field-label">LIVE INDEX STRUCTURE</div><div className="index-graph-nodes"><div className="index-graph-box active"><GitBranch size={16}/><b>Repository</b><small>{job.stage==='cloning'?'Cloning…':'Source checkout'}</small></div>{extracted&&<><div className="index-graph-wire"/><div className="index-graph-box revealed"><Layers size={16}/><b>{symbolCount.toLocaleString()} symbols</b><small>Static structure</small></div><div className="index-graph-wire"/><div className="index-graph-box revealed"><CircleDot size={16}/><b>{chunkCount.toLocaleString()} chunks</b><small>Semantic index</small></div></>}{(job.stage==='persisting'||job.status==='complete')&&<><div className="index-graph-wire"/><div className="index-graph-box revealed"><GitCommitHorizontal size={16}/><b>PostgreSQL</b><small>Persisted</small></div></>}</div></div>}
      {job?.status==='failed'&&<div className="job-failure"><XCircle size={17}/>{job.error||job.detail}</div>}{job&&['queued','running','retrying'].includes(job.status)&&<button className="subtle-btn" onClick={()=>void api.cancelJob(job.id).then(setJob).catch(e=>setError(e instanceof Error?e.message:'Could not cancel indexing'))}><XCircle size={14}/>Cancel indexing</button>}
      {job?.status==='complete'&&job.result?.repo_id&&<button className="primary-btn" onClick={()=>onFinished(job.result!.repo_id!)}>Explore indexed repository <ArrowRight size={16}/></button>}
      {job&&<div className="index-events"><div className="field-label">PROCESS LOG</div>{job.events.slice(-7).map((ev,i)=><div key={`${ev.time}-${i}`} className="log-entry"><span className="event-time">{new Date(ev.time>1e12?ev.time:ev.time*1000).toLocaleTimeString()}</span><span className="log-status"/>{ev.detail}</div>)}</div>}
    </section>
    <div className="footnote">{hosted?'Indexing continues in the background. Your ten most recent jobs can be resumed here across devices; job status is kept for seven days. Your saved conversations stay in history.':'Local indexing runs while the development server is active.'}</div>
  </div>
}
