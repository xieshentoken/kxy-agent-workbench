/* Independent browser acceptance against a running localhost kxy. Synthetic inputs only.
   NODE_PATH=<playwright package directory> node acceptance/browser_checks.cjs */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ROOT=path.resolve(__dirname,'browser-results'); fs.mkdirSync(ROOT,{recursive:true});
const BASE=process.env.KXY_BASE_URL || 'http://127.0.0.1:8710';
const executable=process.env.KXY_BROWSER_EXECUTABLE;
const errors=[]; const passed=[];
const mark=x=>{passed.push(x);console.log('PASS',x)};
(async()=>{
 const browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())});
 try {
 await page.goto(BASE);await page.locator('.react-flow__node').first().waitFor();
 await page.waitForTimeout(800);
 assert.equal(await page.locator('.react-flow__controls').evaluate(e=>getComputedStyle(e).position),'absolute');
 await page.screenshot({path:path.join(ROOT,'1440-initial.png')});mark('canvas styles and initial rendering');
 const initial=await page.locator('.react-flow__node').count();
 const data=await page.evaluateHandle(()=>{const d=new DataTransfer();d.items.add(new File(['Browser acceptance data: A20, B12, margins unknown.'],'browser-fixture.md',{type:'text/markdown'}));return d});
 await page.locator('.flow-frame').dispatchEvent('drop',{dataTransfer:data,clientX:560,clientY:380});
 await page.waitForFunction(n=>document.querySelectorAll('.react-flow__node').length===n+1,initial);
 const dropped=page.locator('.react-flow__node').filter({hasText:'browser-fixture.md'}).first();
 await dropped.click();assert.equal(await dropped.locator('.target-handle').count(),0);
 await page.getByLabel('节点名称',{exact:true}).fill('验收附件节点');mark('actual file drop creates bound input node');
 const nodeRect=await dropped.boundingBox();await page.mouse.move(nodeRect.x+30,nodeRect.y+15);await page.mouse.down();await page.mouse.move(nodeRect.x+80,nodeRect.y+45,{steps:6});await page.mouse.up();
 const moved=await dropped.boundingBox();assert.ok(Math.abs(moved.x-nodeRect.x)>20);mark('canvas node dragging');
 const workflow={id:'kxy-browser-acceptance',name:'验收 · 条件路由',version:'kxy.workflow.v1',nodes:[
  {id:'source',type:'text',position:{x:40,y:220},data:{label:'验收来源',text:'KEEP_UI_TEXT'}},
  {id:'condition',type:'condition',position:{x:320,y:220},data:{label:'验收条件',field:'status',operator:'equals',expected:'source'}},
  {id:'yes',type:'container',position:{x:600,y:110},data:{label:'真分支输出'}},
  {id:'no',type:'container',position:{x:600,y:380},data:{label:'假分支输出'}}],edges:[
  {id:'a',source:'source',target:'condition',sourceHandle:'result',targetHandle:'items'},
  {id:'b',source:'condition',target:'yes',sourceHandle:'true',targetHandle:'items'},
  {id:'c',source:'condition',target:'no',sourceHandle:'false',targetHandle:'items'}]};
 await page.locator('input[accept="application/json,.json"]').setInputFiles({name:'browser-flow.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(workflow))});
 await page.getByTitle('自动适配画布').click();await page.waitForTimeout(500);
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.waitForTimeout(500);await page.reload();
 await page.getByLabel('打开已保存流程').selectOption('kxy-browser-acceptance');
 await page.locator('.react-flow__node[data-id="source"]').click();assert.equal(await page.getByLabel('输入内容',{exact:false}).inputValue(),'KEEP_UI_TEXT');mark('workflow JSON import, save, reload and inspect');
 await page.getByRole('button',{name:'运行流程',exact:true}).click();await page.locator('.run-status.status-succeeded').waitFor({timeout:20000});
 await page.waitForTimeout(300);assert.match(await page.locator('.run-nodes').innerText(),/no\s+skipped/);mark('true condition route through real LFX');
 await page.locator('.react-flow__node[data-id="condition"]').click();await page.getByLabel('预期值',{exact:true}).fill('other');
 await page.getByRole('button',{name:'运行流程',exact:true}).click();await page.locator('.run-status.status-succeeded').waitFor({timeout:20000});await page.waitForTimeout(300);
 assert.match(await page.locator('.run-nodes').innerText(),/yes\s+skipped/);assert.match(await page.locator('.run-panel').innerText(),/KEEP_UI_TEXT/);mark('false route preserves upstream text and previews results');
 assert.ok(await page.locator('a.artifact-link').count()>0);const downloadPromise=page.waitForEvent('download');await page.locator('a.artifact-link').first().click();const download=await downloadPromise;assert.ok(download.suggestedFilename());mark('artifact download');
 await page.getByTitle('外观设置').click();await page.getByLabel('字体预设').selectOption('mono');await page.getByLabel('强调色',{exact:true}).fill('#627c75');await page.getByLabel('画布底色',{exact:true}).fill('#f3f7f4');await page.getByRole('button',{name:'保存外观',exact:true}).click();await page.waitForTimeout(300);await page.reload();
 await page.waitForFunction(()=>document.querySelector('.kxy-app')?.classList.contains('font-mono'));assert.match(await page.locator('.kxy-app').getAttribute('class'),/font-mono/);assert.equal(await page.locator('.kxy-app').evaluate(e=>getComputedStyle(e).getPropertyValue('--kxy-accent').trim()),'#627c75');mark('font and colors persist across reload');
 await page.getByRole('button',{name:'恢复默认',exact:true}).click();await page.getByRole('button',{name:'保存外观',exact:true}).click();
 await page.getByLabel('打开已保存流程').selectOption('kxy-browser-acceptance');
 await page.getByTitle('收起执行面板').click();
 await page.getByTitle('自动适配画布').click();await page.waitForTimeout(350);
 for(const viewport of [{width:1440,height:900},{width:1280,height:720},{width:390,height:844}]){
  await page.setViewportSize(viewport);await page.waitForTimeout(350);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(ROOT,`${viewport.width}x${viewport.height}.png`)});
 }
 mark('1440, 1280 and narrow viewport overflow check');
 assert.deepEqual(errors,[]);mark('no browser runtime or console errors');
 fs.writeFileSync(path.join(ROOT,'results.json'),JSON.stringify({passed,errors},null,2));
 }catch(e){await page.screenshot({path:path.join(ROOT,'failure.png')});fs.writeFileSync(path.join(ROOT,'results.json'),JSON.stringify({passed,errors,error:String(e)},null,2));throw e}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
