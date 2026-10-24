import {useEffect,useMemo,useRef,useState} from 'react';
import Editor, {type OnMount} from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';
import {AlertTriangle,Braces,ChevronDown,ChevronRight,Copy,ExternalLink,FileCode2,Folder,FolderOpen,Search} from 'lucide-react';
import type {CodeSymbol,FileResponse,Repo,RepoFile} from '../lib/types';
import {api} from '../lib/api';
import {Empty,ErrorPanel,Loading,PaneTitle} from './Shared';

type Dir={name:string;path:string;dirs:Map<string,Dir>;files:RepoFile[]};
const mkDir=(name:string,path:string):Dir=>({name,path,dirs:new Map(),files:[]});
function buildTree(files:RepoFile[]):Dir{const root=mkDir('root','');for(const f of files){const bits=f.path.split('/');let curr=root;
  for(const part of bits.slice(0,-1)){const path=[curr.path,part].filter(Boolean).join('/');if(!curr.dirs.has(part))curr.dirs.set(part,mkDir(part,path));curr=curr.dirs.get(part)!;}
  curr.files.push(f);
}return root;}
function language(path:string){const ext=path.split('.').pop()?.toLowerCase();return ({py:'python',ts:'typescript',tsx:'typescript',js:'javascript',jsx:'javascript',json:'json',md:'markdown',yml:'yaml',yaml:'yaml',toml:'ini',sql:'sql',css:'css',html:'html'} as Record<string,string>)[ext||'']||'plaintext';}
function Branch({dir,selected,onChoose,filter,depth=0}:{dir:Dir;selected?:string;onChoose:(path:string)=>void;filter:string;depth?:number}){
  const [expanded,setExpanded]=useState(depth===0||depth===1||!!filter);
  const children=[...dir.dirs.values()].sort((a,b)=>a.name.localeCompare(b.name));
  const files=dir.files.filter(f=>f.path.toLowerCase().includes(filter));
  const hasMatches=(d:Dir):boolean=>d.files.some(f=>f.path.toLowerCase().includes(filter))||[...d.dirs.values()].some(hasMatches);
  return <>{depth>0&&<button className="tree-row tree-folder" style={{paddingLeft:9+depth*12}} onClick={()=>setExpanded(v=>!v)}><span>{expanded?<ChevronDown size={13}/>:<ChevronRight size={13}/>}</span>{expanded?<FolderOpen size={15}/>:<Folder size={15}/>}<span>{dir.name}</span></button>}
    {(expanded||!!filter)&&<>{children.filter(d=>hasMatches(d)).map(d=><Branch key={d.path} dir={d} selected={selected} onChoose={onChoose} filter={filter} depth={depth+1}/>)}{files.sort((a,b)=>a.path.localeCompare(b.path)).map(f=><button key={f.path} onClick={()=>onChoose(f.path)} title={f.path} className={'tree-row '+(selected===f.path?'selected':'')} style={{paddingLeft:24+(depth)*12}}><FileCode2 size={14}/><span>{f.path.split('/').pop()}</span>{!f.exact&&<i className="partial-indicator" title="Partial source"/>}</button>)}</>}
  </>
}
export function ExplorerView({repo,selectedFile,onSelectionChange}:{repo:Repo;selectedFile:{path:string;line?:number}|null;onSelectionChange:(value:{path:string;line?:number})=>void}){
  const [files,setFiles]=useState<RepoFile[]>([]);const [content,setContent]=useState<FileResponse|null>(null);
  const [symbols,setSymbols]=useState<CodeSymbol[]>([]);const [fileError,setFileError]=useState('');const [loading,setLoading]=useState(true);const [loadingFile,setLoadingFile]=useState(false);
  const [search,setSearch]=useState('');const [copied,setCopied]=useState(false);
  const editorRef=useRef<Monaco.editor.IStandaloneCodeEditor|null>(null);
  const marks=useRef<Monaco.editor.IEditorDecorationsCollection|null>(null);
  useEffect(()=>{let ok=true;api.files(repo.id).then(rows=>{if(!ok)return;setFiles(rows);setLoading(false);
    if(!selectedFile&&rows.length)onSelectionChange({path:rows[0].path});
  }).catch(e=>{if(ok){setFileError(String(e));setLoading(false)}});return()=>{ok=false}},[repo.id]);
  useEffect(()=>{if(!selectedFile?.path)return;let live=true;setLoadingFile(true);setFileError('');
    Promise.all([api.file(repo.id,selectedFile.path),api.symbols(repo.id,selectedFile.path)]).then(([file,syms])=>{if(live){setContent(file);setSymbols(syms)}}).catch(e=>{if(live){setFileError(String(e));setContent(null)}}).finally(()=>{if(live)setLoadingFile(false)});
    return()=>{live=false};
  },[repo.id,selectedFile?.path]);
  useEffect(()=>{const line=selectedFile?.line||0;if(line&&editorRef.current){editorRef.current.revealLineInCenter(line);
    marks.current?.set([{range:{startLineNumber:line,startColumn:1,endLineNumber:line,endColumn:1},options:{isWholeLine:true,className:'source-highlight',linesDecorationsClassName:'source-gutter'}}]);
  }else marks.current?.clear()},[selectedFile?.line,content?.path]);
  const tree=useMemo(()=>buildTree(files),[files]);
  const editorMount:OnMount=(editor)=>{editorRef.current=editor;marks.current=editor.createDecorationsCollection([]);
    const line=selectedFile?.line;if(line){editor.revealLineInCenter(line);marks.current.set([{range:{startLineNumber:line,startColumn:1,endLineNumber:line,endColumn:1},options:{isWholeLine:true,className:'source-highlight'}}])}
  };
  const file=selectedFile?.path||'';
  return <div className="page explorer-page entrance"><PaneTitle eyebrow="SOURCE EXPLORER" title="Code explorer" detail="Browse the exact indexed commit, inspect symbols, and follow source citations." right={<span className="tiny-count">{files.length} files</span>}/>
  {loading?<Loading label="Loading file tree…"/>:<div className="explorer-layout">
    <aside className="file-tree panel"><div className="section-heading"><h3>Files</h3><span className="tiny-count">{files.length}</span></div><div className="searchbox"><Search size={14}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Filter files…"/></div>
      <div className="tree-scroller">{files.length?<Branch dir={tree} selected={file} onChoose={path=>onSelectionChange({path})} filter={search.toLowerCase()}/>:<Empty title="No files" description="Refresh the repository index."/>}</div>
    </aside>
    <section className="editor-pane panel"><div className="editor-toolbar"><div className="editor-crumb"><FileCode2 size={16}/><span title={file}>{file||'Select a file'}</span></div><div className="toolbar-small"><span>{content?`${content.lines} lines`:''}</span>{file&&<a className="icon-btn" title="View this commit on GitHub" rel="noopener noreferrer" target="_blank" href={`${repo.url}/blob/${repo.commit_sha}/${file.split('/').map(encodeURIComponent).join('/')}`}><ExternalLink size={15}/></a>}<button className="icon-btn" disabled={!content} onClick={async()=>{if(content){await navigator.clipboard.writeText(content.content);setCopied(true);setTimeout(()=>setCopied(false),1500)}}} title="Copy file text"><Copy size={15}/></button>{copied&&<span>Copied</span>}</div></div>
      {content?.partial&&<div className="partial-banner"><AlertTriangle size={15}/> Legacy indexed chunks only: missing lines may be blank. Reindex this commit for complete source snapshots.</div>}
      {fileError?<ErrorPanel message={fileError}/>:loadingFile?<Loading label="Opening source file…"/>:content?<div className="monaco-wrap"><Editor path={file} language={language(file)} value={content.content} onMount={editorMount} theme={document.documentElement.dataset.theme==='light'?'vs':'vs-dark'} loading={<Loading/>} options={{readOnly:true,automaticLayout:true,minimap:{enabled:true},fontSize:12,fontFamily:'"SFMono-Regular",Consolas,"Liberation Mono",monospace',lineHeight:21,scrollBeyondLastLine:false,wordWrap:'off',renderLineHighlight:'all',folding:true,glyphMargin:true,overviewRulerBorder:false,padding:{top:16,bottom:16}}}/></div>:<Empty title="Select a file" description="Choose a file from the tree to inspect its indexed source."/>}</section>
    <aside className="symbols-pane panel"><div className="section-heading"><h3>Outline</h3><span className="tiny-count">{symbols.length}</span></div><div className="symbols-list">{symbols.map(s=><button key={s.id} className="symbol-item" onClick={()=>onSelectionChange({path:file,line:s.start_line})}><Braces size={14}/><span><b>{s.qualified_name}</b><small>{s.kind} · L{s.start_line}–{s.end_line}</small></span><ChevronRight size={14}/></button>)}{!symbols.length&&<div className="micro-muted inset">No extracted symbols in this file.</div>}</div></aside>
  </div>}
  </div>
}
