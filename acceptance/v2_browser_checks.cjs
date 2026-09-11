/* Parent-authored integration checks. Real local backend/LFX; synthetic inputs.
   Native picker is stubbed here and verified separately through native UI. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE=process.env.KXY_BASE_URL||'http://127.0.0.1:8711';
const ROOT=fs.readFileSync(path.join(__dirname,'v2-browser-root.txt'),'utf8').trim();
const OUT=path.join(__dirname,'v2-evidence','browser');fs.mkdirSync(OUT,{recursive:true});
const passed=[],errors=[];const mark=x=>{passed.push(x);console.log('PASS',x)};
const n=(id,type,data={},x=0,y=0)=>({id,type,data:{label:id,...data},position:{x,y}});
const e=(source,target,sourceHandle='result')=>({id:`${source}-${sourceHandle}-${target}`,source,target,sourceHandle,targetHandle:'items'});
const f=(nodes,edges)=>({version:'kxy.workflow.v1',id:'v2-ui-acceptance',name:'V2 界面验收',nodes,edges});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.KXY_BROWSER_EXECUTABLE});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 page.on('pageerror',x=>errors.push(x.message));
 page.on('console',x=>{if(x.type()==='error')errors.push(x.text())});
 const importFlow=async flow=>{
  await page.locator('input[accept="application/json,.json"]').setInputFiles({name:'v2-ui.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(flow))});
  await page.waitForFunction(id=>Boolean(document.querySelector(`.react-flow__node[data-id="${id}"]`)),flow.nodes[0].id);
  await page.getByTitle('自动适配画布').click();await page.waitForTimeout(350);
 };
 const exportFlow=async()=>{
  const promise=page.waitForEvent('download');await page.getByRole('button',{name:'导出',exact:true}).click();
  return JSON.parse(fs.readFileSync(await(await promise).path(),'utf8'));
 };
 try{
  await page.goto(BASE);await page.locator('.left-panel').waitFor();await page.waitForTimeout(1000);
  await page.getByTitle('全局设置',{exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'全局设置'});await dialog.waitFor();
  assert.equal(await dialog.locator('.agent-row').count(),7);
  const discovered=page.waitForResponse(r=>r.url().endsWith('/api/agents/codex/discover'),{timeout:40000});
  await dialog.getByRole('button',{name:'发现',exact:true}).click();
  assert.equal((await discovered).status(),200);
  await dialog.locator('.settings-feedback').waitFor();
  mark('global settings expose seven agent profiles and real Codex discovery');
  // Clear only isolated test profile roots, select synthetic folder through picker contract.
  while(await dialog.getByTitle('移除目录',{exact:true}).count())await dialog.getByTitle('移除目录',{exact:true}).first().click();
  let pickerCalls=0;
  await page.route('**/api/picker',async route=>{pickerCalls++;await route.fulfill({json:{cancelled:false,path:path.join(ROOT,'fixture-skill')}})});
  await dialog.getByRole('button',{name:'添加 Skill 文件夹',exact:true}).click();
  await dialog.getByRole('button',{name:'保存 Agent',exact:true}).click();
  await page.waitForTimeout(350);
  await dialog.getByRole('button',{name:'扫描 Skills',exact:true}).click();
  const candidate=dialog.locator('.candidate-row').filter({hasText:'v2-browser-method'});await candidate.waitFor();
  await candidate.locator('input').check();
  await dialog.getByRole('button',{name:'导入选中的 Skill 快照',exact:true}).click();
  await page.waitForTimeout(500);assert.ok(pickerCalls>0);mark('folder picker contract, profile save, real skill scan and checked snapshot import');
  await dialog.getByRole('button',{name:'模型 / API',exact:true}).click();
  assert.equal(await dialog.getByLabel('API key',{exact:false}).getAttribute('type'),'password');
  await dialog.getByLabel('来源',{exact:false}).selectOption('manual');
  await dialog.getByLabel('显示 alias',{exact:false}).fill('验收 · 手动模型');
  await dialog.getByLabel('实际模型标识',{exact:false}).fill('SYNTHETIC_UI_MODEL');
  await dialog.getByLabel('支持的 effort',{exact:false}).fill('low, high');
  await dialog.getByLabel('默认 effort',{exact:false}).selectOption('low');
  const savedModel=page.waitForResponse(r=>r.url().endsWith('/api/agent-models')&&r.request().method()==='POST');
  await dialog.getByRole('button',{name:'创建模型',exact:true}).click();const modelResponse=await savedModel;
  assert.equal(modelResponse.status(),200,await modelResponse.text());const model=await modelResponse.json();
  await dialog.getByTitle('关闭设置',{exact:true}).click();
  await page.locator('.library-item').filter({hasText:'CLI 分析器'}).click();
  await page.getByLabel('模型记录',{exact:false}).selectOption(model.id);
  assert.equal(await page.getByLabel('effort',{exact:false}).inputValue(),'low');
  assert.equal(await page.locator('.right-panel input[type="password"]').count(),0);
  await page.locator('.skill-check').filter({hasText:'v2-browser-method'}).locator('input').check();
  await page.getByRole('button',{name:'保存为分析器预设',exact:true}).click();
  await page.locator('.node-skill-badge').first().waitFor();mark('global model creation, alias/effort selection and Skill analyzer preset');
  // Long filename is an actual browser File drop, not a fabricated node.
  const longName='资料名称非常长'.repeat(18)+'.md';
  const before=await page.locator('.react-flow__node').count();
  const data=await page.evaluateHandle(name=>{const d=new DataTransfer();d.items.add(new File(['SYNTHETIC_LONG_FILENAME'],name,{type:'text/markdown'}));return d},longName);
  await page.locator('.flow-frame').dispatchEvent('drop',{dataTransfer:data,clientX:530,clientY:400});
  await page.waitForFunction(count=>document.querySelectorAll('.react-flow__node').length===count+1,before);
  const label=page.locator('.react-flow__node .node-label').filter({hasText:longName});await label.waitFor();
  assert.equal(await label.getAttribute('title'),longName);
  assert.equal(await label.evaluate(el=>getComputedStyle(el).textOverflow),'ellipsis');
  assert.ok(await label.evaluate(el=>el.getBoundingClientRect().width<=el.closest('.kxy-node').getBoundingClientRect().width));mark('long Unicode filename drop, containment and full hover title');
  // Real human breakpoint and reload recovery through durable history.
  const human=f([n('review-source','text',{text:'UI_HUMAN_PAYLOAD_953'},20,200),n('review-human','human',{content:'请核对 UI_HUMAN_PAYLOAD_953',confirm_label:'确认继续'},300,200),n('review-output','container',{},580,200)],[e('review-source','review-human'),e('review-human','review-output')]);
  await importFlow(human);await page.getByRole('button',{name:'保存',exact:true}).click();
  await page.getByRole('button',{name:'运行流程',exact:true}).click();await page.locator('.run-status.status-waiting').waitFor({timeout:20000});
  assert.match(await page.locator('.approval-content').innerText(),/UI_HUMAN_PAYLOAD_953/);
  await page.reload();await page.locator('.run-history button').filter({hasText:'waiting'}).first().click();
  await page.locator('.approval-card.approval-pending').waitFor();
  await page.locator('.approval-actions .run-button').click();await page.locator('.run-status.status-succeeded').waitFor({timeout:20000});
  mark('real LFX human pause, custom content, browser reload and confirmation continue');
  // Pack a processor/human chain, then edit and run inside the box.
  const boxFlow=f([n('box-source','text',{text:'UI_BOX_PAYLOAD_467'},20,200),n('box-review','human',{content:'黑盒内部确认'},300,200),n('box-out','container',{},580,200)],[e('box-source','box-review'),e('box-review','box-out')]);
  await importFlow(boxFlow);await page.getByTitle('收起执行面板').click();
  await page.locator('.react-flow__node[data-id="box-review"]').click();
  await page.getByTitle('封装选中节点为黑盒子').click();
  await page.getByRole('button',{name:'进入编辑内部画布',exact:true}).click();
  await page.locator('.react-flow__node[data-id="box-review"]').click();
  await page.getByLabel('确认说明',{exact:false}).fill('EDITED_INNER_REVIEW_467');
  await page.getByRole('button',{name:'返回上一级',exact:false}).click();
  const packed=await exportFlow();const box=packed.nodes.find(n=>n.type==='blackbox');assert.ok(box);
  assert.equal(box.data.workflow.nodes.find(n=>n.id==='box-review').data.content,'EDITED_INNER_REVIEW_467');
  assert.ok(!JSON.stringify(packed).includes('credential_id'));assert.ok(!JSON.stringify(packed).includes('grant_id'));
  await page.getByRole('button',{name:'运行流程',exact:true}).click();
  if(await page.locator('.run-dock').count())await page.locator('.run-dock').click();
  await page.locator('.run-status.status-waiting').waitFor({timeout:20000});assert.match(await page.locator('.approval-content').innerText(),/EDITED_INNER_REVIEW_467/);
  await page.locator('.approval-actions .run-button').click();await page.locator('.run-status.status-succeeded').waitFor({timeout:20000});
  mark('blackbox pack, inner canvas edit, export and real inner approval execution');
  await page.getByTitle('收起执行面板').click();
  await page.locator(`.react-flow__node[data-id="${box.id}"]`).click();
  await page.getByRole('button',{name:'解包并保留连线',exact:true}).click();
  const unpacked=await exportFlow();assert.deepEqual(unpacked.nodes.map(n=>n.id).sort(),boxFlow.nodes.map(n=>n.id).sort());
  assert.deepEqual(unpacked.edges.map(x=>[x.source,x.target,x.sourceHandle,x.targetHandle]).sort(),boxFlow.edges.map(x=>[x.source,x.target,x.sourceHandle,x.targetHandle]).sort());
  mark('blackbox unpack preserves all external connections');
  for(const viewport of [{width:1440,height:900},{width:1280,height:720},{width:390,height:844}]){
   await page.setViewportSize(viewport);await page.getByTitle('全局设置',{exact:true}).click();await page.waitForTimeout(200);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:path.join(OUT,`settings-${viewport.width}.png`)});await page.getByTitle('关闭设置',{exact:true}).click();
  }
  mark('1440/1280/narrow settings and canvas overflow');
  assert.deepEqual(errors,[]);mark('no browser runtime/console errors');
  fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,picker:'stubbed; native tested separately'},null,2));
 }catch(error){await page.screenshot({path:path.join(OUT,'failure.png')});fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,error:String(error)},null,2));throw error}
 finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
