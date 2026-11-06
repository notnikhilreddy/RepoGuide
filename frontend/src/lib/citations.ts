import type {Answer} from './types';
export function citationMarkdown(answer:Answer){
  const labels=new Set([...answer.sources,...answer.docs_sources].map(s=>s.label));
  return answer.answer.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map(part=>part.startsWith('`')?part:part.replace(/\[([SD]\d+)\](?!\()/g,(full,label:string)=>labels.has(label)?`[${label}](#citation-${label})`:full)).join('');
}
export function safeSourceUrl(value?:string):string|undefined{try{const url=new URL(value||'');return url.protocol==='https:'&&!url.username&&!url.password?url.href:undefined}catch{return undefined}}
