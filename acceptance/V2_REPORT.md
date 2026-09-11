# kxy V2 实现与验收记录

日期：2026-09-06。工作目录：`kxy/`。父任务负责方案、审阅及独立验收，三个 GPT-5.6 Luna max 任务分别实现全局配置、运行时和前端。首版记录 `REPORT.md` 保留。

结论：本次功能增量已落地并更新本机服务；51 项后端检查、9 组页面检查通过，Codex / Claude Code / OpenCode 合成资料的真实执行链路通过。其余 CLI 与原生路径弹窗的验收边界见下文。

## 已实现

- 保留 React / XYFlow、FastAPI / SQLite、自有 `kxy.workflow.v1` 和真实 LFX 1.12.0 执行引擎。无限画布与执行器继续分离；未修改 WhatFa 或外部 Langflow。
- 全局七种 Agent CLI 配置；选择可执行文件、发现模型和 effort、扫描所选 Skill 根目录、勾选导入快照。借鉴 [SkillHub](https://github.com/xieshentoken/skillhub) 的多 Agent 技能发现方式，没有安装其同步/链接操作，也没有改写用户全局配置。
- 全局模型 / API 配置和 Keychain 凭据引用。原生、API、手动模型使用独立记录和 alias；原生 alias 在重新发现后保留。分析器只保存模型引用和选择项；每次运行固定模型、执行文件及凭据绑定。
- 文件和资料文件夹通过浏览器选择；CLI、Skill、授权输出目录通过 macOS 原生选择器。长文件名保留完整 metadata，卡片中省略显示、悬停显示全名，磁盘存储使用短名称。
- 人工确认是真实断点，支持自定义说明/按钮、备注、确认、拒绝及取消；刷新网页后可从历史恢复查看并操作。服务重启后标记中断，不自动重跑。
- 黑盒为可编辑的嵌套工作流，支持封装、进入、返回、解包和执行；单输入/输出，最多四层。内部人工节点、资料/Skill/模型/授权快照和条件分支均进入运行时；不支持无损封装时给出提示并保留原图。
- 保留暖色、低饱和度、圆角卡片，以及全局配色和字体设置。

## 验证证据

检查使用独立临时数据，不把 fixture 结果当成真实模型输出。

| 检查 | 结果 | 证据 |
|---|---|---|
| 原有后端回归 | 7 + 12 项 PASS | `v2-evidence/baseline-supervisor.log`、`baseline-runtime.log` |
| 全局配置 | 10 项 PASS | `v2-evidence/config.log` |
| V2 LFX 运行时 | 13 项 PASS | `v2-evidence/runtime.log` |
| 父任务独立后端验收 | 9 项 PASS | `v2-evidence/supervisor.log` |
| 独立页面操作 | 9 组 PASS | `v2-evidence/browser/results.json` |
| 后续 CUA 实测 | 已保存路径、native alias/刷新、目录 FileChooser、模型 effort 范围 PASS | `v2-evidence/cua-followup.md` |
| TypeScript / Vite | PASS | `v2-evidence/frontend-build.log` |
| 原生 Keychain | 新建合成条目、读取、不泄露 API/DB、清理 PASS | `v2-evidence/keychain.log` |
| 实际 macOS 沙盒 | 工作区内写入允许、外部写入与关闭网络时连接被阻止 PASS | `v2-evidence/sandbox.log` |
| 真实 Codex | 合成资料 → Skill → 分析 → 授权输出/下载 PASS | `v2-evidence/real-codex.log` |
| 真实 OpenCode | 修复附件参数并恢复原生登录只读引用后，相同完整链路 PASS | `v2-evidence/real-opencode-native.log` |
| 真实 Claude Code | 复用本机已有 API 配置，相同完整链路 PASS | `v2-evidence/real-claude-fixed.log` |

页面检查覆盖真实 LFX 人工暂停、刷新、继续、黑盒内部编辑/执行/审批/无损解包、模型/Skill 预设、长中文文件名、1440/1280/390 视口及无浏览器运行错误。自动脚本仅模拟 `/api/picker` 返回；后续资料文件夹导入使用真实浏览器 FileChooser。

运行时额外验证条件未选中分支不暂停或执行黑盒内资料源、拒绝/取消不产生下游结果、审批不可重复提交、服务重启状态不被旧 worker 改回、嵌套输入/技能/模型/授权快照以及认证环境值的日志脱敏。

## 本机发现结果

记录见 `v2-evidence/live-discovery.json`。这些是本机版本、配置及目录的发现结果，不代表登录、模型配额或账号授权。

| CLI | 版本 | 模型目录 | 来源/限制 |
|---|---|---:|---|
| Codex | 0.144.3 | 7 | 本机可见模型缓存，排除隐藏内部项 |
| Claude Code | 2.1.233 | 5 | CLI help 及本机配置的模型/alias，effort 取 help |
| OpenCode | 1.18.18 | 8 | `opencode models` |
| pi | 0.85.1 | 0 | 本机尚无配置的 provider/model；可添加手动/API 模型 |
| Hermes | 0.19.1 | 40 | 本机模型目录及已选模型配置 |
| WorkBuddy | 2.137.1 | 9 | 应用内 bundled CLI help |
| DeepSeek Harness | 未验证 | 0 | headless profile 不存在，web profile 不替代 |

## 明确边界

- 原生 CLI/Skill/输出路径弹窗已实际触发，其 `osascript` 进程已观察到；CUA 无法选择该无 bundle 的原生进程，所以 macOS 弹窗选定/取消的完整操作仍需人工验收。取消及参数边界已通过单元测试，资料文件夹浏览器弹窗已通过真实操作。
- pi、Hermes、WorkBuddy 尚未做真实模型推理验收；不能把 help 启动成功报告为账号调用成功。WorkBuddy 仅复用其 CLI 文档化 settings env，不猜测桌面登录会话存储。pi 本机目前无 provider/model 配置，其原生登录复用未验证。DeepSeek Harness 当前明确不可执行。
- 首版文档解析边界保持：支持文本/Markdown、原生文本 PDF、CSV/XLSX、JPEG/PNG；其他格式可保留为附件，未增加视频转写或完整 Office 解析承诺。
- 输出授权绑定本机目录；导出流程不携带凭据或目录授权。需要另一台机器重新绑定可用模型、资料和授权。

## 本机更新

代码更新前快照位于 `.backups/before-v2-20260906-104405/`，正式服务重启前另备份 SQLite 到 `.backups/pre-v2-launch-20260906-132933/`。验收前确认原数据为一份资料、一次成功运行，无活动运行。独立验收均使用临时数据根目录；正式服务继续使用 `data/`。更新前后资料、运行、流程、Skill、凭据 ID 及历史运行状态逐项核对，见 `v2-evidence/production-before.json` 与 `production-after.json`。

启动：在 `kxy/` 执行 `./start.sh`，访问 http://127.0.0.1:8710/ 。

正式服务已重启，`/api/health` 返回 `ok: true`、`lfx: 1.12.0`；七项全局 CLI 已完成首次发现，CUA 验证正式页面显示其版本与配置。验收用 8711 服务已关闭。最终源码/构建哈希保存在 `v2-evidence/source-hashes.json`。
