// Hosted browser acceptance. Real OAuth and API traffic; no mocked responses.
import {createRequire} from 'node:module';
import {existsSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const require=createRequire(resolve('frontend/package.json'));
const {chromium,expect}=require('@playwright/test');
const preview=JSON.parse(readFileSync('.artifacts/vercel-preview.json','utf8'));
const origin=process.argv.slice(2).find(x=>!x.startsWith('--'))||preview.url;
const readonly=process.argv.includes('--readonly');
const creds=JSON.parse(readFileSync('.artifacts/private/cognito-admin.json','utf8'));
const outputs=JSON.parse(execFileSync('terraform',['-chdir=infra/terraform','output','-json'],{encoding:'utf8'}));
const api=outputs.api_url.value;
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1500,height:1000}});
const page=await context.newPage();
const label=origin===preview.url?'preview':'production';
const report={live_vercel:true,live_cognito:true,live_aws:true,origin,readonly,checks:{}};
const posts=[],csp=[],pageErrors=[];
let startedCompute=false,createdConversation=null;
if(origin===preview.url){
  const path='.artifacts/private/vercel-smoke-bypass.json';
  if(existsSync(path)){
    const bypass=JSON.parse(readFileSync(path,'utf8')).secret;
    await context.request.get(origin,{headers:{'x-vercel-protection-bypass':bypass,'x-vercel-set-bypass-cookie':'true'},maxRedirects:0});
    await context.route(origin+'/**',route=>route.continue({headers:{...route.request().headers(),'x-vercel-protection-bypass':bypass}}));
  }
}
page.on('request',r=>{if(r.url().startsWith(api)&&r.method()==='POST')posts.push(new URL(r.url()).pathname)});
page.on('pageerror',e=>pageErrors.push(e.name));
page.on('console',m=>{if(m.type()==='error'&&m.text().includes('Content Security Policy'))csp.push(m.text().slice(0,180))});
async function token(){return page.evaluate(()=>{for(const k of Object.keys(sessionStorage)){if(k.startsWith('oidc.user:')){const x=JSON.parse(sessionStorage.getItem(k));if(x.access_token)return x.access_token}}return null})}
async function palette(name){await page.keyboard.press('ControlOrMeta+k');await page.getByRole('combobox').fill(name);await page.getByRole('option').filter({hasText:name}).first().click()}
try{
  const health=await fetch(api+'/health');if(!health.ok)throw new Error('API health failed');
  report.release_id=(await health.json()).release;
  const manifest=JSON.parse(readFileSync('.artifacts/release-manifest.json','utf8'));
  if(report.release_id!==manifest.release_id)throw new Error('Backend differs from tested manifest');
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.getByRole('button',{name:'Sign in securely',exact:true}).click();
  await page.locator('input[name="username"]:visible').first().fill(creds.username);
  await page.locator('input[name="password"]:visible').first().fill(creds.password);
  await page.locator('input[name="signInSubmitButton"]:visible,button[name="signInSubmitButton"]:visible').first().click();
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible({timeout:60000});
  report.checks.real_cognito_authorization_code_login=true;
  await page.locator('.repo-selector').click();
  await page.locator('.repo-dropdown button').filter({hasText:'notnikhilreddy/RepoGuide'}).first().click();
  await page.getByRole('button',{name:'Code explorer',exact:true}).click();
  await page.getByPlaceholder('Filter files…').fill('indexer.py');
  await page.getByTitle('src/repoguide/indexer.py',{exact:true}).click();
  await expect(page.locator('.monaco-editor').first()).toBeVisible({timeout:45000});
  await expect(page.locator('.view-lines')).toContainText('from typing',{timeout:30000});
  await expect(page.locator('.symbols-list')).toContainText('index_repository');
  await expect(page.getByRole('button',{name:'Ask about this'})).toBeVisible();
  report.checks.monaco_exact_source_and_symbols=true;
  await page.screenshot({path:'.artifacts/live-'+label+'-explorer.png',fullPage:true});
  await page.getByRole('button',{name:'Architecture',exact:true}).click();
  await expect(page.locator('.module-card').first()).toBeVisible();
  expect(await page.locator('.module-card').count()).toBeLessThanOrEqual(60);
  report.checks.bounded_architecture=true;
  await palette('Dependencies');await expect(page.locator('.dep-row').first()).toBeVisible();report.checks.dependencies=true;
  await palette('Evaluation reports');await expect(page.getByRole('heading',{name:'Evaluation Lab',exact:true})).toBeVisible();report.checks.evaluation_browsing=true;
  if(posts.some(p=>p.startsWith('/api/compute/')||p.includes('index-jobs')||p.includes('ask-jobs')))throw new Error('Browsing started compute or jobs');
  report.checks.browsing_never_starts_compute=true;
  if(!readonly){
    const statusResponse=await fetch(api+'/api/compute/status',{headers:{Authorization:'Bearer '+await token()}});
    const status=await statusResponse.json();
    if(status.workers.answer.desired_state==='off'){
      await page.getByRole('button',{name:'Start answer worker',exact:true}).click();startedCompute=true;
    }
    await expect(page.locator('.worker-pill').first()).toContainText('Running',{timeout:240000});
    report.checks.independent_explicit_ui_start=true;
    await page.getByRole('button',{name:'Conversations',exact:true}).click();
    await page.getByRole('button',{name:'New chat',exact:true}).click();
    await page.getByRole('button',{name:'Options',exact:true}).click();
    await page.locator('.conversation-options select').first().selectOption('never');
    await page.getByLabel('Ask a question').fill('How does index_repository commit database changes and roll back failures?');
    execFileSync('.venv/bin/python',['scripts/acceptance_budget.py','browser-'+label],{stdio:'pipe'});
    await page.getByRole('button',{name:'Send question',exact:true}).click();
    await expect(page.locator('.conversation-assistant')).toBeVisible({timeout:180000});
    await expect(page.locator('.inline-citation').first()).toBeVisible();
    const active=await page.evaluate(()=>Object.entries(localStorage).find(([k])=>k.startsWith('rg.active-conversation.'))?.[1]);
    createdConversation=active;
    if(!createdConversation)throw new Error('No saved conversation identity');
    const savedResponse=await fetch(api+'/api/conversations/'+createdConversation,{headers:{Authorization:'Bearer '+await token()}});
    const saved=await savedResponse.json();
    if(!savedResponse.ok||!saved.messages.some(m=>m.answer?.sources?.length))throw new Error('Answer/citations were not saved');
    report.checks.live_s3_answer_and_citations=true;
    await page.locator('.inline-citation').filter({hasText:/^S\d+$/}).first().click();
    await expect(page.getByRole('dialog',{name:'Sources'})).toBeVisible();
    await expect(page.getByRole('link',{name:'GitHub at this commit'})).toHaveAttribute('href',/\/blob\/[0-9a-f]{40}\/.+#L\d+-L\d+/);
    report.checks.commit_pinned_citation_navigation=true;await page.keyboard.press('Escape');
    await page.getByRole('button',{name:'Helpful',exact:true}).click();await expect(page.getByText('Marked helpful')).toBeVisible();report.checks.linked_feedback=true;
    await page.reload();await page.getByRole('button',{name:'Conversations',exact:true}).click();await expect(page.locator('.conversation-assistant')).toBeVisible();report.checks.refresh_restores_answer=true;
    execFileSync('.venv/bin/python',['scripts/acceptance_budget.py','browser-'+label+'-followup'],{stdio:'pipe'});
    await page.getByLabel('Ask a question').fill('What happens if that transaction fails?');await page.getByRole('button',{name:'Send question',exact:true}).click();await expect(page.locator('.conversation-assistant')).toHaveCount(2,{timeout:180000});report.checks.live_followup=true;
    await page.screenshot({path:'.artifacts/live-'+label+'-answer.png',fullPage:true});
  }
  if(csp.length||pageErrors.length)throw new Error('Browser runtime/CSP errors');
  report.checks.no_csp_or_runtime_errors=true;report.passed=true;
}catch(error){report.passed=false;report.error=error.message;await page.screenshot({path:'.artifacts/private/browser-'+label+'-failure.png',fullPage:true}).catch(()=>{});throw error}
finally{
  const access=await token().catch(()=>null);
  if(access&&createdConversation)await fetch(api+'/api/conversations/'+createdConversation,{method:'DELETE',headers:{Authorization:'Bearer '+access}}).catch(()=>{});
  if(startedCompute&&access)await fetch(api+'/api/compute/answer/stop',{method:'POST',headers:{Authorization:'Bearer '+access,'Content-Type':'application/json'},body:JSON.stringify({force:!report.passed})}).catch(()=>{});
  report.posts=posts;report.csp_errors=csp;report.page_error_types=pageErrors;
  writeFileSync('.artifacts/browser-'+label+'-smoke.json',JSON.stringify(report,null,2));await browser.close();
}
console.log(JSON.stringify(report));
