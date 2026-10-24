import { AlertCircle, CheckCircle2, CircleDashed, LoaderCircle, RefreshCw, X } from 'lucide-react';
import type { ReactNode } from 'react';

export function Loading({label='Loading…'}:{label?:string}){return <div className="state state-loading"><LoaderCircle className="spin" size={18}/><span>{label}</span></div>}
export function Empty({title,description,action}:{title:string;description:string;action?:ReactNode}){return <div className="empty"><CircleDashed size={28}/><h3>{title}</h3><p>{description}</p>{action}</div>}
export function ErrorPanel({message,retry}:{message:string;retry?:()=>void}){return <div className="error-panel"><AlertCircle size={16}/><span>{message}</span>{retry&&<button className="subtle-btn" onClick={retry}><RefreshCw size={14}/> Retry</button>}</div>}
export function Status({status}:{status:string}){return <span className={'status-badge '+(status==='indexed'||status==='complete'||status==='answered'?'success':status==='failed'?'failure':'waiting')}><span className="status-dot"/>{status}</span>}
export function PaneTitle({eyebrow,title,detail,right}:{eyebrow?:string;title:string;detail?:string;right?:ReactNode}){return <header className="pane-title"><div>{eyebrow&&<div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2>{detail&&<p>{detail}</p>}</div>{right&&<div className="pane-actions">{right}</div>}</header>}
export function Dialog({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){return <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}><div className="modal" role="dialog" aria-modal="true" aria-label={title}><header><h3>{title}</h3><button className="icon-btn" title="Close" onClick={onClose}><X size={17}/></button></header>{children}</div></div>}
export function ResultNotice({message,good}:{message:string;good?:boolean}){return <div className={'notice '+(good?'good':'')}><CheckCircle2 size={16}/>{message}</div>}
export function Metric({label,value,note}:{label:string;value:string|number;note?:string}){return <div className="metric"><span>{label}</span><strong>{value}</strong>{note&&<small>{note}</small>}</div>}
export const fmt=(n:number|undefined|null)=>typeof n==='number'?Intl.NumberFormat('en-US').format(n):'—';
export const compact=(n:number|undefined|null)=>typeof n==='number'?Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(n):'—';
