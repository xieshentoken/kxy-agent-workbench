/* Old model_ref/native/variant bindings must display the runtime's real effort. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const OUT=path.join(__dirname,'v5-evidence','compat-browser');fs.mkdirSync(OUT,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),passed=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  const r=await page.request.post('http://127.0.0.1:8720/api/agent-models',{data:{source:'manual',cli_id:'codex',model:'fixture-legacy',alias:'V5 compat saved',efforts:['low','max'],default_effort:'max'}});assert.ok(r.ok());const saved=await r.json();
  const models=await(await page.request.get('http://127.0.0.1:8720/api/agent-models')).json();const native=models.find(m=>m.source==='native'&&m.cli_id==='codex'&&m.model==='fixture-reasoning');assert.ok(native);
  await page.goto('http://127.0.0.1:8720');
  const cases=[{id:saved.id,effort:'max',data:{},label:'legacy record default effort is shown exactly'},
    {id:saved.id,effort:'low',data:{variant:'low'},label:'legacy variant is shown as the effective effort'},
    {id:native.id,effort:'high',data:{},label:'previous native model binding remains selectable and shows its real default'}];
  for(const c of cases){
   const flow={version:'kxy.workflow.v1',name:'V5 compatibility fixture',nodes:[{id:'compat',type:'analyzer',position:{x:120,y:150},data:{label:'V5兼容',cli:'codex',model_ref:c.id,network:true,prompt:'SYNTHETIC',...c.data}}],edges:[]};
   await page.locator('.kxy-app > input[accept="application/json,.json"]').setInputFiles({name:'v5-compat.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(flow))});
   await page.getByTitle('自动适配画布',{exact:true}).click();await page.locator('.react-flow__node[data-id="compat"]').click();
   const inspector=page.locator('.right-panel');
   await page.waitForFunction(expected=>[...document.querySelectorAll('.right-panel label')].some(label=>label.querySelector('span')?.textContent==='effort'&&label.querySelector('select')?.value===expected),c.effort,{timeout:10000});
   assert.equal(await inspector.getByLabel('effort',{exact:false}).inputValue(),c.effort);
   assert.equal(await inspector.getByLabel('模型记录',{exact:false}).inputValue(),c.id);assert.doesNotMatch(await inspector.getByLabel('模型记录',{exact:false}).locator('option:checked').innerText(),/不可用|重新绑定/);
   const pending=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();const exported=JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'));assert.ok(!exported.nodes[0].data.effort,'render must not silently rewrite saved node effort');
   passed.push(c.label);console.log('PASS',c.label);
  }
  assert.deepEqual(errors,[]);await page.screenshot({path:path.join(OUT,'native-binding.png'),fullPage:true});fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors},null,2));
 }catch(e){await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
