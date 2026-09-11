/* Parent-authored browser acceptance against an isolated real kxy server. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const BASE = process.env.KXY_BASE_URL || 'http://127.0.0.1:8712';
const OUT = path.join(__dirname, 'v3-evidence', 'independent-browser');
fs.mkdirSync(OUT, {recursive:true});
const passed = [], errors = [];
const mark = label => { passed.push(label); console.log('PASS', label); };
const node = (id, type, data={}, x=100, y=150) => ({id,type,position:{x,y},data:{label:id,...data}});
const edge = (source,target) => ({id:`${source}-${target}`,source,target,sourceHandle:'result',targetHandle:'items'});
const flow = (nodes,edges=[]) => ({version:'kxy.workflow.v1',id:'v3-independent',name:'独立验收',nodes,edges});

(async()=>{
  const browser = await chromium.launch({headless:true, executablePath:process.env.KXY_BROWSER_EXECUTABLE || '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
    window.__kxyArcs=[];
    const original=CanvasRenderingContext2D.prototype.arc;
    CanvasRenderingContext2D.prototype.arc=function(...args){
      if(this.canvas.dataset.testid==='motion-canvas'){
        window.__kxyArcs.push({x:args[0],y:args[1],time:performance.now()});
        if(window.__kxyArcs.length>2500)window.__kxyArcs.splice(0,500);
      }
      return original.apply(this,args);
    };
  });
  const nodes = ()=>page.locator('.react-flow__node');
  const undo = ()=>page.getByRole('button',{name:'撤回',exact:true});
  const addText = ()=>page.locator('.library-item').filter({hasText:'文字输入'}).click();
  const settle = ()=>page.waitForTimeout(200);
  const exportFlow = async()=>{
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出',exact:true}).click();
    return JSON.parse(fs.readFileSync(await(await pending).path(),'utf8'));
  };
  const importFlow=async value=>{
    await page.locator('input[accept="application/json,.json"]').setInputFiles({name:'v3-independent.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(value))});
    await page.waitForFunction(id=>!!document.querySelector(`.react-flow__node[data-id="${id}"]`),value.nodes[0].id);
    await page.getByTitle('自动适配画布',{exact:true}).click(); await settle();
  };
  const style=async changes=>{
    const current=await(await page.request.get(BASE+'/api/settings')).json();
    const response=await page.request.put(BASE+'/api/settings',{data:{...current,...changes}});
    assert.equal(response.status(),200,await response.text());
    await page.reload();await page.locator('.left-panel').waitFor();await settle();
  };
  const canonical=value=>({nodes:value.nodes.map(n=>({id:n.id,type:n.type,position:n.position,data:{...n.data,...(n.data.workflow?{workflow:canonical(n.data.workflow)}:{})}})).sort((a,b)=>a.id.localeCompare(b.id)),edges:value.edges.map(e=>({source:e.source,target:e.target,sourceHandle:e.sourceHandle,targetHandle:e.targetHandle})).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)))});
  try{
    await page.goto(BASE);await page.locator('.left-panel').waitFor();await settle();
    await style({undo_limit:5,motion_enabled:true});
    const initialCount=await nodes().count();
    await addText();await addText();await addText();
    assert.equal(await nodes().count(),initialCount+3);
    await undo().click();await settle();assert.equal(await nodes().count(),initialCount+2);
    await undo().click();await settle();assert.equal(await nodes().count(),initialCount+1);
    await undo().click();await settle();assert.equal(await nodes().count(),initialCount);
    mark('three independent additions restore successive actual graph states');

    await style({undo_limit:2});
    const startCount=await nodes().count();
    await addText();await addText();await addText();
    await undo().click();await undo().click();await settle();
    assert.equal(await nodes().count(),startCount+1);assert.ok(await undo().isDisabled());
    mark('saved history depth truncates to two and stops at oldest retained edit');
    await style({undo_limit:5});

    await importFlow(flow([node('move-source','text',{text:'SYNTHETIC_MOVE'},80,180),node('move-output','container',{},440,180)],[edge('move-source','move-output')]));
    const beforeDrag=await exportFlow();
    const dragNode=page.locator('.react-flow__node[data-id="move-source"]');
    const bounds=await dragNode.boundingBox();
    await page.mouse.move(bounds.x+bounds.width/2,bounds.y+30);await page.mouse.down();
    await page.mouse.move(bounds.x+bounds.width/2+90,bounds.y+90,{steps:16});await page.mouse.up();await settle();
    const afterDrag=await exportFlow();
    assert.notDeepEqual(afterDrag.nodes.find(n=>n.id==='move-source').position,beforeDrag.nodes.find(n=>n.id==='move-source').position);
    await undo().click();await settle();
    assert.deepEqual((await exportFlow()).nodes.find(n=>n.id==='move-source').position,beforeDrag.nodes.find(n=>n.id==='move-source').position);
    mark('one drag gesture restores original coordinates in one undo');

    await dragNode.click();await page.keyboard.press('Backspace');await settle();
    assert.equal(await nodes().count(),1);
    await undo().click();await settle();
    const restored=await exportFlow();
    assert.equal(restored.nodes.length,2);assert.equal(restored.edges.length,1);
    mark('keyboard deletion restores the node and incident edge together');

    const inner=flow([node('inner-in','subflow_input',{},0,100),node('inner-out','subflow_output',{},500,100)],[edge('inner-in','inner-out')]);
    await importFlow(flow([node('outer-box','blackbox',{workflow:inner},200,160)]));
    const baseline=canonical(await exportFlow());
    const historyBefore=await undo().getAttribute('title');
    await page.locator('.react-flow__node[data-id="outer-box"]').dblclick();await settle();
    await page.getByRole('button',{name:'返回上一级',exact:false}).click();await settle();
    assert.equal(await undo().getAttribute('title'),historyBefore);
    await page.locator('.react-flow__node[data-id="outer-box"]').dblclick();await settle();
    await addText();await settle();
    await page.getByRole('button',{name:'返回上一级',exact:false}).click();await settle();
    await undo().click();await settle();
    // Undo restores the edit's canvas context; return to compare the full graph.
    if(await page.getByRole('button',{name:'返回上一级',exact:false}).count()){
      await page.getByRole('button',{name:'返回上一级',exact:false}).click();await settle();
    }
    assert.deepEqual(canonical(await exportFlow()),baseline);
    mark('blackbox navigation adds no history and inner edits undo consistently after returning');

    await page.getByTitle('全局设置',{exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'全局设置'});
    await dialog.getByRole('button',{name:'外观',exact:true}).click();
    await dialog.getByLabel('文本字体',{exact:true}).fill('PingFang SC');
    await dialog.getByLabel('代码字体',{exact:true}).fill('Menlo');
    await dialog.getByLabel('文本字号',{exact:true}).fill('18');
    await dialog.getByLabel('代码字号',{exact:true}).fill('16');
    await dialog.getByRole('button',{name:'保存为默认样式',exact:true}).click();await settle();
    await page.reload();await page.getByTitle('全局设置',{exact:true}).click();
    await dialog.getByRole('button',{name:'外观',exact:true}).click();
    assert.equal(await dialog.getByLabel('文本字体',{exact:true}).inputValue(),'PingFang SC');
    assert.equal(await dialog.getByLabel('代码字体',{exact:true}).inputValue(),'Menlo');
    const preview=await dialog.locator('.appearance-preview code').evaluate(el=>({family:getComputedStyle(el).fontFamily,size:getComputedStyle(el).fontSize}));
    assert.match(preview.family,/Menlo/);assert.equal(preview.size,'16px');
    const headingFont=await dialog.locator('h2').evaluate(el=>getComputedStyle(el).fontFamily);
    assert.match(headingFont,/PingFang SC/);
    await page.screenshot({path:path.join(OUT,'appearance.png')});
    mark('separate text/code fonts and sizes save as default and reload');
    await dialog.getByTitle('关闭设置',{exact:true}).click();

    await importFlow(flow([node('particle-card','text',{text:'SYNTHETIC_PARTICLES'},180,200)]));
    await page.waitForTimeout(1600);
    await page.evaluate(()=>window.__kxyArcs=[]);
    const frame=await page.locator('.flow-frame').boundingBox();
    await page.mouse.move(frame.x+80,frame.y+80);
    await page.mouse.move(frame.x+240,frame.y+100,{steps:15});await page.waitForTimeout(100);
    assert.ok(await page.evaluate(()=>window.__kxyArcs.length>0));
    await page.screenshot({path:path.join(OUT,'pointer-trail.png')});
    await page.waitForTimeout(1200);await page.evaluate(()=>window.__kxyArcs=[]);
    await page.locator('.react-flow__node[data-id="particle-card"]').click();await page.waitForTimeout(100);
    const outside=await page.evaluate(()=>{
      const frame=document.querySelector('.flow-frame').getBoundingClientRect();
      const rect=document.querySelector('.react-flow__node[data-id="particle-card"]').getBoundingClientRect();
      return window.__kxyArcs.some(p=>p.x<rect.left-frame.left||p.x>rect.right-frame.left||p.y<rect.top-frame.top||p.y>rect.bottom-frame.top);
    });
    assert.ok(outside,'selection particles must be visible outside the card rectangle');
    await page.screenshot({path:path.join(OUT,'selected-particles.png')});
    await page.waitForTimeout(1300);await page.evaluate(()=>window.__kxyArcs=[]);
    await addText();await page.waitForTimeout(180);
    assert.ok(await page.evaluate(()=>window.__kxyArcs.length>0),'newly added selected card must emit particles after layout');
    await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(200);
    await page.evaluate(()=>window.__kxyArcs=[]);
    await page.mouse.move(frame.x+90,frame.y+130,{steps:10});await page.waitForTimeout(150);
    assert.equal(await page.evaluate(()=>window.__kxyArcs.length),0);
    assert.equal(await page.getByTestId('motion-canvas').evaluate(el=>getComputedStyle(el).pointerEvents),'none');
    mark('actual Canvas drawing follows pointer and surrounds selected cards; reduced motion stops it');
    assert.deepEqual(errors,[]);
  } finally {
    fs.writeFileSync(path.join(OUT,'results.json'),JSON.stringify({base:BASE,passed,errors},null,2));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exit(1)});
