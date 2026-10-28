import {useEffect,useRef,useState} from 'react';
import ReactMarkdown from 'react-markdown';
import {Activity,ArrowRight,BookOpen,Braces,Check,ChevronDown,Clock3,Copy,ExternalLink,MessageSquareText,Pause,Search,Send,ShieldCheck,ThumbsDown,ThumbsUp,Workflow, Network} from 'lucide-react';
import type {Answer,Repo,Source} from '../lib/types';
import {api,streamAnswer} from '../lib/api';
import {Empty,ErrorPanel,PaneTitle,Status} from './Shared';
const prompts=["How does a repository indexing request reach the database?","Trace the authentication flow across files","Which external libraries are used, and why?"];
const modes=['hybrid','hybrid_rerank','hybrid_graph','dense','graph','keyword','hybrid_graph_rerank'];
export function ChatView({repo,onFile}:{repo:Repo;onFile:(path:string,line?:number)=>void}){
  const [question,setQuestion]=useState('');const [depth,setDepth]=useState('auto');const [mode,setMode]=useState('hybrid');const [docs,setDocs]=useState('auto');
  const [sourceSort,setSourceSort]=useState<'final'|'fusion'|'rerank'|'dense'>('final');
  const [streaming,setStreaming]=useState(!import.meta.env.VITE_API_BASE_URL);const [busy,setBusy]=useState(false);const [answer,setAnswer]=useState<Answer|null>(null);const [previousQuestion,setPreviousQuestion]=useState('');const [step,setStep]=useState('');const [error,setError]=useState('');const [feedback,setFeedback]=useState('');const [expanded,setExpanded]=useState(true);
  const abort=useRef<AbortController|null>(null);
  useEffect(()=>()=>abort.current?.abort(),[]);
  async function send(custom?:string){const text=(custom||question).trim();if(text.length<3||busy)return;
    setQuestion(text);setPreviousQuestion(text);setAnswer(null);setStep('Retrieving repository evidence');setError('');setFeedback('');setBusy(true);
    const payload={question:text,top_k:8,docs_policy:docs,retrieval_mode:mode,answer_depth:depth};
    const controller=new AbortController();abort.current=controller;
    try{
      if(streaming){let received=false;
        await streamAnswer(repo.id,payload,(event,data)=>{
          if(event==='status')setStep(String(data.step||'Processing evidence'));
          if(event==='draft_delta')setStep('Generating answer · final validation pending');
          if(event==='final'){setAnswer(data as unknown as Answer);setStep('');received=true}
          if(event==='error')setError(String(data.message||'Generation failed'));
        },controller.signal);
        if(!received&&!controller.signal.aborted)setError('Stream ended before a validated final answer arrived');
      }else setAnswer(await api.ask(repo.id,payload));
    }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'Request failed')}
    finally{setBusy(false);setStep('');abort.current=null}
  }
  async function rate(rating:number,category:string){if(!answer?.trace_id)return;
    try{await api.feedback(answer.trace_id,rating,category);setFeedback('Feedback linked to MLflow trace.')}catch(e){setFeedback(`Feedback unavailable: ${e instanceof Error?e.message:String(e)}`)}
  }
  // Links to sources are anchored by known source labels, never generated URLs from model content.
  const sourceByLabel=new Map(answer?.sources.map(s=>[s.label,s])||[]);
  const rankedSources=[...(answer?.sources||[])].sort((a,b)=>{
    if(sourceSort==='final')return 0;
    if(sourceSort==='dense')return (a.distance??999)-(b.distance??999);
    if(sourceSort==='fusion')return (b.fusion_score??-1)-(a.fusion_score??-1);
    return (b.rerank_score??-999)-(a.rerank_score??-999);
  });
  const formatted=answer?.answer.replace(/\[(S\d+)\]/g,(_full,label)=>`[${label}](#source-${label})`)||'';
  return <div className="page chat-page entrance"><PaneTitle eyebrow="GROUNDED CODE ASSISTANT" title="Ask RepoGuide" detail="Answers backed by indexed repository evidence, with optional external documentation." right={<span className="tiny-count"><ShieldCheck size={14}/> Evidence-first generation</span>}/>
  <div className="chat-layout"><section className="chat-conversation panel">
    <div className="chat-content">{!previousQuestion&&!answer&&!busy?<div className="chat-welcome"><div className="welcome-icon"><MessageSquareText size={23}/></div><h2>Understand this codebase.</h2><p>Ask architectural questions, trace cross-file behavior, or inspect dependency usage. Every claim can be checked against the indexed evidence.</p><div className="suggestions">{prompts.map(s=><button key={s} onClick={()=>{setQuestion(s);void send(s)}}><span>{s}</span><ArrowRight size={15}/></button>)}</div></div>:<>
      {previousQuestion&&<div className="question-bubble"><span>YOU</span><p>{previousQuestion}</p></div>}
      {busy&&<div className="assistant-loading"><div className={'pulsing-bars '+(step==='external_lookup'?'mcp-pulse':'')}>{step==='external_lookup'?<Network size={20}/>:<><i/><i/><i/></>}</div><div><b>RepoGuide is working</b><span>{step==='external_lookup'?'External MCP documentation lookup':step.replaceAll('_',' ')||'Collecting evidence'}</span><small>Streaming draft output is hidden until citation validation completes.</small></div></div>}
      {error&&<ErrorPanel message={error}/>}
      {answer&&<article className="answer-body"><div className="answer-header"><div className="assistant-icon"><BookOpen size={15}/></div><strong>RepoGuide</strong><Status status={answer.status}/>{answer.cached&&<span className="chip">Cached</span>}</div><div className="markdown-body"><ReactMarkdown components={{a:({href,children})=>href?.startsWith('#source-')?<button className="inline-citation" onClick={()=>{const s=sourceByLabel.get(href.slice(8));if(s)onFile(s.file_path,s.start_line)}}>{children}</button>:<a href={href} target="_blank" rel="noopener noreferrer">{children}</a>}}>{formatted}</ReactMarkdown></div>
        {(answer.limitations?.length||0)>0&&<div className="limit-note"><b>Limitations</b>{answer.limitations?.join(' · ')}</div>}
        <div className="answer-footer">{answer.trace_id&&<span className="trace-id" title={answer.trace_id}><Activity size={13}/> Trace {answer.trace_id.slice(0,12)}</span>}<button className="icon-btn" title="Copy answer" onClick={()=>void navigator.clipboard.writeText(answer.answer)}><Copy size={15}/></button>{answer.trace_id&&<><button className="icon-btn" title="Helpful" onClick={()=>void rate(5,'correct')}><ThumbsUp size={15}/></button><button className="icon-btn" title="Needs improvement" onClick={()=>void rate(2,'incorrect')}><ThumbsDown size={15}/></button></>}</div>
        {feedback&&<div className="micro-muted">{feedback}</div>}
      </article>}
    </>}</div>
    <div className="composer"><div className="composer-options"><label>Retrieval <select value={mode} onChange={e=>setMode(e.target.value)}>{modes.map(x=><option key={x}>{x}</option>)}</select></label><label>Docs <select value={docs} onChange={e=>setDocs(e.target.value)}><option value="auto">Auto</option><option value="never">Never</option><option value="always">Always</option></select></label><label>Detail <select value={depth} onChange={e=>setDepth(e.target.value)}><option value="auto">Auto</option><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label><label className="switch-label"><input type="checkbox" disabled={Boolean(import.meta.env.VITE_API_BASE_URL)} checked={streaming} onChange={e=>setStreaming(e.target.checked)}/> Stream</label></div>
      <div className="composer-text"><textarea aria-label="Ask a question" value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();void send()}}} rows={2} placeholder="Ask how this repository works…"/><button className="send-btn" disabled={question.trim().length<3&&!busy} onClick={()=>{if(busy)abort.current?.abort();else void send()}} title={busy?'Cancel request':'Send'}>{busy?<Pause size={17}/>:<Send size={17}/>}</button></div>
      <div className="composer-hint">Enter to send · Shift + Enter for new line · Evidence is read-only</div>
    </div>
  </section><aside className="evidence-panel panel"><div className="section-heading"><h3>Evidence</h3><span className="tiny-count">{(answer?.sources.length||0)+(answer?.docs_sources.length||0)} sources</span></div>
    {answer?<><div className="evidence-tabs"><button className="active"><Braces size={14}/> Code ({answer.sources.length})</button><button onClick={()=>setExpanded(e=>!e)}><Workflow size={14}/> Trace <ChevronDown size={13}/></button></div>
      <div className="evidence-scroll"><div className="evidence-sort"><span>RANK BY</span><select aria-label="Evidence ranking" value={sourceSort} onChange={e=>setSourceSort(e.target.value as typeof sourceSort)}><option value="final">Final order</option><option value="fusion">RRF score</option><option value="rerank">Rerank score</option><option value="dense">Cosine distance</option></select></div>{rankedSources.map((s,i)=><button className="evidence-card" key={`${s.label}-${i}`} onClick={()=>onFile(s.file_path,s.start_line)}><div><span className="source-label">{s.label}</span><span className="evidence-path">{s.file_path.split('/').pop()}</span><ArrowRight size={14}/></div><p>{s.symbol_name||s.file_path}</p><footer><span>Lines {s.start_line}–{s.end_line}</span><span>{s.origin||s.channels?.join(' + ')||'retrieval'}</span></footer></button>)}
      {answer.docs_sources.length>0&&<><div className="field-label divider-label">EXTERNAL DOCUMENTATION</div>{answer.docs_sources.map(s=><a key={s.label} className="evidence-card doc-card" href={s.url} target="_blank" rel="noopener noreferrer"><div><span className="source-label docs">{s.label}</span><span className="evidence-path">{s.library}</span><ExternalLink size={14}/></div><p>{s.title}</p></a>)}</>}
      {expanded&&answer.trace?.length>0&&<><div className="field-label divider-label">PIPELINE TRACE</div>{answer.trace.map((s,i)=><div className="trace-row" key={i}><span className="trace-pip"/><span>{s}</span></div>)}</>}
      {answer.sources.length===0&&answer.docs_sources.length===0&&<Empty title="No evidence" description="The system returned no supported sources."/>}</div>
    </>:<div className="evidence-empty"><Search size={25}/><h3>Evidence appears here</h3><p>Relevant files, documentation and pipeline steps will accompany each validated answer.</p></div>}
  </aside></div>
  </div>
}
