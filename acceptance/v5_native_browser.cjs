/* Real installed Codex catalog to saved config to Inspector; no inference. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const OUT=path.join(__dirname,'v5-evidence','native-browser');fs.mkdirSync(OUT,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:8721');await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:'模型 / API',exact:true}).click();
  const editor=page.locator('.settings-editor-card').first().locator('form').first();
  const model=editor.getByLabel('实际模型标识',{exact:false});
  await model.locator('option').filter({hasText:'gpt-5.6-luna'}).waitFor({state:'attached',timeout:30000});
  const models=await model.locator('option').evaluateAll(os=>os.filter(o=>o.value).map(o=>({value:o.value,label:o.textContent})));
  const luna=models.find(o=>o.label.includes('gpt-5.6-luna'));assert.ok(luna);await model.selectOption(luna.value);
  const effort=editor.getByLabel('默认 effort',{exact:false});assert.ok((await effort.locator('option').allTextContents()).some(t=>t==='max'));await effort.selectOption('max');
  await editor.getByLabel('显示 alias',{exact:false}).fill('V5 本机 Codex Luna 检查');
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/agent-models')&&r.request().method()==='POST');await editor.getByRole('button',{name:'创建模型',exact:true}).click();const response=await pending;assert.ok(response.ok(),await response.text());const saved=await response.json();
  assert.equal(saved.model,'gpt-5.6-luna');assert.equal(saved.default_effort,'max');assert.equal(saved.credential_id,null);
  await page.getByTitle('关闭设置',{exact:true}).click();await page.locator('.library-item').filter({hasText:'CLI 分析器'}).click();
  const inspector=page.locator('.right-panel');const agent=inspector.locator('select').first();
  const value=await agent.locator('option').evaluateAll((os,id)=>os.find(o=>o.value===id||o.value.endsWith(id))?.value,saved.id);assert.ok(value);await agent.selectOption(value);
  assert.equal(await inspector.getByLabel('effort',{exact:false}).inputValue(),'max');
  assert.ok((await inspector.getByLabel('模型记录',{exact:false}).locator('option:checked').innerText()).startsWith('gpt-5.6-luna'));
  assert.match(await inspector.getByLabel('模型记录',{exact:false}).getAttribute('title'),/gpt-5.6-luna/);
  const runs=await(await page.request.get('http://127.0.0.1:8721/api/runs')).json();assert.equal(runs.length,0);assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(OUT,'inspector.png'),fullPage:true});
  fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed:true,catalog_count:models.length,model:saved.model,effort:saved.default_effort,credential_bound:false,model_inference_run:false,errors},null,2));
  console.log('PASS real Codex catalog → gpt-5.6-luna / max config → exact Inspector selection; zero inference runs');
 }catch(e){await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
