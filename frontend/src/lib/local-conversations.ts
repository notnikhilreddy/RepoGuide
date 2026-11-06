import type {Conversation,ConversationSummary} from './types';

// Local development has no authenticated S3 service. Hosted builds always use
// the API below; only loopback development uses this explicitly local store.
const key='repoguide.local-conversations.v1';
function read():Conversation[]{try{return JSON.parse(localStorage.getItem(key)||'[]') as Conversation[]}catch{return []}}
export function saveLocal(document:Conversation){const all=read().filter(x=>x.id!==document.id);document.updated_at=Date.now();all.push(document);localStorage.setItem(key,JSON.stringify(all));return document}
export function localConversations(repoId?:string,q=''):ConversationSummary[]{return read().filter(x=>(!repoId||x.repo_id===repoId)&&x.title.toLowerCase().includes(q.toLowerCase())).sort((a,b)=>b.updated_at-a.updated_at)}
export function localConversation(id:string){const document=read().find(x=>x.id===id);if(!document)throw new Error('Conversation not found');return document}
export function createLocal(repoId:string){return saveLocal({id:crypto.randomUUID(),repo_id:repoId,title:'New conversation',version:1,updated_at:Date.now(),messages:[]})}
export function deleteLocal(id:string){localStorage.setItem(key,JSON.stringify(read().filter(x=>x.id!==id)));return {deleted:true}}
