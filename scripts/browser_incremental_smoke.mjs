// Real production owner session: detect an upstream revision and explicitly update.
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const require=createRequire(resolve('frontend/package.json'));
const {chromium,expect}=require('@playwright/test');
const setup=JSON.parse(readFileSync('.artifacts/private/cognito-incremental-smoke.json','utf8'));
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1400,height:1000}});
const report={real_browser:true,origin:'https://repo-guide-five.vercel.app',checks:{},old_repo_id:setup.old_repo_id};
async function token(){return page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('oidc.user:')).map(k=>JSON.parse(sessionStorage.getItem(k))).find(x=>x.access_token)?.access_token)}
try{
  await page.goto(report.origin);
  await page.getByRole('button',{name:'Sign in securely',exact:true}).click();
  await page.locator('input[name="username"]:visible').first().fill(setup.username);
  await page.locator('input[name="password"]:visible').first().fill(setup.password);
  await page.locator('input[name="signInSubmitButton"]:visible,button[name="signInSubmitButton"]:visible').first().click();
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible({timeout:60000});
  await page.locator('.repo-selector').click();
  await page.locator('.repo-dropdown button').filter({hasText:'markupsafe'}).filter({hasText:'Private'}).click();
  const check=page.waitForResponse(r=>r.url()===setup.api_url+'/repositories/'+setup.old_repo_id+'/check-update'&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Check remote revision',exact:true}).click();
  const checked=await check;if(!checked.ok())throw new Error('Remote check failed');
  const freshness=await checked.json();
  if(freshness.freshness_status!=='update_available'||freshness.remote_sha===setup.old_sha)throw new Error('Real upstream advance not detected');
  report.remote_sha=freshness.remote_sha;
  await expect(page.getByText('Update available',{exact:true})).toBeVisible();
  report.checks.actual_upstream_advance_badge=true;
  const accepted=page.waitForResponse(r=>r.url()===setup.api_url+'/repositories/'+setup.old_repo_id+'/update'&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Update index',exact:true}).click();
  const response=await accepted;if(response.status()!==202)throw new Error('Explicit update was not accepted');
  const job=await response.json();report.job_id=job.id;
  const old=await fetch(setup.api_url+'/api/ui/repositories/'+setup.old_repo_id+'/overview',{headers:{Authorization:'Bearer '+await token()}});
  if(!old.ok()||(await old.json()).commit_sha!==setup.old_sha)throw new Error('Old index unavailable during update');
  report.checks.old_index_usable_during_update=true;
  await expect(page.getByRole('button',{name:'Explore indexed repository',exact:true})).toBeVisible({timeout:900000});
  await page.getByRole('button',{name:'Explore indexed repository',exact:true}).click();
  await expect(page.getByText(freshness.remote_sha.slice(0,10),{exact:false}).first()).toBeVisible({timeout:30000});
  report.checks.new_revision_visible=true;
  await page.screenshot({path:'.artifacts/live-incremental-update.png',fullPage:true});
  report.passed=true;
}catch(error){report.error=error.message;report.passed=false;throw error}
finally{writeFileSync('.artifacts/product-incremental-browser.json',JSON.stringify(report,null,2));await browser.close()}
console.log(JSON.stringify(report));
