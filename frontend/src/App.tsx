import { useEffect, useState, useCallback } from 'react';
import { Activity, ArrowRight, BookOpenText, Braces, ChartNoAxesColumnIncreasing, ChevronsUpDown,
  Command, Database, GitBranch, Github, LayoutDashboard, Menu, Moon, Plus, Search, Sun, TerminalSquare,
  X, Layers3, LoaderCircle } from 'lucide-react';
import { api } from './lib/api';
import {authEnabled,authManager} from './lib/auth';
import type { Repo, RepoFile } from './lib/types';
import { Dialog, Empty, ErrorPanel, Status } from './components/Shared';
import { OverviewView } from './components/OverviewView';
import { GraphView } from './components/GraphView';
import { ExplorerView } from './components/ExplorerView';
import { ChatView } from './components/ChatView';
import { DependenciesView } from './components/DependenciesView';
import { EvaluationView } from './components/EvaluationView';
import { IndexView } from './components/IndexView';

export type View='overview'|'architecture'|'explorer'|'ask'|'dependencies'|'evaluation'|'indexing';
const navigation: {id:View;label:string;icon:typeof Activity;hint?:string}[]=[
  {id:'overview',label:'Overview',icon:LayoutDashboard},
  {id:'architecture',label:'Architecture',icon:GitBranch},
  {id:'explorer',label:'Code explorer',icon:Braces},
  {id:'ask',label:'Ask RepoGuide',icon:BookOpenText},
  {id:'dependencies',label:'Dependencies',icon:Layers3},
  {id:'evaluation',label:'Evaluation Lab',icon:ChartNoAxesColumnIncreasing},
  {id:'indexing',label:'Indexing',icon:Activity},
];

export default function App(){
  const [view,setView]=useState<View>('overview');
  const [repos,setRepos]=useState<Repo[]>([]);
  const [repoId,setRepoId]=useState<string>(()=>localStorage.getItem('rg.repo')||'');
  const [repoError,setRepoError]=useState('');
  const [filePalette,setFilePalette]=useState<RepoFile[]>([]);
  const [loadingRepos,setLoadingRepos]=useState(true);
  const [repoDropdown,setRepoDropdown]=useState(false);
  const [command,setCommand]=useState(false);
  const [commandFilter,setCommandFilter]=useState('');
  const [selectedFile,setSelectedFile]=useState<{path:string;line?:number}|null>(null);
  const [theme,setTheme]=useState<'dark'|'light'>(()=>localStorage.getItem('rg.theme')==='light'?'light':'dark');
  const [mobileMenu,setMobileMenu]=useState(false);

  const refreshRepos=useCallback(async()=>{
    try{const items=await api.repos();setRepos(items);setRepoError('');
      setRepoId(prev=>{const found=items.some(x=>x.id===prev);return found?prev:items[0]?.id||'';});
    }catch(e){setRepoError(e instanceof Error?e.message:'Could not connect to API');}
    finally{setLoadingRepos(false)}
  },[]);
  useEffect(()=>{void refreshRepos()},[refreshRepos]);
  useEffect(()=>{let live=true;if(repoId)api.files(repoId).then(x=>{if(live)setFilePalette(x)}).catch(()=>{if(live)setFilePalette([])});return()=>{live=false}},[repoId]);
  useEffect(()=>{document.documentElement.dataset.theme=theme;localStorage.setItem('rg.theme',theme)},[theme]);
  useEffect(()=>{if(repoId)localStorage.setItem('rg.repo',repoId)},[repoId]);
  useEffect(()=>{const handler=(e:KeyboardEvent)=>{
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setCommand(v=>!v)}
    if(e.key==='Escape'){setCommand(false);setRepoDropdown(false);setMobileMenu(false)}
  };window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler)},[]);
  const repo=repos.find(r=>r.id===repoId);
  const jumpToFile=(path:string,line?:number)=>{setSelectedFile({path,line});setView('explorer')};
  const chooseView=(next:View)=>{setView(next);setMobileMenu(false);setCommand(false)};
  const selectRepo=(id:string)=>{setRepoId(id);setSelectedFile(null);setRepoDropdown(false);setCommand(false)};
  const navResults=navigation.filter(n=>n.label.toLowerCase().includes(commandFilter.toLowerCase()));
  const repoResults=repos.filter(r=>r.name.toLowerCase().includes(commandFilter.toLowerCase()));
  const fileResults=commandFilter?filePalette.filter(f=>f.path.toLowerCase().includes(commandFilter.toLowerCase())).slice(0,12):[];
  return <div className="app-shell">
    <aside className={'sidebar '+(mobileMenu?'sidebar-open':'')}>
      <div className="brand"><div className="brand-mark"><TerminalSquare size={19} strokeWidth={2.2}/></div><span>RepoGuide</span><small>WORKSPACE</small></div>
      <div className="side-section-label">WORKSPACE</div>
      <div className="repo-select-wrap">
        <button className="repo-selector" onClick={()=>setRepoDropdown(v=>!v)} aria-expanded={repoDropdown}>
          <div className="repo-avatar"><Github size={16}/></div>
          <span className="repo-current"><b>{repo?.name.split('/').pop()||'Select repository'}</b><small>{repo?.name.split('/')[0]||'No active repo'}</small></span>
          <ChevronsUpDown size={15}/>
        </button>
        {repoDropdown&&<div className="repo-dropdown">
          {repos.map(r=><button key={r.id} className={r.id===repoId?'active':''} onClick={()=>selectRepo(r.id)}><Github size={15}/><span>{r.name}</span><Status status={r.status}/></button>)}
          {repos.length===0&&<p className="dropdown-empty">No indexed repositories</p>}
          <button onClick={()=>{setRepoDropdown(false);chooseView('indexing')}}><Plus size={15}/>Index a repository</button>
        </div>}
      </div>
      <nav className="sidebar-nav" aria-label="Main navigation">
        <div className="side-section-label">EXPLORE</div>
        {navigation.map(({id,label,icon:Icon})=><button key={id} onClick={()=>chooseView(id)} className={'nav-link '+(id===view?'active':'')}><Icon size={17}/><span>{label}</span>{id===view&&<div className="nav-indicator"/>}</button>)}
      </nav>
      <div className="sidebar-spacer"/>
      <button className="command-shortcut" onClick={()=>{setCommand(true);setCommandFilter('')}}><Search size={16}/><span>Quick search</span><kbd>⌘ K</kbd></button>
      <div className="side-footer"><span className="live-dot"/> <span>{import.meta.env.VITE_API_BASE_URL ? "Cloud workspace" : "Local workspace"}</span><small>v0.7.0</small></div>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <button className="icon-btn mobile-toggle" onClick={()=>setMobileMenu(v=>!v)} aria-label="Toggle menu"><Menu size={19}/></button>
        <div className="breadcrumbs"><span>Workspace</span><span className="slash">/</span><span>{repo?.name||'No repository'}</span><span className="slash">/</span><strong>{navigation.find(n=>n.id===view)?.label}</strong></div>
        <div className="topbar-actions">
          {repo&&<div className="commit-chip" title={repo.commit_sha}><GitBranch size={13}/>{repo.commit_sha.slice(0,7)}</div>}
          <button className="icon-btn" title="Toggle theme" onClick={()=>setTheme(t=>t==='dark'?'light':'dark')}>{theme==='dark'?<Sun size={17}/>:<Moon size={17}/>}</button>
          <a className="icon-btn" href={import.meta.env.VITE_MLFLOW_URL || "http://127.0.0.1:5000"} target="_blank" rel="noreferrer" title="Open local MLflow"><Database size={17}/></a>
          {authEnabled&&<button className="icon-btn" title="Sign out" onClick={()=>void authManager?.signoutRedirect()}><span style={{fontSize:11}}>Sign out</span></button>}
        </div>
      </header>
      {repoError&&<div className="api-banner"><ErrorPanel message={`Backend connection: ${repoError}`} retry={()=>void refreshRepos()}/></div>}
      <main className="workspace">
        {view==='indexing'?<IndexView initialUrl={repo?.url||''} onFinished={async id=>{await refreshRepos();setRepoId(id);chooseView('overview')}}/>:
         !repo ? (loadingRepos?<div className="empty"><LoaderCircle className="spin"/><p>Connecting to RepoGuide…</p></div>:<Empty title="Your workspace is ready" description="Index your first GitHub repository to explore its architecture and ask grounded questions." action={<button className="primary-btn" onClick={()=>chooseView('indexing')}><Plus size={15}/>Index a repository<ArrowRight size={15}/></button>}/>) :
         <div key={repoId} className="view-frame">
          {view==='overview'&&<OverviewView repo={repo} onOpen={chooseView} onFile={jumpToFile}/>}
          {view==='architecture'&&<GraphView repo={repo} onFile={jumpToFile}/>}
          {view==='explorer'&&<ExplorerView repo={repo} selectedFile={selectedFile} onSelectionChange={setSelectedFile}/>}
          {view==='ask'&&<ChatView repo={repo} onFile={jumpToFile}/>}
          {view==='dependencies'&&<DependenciesView repo={repo} onFile={jumpToFile}/>}
          {view==='evaluation'&&<EvaluationView repo={repo}/>}
         </div>}
      </main>
    </div>
    {command&&<Dialog title="Go to…" onClose={()=>setCommand(false)}>
      <div className="palette-search"><Search size={17}/><input autoFocus value={commandFilter} onChange={e=>setCommandFilter(e.target.value)} placeholder="Search pages and repositories…"/></div>
      <div className="palette-list"><div className="side-section-label">PAGES</div>
        {navResults.map(x=><button key={x.id} onClick={()=>chooseView(x.id)}><x.icon size={17}/>{x.label}<ArrowRight size={14}/></button>)}
        <div className="side-section-label">REPOSITORIES</div>
        {repoResults.map(r=><button key={r.id} onClick={()=>selectRepo(r.id)}><Github size={16}/>{r.name}<ArrowRight size={14}/></button>)}
        {fileResults.length>0&&<><div className="side-section-label">FILES IN CURRENT REPO</div>{fileResults.map(f=><button key={f.path} onClick={()=>{jumpToFile(f.path);setCommand(false)}}><Braces size={15}/>{f.path}<ArrowRight size={14}/></button>)}</>}
      </div><div className="palette-footer"><kbd>ESC</kbd> to close</div>
    </Dialog>}
    {mobileMenu&&<button className="mobile-scrim" onClick={()=>setMobileMenu(false)} aria-label="Close menu"/>}
  </div>
}
