import { useEffect, useState } from 'react';
import { ArrowRight, Check, CircleDot, GitBranch, GitCommitHorizontal, Layers, LoaderCircle, Plus, RefreshCw, XCircle } from 'lucide-react';
import { api } from '../lib/api';
import type { Job } from '../lib/types';
import { PaneTitle, ErrorPanel } from './Shared';
const stages=[{id:'cloning',label:'Clone',icon:GitBranch},{id:'parsing',label:'Analyze',icon:Layers},{id:'embedding',label:'Embed',icon:CircleDot},{id:'persisting',label:'Persist',icon:GitCommitHorizontal}];
export function IndexView({onFinished,initialUrl=""}:{onFinished:(id:string)=>void;initialUrl?:string}){
  const [url,setUrl]=useState(initialUrl);const [force,setForce]=useState(false);
  const [job,setJob]=useState<Job|null>(null);
  const [worker,setWorker]=useState<{paused:boolean;desired:number;running:number;queued:number;inflight:number;local?:boolean}|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  useEffect(()=>{
    if(!import.meta.env.VITE_API_BASE_URL)return;
    void api.workerStatus().then(setWorker).catch(()=>setWorker(null));
  },[]);
  async function changeWorker(action:'wake'|'sleep'){
    try{setWorker(await api.workerAction(action));setError('')}catch(e){setError(e instanceof Error?e.message:'Worker control failed')}
  }
  useEffect(()=>{
    if(!job||job.status==='complete'||job.status==='failed')return;
    const timer=window.setInterval(async()=>{try{setJob(await api.job(job.id))}catch(e){setError(e instanceof Error?e.message:'Job status unavailable')}},800);
    return ()=>clearInterval(timer);
  },[job?.id,job?.status]);
  async function submit(e:React.FormEvent){e.preventDefault();if(!url.trim()||busy)return;
    setBusy(true);setError('');try{setJob(await api.index(url.trim(),force));}catch(e){setError(e instanceof Error?e.message:'Could not start job')}finally{setBusy(false)}
  }
  const current=stages.findIndex(s=>s.id===job?.stage);
  const parsedEvent=job?.events.find(e=>e.stage==='parsing'&&e.detail.startsWith('Parsed '));
  const extracted=parsedEvent?.detail.match(/Parsed (\d+) code chunks, (\d+) symbols/);
  const chunkCount=extracted?Number(extracted[1]):0;
  const symbolCount=extracted?Number(extracted[2]):0;
  return <div className="page page-narrow entrance">
    <PaneTitle eyebrow="REPOSITORY INGESTION" title="Index a repository" detail="Build a searchable semantic and structural index. Progress reflects actual backend stages, not a simulated animation."/>
    {import.meta.env.VITE_API_BASE_URL&&<section className="panel index-form">
      <div className="section-heading"><h3>Background workers</h3><span>{worker ? (worker.paused?'Paused':worker.running?'Running':'Sleeping / starting'):'Only admins can control workers'}</span></div>
      {worker&&<div style={{display:'flex',alignItems:'center',gap:12,flexWrap:'wrap'}}><span className="micro-muted">ECS tasks: {worker.running} · Queued: {worker.queued} · In flight: {worker.inflight}</span>
      <button className="primary-btn" type="button" onClick={()=>void changeWorker('wake')}>Wake worker</button>
      <button type="button" onClick={()=>void changeWorker('sleep')}>Sleep worker</button></div>}
    </section>}
    <section className="panel index-form"><form onSubmit={submit}>
      <label className="field-label" htmlFor="giturl">Public GitHub repository URL</label>
      <div className="input-action"><GitBranch size={18}/><input id="giturl" type="url" value={url} onChange={e=>setUrl(e.target.value)} required placeholder="https://github.com/owner/repository" disabled={job?.status==='running'||job?.status==='queued'}/><button className="primary-btn" type="submit" disabled={busy||job?.status==='running'||job?.status==='queued'||!url.trim()}>{busy?<LoaderCircle size={16} className="spin"/>:<Plus size={16}/>} Index</button></div>
      <label className="checkbox-row"><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)}/> Reindex this commit and capture exact source snapshots <small>(may regenerate embeddings)</small></label>
    </form>{error&&<ErrorPanel message={error}/>}</section>
    <section className="panel index-progress"><div className="section-heading"><h3>Indexing pipeline</h3><span className="micro-muted">{job?.status||'Waiting'}</span></div>
      <div className="stage-track">{stages.map((s,i)=>{const passed=job?.status==='complete'||current>i;const active=current===i&&job?.status==='running';const Icon=s.icon;return <div key={s.id} className={'stage '+(passed?'stage-done ':'')+(active?'stage-active':'')}><div className="stage-icon">{passed?<Check size={20}/>:active?<LoaderCircle className="spin" size={19}/>:<Icon size={19}/>}</div><strong>{s.label}</strong><small>{['Git checkout','AST + symbols','Vectors','Database'][i]}</small>{i<stages.length-1&&<div className={'stage-bridge '+(passed?'lit':'')}/>}</div>})}</div>
      <div className="progress-line"><div style={{width:`${job?.percent||0}%`}}/></div>
      <div className="progress-details"><span>{job?.detail||'Enter a repository URL to begin indexing'}</span><strong>{job?.percent||0}%</strong></div>
      {job&&<div className="index-graph-live"><div className="field-label">LIVE INDEX STRUCTURE</div><div className="index-graph-nodes"><div className="index-graph-box active"><GitBranch size={16}/><b>Repository</b><small>{job.stage==='cloning'?'Cloning…':'Source checkout'}</small></div>{extracted&&<><div className="index-graph-wire"/><div className="index-graph-box revealed"><Layers size={16}/><b>{symbolCount.toLocaleString()} symbols</b><small>Static structure</small></div><div className="index-graph-wire"/><div className="index-graph-box revealed"><CircleDot size={16}/><b>{chunkCount.toLocaleString()} chunks</b><small>Semantic index</small></div></>}{(job.stage==='persisting'||job.status==='complete')&&<><div className="index-graph-wire"/><div className="index-graph-box revealed"><GitCommitHorizontal size={16}/><b>PostgreSQL</b><small>Persisted</small></div></>}</div></div>}
      {job?.status==='failed'&&<div className="job-failure"><XCircle size={17}/>{job.detail}</div>}
      {job?.status==='complete'&&job.result?.repo_id&&<button className="primary-btn" onClick={()=>onFinished(job.result!.repo_id!)}>Explore indexed repository <ArrowRight size={16}/></button>}
      {job&&<div className="index-events"><div className="field-label">PROCESS LOG</div>{job.events.slice(-7).map((ev,i)=><div key={`${ev.time}-${i}`} className="log-entry"><span className="event-time">{new Date(ev.time*1000).toLocaleTimeString()}</span><span className="log-status"/>{ev.detail}</div>)}</div>}
    </section>
    <div className="footnote">{import.meta.env.VITE_API_BASE_URL ? 'Cloud jobs persist in DynamoDB and run through SQS + ECS Fargate. Worker task startup can take a few minutes. Jobs expire from the status table after seven days.' : 'Local development uses an in-process worker. Hosted mode uses SQS + Fargate for durable processing.'}</div>
  </div>
}
