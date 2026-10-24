import {useEffect,useMemo,useState} from 'react';
import {Bar,BarChart,CartesianGrid,Legend,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import {Activity,ArrowRight,Beaker,CheckCircle2,Clock,FlaskConical,LoaderCircle,Play,RefreshCw,ShieldCheck} from 'lucide-react';
import type {EvalCase,EvalCatalog,Job,Repo} from '../lib/types';
import {api} from '../lib/api';
import {Empty,ErrorPanel,Loading,Metric,PaneTitle,Status} from './Shared';

type Report={name:string;results:EvalCase[];aggregate?:Record<string,Record<string,number>>;details?:Record<string,unknown[]>;notes?:string};
const average=(rows:EvalCase[],key:keyof EvalCase)=>{const vs=rows.map(x=>x[key]).filter((x):x is number=>typeof x==='number');return vs.length?vs.reduce((a,b)=>a+b,0)/vs.length:null};
const pct=(x:number|null)=>x===null?'—':(x*100).toFixed(1)+'%';
export function EvaluationView({repo}:{repo:Repo}){
  const [catalog,setCatalog]=useState<EvalCatalog|null>(null);const [report,setReport]=useState<Report|null>(null);
  const [name,setName]=useState('');const [dataset,setDataset]=useState('m3_cases.json');
  const [job,setJob]=useState<Job|null>(null);const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');const [selected,setSelected]=useState<number|null>(null);
  const [limit,setLimit]=useState(5);const [rev,setRev]=useState(0);
  useEffect(()=>{let active=true;api.catalog().then(x=>{if(!active)return;setCatalog(x);
    if(x.reports.length){const preferred=x.reports.find(r=>r.name==='m7_latest_results.json')||x.reports[0];setName(preferred.name)}
    if(x.datasets.length)setDataset(x.datasets.some(x=>x.name==='m3_cases.json')?'m3_cases.json':x.datasets[0].name)
  }).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[rev]);
  useEffect(()=>{if(!name)return;let active=true;api.report(name).then(x=>{if(active){setReport(x);setSelected(null)}}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[name,rev]);
  useEffect(()=>{if(!job||job.status==='complete'||job.status==='failed')return;
    const timer=window.setInterval(async()=>{try{const updated=await api.job(job.id);setJob(updated);
      if(updated.status==='complete'){setRev(x=>x+1);setName('m7_latest_results.json')}}catch(e){setError(String(e))}},1100);
    return()=>window.clearInterval(timer);
  },[job?.id,job?.status]);
  async function launch(){if(busy)return;setBusy(true);setError('');try{setJob(await api.evaluate(repo.id,dataset,limit))}catch(e){setError(String(e))}finally{setBusy(false)}}
  const agg=report?.aggregate||{};
  const rows=report?.results||[];
  const chartData=Object.entries(agg).map(([mode,m])=>({mode,hit:Math.round((m.hit||0)*100),mrr:Math.round((m.mrr||0)*100),recall:Math.round((m.file_recall||0)*100),p95:Math.round(m.p95_ms||0)}));
  const row=selected===null?null:rows[selected];
  return <div className="page entrance"><PaneTitle eyebrow="QUALITY ENGINEERING" title="Evaluation Lab" detail="Review reproducible retrieval benchmarks, inspect per-question results, and launch a small traced evaluation run." right={<span className="tiny-count"><FlaskConical size={15}/> MLflow-compatible metrics</span>}/>
    <section className="panel eval-run"><div><div className="panel-kicker"><Beaker size={16}/> RUN EVALUATION</div><p>Benchmarks run against the currently selected indexed repository and write per-question trace IDs.</p></div>
      <div className="eval-run-actions"><select aria-label="Evaluation dataset" value={dataset} onChange={e=>setDataset(e.target.value)}>{catalog?.datasets.map(x=><option key={x.name} value={x.name}>{x.name} ({x.cases})</option>)}</select><select aria-label="Number of cases" value={limit} onChange={e=>setLimit(Number(e.target.value))}><option value={3}>3 cases</option><option value={5}>5 cases</option><option value={10}>10 cases</option><option value={20}>20 cases</option></select><button className="primary-btn" onClick={()=>void launch()} disabled={busy||job?.status==='running'||job?.status==='queued'||!catalog?.datasets.length}>{busy?<LoaderCircle className="spin" size={16}/>:<Play size={16}/>} Run benchmark</button></div>
    </section>
    {job&&<div className="panel eval-job"><div className="section-heading"><h3>Active evaluation</h3><Status status={job.status}/></div><p>{job.detail}</p><div className="progress-line"><div style={{width:`${job.percent}%`}}/></div><div className="progress-details"><span>{job.stage}</span><strong>{job.percent}%</strong></div></div>}
    {error&&<ErrorPanel message={error}/>}
    {!catalog?<Loading label="Loading evaluation catalog…"/>:<>
      <div className="report-selector"><div><span className="field-label">SAVED REPORT</span><select aria-label="Saved evaluation report" value={name} onChange={e=>setName(e.target.value)}>{catalog.reports.length===0?<option value="">No reports yet</option>:catalog.reports.map(x=><option key={x.name}>{x.name}</option>)}</select></div><button className="subtle-btn" onClick={()=>setRev(x=>x+1)}><RefreshCw size={15}/> Refresh</button></div>
      {!report?<Empty title="No evaluation report selected" description="Run a benchmark to create the first report, or select an existing one."/>:<>
        <div className="stats-grid"><Metric label="EVALUATED CASES" value={rows.length||Object.values(report.details||{})[0]?.length||0}/><Metric label="HIT@8" value={chartData.length?`${chartData[0].hit}%`:pct(average(rows,'hit_at_8'))}/><Metric label="MRR@8" value={chartData.length?`${chartData[0].mrr}%`:pct(average(rows,'mrr_at_8'))}/><Metric label="LATENCY" value={rows.length?`${Math.round(average(rows,'latency_ms')||0)} ms`:'See chart'}/></div>
        {chartData.length>0&&<section className="panel eval-chart"><div className="section-heading"><h3>Retrieval method comparison</h3><span className="tiny-count">Measured results from {report.name}</span></div>
          <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{top:8,right:14,left:-12,bottom:24}}><CartesianGrid stroke="var(--chart-grid)" vertical={false}/><XAxis dataKey="mode" tick={{fontSize:11,fill:'var(--muted)'}} interval={0} angle={-15} textAnchor="end" height={64}/><YAxis domain={[0,100]} tick={{fontSize:11,fill:'var(--muted)'}}/><Tooltip contentStyle={{background:'var(--surface-raised)',border:'1px solid var(--border)',borderRadius:8,color:'var(--text)'}}/><Legend/><Bar dataKey="hit" name="Hit@8 (%)" fill="#63b9a8" radius={[3,3,0,0]}/><Bar dataKey="mrr" name="MRR@8 (%)" fill="#6f8fdd" radius={[3,3,0,0]}/><Bar dataKey="recall" name="File recall (%)" fill="#d6a767" radius={[3,3,0,0]}/></BarChart></ResponsiveContainer></div>
          {report.notes&&<div className="footnote">{report.notes}</div>}
        </section>}
        {rows.length>0&&<section className="panel"><div className="section-heading"><h3>Case explorer</h3><span className="tiny-count">{rows.length} cases</span></div><div className="eval-cases"><div className="case-list">{rows.map((x,i)=><button className={'case-item '+(selected===i?'active':'')} key={i} onClick={()=>setSelected(i)}><span className="case-index">{String(i+1).padStart(2,'0')}</span><span>{x.question}</span>{typeof x.hit_at_8==='number'&&<span className={'case-score '+(x.hit_at_8?'pass':'fail')}>{x.hit_at_8?'PASS':'MISS'}</span>}</button>)}</div><div className="case-detail">{row?<><div className="field-label">CASE DETAIL</div><h3>{row.question}</h3><div className="case-metrics"><div>Hit@8 <b>{typeof row.hit_at_8==='number'?pct(row.hit_at_8):'—'}</b></div><div>MRR <b>{pct(typeof row.mrr_at_8==='number'?row.mrr_at_8:null)}</b></div><div>Latency <b>{row.latency_ms?Math.round(row.latency_ms)+'ms':'—'}</b></div></div><div className="field-label">EXPECTED FILES</div>{row.expected_paths?.map(x=><code key={x} className="path-chip">{x}</code>)}<div className="field-label divider-label">RETRIEVED FILES</div>{row.observed_paths?.slice(0,8).map(x=><code key={x} className="path-chip">{x}</code>)}{row.answer&&<div className="eval-answer">{row.answer.slice(0,1500)}</div>}{row.trace_id&&<div className="trace-id">Trace: {row.trace_id}</div>}</>:<div className="evidence-empty"><Activity size={23}/><h3>Select a case</h3><p>Inspect individual expected paths, rankings and traces.</p></div>}</div></div></section>}
        {!rows.length&&!chartData.length&&<Empty title="No standardized metrics" description="This report uses an older result schema; run a new evaluation for detailed case metrics."/>}
      </>}
    </>}
    <div className="footnote">Benchmarks can trigger LLM calls and incur cost. The local worker is limited to 20 cases. For automated CI gates, use the Milestone 6 evaluation scripts; public deployment requires authenticated job execution.</div>
  </div>
}
