import {requireAuthHeaders} from './auth';
import type { Answer, CodeSymbol, Dependency, EvalCase, EvalCatalog, FileResponse, GraphData, Job, Overview, Repo, RepoFile } from './types';

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
  repos:()=>json<Repo[]>(`${ui}/repositories`),
  workerStatus:()=>json<{paused:boolean;desired:number;running:number;queued:number;inflight:number;local?:boolean}>(`${ui}/worker-control`),
  workerAction:(action:'wake'|'sleep')=>json<{paused:boolean;desired:number;running:number;queued:number;inflight:number}>(`${ui}/worker-control`,{method:'POST',body:JSON.stringify({action})}),
  overview:(id:string)=>json<Overview>(`${repo(id)}/overview`),
  files:(id:string)=>json<RepoFile[]>(`${repo(id)}/files`),
  file:(id:string,path:string)=>json<FileResponse>(`${repo(id)}/file?path=${encodeURIComponent(path)}`),
  symbols:(id:string,path:string)=>json<CodeSymbol[]>(`${repo(id)}/symbols-in-file?path=${encodeURIComponent(path)}`),
  graph:(id:string,limit=600)=>json<GraphData>(`/repositories/${encodeURIComponent(id)}/graph?limit=${limit}`),
  dependencies:(id:string)=>json<Dependency[]>(`/repositories/${encodeURIComponent(id)}/dependencies`),
  job:(id:string)=>json<Job>(`${ui}/jobs/${encodeURIComponent(id)}`),
  index:(url:string,force=false)=>json<Job>(`${ui}/index-jobs`,{method:'POST',body:JSON.stringify({url,force})}),
  catalog:()=>json<EvalCatalog>(`${ui}/evaluations`),
  report:(name:string)=>json<{name:string;results:EvalCase[]}>(`${ui}/evaluations/reports/${encodeURIComponent(name)}`),
  evaluate:(repo_id:string,dataset:string,limit:number)=>json<Job>(`${ui}/evaluation-jobs`,{method:'POST',body:JSON.stringify({repo_id,dataset,limit})}),
  ask:(id:string, payload:{question:string;top_k:number;docs_policy:string;retrieval_mode:string;answer_depth:string})=>
    json<Answer>(`/repositories/${encodeURIComponent(id)}/ask/robust`,{method:'POST',body:JSON.stringify(payload)}),
  feedback:(trace_id:string,rating:number,category:string,comment='')=>json<{recorded:boolean}>('/feedback',{method:'POST',body:JSON.stringify({trace_id,rating,category,comment})}),
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
