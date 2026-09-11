/*
 * kxy V3 frontend acceptance. Use an isolated backend/data root and an
 * existing browser binary, for example:
 *   KXY_BASE_URL=http://127.0.0.1:8712 \
 *   KXY_BROWSER_EXECUTABLE='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge' \
 *   node acceptance/v3_browser_checks.cjs
 *
 * The script writes only to /private/tmp unless KXY_V3_OUT is provided.
 * Picker responses are stubbed so native macOS chooser state is not touched.
 */
const { chromium } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const BASE = process.env.KXY_BASE_URL || 'http://127.0.0.1:8711'
const OUT = process.env.KXY_V3_OUT || '/private/tmp/kxy-v3-browser'
const FIXTURE_ROOT = process.env.KXY_V3_FIXTURES || '/private/tmp/kxy-v3-browser-fixtures'
fs.mkdirSync(OUT, { recursive: true })
fs.mkdirSync(FIXTURE_ROOT, { recursive: true })

function makeSkill(name, description, marker) {
  const root = path.join(FIXTURE_ROOT, name)
  fs.mkdirSync(path.join(root, 'references'), { recursive: true })
  fs.writeFileSync(path.join(root, 'SKILL.md'), `---\nname: ${name}\ndescription: ${description}\n---\n\nReturn ${marker}.\n`, 'utf8')
  fs.writeFileSync(path.join(root, 'references', 'method.md'), `Synthetic ${marker}\n`, 'utf8')
}
makeSkill('fixture-skill', 'Synthetic method A', 'KXY_SKILL_A')
makeSkill('fixture-skill-two', 'Synthetic method B', 'KXY_SKILL_B')

const passed = []
const errors = []
const mark = (name) => { passed.push(name); console.log('PASS', name) }
const node = (id, type, data = {}, x = 0, y = 0) => ({ id, type, data: { label: id, ...data }, position: { x, y } })
const edge = (source, target, sourceHandle = 'result') => ({ id: `${source}-${sourceHandle}-${target}`, source, target, sourceHandle, targetHandle: 'items' })
const flow = (nodes, edges) => ({ version: 'kxy.workflow.v1', id: 'v3-browser', name: 'V3 前端验收', nodes, edges })

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.KXY_BROWSER_EXECUTABLE })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(`console: ${message.text()}`) })
  const settings = () => page.getByRole('dialog', { name: '全局设置' })
  const undoCount = async () => Number(await page.locator('.undo-button small').first().innerText().catch(() => '0'))
  const importFlow = async (value) => {
    await page.locator('input[accept="application/json,.json"]').setInputFiles({ name: 'v3-flow.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) })
    await page.waitForFunction((id) => Boolean(document.querySelector(`.react-flow__node[data-id="${id}"]`)), value.nodes[0].id)
    await page.getByTitle('自动适配画布').click()
    await page.waitForTimeout(250)
  }
  const pixelAlpha = () => page.locator('[data-testid="motion-canvas"]').evaluate((canvas) => {
    const context = canvas.getContext('2d')
    if (!context) return 0
    const image = context.getImageData(0, 0, canvas.width, canvas.height).data
    let sum = 0
    for (let index = 3; index < image.length; index += 4) sum += image[index]
    return sum
  })

  try {
    await page.goto(BASE)
    await page.locator('.left-panel').waitFor()
    await page.locator('[data-testid="motion-canvas"]').waitFor()
    await page.waitForTimeout(500)

    // Real pointer motion changes the Canvas pixels; the overlay never owns input.
    const canvas = page.locator('[data-testid="motion-canvas"]')
    assert.equal(await canvas.evaluate((element) => getComputedStyle(element).pointerEvents), 'none')
    const frame = await page.locator('.flow-frame').boundingBox()
    assert.ok(frame)
    await page.mouse.move(frame.x + 90, frame.y + 90)
    await page.mouse.move(frame.x + 230, frame.y + 170, { steps: 8 })
    await page.waitForTimeout(120)
    assert.ok(await pixelAlpha() > 0, 'pointer trail should draw visible Canvas pixels')
    mark('pointer movement produces visible pointer-events-none Canvas grid response')

    await page.getByTitle('全局设置', { exact: true }).click()
    const dialog = settings()
    await dialog.getByRole('button', { name: '外观', exact: true }).click()
    await dialog.getByLabel('文本字体', { exact: true }).fill('PingFang SC')
    await dialog.getByLabel('代码字体', { exact: true }).fill('SF Mono')
    await dialog.getByLabel('文本字号', { exact: true }).fill('17')
    await dialog.getByLabel('代码字号', { exact: true }).fill('15')
    await dialog.getByLabel('撤回步数', { exact: true }).fill('7')
    // Use the repository's multi-color reference so this checks actual image
    // visibility, not only that a one-pixel URL was accepted by the backend.
    const png = fs.readFileSync(path.join(__dirname, '..', 'docs', 'reference.png'))
    const backgroundUpload = page.waitForResponse((response) => response.url().endsWith('/api/appearance/background') && response.request().method() === 'POST')
    await dialog.locator('input[accept="image/png,image/jpeg,image/webp"]').setInputFiles({ name: 'v3-background.png', mimeType: 'image/png', buffer: png })
    assert.equal((await backgroundUpload).status(), 200)
    await page.waitForTimeout(250)
    await dialog.getByRole('button', { name: '保存为默认样式', exact: true }).click()
    await page.waitForTimeout(300)
    await page.reload()
    await page.getByTitle('全局设置', { exact: true }).click()
    await settings().getByRole('button', { name: '外观', exact: true }).click()
    assert.equal(await settings().getByLabel('文本字体', { exact: true }).inputValue(), 'PingFang SC')
    assert.equal(await settings().getByLabel('代码字体', { exact: true }).inputValue(), 'SF Mono')
    assert.equal(await settings().getByLabel('文本字号', { exact: true }).inputValue(), '17')
    assert.equal(await settings().getByLabel('代码字号', { exact: true }).inputValue(), '15')
    assert.equal(await settings().getByLabel('撤回步数', { exact: true }).inputValue(), '7')
    assert.ok(await settings().locator('.appearance-background-preview').evaluate((element) => Boolean(getComputedStyle(element).backgroundImage.includes('url'))))
    mark('local text/code fonts, independent sizes, background upload and default persistence')
    await settings().getByTitle('关闭设置', { exact: true }).click()

    // Skill search/sort preserves a checked candidate through a no-match filter.
    await page.route('**/api/picker', async (route) => route.fulfill({ json: { cancelled: false, path: FIXTURE_ROOT } }))
    await page.getByTitle('全局设置', { exact: true }).click()
    const agentSettings = settings()
    // The settings panel stays mounted between opens, so explicitly return to
    // the Agent tab after the appearance round-trip.
    await agentSettings.getByRole('button', { name: 'Agent 配置', exact: true }).click()
    while (await agentSettings.getByTitle('移除目录', { exact: true }).count()) await agentSettings.getByTitle('移除目录', { exact: true }).first().click()
    await agentSettings.getByRole('button', { name: '添加 Skill 文件夹', exact: true }).click()
    await agentSettings.getByRole('button', { name: '保存 Agent', exact: true }).click()
    const scan = page.waitForResponse((response) => response.url().endsWith('/api/agents/codex/skills') && response.request().method() === 'GET')
    await agentSettings.getByRole('button', { name: '扫描 Skills', exact: true }).click()
    assert.equal((await scan).status(), 200)
    await agentSettings.locator('.candidate-row').filter({ hasText: 'fixture-skill' }).first().waitFor()
    const checked = agentSettings.locator('.candidate-row').filter({ hasText: 'fixture-skill' }).first()
    await checked.locator('input').check()
    await agentSettings.getByLabel('搜索 Skill 名', { exact: true }).fill('definitely-no-skill')
    await agentSettings.getByText('没有匹配的 Skill', { exact: false }).waitFor()
    assert.equal(await agentSettings.locator('.candidate-row').count(), 0)
    await agentSettings.getByLabel('搜索 Skill 名', { exact: true }).fill('')
    assert.equal(await checked.locator('input').isChecked(), true)
    await agentSettings.getByLabel('Skill 排序', { exact: true }).selectOption('modified_at')
    await agentSettings.getByLabel('切换 Skill 排序方向', { exact: true }).click()
    mark('Skill name search, name/date direction controls and checked-state preservation')

    // MCP discovery is explicitly initiated and must return a public metadata response.
    const mcpResponse = page.waitForResponse((response) => response.url().endsWith('/api/agents/codex/mcps') && response.request().method() === 'GET')
    await agentSettings.getByRole('button', { name: '发现 MCP（仅读取配置）', exact: true }).click()
    assert.equal((await mcpResponse).status(), 200)
    assert.match(await agentSettings.innerText(), /不会启动服务|默认不启用/)
    mark('MCP discovery is explicit, metadata-only and visibly opt-in')
    await agentSettings.getByTitle('关闭设置', { exact: true }).click()

    // Add, multi-file import and one-drag undo each create one graph step.
    const initialCount = await page.locator('.react-flow__node').count()
    await page.locator('.library-item').filter({ hasText: '文字输入' }).click()
    await page.waitForFunction((count) => document.querySelectorAll('.react-flow__node').length === count + 1, initialCount)
    assert.ok(await undoCount() >= 1)
    await page.locator('.undo-button').click()
    await page.waitForFunction((count) => document.querySelectorAll('.react-flow__node').length === count, initialCount)
    const beforeFiles = await page.locator('.react-flow__node').count()
    const files = await page.evaluateHandle(() => { const data = new DataTransfer(); data.items.add(new File(['A'], 'v3-a.md', { type: 'text/markdown' })); data.items.add(new File(['B'], 'v3-b.md', { type: 'text/markdown' })); return data })
    await page.locator('.flow-frame').dispatchEvent('drop', { dataTransfer: files, clientX: frame.x + 410, clientY: frame.y + 290 })
    await page.waitForFunction((count) => document.querySelectorAll('.react-flow__node').length === count + 2, beforeFiles, { timeout: 20000 })
    await page.locator('.undo-button').click()
    await page.waitForFunction((count) => document.querySelectorAll('.react-flow__node').length === count, beforeFiles)
    const draggable = page.locator('.react-flow__node').first()
    const beforeDrag = await draggable.boundingBox()
    const beforeDragHistory = await undoCount()
    assert.ok(beforeDrag)
    await page.mouse.move(beforeDrag.x + 40, beforeDrag.y + 40)
    await page.mouse.down(); await page.mouse.move(beforeDrag.x + 130, beforeDrag.y + 70, { steps: 8 }); await page.mouse.up()
    await page.waitForTimeout(120)
    assert.equal(await undoCount(), beforeDragHistory + 1)
    await page.locator('.undo-button').click()
    mark('add, multi-file import and one-drag gesture each undo as one graph step')

    const editable = page.locator('.react-flow__node').first()
    await editable.click()
    const nameField = page.locator('.right-panel .form-field').filter({ hasText: '节点名称' }).first().locator('input')
    await page.locator('.react-flow__node.selected').first().waitFor()
    await nameField.waitFor({ state: 'visible' })
    const editableId = await editable.getAttribute('data-id')
    const originalName = await nameField.inputValue()
    await nameField.fill('连续输入应合并')
    await nameField.press('Meta+z')
    assert.equal(await nameField.inputValue(), originalName)
    await nameField.fill('连续输入应合并')
    await page.locator('.undo-button').click()
    const restoredEditable = page.locator(`.react-flow__node[data-id="${editableId}"]`)
    await restoredEditable.click()
    const restoredNameField = page.locator('.right-panel .form-field').filter({ hasText: '节点名称' }).first().locator('input')
    await restoredNameField.waitFor({ state: 'visible' })
    assert.equal(await restoredNameField.inputValue(), originalName)
    mark('text editor keeps native typing undo separate and graph undo restores the field after reselection')

    // Nested blackbox edit is captured by the inner graph history; returning is navigation only.
    const boxFlow = flow([node('box-source', 'text', { text: 'V3_BOX_SOURCE' }, 30, 220), node('box-review', 'human', { content: '旧的黑盒内容' }, 300, 220), node('box-out', 'container', {}, 580, 220)], [edge('box-source', 'box-review'), edge('box-review', 'box-out')])
    await importFlow(boxFlow)
    if (await page.getByTitle('收起执行面板').count()) await page.getByTitle('收起执行面板').click()
    await page.locator('.react-flow__node[data-id="box-review"]').click()
    await page.getByTitle('封装选中节点为黑盒子').click()
    await page.getByRole('button', { name: '进入编辑内部画布', exact: true }).click()
    const innerReview = page.locator('.react-flow__node[data-id="box-review"]')
    await innerReview.click()
    await page.getByLabel('确认说明', { exact: false }).fill('新的黑盒内容')
    await page.getByRole('button', { name: '返回上一级', exact: false }).click()
    await page.locator('.undo-button').click()
    await page.locator('.canvas-breadcrumb').waitFor()
    await innerReview.click()
    const restoredApproval = page.getByLabel('确认说明', { exact: false })
    await restoredApproval.waitFor({ state: 'visible' })
    assert.equal(await restoredApproval.inputValue(), '旧的黑盒内容')
    mark('nested blackbox edit returns without duplicate navigation step and undoes coherently')
    await page.getByRole('button', { name: '返回上一级', exact: false }).click()

    // Selection burst starts outside the selected card and follows the DOM rectangle.
    const selectedNode = page.locator('.react-flow__node').first()
    await selectedNode.click(); await page.waitForTimeout(120)
    assert.ok(await pixelAlpha() > 0, 'selection burst should draw particles around card')
    mark('selected-card particle burst is visible in Canvas')
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.mouse.move(frame.x + 320, frame.y + 210)
    await page.waitForTimeout(120)
    assert.equal(await pixelAlpha(), 0)
    mark('prefers-reduced-motion pauses Canvas animation')

    for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport)
      await page.waitForTimeout(250)
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
      await page.screenshot({ path: path.join(OUT, `${viewport.width}x${viewport.height}.png`) })
    }
    mark('1440, 1280 and narrow viewport have no horizontal overflow')
    assert.deepEqual(errors, [])
    mark('no browser runtime or console errors')
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: BASE, passed, errors }, null, 2))
  } catch (error) {
    await page.screenshot({ path: path.join(OUT, 'failure.png') }).catch(() => {})
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: BASE, passed, errors, error: String(error) }, null, 2))
    throw error
  } finally {
    await browser.close()
  }
}

main().catch((error) => { console.error(error); process.exit(1) })
