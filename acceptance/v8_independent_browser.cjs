/* Parent acceptance: isolated API/LFX and synthetic analyzer; no real inference. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE='http://127.0.0.1:8724',DATA='/private/tmp/kxy-v8-browser-data';
const OUT=path.join(__dirname,'v8-evidence','browser');fs.mkdirSync(OUT,{recursive:true});
const passed=[],errors=[],mark=x=>{passed.push(x);console.log('PASS',x)};
const n=(id,type,data={},x=0)=>({id,type,data,position:{x,y:120}});
const e=(source,target)=>({id:source+'-'+target,source,target,sourceHandle:'result',targetHandle:'items'});
const f=(nodes,edges)=>({version:'kxy.workflow.v1',name:'V8 browser synthetic',nodes,edges});
const child=f([n('entry','subflow_input'),n('inside','text',{text:'nested synthetic'},260),n('exit','subflow_output',{},520)],[e('entry','exit'),e('inside','exit')]);
const deep=f([n('entry','subflow_input'),n('long'.repeat(25),'blackbox',{workflow:child},260),n('exit','subflow_output',{},520)],[e('entry','long'.repeat(25)),e('long'.repeat(25),'exit')]);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',x=>errors.push(x.message));
 const get=async route=>(await page.request.get(BASE+route)).json();
 const post=async(route,data)=>{const r=await page.request.post(BASE+route,{data});assert.ok(r.ok(),await r.text());return r.json()};
 const rows=()=>page.locator('.preset-item');
 const named=name=>rows().filter({has:page.locator('.preset-expand span',{hasText:name})});
 const exportFlow=async()=>{const pending=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'))};
 const importFlow=async document=>{await page.locator('input[type=file][accept="application/json,.json"]').setInputFiles({name:'v8.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(document))});await page.waitForTimeout(250)};
 const settings=async()=>{await page.getByTitle('全局设置',{exact:true}).click();await page.getByRole('button',{name:'外观',exact:true}).click()};
 const close=()=>page.getByTitle('关闭设置',{exact:true}).click();
 const setStrength=async value=>{const slider=page.getByRole('slider',{name:/强度/});await slider.evaluate((el,v)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,String(v));el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))},value)};
 try {
  for(const p of await get('/api/presets'))await page.request.delete(BASE+(p.source==='analyzer'?'/api/analyzers/':'/api/presets/')+p.id);
  await page.request.put(BASE+'/api/settings',{data:{motion_intensity:30,motion_enabled:true}});
  await post('/api/analyzers',{name:'V8 legacy analyzer',config:{cli:'codex',prompt:'legacy'}});
  for(const kind of ['file','text','input','container','condition','human'])await post('/api/presets',{kind,name:'V8 '+kind,config:{label:'V8 '+kind,...(kind==='file'?{file_id:'missing-v8-file'}:{}),...(kind==='text'?{text:'literal'}:{})}});
  await post('/api/presets',{kind:'blackbox',name:'V8 nested missing',config:{workflow:f([n('entry','subflow_input'),n('a','analyzer',{cli:'codex',skill_ids:['missing-v8-skill']}),n('exit','subflow_output')],[e('entry','a'),e('a','exit')])}});
  for(const name of ['A sort text','Z sort text'])await post('/api/presets',{kind:'text',name,config:{label:name,text:name}});
  await page.goto(BASE);await page.waitForFunction(()=>document.querySelectorAll('.preset-group').length===8);
  assert.equal(await named('V8 legacy analyzer').count(),1);mark('eight component categories and legacy analyzer appear without duplicates');
  const textGroup=page.locator('.preset-group').filter({has:named('A sort text')});
  assert.equal(await textGroup.locator('.preset-expand span').first().innerText(),'Z sort text');
  await page.getByRole('button',{name:'切换预设排序',exact:true}).click();
  assert.equal(await textGroup.locator('.preset-expand span').first().innerText(),'A sort text');mark('category groups switch between newest date and name order');
  assert.ok(await named('V8 nested missing').locator('.preset-apply').isDisabled());
  assert.match(await named('V8 nested missing').innerText(),/missing-v8-skill/);mark('missing resources inside blackboxes are visible and block insertion');
  const document=f([n('source','text',{label:'Source',text:'hello'}),n('box','blackbox',{label:'V8 UI blackbox',workflow:deep},300),n('out','container',{export_formats:[]},600)],[e('source','box'),e('box','out')]);
  await importFlow(document);await page.locator('.react-flow__node[data-id="box"]').click();
  const save=page.waitForResponse(r=>r.url().endsWith('/api/presets')&&r.request().method()==='POST');
  await page.locator('.right-panel').getByRole('button',{name:/保存.*预设/}).click();assert.ok((await save).ok());await named('V8 UI blackbox').waitFor();
  const original=await exportFlow();await named('V8 UI blackbox').locator('.preset-expand').click();assert.deepEqual((await exportFlow()).nodes,original.nodes);
  await named('V8 UI blackbox').locator('.preset-apply').click();await named('V8 UI blackbox').locator('.preset-apply').click();
  const inserted=await exportFlow();assert.equal(inserted.nodes.length,original.nodes.length+2);
  for(const box of inserted.nodes.filter(x=>x.type==='blackbox')){
    const response=await post('/api/workflows/validate',f([box],[]));assert.ok(response.ok,JSON.stringify(response));
  }
  const added=inserted.nodes.filter(x=>!original.nodes.some(y=>y.id===x.id));
  const ids=[];const visit=w=>{for(const node of w.nodes){ids.push(node.id);assert.ok(node.id.length<=100);if(node.type==='blackbox')visit(node.data.workflow)}};for(const box of added){ids.push(box.id);visit(box.data.workflow)}
  assert.equal(new Set(ids).size,ids.length);await page.getByRole('button',{name:'撤回',exact:true}).click();assert.equal((await exportFlow()).nodes.length,original.nodes.length+1);
  mark('UI saves nested blackbox; details do not apply; repeated insertion remaps IDs and undo removes one insertion');
  await page.setViewportSize({width:1280,height:720});await rows().last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(OUT,'presets-1280.png')});assert.ok(await rows().last().isVisible());
  await page.reload();await named('V8 UI blackbox').waitFor();mark('saved presets survive reload and remain reachable at 1280x720');
  await page.setViewportSize({width:1440,height:900});await settings();assert.equal(await page.getByRole('slider',{name:/强度/}).inputValue(),'30');await close();assert.equal(await page.locator('.motion-canvas').getAttribute('data-motion-coefficient'),'1');
  await settings();await setStrength(100);await close();assert.equal(await page.locator('.motion-canvas').getAttribute('data-motion-coefficient'),'3');
  const frame=await page.locator('.flow-frame').boundingBox();await page.mouse.move(frame.x+frame.width-50,frame.y+50);await page.mouse.move(frame.x+frame.width-80,frame.y+80,{steps:4});await page.waitForTimeout(80);
  const grid=await page.evaluate(()=>{const p=document.querySelector('.react-flow__background pattern'),d=p.querySelector('circle'),m=p.patternTransform.baseVal.consolidate()?.matrix||{e:0,f:0};return {gx:+p.getAttribute('width'),gy:+p.getAttribute('height'),ox:+p.getAttribute('x')+m.e+(+d.getAttribute('cx')),oy:+p.getAttribute('y')+m.f+(+d.getAttribute('cy')),r:+d.getAttribute('r'),dots:[...document.querySelectorAll('.motion-grid-arc')].map(x=>({x:+x.getAttribute('cx'),y:+x.getAttribute('cy'),r:+x.getAttribute('r')}))}});
  assert.ok(grid.dots.length>0);for(const p of grid.dots){assert.ok(Math.abs((p.x-grid.ox)/grid.gx-Math.round((p.x-grid.ox)/grid.gx))*grid.gx<.12);assert.ok(Math.abs((p.y-grid.oy)/grid.gy-Math.round((p.y-grid.oy)/grid.gy))*grid.gy<.12);assert.ok(Math.abs(p.r-grid.r)<.12)}
  await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>matchMedia('(prefers-reduced-motion: reduce)').matches&&getComputedStyle(document.querySelector('.motion-canvas')).display==='none',null,{timeout:1000});await page.emulateMedia({reducedMotion:'no-preference'});
  await settings();await setStrength(0);await page.getByRole('button',{name:'保存为默认样式',exact:true}).click();await close();await page.reload();assert.equal((await get('/api/settings')).motion_intensity,0);assert.equal(await page.locator('.motion-grid-arc').count(),0);
  await settings();await page.getByRole('button',{name:'恢复默认',exact:true}).click();assert.equal(await page.getByRole('slider',{name:/强度/}).inputValue(),'30');await page.screenshot({path:path.join(OUT,'motion-scale.png')});await close();mark('30 equals old maximum, 100 uses coefficient 3, grid alignment and reduced motion retained, zero persists');
  const workflow=f([n('s','text',{text:'synthetic'}),n('a','analyzer',{cli:'codex',prompt:'V8_UPSTREAM'},250),n('b','analyzer',{cli:'codex',prompt:'V8_FAIL_ONCE'},500),n('o','container',{export_formats:[],allowed_file_extensions:[]},750)],[e('s','a'),e('a','b'),e('b','o')]);
  await importFlow(workflow);const submit=page.waitForResponse(r=>r.url().endsWith('/api/runs')&&r.request().method()==='POST');await page.getByRole('button',{name:'运行流程',exact:true}).click();const rid=(await(await submit).json()).id;
  await page.getByRole('button',{name:'从检查点恢复',exact:true}).waitFor();await page.locator('.react-flow__node[data-id="a"]').click();await page.locator('.right-panel').getByLabel('分析提示词',{exact:false}).fill('EDITED AFTER FAILURE');
  const resume=page.waitForResponse(r=>r.url().endsWith('/resume'));await page.getByRole('button',{name:'从检查点恢复',exact:true}).click();assert.ok((await resume).ok());
  let final;for(let i=0;i<100;i++){final=await get('/api/runs/'+rid);if(final.status==='succeeded')break;await page.waitForTimeout(100)}assert.equal(final.status,'succeeded',final.error);
  const counts=JSON.parse(fs.readFileSync(path.join(DATA,'synthetic-counts.json')));assert.equal(counts[rid+':a'],1);assert.equal(counts[rid+':b'],2);assert.equal(final.snapshot.workflow.nodes.find(x=>x.id==='a').data.prompt,'V8_UPSTREAM');assert.equal(final.attempts.length,2);
  await page.locator('.run-status.status-succeeded').waitFor();await page.screenshot({path:path.join(OUT,'resumed-run.png')});mark('UI restores original run snapshot; completed analyzer called once, failed analyzer retried, two attempts audited');
  assert.deepEqual(errors,[]);mark('no browser runtime errors');fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors,realInference:false,runId:rid},null,2));
 }catch(error){await page.screenshot({path:path.join(OUT,'failure.png')});const motion=await page.evaluate(()=>({reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,visible:document.visibilityState,dots:document.querySelectorAll('.motion-grid-arc').length}));fs.writeFileSync(path.join(OUT,'failure.txt'),String(error)+'\n'+JSON.stringify(motion)+'\n'+await page.locator('body').innerText());throw error}
 finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
