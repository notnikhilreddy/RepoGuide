import {test,expect,type Page} from '@playwright/test';
import {randomUUID} from 'node:crypto';
const id='12345678-1234-4234-8234-123456789abc';
const counts={chunks:5,symbols:3,edges:2,dependencies:1,files:3};
const source={label:'S1',repo_id:id,commit_sha:'a'.repeat(40),file_path:'src/indexer.py',symbol_name:'index_repository',start_line:1,end_line:2,url:'https://github.com/example/project/blob/'+ 'a'.repeat(40)+'/src/indexer.py#L1-L2',excerpt:'def index_repository():\n    return "indexed"'};
const answer={answer:'Indexing commits its transaction. [S1] Official documentation explains transactions. [D1] [Untrusted model link](https://example.invalid/fabricated)',status:'answered',cached:false,trace_id:'fixture-trace',sources:[source],docs_sources:[{label:'D1',library:'sqlalchemy',title:'Transactions',topic:'transactions',url:'https://docs.sqlalchemy.org/en/20/orm/session_transaction.html'}],trace:['retrieval','validation'],diagnostics:{candidate_count:2,selected_count:1,routing:{reason:'Repository evidence is sufficient',sufficient:true,tools:[]},candidates:[{file_path:'src/indexer.py',start_line:1,end_line:2,rerank_score:3.5,selected:true,decision:'selected'}]},timeline:[{name:'retrieval.hybrid',started_ms:0,duration_ms:40,status:'complete'}],usage:{input_tokens:1000,output_tokens:200,estimated_cost_micros:200,latency_ms:2000}};
async function fixture(page:Page,{admin=true,ready=false,hold=false,update=false}={}){
  const posts:string[]=[];const submissions:Record<string,unknown>[]=[];const saved=new Map<string,any>();const jobs=new Map<string,any>();let phase=ready?'ready':'stopped';let indexPolls=0;
  const repo={id,name:'example/project',url:'https://github.com/example/project',commit_sha:'a'.repeat(40),status:'indexed',counts,visibility:'shared',can_update:admin,monitored_branch:'main',freshness_status:update?'update_available':'up_to_date',remote_sha:update?'b'.repeat(40):'a'.repeat(40)};
  const files=[{path:'src/indexer.py',bytes:80,exact:true,chunks:2},{path:'tests/test_indexer.py',bytes:70,exact:true,chunks:2},{path:'pyproject.toml',bytes:30,exact:true,chunks:1}];
  const modules=[{id:'src',scope:'src',label:'src',kind:'module',files:1,symbols:1,preview_path:'src/indexer.py'},{id:'tests',scope:'tests',label:'tests',kind:'module',files:1,symbols:1,preview_path:'tests/test_indexer.py'},{id:'@root',scope:'@root',label:'Repository files',kind:'module',files:1,symbols:0,preview_path:'pyproject.toml'}];
  await page.route('http://127.0.0.1:8899/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();let body:any={};let status=200;
    if(method==='OPTIONS'){await route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,POST,PATCH,DELETE,OPTIONS'}});return}
    if(method==='POST')posts.push(path);
    if(path==='/api/compute/status')body={admin,workers:Object.fromEntries(['answer','index'].map(kind=>[kind,{kind,desired_state:phase==='stopped'?'off':'on',observed_state:phase,pending:0,queued:0,inflight:0,delayed:0}]))};
    else if(path.startsWith('/api/compute/')){if(!admin){status=403;body={detail:'Administrator permissions required'}}else{phase=path.endsWith('start')?'loading':'stopped';body={observed_state:phase}}}
    else if(path==='/api/ui/repositories')body=[repo];
    else if(path.endsWith('/overview'))body={...repo,languages:{python:2},edge_types:{calls:2},has_exact_sources:true,summary:'Three files define the source, tests and dependency manifest.',modules,entrypoints:[],tech_stack:[{name:'sqlalchemy',spec:'2',manifest:'pyproject.toml',group:'runtime'}],suggested_questions:['How does src/indexer.py persist its index?']};
    else if(path.endsWith('/files'))body=files;
    else if(path.endsWith('/file'))body={path:url.searchParams.get('path'),content:'def index_repository():\n    return "indexed"\n',partial:false,lines:3,byte_count:55};
    else if(path.endsWith('/symbols-in-file'))body=[{id:'s1',name:'index_repository',qualified_name:'index_repository',kind:'function',start_line:1,end_line:2}];
    else if(path.endsWith('/architecture')){const scope=url.searchParams.get('scope')||'';body=scope?{scope,nodes:[{id:scope+'/indexer.py',scope:scope+'/indexer.py',label:'indexer.py',kind:'file',files:1,symbols:1,preview_path:scope+'/indexer.py'}],edges:[],truncated:false,total_nodes:1}:{scope:'',nodes:modules,edges:[{source:'tests',target:'src',kind:'calls',count:2}],truncated:false,total_nodes:3}}
    else if(path.endsWith('/dependencies'))body=[{name:'sqlalchemy',spec:'2',manifest:'pyproject.toml',group:'runtime'}];
    else if(path.endsWith('/check-update'))body={freshness_status:repo.freshness_status,remote_sha:repo.remote_sha,monitored_branch:'main',checked_at:Math.floor(Date.now()/1000)};
    else if(path.endsWith('/health'))body={commit_sha:repo.commit_sha,branch:'main',status:'indexed',indexed_at:new Date().toISOString(),diagnostics_available:true,indexed_files:3,chunks:5,embedded_chunks:3,reused_chunks:2,warnings:[]};
    else if(path.endsWith('/update')){status=202;body={id:'index-job',kind:'index',status:'queued',stage:'queued',percent:0,detail:'Queued',events:[]}}
    else if(path==='/api/ui/jobs/index-job'){indexPolls++;body={id:'index-job',kind:'index',status:indexPolls>1?'complete':'running',stage:indexPolls>1?'complete':'embedding',percent:indexPolls>1?100:60,detail:indexPolls>1?'Complete':'Reusing unchanged chunks',events:[],result:indexPolls>1?{repo_id:id}:null}}
    else if(path==='/api/conversations'&&method==='GET')body=[...saved.values()].map(({id,repo_id,title,updated_at})=>({id,repo_id,title,updated_at}));
    else if(path==='/api/conversations'&&method==='POST'){const data=req.postDataJSON();const conversation={id:randomUUID(),repo_id:data.repo_id,title:'New conversation',updated_at:Date.now(),version:1,messages:[]};saved.set(conversation.id,conversation);body=conversation;status=201}
    else if(/^\/api\/conversations\/[^/]+\/messages$/.test(path)){const conversation=saved.get(path.split('/')[3]),data=req.postDataJSON();submissions.push(data);const job={id:randomUUID(),kind:'answer',status:'queued',stage:'queued',percent:0,detail:'Queued',events:[],polls:0};jobs.set(job.id,job);conversation.messages.push({id:randomUUID(),role:'user',content:data.question,created_at:Date.now()},{id:data.message_id,role:'assistant',status:'queued',created_at:Date.now(),job_id:job.id});conversation.title=conversation.title==='New conversation'?data.question:conversation.title;conversation.active_turn=data.message_id;body={conversation,job};status=202}
    else if(/^\/api\/conversations\/[^/]+$/.test(path)){const conversation=saved.get(path.split('/')[3]);if(!conversation){status=404;body={detail:'Conversation not found'}}else if(method==='PATCH'){conversation.title=req.postDataJSON().title;body=conversation}else if(method==='DELETE'){saved.delete(conversation.id);body={deleted:true}}else{const active=conversation.messages.find((m:any)=>m.id===conversation.active_turn);if(active){const job=jobs.get(active.job_id);if(job.status==='cancelled'){active.status='cancelled';delete conversation.active_turn}else{job.polls++;active.status='running';active.stage=job.polls<2?'retrieval':job.polls<3?'reranking':'generation';if(!hold&&job.polls>3){active.status='complete';active.answer=answer;delete conversation.active_turn;job.status='complete';job.result=answer}}}body=conversation}}
    else if(path.endsWith('/cancel')){const job=jobs.get(path.split('/')[4]);if(job){job.status='cancelled';body=job}else{status=404;body={detail:'Job not found'}}}
    else if(path==='/feedback')body={recorded:true};
    else if(path==='/api/usage')body={days:[{catalog_sk:'usage#2026-11-05',answers:2,input_tokens:1000,output_tokens:200,estimated_cost_micros:200,latency_ms:2000,indexed_files:3,reused_chunks:2}],cost_is_estimate:true};
    else if(path==='/api/ui/evaluations')body={datasets:[],reports:[]};
    else{status=404;body={detail:'Unknown fixture route: '+path}}
    await route.fulfill({status,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'},body:JSON.stringify(body)});
  });
  return {posts,submissions,saved};
}

async function ask(page:Page,question='How does indexing commit data?'){
  await page.getByRole('button',{name:'Conversations',exact:true}).click();
  await page.getByLabel('Ask a question').fill(question);
  await page.getByRole('button',{name:'Send question',exact:true}).click();
}

test('browsing never starts compute; header controls require explicit admin action',async({page})=>{
  const {posts}=await fixture(page);await page.goto('/');await expect(page.getByRole('button',{name:'Start answer worker'})).toBeVisible();
  await page.getByRole('button',{name:'Architecture',exact:true}).click();await expect(page.locator('.module-card')).toHaveCount(3);
  expect(posts.filter(p=>p.startsWith('/api/compute/'))).toEqual([]);
  await page.getByRole('button',{name:'Start answer worker'}).click();await expect(page.locator('.worker-pill').first()).toContainText('Starting');
  expect(posts.filter(p=>p.startsWith('/api/compute/'))).toEqual(['/api/compute/answer/start']);
});

test('ordinary users see worker states and cannot start compute',async({page})=>{
  await fixture(page,{admin:false});await page.goto('/');await expect(page.locator('.worker-pill').first()).toContainText('Stopped');await expect(page.getByRole('button',{name:/Start .* worker/})).toHaveCount(0);
  const status=await page.evaluate(async()=>(await fetch('http://127.0.0.1:8899/api/compute/index/start',{method:'POST'})).status);expect(status).toBe(403);
});

test('conversations survive refresh, show validated citations, and accept follow-ups',async({page})=>{
  const {submissions,saved}=await fixture(page,{ready:true});await page.goto('/');await ask(page);await expect(page.locator('.conversation-assistant')).toContainText('Indexing commits its transaction.',{timeout:20000});
  await expect(page.locator('a[href="https://example.invalid/fabricated"]')).toHaveCount(0);
  await expect(page.getByRole('link',{name:'D1',exact:true})).toHaveAttribute('href','https://docs.sqlalchemy.org/en/20/orm/session_transaction.html');
  await page.locator('.inline-citation').filter({hasText:'S1'}).click();await expect(page.getByRole('dialog',{name:'Sources'})).toBeVisible();await expect(page.getByRole('link',{name:'GitHub at this commit'})).toHaveAttribute('href',source.url);await page.keyboard.press('Escape');
  await page.reload();await page.getByRole('button',{name:'Conversations',exact:true}).click();await expect(page.locator('.conversation-assistant')).toContainText('Indexing commits its transaction.');
  await page.getByLabel('Ask a question').fill('What happens if it fails?');await page.getByRole('button',{name:'Send question',exact:true}).click();await expect(page.locator('.conversation-assistant')).toHaveCount(2,{timeout:20000});
  expect(submissions).toHaveLength(2);expect([...saved.values()][0].messages.filter((m:any)=>m.role==='user')).toHaveLength(2);
  await page.screenshot({path:'../.artifacts/product-chat-desktop.png',fullPage:true});
});

test('stopping an accepted job preserves its question and recovers after refresh',async({page})=>{
  await fixture(page,{ready:true,hold:true});await page.goto('/');await ask(page,'Explain the durable job flow');await expect(page.getByRole('button',{name:'Stop generation'})).toBeEnabled();await page.reload();await page.getByRole('button',{name:'Conversations',exact:true}).click();await expect(page.locator('.conversation-user')).toContainText('durable job flow');await page.getByRole('button',{name:'Stop generation'}).click();await expect(page.getByText('Generation stopped. Your question is saved.')).toBeVisible();
});

test('history can rename and delete conversations without exposing raw diagnostics by default',async({page})=>{
  await fixture(page,{ready:true});await page.goto('/');await ask(page);await expect(page.locator('.conversation-assistant')).toBeVisible({timeout:20000});await expect(page.locator('.candidate-list')).toHaveCount(0);
  await page.getByLabel('Conversation actions').click();await page.getByRole('button',{name:'Rename conversation',exact:true}).click();await page.getByRole('dialog',{name:'Rename conversation'}).getByRole('textbox').fill('Durable indexing notes');await page.getByRole('button',{name:'Save title'}).click();await expect(page.locator('.conversation-toolbar h2')).toHaveText('Durable indexing notes');
  await page.getByRole('button',{name:'Inspect',exact:true}).click();await expect(page.getByRole('dialog',{name:'Inspect this answer'})).toContainText('Repository evidence is sufficient');await page.keyboard.press('Escape');
  await page.getByLabel('Conversation actions').click();await page.getByRole('button',{name:'Delete conversation',exact:true}).click();await page.getByRole('dialog',{name:'Delete this conversation?'}).getByRole('button',{name:'Delete conversation'}).click();await expect(page.getByText('Follow the code.')).toBeVisible();
});

test('architecture expands stable groups and sends indexed source context into chat',async({page})=>{
  const {submissions}=await fixture(page,{ready:true,hold:true});await page.goto('/');await page.getByRole('button',{name:'Architecture',exact:true}).click();await page.locator('.module-card').filter({has:page.getByRole('heading',{name:'src',exact:true})}).locator('.module-card-main').click();await expect(page.locator('.module-card')).toHaveCount(1);await page.locator('.module-card-main').click();await page.getByRole('button',{name:'Ask about this',exact:true}).click();await expect(page.getByLabel('Ask a question')).toHaveValue(/src\/indexer.py/);await page.getByRole('button',{name:'Send question',exact:true}).click();await expect.poll(()=>submissions.length).toBe(1);expect(submissions[0].focus).toEqual({path:'src/indexer.py'});
});

test('new commits prompt an explicit incremental update rather than automatic indexing',async({page})=>{
  const {posts}=await fixture(page,{update:true,ready:true});await page.goto('/');await expect(page.getByText('Update available',{exact:true})).toBeVisible();expect(posts.filter(p=>p.endsWith('/update'))).toEqual([]);await page.getByRole('button',{name:'Update index',exact:true}).click();await expect(page.getByRole('heading',{name:'Index a repository'})).toBeVisible();await expect(page.getByRole('button',{name:'Explore indexed repository'})).toBeVisible({timeout:15000});expect(posts.filter(p=>p.endsWith('/update'))).toEqual([`/repositories/${id}/update`]);
});

test('command palette supports keyboard navigation and modal focus',async({page})=>{
  await fixture(page);await page.goto('/');await expect(page.getByRole('heading',{name:'project',exact:true})).toBeVisible();await page.keyboard.press('Control+k');const input=page.getByRole('combobox');await expect(input).toBeFocused();await input.fill('Architecture');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');await expect(page.getByRole('heading',{name:'A map you can follow'})).toBeVisible();await page.keyboard.press('Control+k');await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('source explorer loads local workers with no external assets and offers source-to-chat',async({page})=>{
  page.on('pageerror',error=>console.error('Browser error:',error.message));
  const {posts}=await fixture(page);const external:string[]=[];page.on('request',request=>{if(!request.url().startsWith('http://127.0.0.1:'))external.push(request.url())});await page.goto('/');await page.getByRole('button',{name:'Code explorer',exact:true}).click();await expect(page.locator('.monaco-editor').first()).toBeVisible({timeout:30000});await expect(page.locator('.view-lines')).toContainText('index_repository');await expect(page.getByRole('button',{name:'Ask about this'})).toBeVisible();expect(posts.filter(p=>p.startsWith('/api/compute/'))).toEqual([]);expect(external).toEqual([]);
});

test('mobile and reduced-motion browsing fit the viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});await fixture(page);await page.goto('/');await expect(page.getByRole('button',{name:'Open navigation'})).toBeVisible();await page.getByRole('button',{name:'Open navigation'}).click();await page.getByRole('button',{name:'Conversations',exact:true}).click();await expect(page.getByLabel('Ask a question')).toBeVisible();const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);expect(overflow).toBe(false);await page.screenshot({path:'../.artifacts/product-chat-mobile.png',fullPage:true});
});
