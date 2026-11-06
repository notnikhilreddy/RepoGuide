import {requireAuthHeaders} from './auth';
import type { Answer, CodeSymbol, ComputeStatus, Dependency, EvalCase, EvalCatalog, FileResponse, GraphData, Job, Overview, Repo, RepoFile,Conversation,ConversationSummary,AskOptions,Architecture,IndexHealth,Usage } from './types';
import {localConversations,localConversation,createLocal,deleteLocal,saveLocal} from './local-conversations';
import {localArchitecture} from './architecture';
export const hosted=Boolean(import.meta.env.VITE_API_BASE_URL);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name='ApiError'; }
}
export async function json<T>(url: string, options?: RequestInit): Promise<T> {
  const headers=await requireAuthHeaders();
  const base=import.meta.env.VITE_API_BASE_URL || '';
  const response=await fetch(`${base}${url}`,{...options,headers:{'Content-Type':'application/json',...headers,...options?.headers}});
  if (!response.ok) {
    let reason = `${response.status} ${response.statusText}`;
    try { const body=await response.json(); reason=typeof body.detail==='string'?body.detail:reason; } catch { /* not JSON */ }
    throw new ApiError(response.status,reason);
  }
  return response.json() as Promise<T>;
}
const ui='/api/ui';
const repo=(id:string)=>`${ui}/repositories/${encodeURIComponent(id)}`;
export const api={
  conversationPage:async(repoId?:string,q='',cursor?:string):Promise<{items:ConversationSummary[];next_cursor:string|null}>=>{
    if(!hosted)return {items:localConversations(repoId,q),next_cursor:null};
    const result=await json<{items:ConversationSummary[];next_cursor:string|null}|ConversationSummary[]>(`/api/conversations?${new URLSearchParams({...(repoId?{repo_id:repoId}:{}),q,page:'1',...(cursor?{cursor}:{})})}`);
    return Array.isArray(result)?{items:result,next_cursor:null}:result;
  },
  conversations:async(repoId?:string,q=''):Promise<ConversationSummary[]> => (await api.conversationPage(repoId,q)).items,

  conversation:(id:string)=>hosted?json<Conversation>(`/api/conversations/${encodeURIComponent(id)}`):Promise.resolve(localConversation(id)),
  newConversation:(repo_id:string)=>hosted?json<Conversation>('/api/conversations',{method:'POST',body:JSON.stringify({repo_id})}):Promise.resolve(createLocal(repo_id)),
  renameConversation:(id:string,title:string)=>hosted?json<Conversation>(`/api/conversations/${encodeURIComponent(id)}`,{method:'PATCH',body:JSON.stringify({title})}):Promise.resolve(saveLocal({...localConversation(id),title})),
  deleteConversation:(id:string)=>hosted?json<{deleted:boolean}>(`/api/conversations/${encodeURIComponent(id)}`,{method:'DELETE'}):Promise.resolve(deleteLocal(id)),
  reply:async(id:string,options:AskOptions,message_id:string,signal?:AbortSignal):Promise<{conversation:Conversation;job:Job}>=>{
    if(hosted)return json(`/api/conversations/${encodeURIComponent(id)}/messages`,{method:'POST',body:JSON.stringify({...options,message_id}),signal});
    const document=localConversation(id);const now=Date.now();document.messages.push({id:crypto.randomUUID(),role:'user',content:options.question,created_at:now},{id:message_id,role:'assistant',status:'running',created_at:now});document.active_turn=message_id;if(document.title==='New conversation')document.title=options.question.slice(0,100);saveLocal(document);
    try{const history=document.messages.slice(0,-2).slice(-6).filter(m=>m.role==='user'||m.status==='complete').map(m=>({role:m.role,content:m.role==='user'?(m.content||'').slice(0,800):(m.answer?.answer||'').slice(0,1200),paths:m.answer?.sources.map(s=>s.file_path).slice(0,5)||[]}));const answer=await api.ask(document.repo_id,{...options,history},undefined,signal);document.messages[document.messages.length-1]={id:message_id,role:'assistant',status:'complete',answer,created_at:now};delete document.active_turn;return {conversation:saveLocal(document),job:{id:message_id,kind:'answer',status:'complete',stage:'complete',percent:100,detail:'Complete',result:answer,events:[]}}}catch(error){document.messages[document.messages.length-1].status='failed';document.messages[document.messages.length-1].error=signal?.aborted?'Request interrupted. Your question was saved.':error instanceof Error?error.message:'Request failed';delete document.active_turn;saveLocal(document);throw error}
  },
  cancelJob:(id:string)=>json<Job>(`/api/ui/jobs/${encodeURIComponent(id)}/cancel`,{method:'POST',body:'{}'}),
  architecture:async(id:string,scope='',q='',limit=scope?40:12):Promise<Architecture>=>{
    if(hosted)return json<Architecture>(`/repositories/${encodeURIComponent(id)}/architecture?${new URLSearchParams({scope,q,limit:String(limit)})}`);
    const graph=localArchitecture(await api.graph(id,2000),await api.files(id),scope);const nodes=graph.nodes.filter(n=>(n.scope+' '+n.label).toLowerCase().includes(q.toLowerCase()));return {...graph,nodes:nodes.slice(0,limit),total_nodes:nodes.length,truncated:nodes.length>limit};
  },

  indexHealth:(id:string)=>json<IndexHealth>(`/repositories/${encodeURIComponent(id)}/health`),
  checkUpdate:(id:string)=>json<Partial<Repo>>(`/repositories/${encodeURIComponent(id)}/check-update`,{method:'POST',body:'{}'}),
  updateIndex:(id:string)=>json<Job>(`/repositories/${encodeURIComponent(id)}/update`,{method:'POST',body:'{}'}),
  usage:()=>json<Usage>('/api/usage'),
  computeStatus:()=>json<ComputeStatus>('/api/compute/status'),
  computeAction:(kind:'answer'|'index',action:'start'|'stop',force=false)=>json(`/api/compute/${kind}/${action}`,{method:'POST',body:JSON.stringify({force})}),
  repos:()=>json<Repo[]>(`${ui}/repositories?limit=100`),
  overview:(id:string)=>json<Overview>(`${repo(id)}/overview`),
  files:(id:string)=>json<RepoFile[]>(`${repo(id)}/files`),
  file:(id:string,path:string)=>json<FileResponse>(`${repo(id)}/file?path=${encodeURIComponent(path)}`),
  symbols:(id:string,path:string)=>json<CodeSymbol[]>(`${repo(id)}/symbols-in-file?path=${encodeURIComponent(path)}`),
  graph:(id:string,limit=600)=>json<GraphData>(`/repositories/${encodeURIComponent(id)}/graph?limit=${limit}`),
  dependencies:(id:string)=>json<Dependency[]>(`/repositories/${encodeURIComponent(id)}/dependencies`),
  indexJobs:()=>json<Job[]>('/api/jobs'),
  job:(id:string)=>json<Job>(`${ui}/jobs/${encodeURIComponent(id)}`),
  index:(url:string,force=false,branch?:string)=>json<Job>(`${ui}/index-jobs`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({url,force,...(branch?.trim()?{branch:branch.trim()}:{})})}),
  catalog:()=>json<EvalCatalog>(`${ui}/evaluations`),
  report:(name:string)=>json<{name:string;results:EvalCase[]}>(`${ui}/evaluations/reports/${encodeURIComponent(name)}`),
  evaluate:(repo_id:string,dataset:string,limit:number)=>json<Job>(`${ui}/evaluation-jobs`,{method:'POST',body:JSON.stringify({repo_id,dataset,limit})}),
  ask:async(id:string, payload:AskOptions & {history?:Record<string,unknown>[]},onStage?:(stage:string)=>void,signal?:AbortSignal):Promise<Answer>=>{
    if(!import.meta.env.VITE_API_BASE_URL)return json<Answer>(`/repositories/${encodeURIComponent(id)}/ask/robust`,{method:'POST',body:JSON.stringify(payload),signal});
    let job=await json<Job>('/ask-jobs',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({...payload,repo_id:id}),signal});
    while(!['complete','failed','cancelled'].includes(job.status)){
      onStage?.(job.stage);
      await new Promise<void>((resolve,reject)=>{if(signal?.aborted){reject(new DOMException('Polling stopped','AbortError'));return}const stop=()=>{clearTimeout(timer);reject(new DOMException('Polling stopped','AbortError'))};const timer=window.setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve()},2000);signal?.addEventListener('abort',stop,{once:true})});
      job=await json<Job>(`${ui}/jobs/${encodeURIComponent(job.id)}`,{signal});
    }
    if(job.status!=='complete'||!job.result?.answer)throw new Error(job.error||job.detail||'Answer job failed');
    return job.result as Answer;
  },
  feedback:(job_id:string,rating:number,category:string,conversation_id?:string,message_id?:string)=>json<{recorded:boolean}>('/feedback',{method:'POST',body:JSON.stringify({job_id,rating,category,conversation_id,message_id})}),
};

export async function streamAnswer(id:string,payload:object,
  onEvent:(event:string,data:Record<string,unknown>)=>void,signal:AbortSignal) {
  // AWS API Gateway HTTP API + Mangum buffers the response. Use robust JSON in cloud.
  const base=import.meta.env.VITE_API_BASE_URL || '';
  const headers=await requireAuthHeaders();
  const response=await fetch(`${base}/repositories/${encodeURIComponent(id)}/ask/stream`,{
    method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(payload),signal,
  });
  if(!response.ok) throw new ApiError(response.status,`Stream request failed (${response.status})`);
  if(!response.body) throw new Error('Streaming not supported in this browser');
  const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
  try {
    while(true){
      const {value,done}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true}).replace(/\r\n/g,'\n');
      let idx;
      while((idx=buffer.indexOf('\n\n'))!==-1){
        const block=buffer.slice(0,idx);buffer=buffer.slice(idx+2);
        const event=block.split('\n').find(x=>x.startsWith('event:'))?.slice(6).trim()||'message';
        const raw=block.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');
        if(raw){try{onEvent(event,JSON.parse(raw) as Record<string,unknown>);}catch{/* malformed event ignored */}}
      }
    }
  } finally {reader.releaseLock();}
}
