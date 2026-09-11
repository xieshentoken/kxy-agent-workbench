/* Deliberately delay the initial credential snapshot; new service must survive it. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE='http://127.0.0.1:8722',DATA='/private/tmp/kxy-v6-browser-data';
const OUT=path.join(__dirname,'v6-evidence','browser-race');fs.mkdirSync(OUT,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 let release;const gate=new Promise(r=>release=r);let captured=false;
 try{
   for(const m of await(await page.request.get(BASE+'/api/agent-models')).json())if(m.alias?.startsWith('V6 Race'))await page.request.delete(BASE+'/api/agent-models/'+m.id);
   for(const s of await(await page.request.get(BASE+'/api/credentials')).json())if(s.name?.startsWith('V6 Race'))await page.request.delete(BASE+'/api/credentials/'+s.id);
   await page.route('**/api/credentials',async route=>{
     if(route.request().method()==='GET'&&!captured){const response=await route.fetch();captured=true;await gate;await route.fulfill({response})}
     else await route.continue();
   });
   await page.goto(BASE);await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:'AI 服务',exact:true}).click();
   const editor=page.locator('.service-editor'),field=name=>editor.getByLabel(name,{exact:false});
   await field('服务名称').fill('V6 Race newly created');
   await field('Endpoint').fill(JSON.parse(fs.readFileSync(path.join(DATA,'fixture-info.json'))).catalog_endpoint);
   await field('API key').fill('V6-fake-race-key');
   const saved=page.waitForResponse(r=>r.url().endsWith('/api/credentials/store'));
   await editor.getByRole('button',{name:'写入 Keychain 并保存',exact:true}).click();const sr=await saved;assert.ok(sr.ok(),await sr.text());const record=await sr.json();
   await page.locator('.service-row').filter({hasText:'V6 Race newly created'}).waitFor();assert.ok(captured);
   await page.getByRole('button',{name:'模型 / API',exact:true}).click();
   const form=page.locator('.settings-model-editor form'),mf=name=>form.getByLabel(name,{exact:false});
   await mf('绑定 Agent').selectOption('codex');await mf('来源').selectOption('api');await mf('服务引用').selectOption(record.id);
   await mf('实际模型标识').fill('fixture-a');await mf('显示 alias').fill('V6 Race newly created model');
   const modelSaved=page.waitForResponse(r=>r.url().endsWith('/api/agent-models')&&r.request().method()==='POST');
   await form.getByRole('button',{name:'创建模型',exact:true}).click();assert.ok((await modelSaved).ok());
   await page.locator('.model-row').filter({hasText:'V6 Race newly created model'}).waitFor();
   const initialArrived=page.waitForResponse(r=>r.url().endsWith('/api/credentials')&&r.request().method()==='GET');
   release();await initialArrived;await page.waitForTimeout(700);
   assert.equal(await page.locator('.model-row').filter({hasText:'V6 Race newly created model'}).count(),1,'late initial refresh discarded newly created Agent model');
   await page.getByRole('button',{name:'AI 服务',exact:true}).click();
   assert.equal(await page.locator('.service-row').filter({hasText:'V6 Race newly created'}).count(),1,'late initial refresh discarded newly created service');
   assert.ok((await(await page.request.get(BASE+'/api/credentials')).json()).some(s=>s.id===record.id));
   await page.screenshot({path:path.join(OUT,'surviving-service.png')});
   fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed:true,scenario:'late initial resource snapshot does not overwrite newly saved service or Agent model'},null,2));
   console.log('PASS late initial resource snapshot does not overwrite newly saved service or Agent model');
 }catch(e){await page.screenshot({path:path.join(OUT,'failure.png')});fs.writeFileSync(path.join(OUT,'failure.txt'),String(e));throw e}
 finally{release();await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
