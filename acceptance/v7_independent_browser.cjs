/* Real Keychain via isolated V7 server; only synthetic keys/catalog and no inference. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE='http://127.0.0.1:8723',DATA='/private/tmp/kxy-v7-browser-data';
const OUT=path.join(__dirname,'v7-evidence','browser');fs.mkdirSync(OUT,{recursive:true});
const passed=[],errors=[],mark=x=>{passed.push(x);console.log('PASS',x)};
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));
 const get=async route=>(await page.request.get(BASE+route)).json();
 const settings=async tab=>{await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:tab,exact:true}).click()};
 const close=()=>page.getByTitle('关闭设置',{exact:true}).click();
 const ins=()=>page.locator('.right-panel'),editor=()=>page.locator('.service-editor');
 const field=name=>editor().getByLabel(name,{exact:false});
 const exportFlow=async()=>{const pending=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'))};
 let release=()=>{};
 try{
  for(const p of await get('/api/analyzers'))await page.request.delete(BASE+'/api/analyzers/'+p.id);
  for(const s of await get('/api/credentials'))await page.request.delete(BASE+'/api/credentials/'+s.id);
  await page.request.put(BASE+'/api/settings',{data:{motion_intensity:100,motion_enabled:true}});
  for(const name of ['V7 Existing A','V7 Existing B']){
    const r=await page.request.post(BASE+'/api/analyzers',{data:{name,config:{label:name,kind:'analyzer',cli:'codex',prompt:name+' literal prompt'}}});assert.ok(r.ok());
  }
  let held=false;const gate=new Promise(r=>release=r);
  await page.route('**/api/analyzers',async route=>{
   if(route.request().method()==='GET'&&!held){const response=await route.fetch();held=true;await gate;await route.fulfill({response})}else await route.continue();
  });
  await page.goto(BASE);await page.locator('.react-flow__node[data-id="analyzer"]').click();
  for(const name of ['V7 Created C','V7 Created D','V7 Created E']){
   await ins().getByLabel('节点名称',{exact:false}).fill(name);await ins().getByLabel('分析提示词',{exact:false}).fill(name+' literal prompt');
   const saved=page.waitForResponse(r=>r.url().endsWith('/api/analyzers')&&r.request().method()==='POST');
   await ins().getByRole('button',{name:/保存.*预设/}).click();assert.ok((await saved).ok());
  }
  assert.ok(held);release();await page.waitForTimeout(900);
  const presetRows=()=>page.locator('.preset-item');
  assert.equal(await presetRows().count(),5,'late initial resource response must preserve old and new presets');
  assert.equal((await get('/api/analyzers')).length,5);mark('all five presets remain visible after delayed initial load and three new saves');
  const before=await exportFlow();
  const a=presetRows().filter({hasText:'V7 Existing A'});
  await a.getByRole('button',{name:/展开/}).click();assert.match(await a.innerText(),/V7 Existing A literal prompt/);
  assert.deepEqual((await exportFlow()).nodes,before.nodes,'expanding a preset must not apply it');
  await a.getByRole('button',{name:/应用/}).click();assert.equal(await ins().getByLabel('分析提示词',{exact:false}).inputValue(),'V7 Existing A literal prompt');
  mark('preset details expand independently and explicit apply loads exact saved prompt');
  await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.preset-item').length===5);
  await page.setViewportSize({width:1280,height:720});await presetRows().last().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(OUT,'presets-1280.png')});assert.ok(await presetRows().last().isVisible());
  mark('all saved presets survive reload and last entry is reachable at 1280x720');
  await page.setViewportSize({width:1440,height:900});await settings('AI 服务');
  const endpoint=JSON.parse(fs.readFileSync(path.join(DATA,'fixture-info.json'))).catalog_endpoint;
  await field('服务名称').fill('V7 Browser real Keychain synthetic service');await field('Endpoint').fill(endpoint);await field('API key').fill('V7-browser-synthetic-not-a-real-provider-key');
  const test=page.waitForResponse(r=>r.url().endsWith('/api/credentials/test'));await editor().getByRole('button',{name:/测试.*models/}).click();assert.ok((await test).ok());
  await editor().locator('.service-model-row').last().waitFor();
  assert.equal(await editor().locator('.service-model-row').count(),3);assert.equal(await editor().locator('.service-model-row input:checked').count(),0);
  mark('fresh catalog defaults to no selected models');
  await editor().getByRole('button',{name:'全选当前',exact:true}).click();assert.equal(await editor().locator('.service-model-row input:checked').count(),3);
  await editor().getByRole('button',{name:'反选当前',exact:true}).click();assert.equal(await editor().locator('.service-model-row input:checked').count(),0);
  await editor().locator('.service-model-row').filter({hasText:'fixture-b'}).getByRole('checkbox').check();
  await field('搜索服务模型').fill('fixture-a');await editor().getByRole('button',{name:'全选当前',exact:true}).click();
  await editor().getByRole('button',{name:'反选当前',exact:true}).click();await field('搜索服务模型').fill('');
  assert.equal(await editor().locator('.service-model-row input:checked').count(),1);assert.ok(await editor().locator('.service-model-row').filter({hasText:'fixture-b'}).getByRole('checkbox').isChecked());
  await field('搜索服务模型').fill('nothing-matches');assert.ok(await editor().getByRole('button',{name:'全选当前',exact:true}).isDisabled());await field('搜索服务模型').fill('');
  mark('model select/invert respects search scope, hidden selections, and empty results');
  const save=page.waitForResponse(r=>r.url().endsWith('/api/credentials/store'));await editor().getByRole('button',{name:'写入 Keychain 并保存',exact:true}).click();
  const sr=await save;assert.ok(sr.ok(),await sr.text());const service=await sr.json();assert.ok(service.configured);assert.deepEqual(service.models.map(m=>m.id),['fixture-b']);assert.equal(await field('API key').inputValue(),'');
  const row=page.locator('.service-row').filter({hasText:'V7 Browser real Keychain synthetic service'});await row.getByRole('button',{name:'编辑',exact:true}).click();
  const savedTest=page.waitForResponse(r=>r.url().endsWith('/api/credentials/test'));await editor().getByRole('button',{name:/测试.*models/}).click();const tr=await savedTest;assert.ok(tr.ok()&&(await tr.json()).ok);
  assert.equal(await editor().locator('.service-model-row input:checked').count(),1);
  assert.ok(await editor().locator('.service-model-row').filter({hasText:'fixture-b'}).getByRole('checkbox').isChecked());
  await page.screenshot({path:path.join(OUT,'keychain-service.png')});mark('browser saves a real Keychain item and saved-key retest preserves explicit selections');
  await close();await page.locator('.react-flow__node[data-id="output"]').click();
  const filePolicy=ins().locator('.output-policy-card');
  await filePolicy.getByRole('button',{name:/全选/}).click();const extensions=await ins().locator('.generated-file-list input').count();assert.ok(extensions>=17);assert.equal(await ins().locator('.generated-file-list input:checked').count(),extensions);
  await filePolicy.getByRole('button',{name:/反选/}).click();assert.equal(await ins().locator('.generated-file-list input:checked').count(),0);
  await ins().locator('.generated-file-list').getByLabel('.pdf',{exact:true}).check();await filePolicy.getByRole('button',{name:/反选/}).click();
  assert.equal(await ins().locator('.generated-file-list input:checked').count(),extensions-1);assert.ok(!(await ins().locator('.generated-file-list').getByLabel('.pdf',{exact:true}).isChecked()));
  await ins().getByRole('button',{name:/全选正文/}).click();assert.equal(await ins().locator('.format-check-list:not(.generated-file-list) input:checked').count(),3);
  await ins().getByRole('button',{name:/反选正文/}).click();assert.equal(await ins().locator('.format-check-list:not(.generated-file-list) input:checked').count(),0);
  const output=(await exportFlow()).nodes.find(n=>n.id==='output').data;assert.equal(output.allowed_file_extensions.length,extensions-1);assert.deepEqual(output.export_formats,[]);
  await page.screenshot({path:path.join(OUT,'output-bulk.png')});mark('file and reply format bulk controls operate independently and persist in workflow JSON');
  const setStrength=async(value,save=false)=>{
    await settings('外观');const slider=page.getByRole('slider',{name:/强度/});await slider.fill(String(value));
    assert.equal(await slider.inputValue(),String(value));if(save){const pending=page.waitForResponse(r=>r.url().endsWith('/api/settings')&&r.request().method()==='PUT');await page.getByRole('button',{name:'保存为默认样式',exact:true}).click();assert.ok((await pending).ok())}
    await close();
  };
  const sample=async(mode='trail')=>{
   const f=await page.locator('.flow-frame').boundingBox();await page.mouse.click(f.x+45,f.y+45);await page.waitForTimeout(1200);
   if(mode==='selection'){await page.locator('.react-flow__node[data-id="analyzer"]').click();await page.waitForTimeout(130)}
   else{await page.mouse.move(f.x+45,f.y+45);await page.mouse.move(f.x+240,f.y+65,{steps:12});await page.waitForTimeout(45)}
   return page.locator('.motion-canvas circle').evaluateAll(cs=>cs.map(c=>({opacity:+c.getAttribute('opacity'),x:+c.getAttribute('cx'),y:+c.getAttribute('cy'),r:+c.getAttribute('r')})));
  };
  await setStrength(0,true);assert.equal((await sample()).length,0);await page.reload();await page.waitForTimeout(800);await settings('外观');assert.equal(await page.getByRole('slider',{name:/强度/}).inputValue(),'0');await close();
  mark('zero intensity clears highlights and survives save/reload');
  await setStrength(20);const low=await sample();assert.ok(low.length);const lowSelection=await sample('selection');assert.ok(lowSelection.length);await page.waitForTimeout(500);assert.equal(await page.locator('.motion-canvas circle').count(),0,'weak selection pulse should expire quickly');
  await setStrength(100);const high=await sample();assert.ok(high.length);const highSelection=await sample('selection');assert.ok(highSelection.length);await page.waitForTimeout(500);assert.ok(await page.locator('.motion-canvas circle').count()>0,'strong selection pulse should remain visible longer');
  const lowMax=Math.max(...low.map(p=>p.opacity)),highMax=Math.max(...high.map(p=>p.opacity));assert.ok(highMax>lowMax*2,JSON.stringify({lowMax,highMax}));
  const lowSelectionMax=Math.max(...lowSelection.map(p=>p.opacity)),highSelectionMax=Math.max(...highSelection.map(p=>p.opacity));
  const alignment=await page.evaluate(()=>{const p=document.querySelector('.react-flow__background pattern'),d=p.querySelector('circle'),t=p.patternTransform.baseVal.consolidate()?.matrix||{e:0,f:0};return {gx:+p.getAttribute('width'),gy:+p.getAttribute('height'),ox:+p.getAttribute('x')+t.e+(+d.getAttribute('cx')),oy:+p.getAttribute('y')+t.f+(+d.getAttribute('cy')),r:+d.getAttribute('r')}});
  assert.ok(high.every(p=>Math.abs((p.x-alignment.ox)/alignment.gx-Math.round((p.x-alignment.ox)/alignment.gx))*alignment.gx<0.12&&Math.abs((p.y-alignment.oy)/alignment.gy-Math.round((p.y-alignment.oy)/alignment.gy))*alignment.gy<0.12&&Math.abs(p.r-alignment.r)<0.12));
  mark('higher intensity increases trail brightness and selection-pulse duration while highlights stay on actual grid points');
  await page.emulateMedia({reducedMotion:'reduce'});assert.equal((await sample()).length,0);await page.emulateMedia({reducedMotion:'no-preference'});
  await settings('外观');await page.getByLabel('启用画布点动效',{exact:false}).uncheck();await close();assert.equal((await sample()).length,0);
  await settings('外观');await page.getByRole('button',{name:'恢复默认',exact:true}).click();assert.equal(await page.getByRole('slider',{name:/强度/}).inputValue(),'100');assert.ok(await page.getByLabel('启用画布点动效',{exact:false}).isChecked());
  await page.screenshot({path:path.join(OUT,'motion-strength.png')});mark('reduced motion and disabled effects override intensity; reset restores defaults');
  assert.deepEqual(errors,[]);mark('no browser runtime errors');
  fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,serviceId:service.id,realKeychain:true,realInference:false,lowMax,highMax,lowSelectionMax,highSelectionMax},null,2));
 }catch(e){await page.screenshot({path:path.join(OUT,'failure.png')});fs.writeFileSync(path.join(OUT,'failure.txt'),String(e)+'\n'+await page.locator('body').innerText());throw e}
 finally{release();await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
