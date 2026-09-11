/* Parent-owned browser acceptance; only the isolated V6 fixture on 8722. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE='http://127.0.0.1:8722',DATA='/private/tmp/kxy-v6-browser-data';
const OUT=path.join(__dirname,'v6-evidence','browser');fs.mkdirSync(OUT,{recursive:true});
const passed=[],errors=[];const mark=x=>{passed.push(x);console.log('PASS',x)};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 page.on('pageerror',e=>errors.push(e.message));
 const sf=()=>page.locator('.service-editor');
 const field=(name,scope=sf())=>scope.getByLabel(name,{exact:false});
 const modelForm=()=>page.locator('.settings-editor-card').first().locator('form').first();
 const mf=name=>field(name,modelForm());
 const inspector=()=>page.locator('.right-panel');
 const get=async route=>(await page.request.get(BASE+route)).json();
 const settings=async tab=>{await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:tab,exact:true}).click()};
 const close=()=>page.getByTitle('关闭设置',{exact:true}).click();
 const exportFlow=async()=>{const pending=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'))};
 const createModel=async(agent,serviceId,alias)=>{
   await mf('绑定 Agent').selectOption(agent);await mf('来源').selectOption('api');
   await mf('服务引用').selectOption(serviceId);
   await mf('服务模型目录').selectOption('fixture-a');await mf('显示 alias').fill(alias);
   const pending=page.waitForResponse(r=>r.url().endsWith('/api/agent-models')&&r.request().method()==='POST');
   await modelForm().getByRole('button',{name:'创建模型',exact:true}).click();
   const response=await pending;assert.ok(response.ok(),await response.text());return response.json();
 };
 try{
   const catalog=JSON.parse(fs.readFileSync(path.join(DATA,'fixture-info.json'),'utf8')).catalog_endpoint;
   for(const model of await get('/api/agent-models'))if(model.alias?.startsWith('V6 Browser'))await page.request.delete(BASE+'/api/agent-models/'+model.id);
   for(const service of await get('/api/credentials'))if(service.name?.startsWith('V6 Browser'))await page.request.delete(BASE+'/api/credentials/'+service.id);
   const grantDir=path.join(DATA,'browser-authorized');fs.mkdirSync(grantDir,{recursive:true});
   const gr=await page.request.post(BASE+'/api/grants',{data:{path:grantDir}});assert.ok(gr.ok());const grant=await gr.json();
   await page.goto(BASE);await page.locator('.left-panel').waitFor();await settings('AI 服务');
   await field('服务名称').fill('V6 Browser Shared Service');
   await field('API 协议').selectOption('openai-responses');
   await field('Endpoint').fill(catalog);await field('API key').fill('V6-fake-browser-key');
   assert.equal(await field('API key').getAttribute('type'),'password');
   const probe=page.waitForResponse(r=>r.url().endsWith('/api/credentials/test'));
   await sf().getByRole('button',{name:/测试.*models/}).click();assert.ok((await probe).ok());
   await sf().locator('.service-model-row').filter({hasText:'fixture-b'}).waitFor();
   await field('搜索服务模型').fill('fixture-b');assert.equal(await sf().locator('.service-model-row').count(),1);
   await sf().locator('.service-model-row').filter({hasText:'fixture-b'}).getByRole('checkbox').uncheck();
   await field('搜索服务模型').fill('');
   await field('添加服务模型 ID').fill('fixture-custom');await sf().getByRole('button',{name:'添加',exact:true}).click();
   mark('standalone service editor fetches, searches, selects and manually extends model catalog');
   const pendingSave=page.waitForResponse(r=>r.url().endsWith('/api/credentials/store'));
   await sf().getByRole('button',{name:'写入 Keychain 并保存',exact:true}).click();
   const sr=await pendingSave;assert.ok(sr.ok(),await sr.text());const service=await sr.json();
   assert.deepEqual(service.models.map(m=>m.id).sort(),['fixture-a','fixture-custom']);
   assert.equal(await field('API key').inputValue(),'');mark('service save persists selected catalog and clears password input');
   await page.locator('.service-row').filter({hasText:'V6 Browser Shared Service'}).getByRole('button',{name:'编辑',exact:true}).click();
   assert.equal(await field('API key').inputValue(),'');
   await field('服务名称').fill('V6 Browser Shared Service Edited');
   const pendingEdit=page.waitForResponse(r=>r.url().endsWith('/api/credentials/'+service.id)&&r.request().method()==='PUT');
   await sf().getByRole('button',{name:'保存服务',exact:true}).click();
   const er=await pendingEdit;assert.ok(er.ok(),await er.text());assert.equal((await er.json()).credential_ref,service.credential_ref);
   mark('blank-key service edit preserves Keychain reference and existing model list');
   await page.locator('.service-row').filter({hasText:'V6 Browser Shared Service Edited'}).getByRole('button',{name:'编辑',exact:true}).click();
   await page.screenshot({path:path.join(OUT,'service-1440.png')});
   await page.setViewportSize({width:1280,height:720});
   await sf().getByRole('button',{name:'保存服务',exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(OUT,'service-1280.png')});
   assert.ok(await sf().getByRole('button',{name:'保存服务',exact:true}).isVisible());
   mark('service editor remains reachable at 1440x900 and 1280x720');
   await page.setViewportSize({width:1440,height:900});await close();await settings('模型 / API');
   const codex=await createModel('codex',service.id,'V6 Browser Codex');
   const pi=await createModel('pi',service.id,'V6 Browser Pi');
   assert.equal(codex.credential_id,pi.credential_id);mark('two Agents reuse one saved service through visible model selectors');
   await mf('绑定 Agent').selectOption('claude');await mf('来源').selectOption('api');
   await page.waitForFunction(id=>document.querySelector('.settings-model-grid .settings-editor-card option[value="'+id+'"]')?.disabled===true,service.id);
   assert.equal(await mf('服务引用').locator('option[value="'+service.id+'"]').evaluate(option=>option.disabled),true);
   mark('incompatible Agent protocol is disabled in service dropdown');
   await close();
   await page.locator('.react-flow__node[data-id="analyzer"]').click();
   await inspector().locator('select').first().selectOption('model:'+codex.id);
   const prompt=inspector().getByLabel('分析提示词',{exact:false});await prompt.fill('V6 Browser literal prompt\n请按我的要求回答。');
   const outputFormat=inspector().locator('select').filter({has:page.locator('option[value="auto"]')});
   assert.equal(await outputFormat.inputValue(),'auto');
   await outputFormat.selectOption('json');await outputFormat.selectOption('auto');
   assert.equal(await prompt.inputValue(),'V6 Browser literal prompt\n请按我的要求回答。');
   await inspector().getByRole('button',{name:'插入工作区提示',exact:true}).click();const expectedPrompt=await prompt.inputValue();
   assert.match(expectedPrompt,/input-context.json/);mark('auto and JSON controls do not rewrite prompt; workspace hints are visibly inserted');
   await page.locator('.react-flow__node[data-id="output"]').click();
   await inspector().locator('.generated-file-list').getByLabel('.pdf',{exact:true}).check();
   await inspector().getByLabel('输出文件夹授权',{exact:false}).selectOption(grant.id);
   const missingTips=await inspector().locator('.generated-file-list label').evaluateAll(items=>items.filter(x=>!x.title).length);
   assert.equal(missingTips,0);
   const workflow=await exportFlow();const output=workflow.nodes.find(n=>n.id==='output').data;
   assert.deepEqual(output.export_formats,[]);assert.deepEqual(output.allowed_file_extensions,['.pdf']);assert.equal(output.grant_id,undefined);
   assert.equal(await inspector().getByLabel('输出文件夹授权',{exact:false}).inputValue(),grant.id);
   assert.ok(!JSON.stringify(workflow).includes('V6-fake-browser-key'));mark('reply and file settings persist; portable export omits local grant and key');
   const pendingRun=page.waitForResponse(r=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');
   await page.locator('.top-actions').locator('button.run-button').click();const rr=await pendingRun;assert.ok(rr.ok(),await rr.text());const rid=(await rr.json()).id;
   let run;for(let i=0;i<200;i++){run=await get('/api/runs/'+rid);if(['succeeded','failed','cancelled'].includes(run.status))break;await page.waitForTimeout(100)}
   assert.equal(run.status,'succeeded',run.error);
   const observed=fs.readFileSync(path.join(DATA,'runs',rid,'workspace','nodes','analyzer','prompt-observed.txt'),'utf8');
   assert.equal(observed,expectedPrompt);mark('browser-configured prompt reaches synthetic CLI byte-for-byte');
   await page.locator('.react-flow__node[data-id="output"]').click();
   await page.waitForTimeout(700);
   const displayed=await inspector().evaluate(el=>el.innerText+'\n'+Array.from(el.querySelectorAll('textarea')).map(x=>x.value).join('\n'));
   assert.match(displayed,/V6 实际文本回复/);
   assert.match(await inspector().locator('.container-reply-card').innerText(),/上游归因：.*analyzer.*codex.*V6 Browser Codex/);
   assert.match(await page.locator('.file-receipt.excluded').innerText(),/data.csv/);
   const destination=run.output_manifest.granted_outputs.find(g=>g.node_id==='output').path;
   const actual=fs.readdirSync(path.join(destination,'files'));assert.equal(actual.length,1);assert.match(actual[0],/\.pdf$/i);
   assert.equal(fs.readFileSync(path.join(destination,'files',actual[0]),'utf8'),'%PDF-1.4\nSYNTHETIC V6 UI FILE');
   await inspector().locator('.container-reply-card').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(OUT,'container-reply.png')});mark('container shows real text and exclusions while authorized directory receives only actual PDF');
   const boxId='box-'+ 'a'.repeat(88);
   const multi={version:'kxy.workflow.v1',name:'V6 two independent output containers',nodes:[
     {id:'text-a',type:'text',position:{x:0,y:0},data:{label:'A source',text:'V6 FIRST CONTAINER REPLY'}},
     {id:'out-a',type:'container',position:{x:260,y:0},data:{label:'A output',export_formats:[],allowed_file_extensions:[]}},
     {id:'text-b',type:'text',position:{x:0,y:160},data:{label:'B source',text:'V6 SECOND CONTAINER REPLY'}},
     {id:'out-b',type:'container',position:{x:260,y:160},data:{label:'B output',export_formats:[],allowed_file_extensions:[]}},
     {id:'text-c',type:'text',position:{x:0,y:320},data:{label:'C source',text:'V6 NESTED CONTAINER REPLY'}},
     {id:boxId,type:'blackbox',position:{x:260,y:320},data:{label:'Nested output',workflow:{version:'kxy.workflow.v1',name:'V6 nested container',nodes:[
       {id:'entry',type:'subflow_input',position:{x:0,y:0},data:{label:'Entry'}},
       {id:'out-a',type:'container',position:{x:260,y:0},data:{label:'Nested A output',export_formats:[],allowed_file_extensions:[]}},
       {id:'exit',type:'subflow_output',position:{x:520,y:0},data:{label:'Exit'}},
     ],edges:[{source:'entry',target:'out-a',sourceHandle:'result',targetHandle:'items'},{source:'out-a',target:'exit',sourceHandle:'result',targetHandle:'items'}]}}},
   ],edges:[{source:'text-a',target:'out-a',sourceHandle:'result',targetHandle:'items'},{source:'text-b',target:'out-b',sourceHandle:'result',targetHandle:'items'},{source:'text-c',target:boxId,sourceHandle:'result',targetHandle:'items'}]};
   const chooser=page.waitForEvent('filechooser');await page.locator('.top-actions').getByRole('button',{name:'导入',exact:true}).click();
   await(await chooser).setFiles({name:'v6-two-containers.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(multi))});
   await page.locator('.react-flow__node[data-id="out-a"]').waitFor();
   const multiPending=page.waitForResponse(r=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');
   await page.locator('.top-actions button.run-button').click();const mr=await multiPending;assert.ok(mr.ok(),await mr.text());const multiId=(await mr.json()).id;
   let multiRun;for(let i=0;i<200;i++){multiRun=await get('/api/runs/'+multiId);if(['succeeded','failed','cancelled'].includes(multiRun.status))break;await page.waitForTimeout(100)}
   assert.equal(multiRun.status,'succeeded',multiRun.error);await page.waitForTimeout(700);
   await page.locator('.react-flow__node[data-id="out-a"]').click();
   assert.equal(await inspector().locator('.container-reply-card textarea').inputValue(),'V6 FIRST CONTAINER REPLY');
   await page.locator('.react-flow__node[data-id="out-b"]').click();
   assert.equal(await inspector().locator('.container-reply-card textarea').inputValue(),'V6 SECOND CONTAINER REPLY');
   await page.screenshot({path:path.join(OUT,'separate-containers.png')});mark('each selected container shows its own reply instead of the last container');
   await page.getByTitle('收起执行面板',{exact:true}).click();
   await page.locator('.react-flow__node[data-id="'+boxId+'"]').dblclick();
   await page.locator('.canvas-breadcrumb').waitFor();await page.locator('.react-flow__node[data-id="out-a"]').click();
   assert.equal(await inspector().locator('.container-reply-card textarea').inputValue(),'V6 NESTED CONTAINER REPLY');
   await page.screenshot({path:path.join(OUT,'nested-container.png')});mark('long nested path resolves the correct container despite sharing a node ID with the parent canvas');
   assert.deepEqual(errors,[]);mark('no browser runtime errors');
   fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,runId:rid,multiContainerRunId:multiId,serviceId:service.id,realInference:false},null,2));
 }catch(error){
   await page.screenshot({path:path.join(OUT,'failure.png')});fs.writeFileSync(path.join(OUT,'failure.txt'),String(error)+'\n'+await page.locator('body').innerText());throw error;
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
