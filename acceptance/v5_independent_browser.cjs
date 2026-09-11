/* Parent-owned V5 UI acceptance against v5_fixture_server.py only. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE=process.env.KXY_BASE_URL||'http://127.0.0.1:8720';
const OUT=path.join(__dirname,'v5-evidence','browser');fs.mkdirSync(OUT,{recursive:true});
const passed=[],errors=[],discovery=[];const mark=x=>{passed.push(x);console.log('PASS',x)};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.url().includes('/discover'))discovery.push(r.url())});
 const editor=()=>page.locator('.settings-editor-card').first().locator('form').first();
 const field=name=>editor().getByLabel(name,{exact:false});
 const chooseModel=async id=>{
   const box=field('实际模型标识');await box.locator('option').filter({hasText:id}).waitFor({state:'attached'});
   const value=await box.locator('option').evaluateAll((list,id)=>list.find(o=>o.textContent.includes(id))?.value,id);
   assert.ok(value,'model option '+id);await box.selectOption(value);
 };
 const optionValues=loc=>loc.locator('option').evaluateAll(os=>os.map(o=>o.value).filter(Boolean));
 const api=async route=>(await page.request.get(BASE+route)).json();
 const openSettings=async()=>{await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:'模型 / API',exact:true}).click()};
 const closeSettings=()=>page.getByTitle('关闭设置',{exact:true}).click();
 const createConfig=async(alias,effort)=>{
   await field('显示 alias').fill(alias);await field('默认 effort').selectOption(effort);
   const response=page.waitForResponse(r=>r.url().endsWith('/api/agent-models')&&r.request().method()==='POST');
   await editor().getByRole('button',{name:'创建模型',exact:true}).click();const r=await response;assert.ok(r.ok(),await r.text());return r.json();
 };
 const exportFlow=async()=>{const pending=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'))};
 const inspector=()=>page.locator('.right-panel');
 const chooseConfigured=async id=>{
   const select=inspector().locator('select').first();
   const value=await select.locator('option').evaluateAll((os,id)=>os.find(o=>o.value===id||o.value.endsWith(id))?.value,id);
   assert.ok(value,'configured analyzer appears in Agent selector');await select.selectOption(value);
 };
 try{
   assert.equal(BASE,'http://127.0.0.1:8720','this fixture test must not target the formal service');
   for(const m of await api('/api/agent-models'))if(m.alias?.startsWith('V5 '))await page.request.delete(BASE+'/api/agent-models/'+m.id);
   await page.goto(BASE);await page.locator('.left-panel').waitFor();await openSettings();
   assert.match(await field('来源').locator('option[value="manual"]').innerText(),/登录态/);
   await chooseModel('fixture-reasoning');assert.ok(discovery.some(u=>u.includes('/codex/discover')));
   assert.deepEqual(await optionValues(field('默认 effort')),['low','high','max']);
   assert.equal(await field('默认 effort').inputValue(),'high');mark('login mode automatically discovers selected Agent models and exact effort options');

   await chooseModel('fixture-quick');assert.deepEqual(await optionValues(field('默认 effort')),['minimal']);assert.equal(await field('默认 effort').inputValue(),'minimal');
   await chooseModel('fixture-unknown');assert.deepEqual(await optionValues(field('默认 effort')),[]);mark('model changes reset effort; unknown capability has only explicit CLI default');
   await chooseModel('fixture-reasoning');const high=await createConfig('V5 慎思','max');assert.equal(high.default_effort,'max');
   await chooseModel('fixture-reasoning');const low=await createConfig('V5 快答','low');assert.notEqual(high.id,low.id);mark('same model creates independent alias and effort configurations');
   await page.locator('.model-row').filter({hasText:'V5 慎思'}).getByTitle('编辑模型',{exact:true}).click();
   await field('显示 alias').fill('V5 慎思 · 已编辑');
   const editedResponse=page.waitForResponse(r=>r.url().endsWith('/api/agent-models/'+high.id)&&r.request().method()==='PUT');
   await editor().getByRole('button',{name:'保存模型',exact:true}).click();const edited=await editedResponse;assert.ok(edited.ok(),await edited.text());assert.equal((await edited.json()).default_effort,'max');mark('editing a saved login configuration successfully persists alias and exact effort');

   await field('绑定 Agent').selectOption('claude');await chooseModel('fixture-claude');assert.deepEqual(await optionValues(field('默认 effort')),['medium']);
   await page.route('**/api/agents/codex/discover',async route=>{await sleep(1300);await route.continue()});
   await field('绑定 Agent').selectOption('codex');await field('绑定 Agent').selectOption('claude');await chooseModel('fixture-claude');await sleep(1900);
   assert.equal(await field('绑定 Agent').inputValue(),'claude');assert.match(await field('实际模型标识').locator('option:checked').innerText(),/fixture-claude/);
   assert.deepEqual(await optionValues(field('默认 effort')),['medium']);await page.unroute('**/api/agents/codex/discover');mark('late discovery response cannot replace another Agent model or effort');

   await field('绑定 Agent').selectOption('opencode');await sleep(500);
   assert.equal((await optionValues(field('实际模型标识'))).length,0);assert.ok(await editor().getByRole('button',{name:'创建模型',exact:true}).isDisabled());mark('empty model catalog explains unavailability and prevents creating invented login entry');
   await field('来源').selectOption('api');assert.equal(await field('实际模型标识').evaluate(e=>e.tagName),'INPUT');
   await field('实际模型标识').fill('synthetic-api-model');assert.ok(await page.getByRole('button',{name:/测试连接/}).count());mark('API mode retains explicit model input and connection test');
   await closeSettings();

   const flow={version:'kxy.workflow.v1',name:'V5 精确绑定验收',nodes:[{id:'analysis',type:'analyzer',position:{x:150,y:150},data:{label:'V5 分析器',cli:'codex',agent_id:'claude',prompt:'SYNTHETIC V5',network:true}}],edges:[]};
   await page.locator('.kxy-app > input[accept="application/json,.json"]').setInputFiles({name:'synthetic-v5.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(flow))});
   await page.getByTitle('自动适配画布',{exact:true}).click();await page.locator('.react-flow__node[data-id="analysis"]').click();
   await chooseConfigured(high.id);
   assert.equal(await inspector().getByLabel('effort',{exact:false}).inputValue(),'max');
   assert.match(await inspector().getByLabel('模型记录',{exact:false}).locator('option:checked').innerText(),/fixture-reasoning/);
   let exported=await exportFlow(),data=exported.nodes[0].data;assert.equal(data.cli,'codex');assert.ok(!data.agent_id||data.agent_id==='codex');assert.equal(data.model_ref,high.id);assert.equal(data.effort,'max');mark('Inspector configured analyzer atomically binds CLI model reference and chosen exact effort');
   await chooseConfigured(low.id);assert.equal(await inspector().getByLabel('effort',{exact:false}).inputValue(),'low');
   await chooseConfigured(high.id);await inspector().getByLabel('effort',{exact:false}).selectOption('low');
   assert.equal((await api('/api/agent-models')).find(m=>m.id===high.id).default_effort,'max');mark('Inspector effort override stays within model capabilities and does not mutate global entry');
   await chooseConfigured(high.id);
   const savedResponse=page.waitForResponse(r=>r.url().endsWith('/api/workflows')&&r.request().method()==='POST');
   await page.locator('.top-actions').getByRole('button',{name:'保存',exact:true}).click();const saved=await(await savedResponse).json();
   await page.reload();await page.getByLabel('打开已保存流程',{exact:true}).selectOption(saved.id);
   await page.locator('.react-flow__node[data-id="analysis"]').click();data=(await exportFlow()).nodes[0].data;
   assert.equal(data.model_ref,high.id);assert.equal(data.effort,'max');
   assert.equal(await inspector().getByLabel('effort',{exact:false}).inputValue(),'max');mark('saved workflow reload preserves exact analyzer selection');
   await page.screenshot({path:path.join(OUT,'inspector.png'),fullPage:true});

   await page.request.delete(BASE+'/api/agent-models/'+high.id);await page.reload();await page.getByLabel('打开已保存流程',{exact:true}).selectOption(saved.id);await page.locator('.react-flow__node[data-id="analysis"]').click();
   assert.match(await inspector().getByLabel('模型记录',{exact:false}).locator('option:checked').innerText(),/不可用|重新绑定/);assert.equal((await exportFlow()).nodes[0].data.model_ref,high.id);mark('deleted model remains explicitly unresolved instead of switching to another analyzer');

   await openSettings();await field('来源').selectOption('manual');await field('绑定 Agent').selectOption('codex');await chooseModel('fixture-reasoning');
   await page.screenshot({path:path.join(OUT,'models.png'),fullPage:true});
   await page.setViewportSize({width:1280,height:720});await page.screenshot({path:path.join(OUT,'models-1280.png'),fullPage:true});
   assert.ok(await editor().isVisible());mark('model configuration is accessible at 1280x720');
   assert.deepEqual(errors,[]);mark('no browser runtime errors');
   fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors},null,2));
 }catch(e){await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});fs.writeFileSync(path.join(OUT,'failure.txt'),await page.locator('body').innerText());fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,failure:String(e)},null,2));throw e}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
