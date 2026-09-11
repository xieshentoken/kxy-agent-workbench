const {chromium}=require('playwright');const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const OUT=path.resolve(__dirname,'browser-results'); const passed=[];const mark=x=>{passed.push(x);console.log('PASS',x)};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.KXY_BROWSER_EXECUTABLE}); const page=await browser.newPage({viewport:{width:1440,height:900}});
 try{
 await page.goto('http://127.0.0.1:8710');await page.locator('.left-panel').waitFor();await page.waitForTimeout(1000);
 page.once('dialog',d=>d.accept('/private/tmp/kxy-acceptance-inputs/fixture-skill'));
 const imported=page.waitForResponse(r=>r.url().endsWith('/api/skills/import-path')&&r.request().method()==='POST');await page.locator('.left-panel').getByRole('button',{name:'导入',exact:true}).click();await imported;await page.locator('.skill-pill').filter({hasText:'fixture-skill'}).first().waitFor();
 await page.locator('.library-item').filter({hasText:'CLI 分析器'}).click();
 await page.locator('.skill-check').filter({hasText:'fixture-skill'}).first().locator('input').check();
 await page.getByLabel('节点名称',{exact:true}).fill('验收 · 资料方法');await page.getByLabel('变体 / effort').fill('high');
 await page.locator('.skill-badge').first().waitFor();const presetSaved=page.waitForResponse(r=>r.url().endsWith('/api/analyzers')&&r.request().method()==='POST');await page.getByRole('button',{name:'保存为分析器预设',exact:true}).click();await presetSaved;await page.locator('.preset-apply').filter({hasText:'验收 · 资料方法'}).first().waitFor();
 assert.ok(await page.locator('.node-skill-badge').count()>0 || (await page.locator('.react-flow__node').filter({hasText:'fixture-skill'}).count()>0));
 await page.screenshot({path:path.join(OUT,'skill-analyzer.png')});mark('skill import, analyzer attachment, badge and preset save');
 const before=await page.locator('.react-flow__node').count();await page.locator('.react-flow__node[data-id="source"]').click();await page.locator('.preset-apply').filter({hasText:'验收 · 资料方法'}).first().click();
 assert.equal(await page.locator('.react-flow__node').count(),before+1);assert.equal(await page.getByLabel('变体 / effort').inputValue(),'high');mark('preset creates analyzer and restores effort');
 assert.equal(await page.getByLabel('API key',{exact:true}).getAttribute('type'),'password');mark('API key uses password input');
 const flow={id:'kxy-browser-connect',name:'验收 · 手动连接',version:'kxy.workflow.v1',nodes:[{id:'source',type:'text',position:{x:40,y:220},data:{label:'连接来源',text:'CONNECT_UI_RESULT'}},{id:'output',type:'container',position:{x:420,y:220},data:{label:'连接输出'}}],edges:[]};
 await page.locator('input[accept="application/json,.json"]').setInputFiles({name:'connection.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(flow))});
 await page.locator('.react-flow__node').filter({hasText:'连接输出'}).waitFor();await page.getByTitle('自动适配画布').click();await page.waitForTimeout(400);
 const source=page.locator('.react-flow__node[data-id="source"] .source-handle');const target=page.locator('.react-flow__node[data-id="output"] .target-handle');const s=await source.boundingBox(),t=await target.boundingBox();
 await page.mouse.move(s.x+s.width/2,s.y+s.height/2);await page.mouse.down();await page.mouse.move(t.x+t.width/2,t.y+t.height/2,{steps:12});await page.mouse.up();
 await page.locator('.react-flow__edge').waitFor({state:'attached'});assert.equal(await page.locator('.react-flow__edge').count(),1);mark('manual handle connection creates edge');
 await page.locator('.react-flow__node[data-id="output"]').click();const exportDir='/private/tmp/kxy-browser-export';fs.mkdirSync(exportDir,{recursive:true});page.once('dialog',d=>d.accept(exportDir));await page.getByRole('button',{name:'授权一个输出文件夹'}).click();await page.waitForTimeout(500);
 const grant=await page.getByLabel('输出文件夹授权').inputValue();assert.ok(grant);
 await page.getByRole('button',{name:'运行流程',exact:true}).click();await page.locator('.run-status.status-succeeded').waitFor({timeout:20000});assert.match(await page.locator('.run-panel').innerText(),/CONNECT_UI_RESULT/);assert.ok(fs.readdirSync(path.join(exportDir,'kxy')).length>0);mark('manual graph run and UI-authorized folder export');
 const downloadP=page.waitForEvent('download');await page.getByRole('button',{name:'导出',exact:true}).click();const download=await downloadP;const raw=fs.readFileSync(await download.path(),'utf8');assert.ok(!raw.includes('grant_id')&&!raw.includes('credential_id'));mark('workflow export removes folder and credential grants');
 await page.locator('.grant-row').filter({hasText:exportDir}).first().getByRole('button',{name:'撤销',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.right-panel select')?.value==='');assert.equal(await page.getByLabel('输出文件夹授权').inputValue(),'');mark('folder authorization revoke');
 await page.locator('.left-panel').getByTitle('收起组件库').click();assert.equal(await page.locator('.left-panel').isVisible(),false);await page.getByRole('button',{name:'组件库',exact:true}).click();assert.equal(await page.locator('.left-panel').isVisible(),true);mark('desktop panel collapse and restore');
 fs.writeFileSync(path.join(OUT,'component-results.json'),JSON.stringify({passed},null,2));
 }catch(e){await page.screenshot({path:path.join(OUT,'component-failure.png')});fs.writeFileSync(path.join(OUT,'component-results.json'),JSON.stringify({passed,error:String(e)},null,2));throw e}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
