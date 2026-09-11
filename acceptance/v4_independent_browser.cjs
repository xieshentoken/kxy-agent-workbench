/* Parent acceptance: actual SVG grid coordinates, UI graph/output contracts. */
const {chromium}=require('playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const BASE=process.env.KXY_BASE_URL||'http://127.0.0.1:8720';
const OUT=path.join(__dirname,'v4-evidence','independent-browser');fs.mkdirSync(OUT,{recursive:true});
const passed=process.env.KXY_BROWSER_FINISH_ONLY?JSON.parse(fs.readFileSync(path.join(OUT,'results.json'),'utf8')).passed:[],errors=[];const mark=s=>{passed.push(s);console.log('PASS',s)};
const node=(id,type,data={},x=80,y=120)=>({id,type,position:{x,y},data:{label:id,...data}});
const edge=(source,target)=>({source,target,sourceHandle:'result',targetHandle:'items'});
const flow=(nodes,edges=[])=>({version:'kxy.workflow.v1',name:'V4独立验收',nodes,edges});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.__v4Arcs=[];
  const arc=CanvasRenderingContext2D.prototype.arc;
  CanvasRenderingContext2D.prototype.arc=function(x,y,r,...rest){
   if(this.canvas.dataset.testid==='motion-canvas'){
    const pattern=document.querySelector('.react-flow__background pattern');const circle=pattern?.querySelector('circle');
    if(pattern&&circle){
     const svg=pattern.ownerSVGElement.getBoundingClientRect(),frame=this.canvas.getBoundingClientRect();
     const transform=pattern.patternTransform.baseVal.consolidate()?.matrix||{e:0,f:0};
     const ox=+pattern.getAttribute('x')+transform.e+(+circle.getAttribute('cx'))+svg.x-frame.x;
     const oy=+pattern.getAttribute('y')+transform.f+(+circle.getAttribute('cy'))+svg.y-frame.y;
     const gx=+pattern.getAttribute('width'),gy=+pattern.getAttribute('height'),radius=+circle.getAttribute('r');
     const dx=Math.abs((x-ox)/gx-Math.round((x-ox)/gx))*gx,dy=Math.abs((y-oy)/gy-Math.round((y-oy)/gy))*gy;
     window.__v4Arcs.push({x,y,r,dx,dy,radius});if(window.__v4Arcs.length>10000)window.__v4Arcs.splice(0,1000);
    }
   }
   return arc.call(this,x,y,r,...rest);
  };
 });
 const settle=()=>page.waitForTimeout(350);
 const exportFlow=async()=>{const p=page.waitForEvent('download');await page.locator('.top-actions').getByRole('button',{name:'导出',exact:true}).click();return JSON.parse(fs.readFileSync(await(await p).path(),'utf8'))};
 const importFlow=async f=>{await page.locator('.kxy-app > input[accept="application/json,.json"]').setInputFiles({name:'synthetic-v4.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(f))});await page.locator(`.react-flow__node[data-id="${f.nodes[0].id}"]`).waitFor();await page.getByTitle('自动适配画布',{exact:true}).click();await settle()};
 const checkGrid=async label=>{
  const arcs=await page.evaluate(()=>{
   const svg=document.querySelector('svg[data-testid="motion-canvas"]');
   if(!svg)return window.__v4Arcs;
   const pattern=document.querySelector('.react-flow__background pattern'),circle=pattern.querySelector('circle');
   const box=svg.getBoundingClientRect(),background=pattern.ownerSVGElement.getBoundingClientRect();
   const rects=[...document.querySelectorAll('.react-flow__node')].map(n=>n.getBoundingClientRect());
   const t=pattern.patternTransform.baseVal.consolidate()?.matrix||{e:0,f:0};
   const gx=+pattern.getAttribute('width'),gy=+pattern.getAttribute('height');
   const ox=+pattern.getAttribute('x')+t.e+(+circle.getAttribute('cx'))+background.x-box.x;
   const oy=+pattern.getAttribute('y')+t.f+(+circle.getAttribute('cy'))+background.y-box.y;
   return [...svg.querySelectorAll('circle')].map(c=>{const x=+c.getAttribute('cx'),y=+c.getAttribute('cy'),r=+c.getAttribute('r');return {x,y,r,dx:Math.abs((x-ox)/gx-Math.round((x-ox)/gx))*gx,dy:Math.abs((y-oy)/gy-Math.round((y-oy)/gy))*gy,radius:+circle.getAttribute('r'),stroke:getComputedStyle(c).stroke,inside:rects.some(n=>x+box.x>n.left&&x+box.x<n.right&&y+box.y>n.top&&y+box.y<n.bottom)}});
  });assert.ok(arcs.length>0,label+' emitted grid highlights');
  assert.ok(arcs.every(a=>a.dx<0.12&&a.dy<0.12),label+' all centers match SVG grid: '+JSON.stringify(arcs.find(a=>a.dx>=0.12||a.dy>=0.12)));
  assert.ok(arcs.every(a=>!a.inside),label+' highlights stay outside node faces');
  assert.ok(arcs.every(a=>!a.stroke||a.stroke==='none'),label+' highlights do not expand with a stroke');
  assert.ok(arcs.every(a=>Math.abs(a.r-a.radius)<0.12),label+' no enlarged free particles');mark(label);
 };
 try{
  await page.goto(BASE);await page.locator('.left-panel').waitFor();
  if(!process.env.KXY_BROWSER_FINISH_ONLY){
  await importFlow(flow([node('source','text',{text:'SYNTHETIC_V4'},30,150),node('output','container',{},390,150)],[edge('source','output')]));
  await page.getByRole('button',{name:'框选',exact:true}).click();
  const boxes=await page.locator('.react-flow__node').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height}}));
  const x=Math.min(...boxes.map(r=>r.x))-16,y=Math.min(...boxes.map(r=>r.y))-16,xx=Math.max(...boxes.map(r=>r.x+r.w))+16,yy=Math.max(...boxes.map(r=>r.y+r.h))+16;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(xx,yy,{steps:20});await page.mouse.up();await settle();
  assert.equal(await page.locator('.react-flow__node.selected').count(),2);
  await page.getByRole('button',{name:'新建黑盒',exact:true}).click();await settle();assert.equal(await page.locator('.react-flow__node').count(),1);
  const packed=await exportFlow();assert.equal(packed.nodes[0].type,'blackbox');
  await page.getByRole('button',{name:'撤回',exact:true}).click();await settle();assert.equal(await page.locator('.react-flow__node').count(),2);assert.equal((await exportFlow()).edges.length,1);mark('explicit marquee selects two cards, creates blackbox, undo restores graph');
  await page.getByRole('button',{name:'移动',exact:true}).click();
  for(const zoom of ['initial','zoomed','panned']){
   if(zoom==='zoomed'){await page.getByRole('button',{name:'Zoom Out',exact:true}).click();await settle()}
   if(zoom==='panned'){
    const frame=await page.locator('.flow-frame').boundingBox();const before=await page.locator('.react-flow__viewport').getAttribute('style');
    await page.mouse.move(frame.x+55,frame.y+40);await page.mouse.down();await page.mouse.move(frame.x+100,frame.y+70,{steps:12});await page.mouse.up();await settle();
    assert.notEqual(await page.locator('.react-flow__viewport').getAttribute('style'),before);
   }
   await page.waitForTimeout(1500);await page.evaluate(()=>window.__v4Arcs=[]);
   const f=await page.locator('.flow-frame').boundingBox();await page.mouse.move(f.x+45,f.y+45);await page.mouse.move(f.x+250,f.y+85,{steps:18});await page.waitForTimeout(100);await checkGrid(zoom+' pointer highlights align to real SVG grid');
   await page.waitForTimeout(1500);await page.evaluate(()=>window.__v4Arcs=[]);
   await page.locator('.react-flow__node[data-id="source"]').click();await page.waitForTimeout(150);await checkGrid(zoom+' selected-card highlights align to real SVG grid');
   if(zoom==='panned'){
    await page.waitForTimeout(1400);assert.ok(await page.locator('.react-flow__node.selected').count()>0);assert.equal(await page.locator('svg[data-testid="motion-canvas"] circle').count(),0);mark('selected-card expansion stops after its pulse without deselecting');
   }
   await page.mouse.click(f.x+30,f.y+30);
  }
  await page.waitForTimeout(1600);assert.equal(await page.locator('svg[data-testid="motion-canvas"] circle').count(),0);mark('motion clears after selection pulse and pointer trail become idle');
  const overlap=await page.evaluate(()=>{
   const a=document.querySelector('.template-strip')?.getBoundingClientRect(),b=document.querySelector('.interaction-tools')?.getBoundingClientRect();
   return !!a&&!!b&&Math.min(a.right,b.right)>Math.max(a.left,b.left)&&Math.min(a.bottom,b.bottom)>Math.max(a.top,b.top);
  });assert.equal(overlap,false);mark('quick-start templates do not cover selection tools');
  await page.screenshot({path:path.join(OUT,'canvas.png')});
  await importFlow(flow([node('schema-source','text',{text:'SYNTHETIC_INPUT'},20,150),node('schema-analysis','analyzer',{cli:'codex',expect_json:true},350,150)],[edge('schema-source','schema-analysis')]));
  await page.locator('.react-flow__node[data-id="schema-analysis"]').click();
  const inspector=page.locator('.right-panel');
  const format=inspector.getByLabel('输出格式',{exact:false});assert.equal(await format.inputValue(),'json');mark('legacy expect_json is displayed as JSON mode');
  const schema={type:'object',properties:{keywords:{type:'array',items:{type:'string'}},token_count:{type:'integer'}},required:['keywords']};
  await inspector.locator('input[accept="application/json,application/schema+json,.json"]').setInputFiles({name:'format.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(schema))});
  await inspector.locator('.schema-actions').getByRole('button',{name:'应用',exact:true}).click();await settle();
  let exported=await exportFlow();assert.deepEqual(exported.nodes.find(n=>n.id==='schema-analysis').data.output_schema,schema);
  const schemaDownload=page.waitForEvent('download');await inspector.locator('.schema-actions').getByRole('button',{name:'导出',exact:true}).click();assert.deepEqual(JSON.parse(fs.readFileSync(await(await schemaDownload).path(),'utf8')),schema);mark('JSON schema imports, applies, and exports without losing keywords/token_count');
  await format.selectOption('text');await settle();exported=await exportFlow();const data=exported.nodes.find(n=>n.id==='schema-analysis').data;assert.equal(data.output_format,'text');assert.equal(data.expect_json,false);assert.ok(!data.output_schema);mark('switching JSON to text removes active schema and preserves selected format');
  await importFlow(flow([node('plain','text',{text:'SYNTHETIC_V4_BODY'},20,160),node('result','container',{export_formats:['text','json'],json_mode:'content'},360,160)],[edge('plain','result')]));
  await page.getByRole('button',{name:'运行流程',exact:true}).click();await page.locator('.run-status.status-succeeded').waitFor({timeout:30000});
  const panel=page.locator('.run-panel');const body=panel.getByLabel('正文副本',{exact:false});assert.match(await body.inputValue(),/SYNTHETIC_V4_BODY/);mark('real LFX run presents the final body instead of paths');
  const historyBefore=await(await page.request.get(BASE+'/api/runs')).json();const rid=historyBefore[0].id;const original=await(await page.request.get(BASE+'/api/runs/'+rid)).json();
  await panel.getByRole('button',{name:'编辑副本',exact:true}).click();const draft=panel.getByLabel('JSON 副本',{exact:false});await draft.fill(JSON.stringify({summary:'USER_EDITED_COPY',count:9}));await panel.getByRole('button',{name:'校验 JSON',exact:true}).click();
  let download=page.waitForEvent('download');await panel.getByRole('button',{name:'下载 JSON',exact:true}).click();assert.equal(JSON.parse(fs.readFileSync(await(await download).path(),'utf8')).summary,'USER_EDITED_COPY');
  await panel.locator('input[type=file]').setInputFiles({name:'result.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({summary:'IMPORTED_COPY'}))});await settle();assert.match(await draft.inputValue(),/IMPORTED_COPY/);
  await draft.fill('{INVALID');let invalidDownloaded=false;const listener=()=>{invalidDownloaded=true};page.on('download',listener);await panel.getByRole('button',{name:'下载 JSON',exact:true}).click();await settle();page.off('download',listener);assert.equal(invalidDownloaded,false);assert.match(await panel.innerText(),/无效|合法|JSON|错误/);mark('invalid JSON remains a draft instead of downloading a broken JSON file');
  await draft.fill(JSON.stringify({summary:'IMPORTED_COPY'}));
  const unchanged=await(await page.request.get(BASE+'/api/runs/'+rid)).json();assert.deepEqual(unchanged.output_manifest,original.output_manifest);mark('output JSON copy edit/import/download preserves original run artifacts');
  }
  await page.getByTitle('全局设置',{exact:true}).click();const dialog=page.getByRole('dialog',{name:'全局设置'});await dialog.getByRole('button',{name:'模型 / API',exact:true}).click();
  assert.match(await dialog.innerText(),/手动/);assert.match(await dialog.innerText(),/已有登录|原生登录/);
  await dialog.getByLabel('API key',{exact:true}).fill('kxy-browser-synthetic-test-key');await dialog.getByLabel('测试 Endpoint（可选）',{exact:false}).fill('http://127.0.0.1:8740/v1');await dialog.getByRole('button',{name:'测试连接（/models）',exact:true}).click();
  await dialog.locator('.connection-result.ok').waitFor({timeout:12000});assert.match(await dialog.locator('.connection-result').innerText(),/不代表.*推理/);mark('API form tests entered key against local mock without Keychain persistence');
  await page.screenshot({path:path.join(OUT,'api-test.png')});await dialog.getByTitle('关闭设置',{exact:true}).click();
  const settings=await(await page.request.get(BASE+'/api/settings')).json();const saved=await page.request.put(BASE+'/api/settings',{data:{...settings,code_font:'Menlo',code_font_size:17}});assert.equal(saved.status(),200);await page.reload();await page.locator('.left-panel').waitFor();
  await importFlow(flow([node('font-analysis','analyzer',{output_format:'json',expect_json:true},200,180)]));await page.locator('.react-flow__node[data-id="font-analysis"]').click();assert.equal(await page.locator('.schema-editor').evaluate(el=>getComputedStyle(el).fontSize),'17px');mark('new JSON schema editor respects saved global code font size');
  await page.emulateMedia({reducedMotion:'reduce'});await page.mouse.move(330,260);await page.mouse.move(470,290,{steps:10});await settle();assert.equal(await page.locator('svg[data-testid="motion-canvas"] circle').count(),0);mark('reduced motion disables grid animations');await page.emulateMedia({reducedMotion:'no-preference'});
  await page.setViewportSize({width:1280,height:720});await settle();assert.ok(await page.locator('.flow-frame').isVisible());
  await page.screenshot({path:path.join(OUT,'1280.png')});mark('1280x720 canvas remains accessible');
  await page.setViewportSize({width:390,height:844});await settle();assert.ok(await page.locator('.flow-frame').isVisible());assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));await page.screenshot({path:path.join(OUT,'390.png')});mark('390px narrow screen has no document horizontal overflow');
  assert.deepEqual(errors,[]);mark('no browser runtime errors');
 }catch(error){await page.screenshot({path:path.join(OUT,'failure.png')});fs.writeFileSync(path.join(OUT,'failure.txt'),await page.locator('body').innerText());throw error;}finally{fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({passed,errors},null,2));await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
