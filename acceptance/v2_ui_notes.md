# V2 UI 浏览器验收清单

这份清单用于父任务的浏览器验收，不代表本次实现已经通过人工浏览器验收。测试应使用独立数据根目录，例如：

```bash
KXY_DATA_ROOT=/private/tmp/kxy-v2-ui-<run-id>
```

前端可用 `npm run dev -- --host 127.0.0.1 --port 5179` 启动；后端由父任务负责。除非专门验证 Keychain 写入，否则不要填写真实 API key，也不要发起真实模型调用。

## 全局设置

- [ ] 点击 `button[title="全局设置"]` 或 `button.top-button` 中的“设置”，打开 `[role="dialog"][aria-labelledby="global-settings-title"]`。
- [ ] `[aria-label="全局设置分区"]` 中存在“Agent 配置”“模型 / API”“外观”三个 tab；切换 tab 不关闭弹窗。
- [ ] Agent tab 显示七个固定 Agent：Codex、Claude Code、OpenCode、pi、Hermes、WorkBuddy、DeepSeek Harness；不可用状态和发现版本可读。
- [ ] 点击 `.agent-row` 后，使用 `POST /api/agents/{id}/discover` 刷新当前 Agent；切换 Agent 后，旧 Agent 的异步发现结果不得覆盖当前编辑器。
- [ ] “可执行文件”选择按钮调用 `POST /api/picker`，请求 `{"kind":"file"}`；“添加 Skill 文件夹”调用 `{"kind":"folder"}`。取消选择后原值不变。确认页面没有 `window.prompt` 路径输入。
- [ ] 长路径在 `.picker-row input`、`.path-chip` 中省略显示，悬停或聚焦时可通过 `title` 查看完整路径。
- [ ] 点击“扫描 Skills”请求当前 Agent 的 `/skills`，`.candidate-row` 显示名称、描述、来源和勾选框；仅勾选项才提交 `/skills/import` 的 `paths`。
- [ ] “保存 Agent”只提交 `executable` 与 `skill_roots`；界面不显示或回显凭据本体。

## 资料文件与目录入口

- [ ] 点击 `.upload-button` 的“导入资料”打开普通多文件选择；点击 `button[title*="目录内文件"]` 的“导入资料文件夹”打开带 `webkitdirectory` 的目录选择。
- [ ] 目录选择返回的 `FileList` 会复用 `uploadFiles`，把所选目录内文件逐个上传并生成资料节点；取消或空选择不改变画布，也不新增任意目录读取 API。
- [ ] 资料检查器 `.file-line strong` 对长文件名显示省略号，并用 `title` 提供完整文件名。

## 模型 / API 与凭据

- [ ] 切换到 `.settings-tab` 的“模型 / API”，模型列表显示 alias、实际模型标识、来源、支持的 effort。
- [ ] 新建模型时来源只能选择 API 或手动；原生模型只能由 Agent discovery 返回，编辑已有原生记录时来源选择保持只读。
- [ ] 新建/编辑模型必须填写 alias 和实际模型标识；支持的 effort 为空时，默认 effort 显示“Agent 默认 / 未设置”，不能凭空写入 `medium`。
- [ ] Keychain 表单使用 `input[type="password"]`；写入成功后输入框清空，模型记录只保留 opaque `credential_id`，页面和网络日志不得出现 key 原文。
- [ ] 删除模型前有明确确认；删除后使用该模型的节点显示“已绑定模型不可用 · 需重新绑定”，不能静默回退到别的模型。
- [ ] 编辑 `source=native` 模型时，Agent、实际模型标识、支持的 effort、来源和凭据均为只读，只允许改 alias / 默认 effort；页面提示如需 API 绑定应新建 API 记录。

## 分析器与旧数据迁移

- [ ] 选中 `.kxy-node` 中的分析器节点，检查器只有 Agent / CLI、模型记录、effort、提示词、Skill 等字段；没有节点级 API key、credential、grant 输入框。
- [ ] 更换 Agent 会清空旧 `model`、`model_ref`、`credential_id`、`variant`，并把 effort 设为该 Agent 已知的第一个 effort 或空值。
- [ ] 选择模型记录后只写 `model_ref`，同时清理 legacy `model`、`credential_id`、`variant`；effort 使用模型声明的默认值、首个支持值或空值。
- [ ] 导入含 legacy `model` 的流程时可读但不自动回退；用户需显式选择新的全局模型记录。

## 人工节点与运行审批

- [ ] 从 `.library-item` 添加“人工确认”，在检查器编辑确认说明和确认按钮文字；保存/导出后字段为 `content`、`confirm_label`。
- [ ] 运行到人工节点时 `.run-status` 显示等待人工确认，`.approval-card` 显示内容、上游 `inputs`、备注框和 `confirm_label || "确认继续"` 对应的确认按钮。
- [ ] 点击确认或拒绝分别 POST `/api/runs/{run_id}/approvals/{node_id}`，可带备注；成功后重新读取完整 run，审批状态、决定、备注和时间戳仍可见。
- [ ] 重复点击、过期审批或服务重启后的旧审批以 409/中断状态呈现，不得把 UI 显示成已通过；运行状态 `waiting`、`rejected`、`interrupted` 均可在运行面板和历史中辨识。

## 黑盒子与无损解包

- [ ] 从 `.library-item` 添加“黑盒子”；默认数据为 `version: "kxy.workflow.v1"`，内部恰好一个 `subflow_input`（`items`）和一个 `subflow_output`（`result`），默认直通，不把边界标记当文件源或容器。
- [ ] 选择普通节点后点击 `[title="封装选中节点为黑盒子"]`；封装前拒绝已有黑盒/边界标记和多条外部边界，保留内部文件/文字源，并确保所有内部节点都能到达输出边界。
- [ ] 黑盒节点支持双击或检查器“进入编辑内部画布”；`.canvas-breadcrumb` 显示层级、返回按钮和当前工作流名，返回上一级会把内部修改写回父黑盒数据。
- [ ] 内部画布可添加、编辑、连线和删除普通节点；边界输入/输出仍分别使用 `items` / `result`，不允许产生第二个边界标记。
- [ ] 选择黑盒后点击“解包”，节点位置、内部/外部边、`sourceHandle`、`targetHandle` 以及 condition true/false 路由均保持；存在无法无损恢复的多边界时 fail-closed 并保留原黑盒。
- [ ] 导出 JSON 后检查黑盒 `data.workflow` 为嵌套自有 schema；导入再进入/返回不会把 nested workflow 展平成 LFX 节点或丢失 edge handle。

## 可读性与响应式

- [ ] `.node-label`、`.node-summary`、`.library-item strong`、`.path-chip`、`.model-copy` 长名称使用省略号且有 `title`，不撑破卡片。
- [ ] 在约 1440×900、1024×768、390×844 三种窗口检查画布、左右面板、设置弹窗和运行面板；设置弹窗内容可滚动，移动端 tab 与按钮不被裁切。
- [ ] 保持既有上传文件、导入/导出流程、预设、授权输出和运行日志功能可用；所有失败请求以 toast/反馈呈现，不静默吞错。

## 验收记录

| 项目 | 结果 | 备注 |
|---|---|---|
| TypeScript / Vite build | 待父任务记录 | 本次实现会重新运行构建 |
| 浏览器交互 | 待父任务记录 | 需要真实后端 V2 route 与原生 picker 响应 |
| 真实 CLI / 模型调用 | NOT RUN | 本任务不发起真实调用 |
| 真实 Keychain 写入 | NOT RUN | 仅在用户明确提供安全测试凭据时执行 |
