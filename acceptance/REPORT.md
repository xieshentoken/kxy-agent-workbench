# kxy MVP 验收记录

日期：2026-09-05。本轮实现与验收均已完成。主任务负责架构、关键执行路径修复和独立验收；指定的 GPT-5.6 Luna / max 新任务完成主体后端、前端和交互修复。代码与数据独立放在 `kxy/`，没有接入 WhatFa 数据模型。

## 已交付

- React / TypeScript / XYFlow / Zustand 画布；FastAPI / SQLite 后端；实际调用固定版本 `lfx==1.12.0` 的 Graph 和原生条件分支机制。
- 拖入文件建节点、文字输入、分析器、Skill 装饰器、自定义分析器预设、条件分流、输出容器。
- Codex / OpenCode CLI 执行、模型和 effort 设置、原生登录或 Keychain API key 配置。
- 工作流保存、重新载入、JSON 导入导出、三种可编辑模板；导出移除凭据与文件夹授权。
- 来源哈希、输入与 Skill 运行快照、每个节点独立工作目录、执行日志、取消、超时、重启中断、产物下载和授权目录保存。
- 暖白、低饱和度、圆角矩形节点；配色、强调色、画布色、字体预设及本地自定义字体可以保存。

## 实测结果

| 检查 | 结果 | 证据 |
|---|---|---|
| TypeScript / Vite 生产构建 | PASS | [构建日志](evidence/frontend-build.log) |
| 独立后端集成检查 | 7 / 7 PASS | [日志](evidence/supervisor-checks.log) |
| 运行时与故障注入检查 | 12 / 12 PASS | [日志](evidence/runtime-checks.log) |
| 主浏览器操作 | 10 / 10 PASS | [结果](browser-results/results.json) |
| Skill、预设、连线与授权操作 | 8 / 8 PASS | [结果](browser-results/component-results.json) |
| Codex 真实完整链路 | PASS | [完整运行记录](evidence/codex-run.json) |
| OpenCode 真实完整链路 | PASS | [完整运行记录](evidence/opencode-run.json) |
| 10 个合成原始文件哈希复核 | PASS，全部未修改 | [原生检查](evidence/native-checks.json) |
| macOS 沙盒：目录外写入、关闭网络 | PASS，实际被系统阻止 | [原生检查](evidence/native-checks.json) |
| macOS Keychain 创建、读取和清理 | PASS，只使用合成条目，测试条目已删除 | [原生检查](evidence/native-checks.json) |

真实 CLI 使用 **kxy 自己的 Python 3.12 环境**，不依赖外部 Langflow checkout：

- Codex CLI `0.144.3`，模型 `gpt-5.4-mini`，effort `low`，使用现有 CLI 登录。
- OpenCode `1.18.18`，模型 `opencode/big-pickle`，在 macOS 文件写入沙盒内执行。
- 两次运行均为：合成收入资料 → 挂载测试 Skill 的分析器 → 授权容器。回答均包含 Skill 指定标记 `KXY_SKILL_LOADED`，正确保留 20 / 12 的收入数据并说明利润率未知；生成文件、版本化保存和下载均通过。
- 这些检查证明执行与数据传递闭环；不将一次模型回答当作普遍的研究质量保证。

后端检查覆盖真假分支、正文保留、空白 PDF、Excel 的 0 / False 与行号、Skill YAML 元数据、错误句柄/版本、跨站请求、目录穿越/压缩包总量、effort 参数、API key 不入 SQLite、授权撤销/符号链接替换、Skill 删除后运行快照仍可执行、非零退出/日志冒充结果、超时/取消、重复容器保存、超大回答显式失败和重启中断状态。

浏览器检查实际操作了：文件 DataTransfer 拖入、移动节点、保存与重载、真假分支运行、下载、外观持久化、Skill 导入与勾选、预设保存复用、手动连接端口、授权输出和撤销、导出脱敏、面板收起恢复。1440×900、1280×720、390×844 检查通过；无浏览器运行错误和控制台错误。

## 截图

- [交付初始工作台](browser-results/final-workbench.png)

- [1440×900](browser-results/1440x900.png)
- [1280×720](browser-results/1280x720.png)
- [窄窗口](browser-results/390x844.png)
- [Skill 分析器](browser-results/skill-analyzer.png)

## 明确边界

- 本版解析 TXT/MD、原生文本 PDF、CSV/XLSX；JPEG/PNG 保留并交给具备相应能力的 CLI/模型。图片识别质量没有逐模型做专项验收。
- 扫描 PDF OCR、DOC/XLS/PPT 旧格式、PPTX、音视频转写没有内置处理链路；可保留为未解析附件。单个上传文件上限 50 MB。
- Claude Code / pi 当前只检测，不能作为执行器；不支持多用户、云部署、定时任务和循环工作流。
- Skill 保留脚本、引用和资源，但其依赖与宿主特定工具不保证跨 CLI 兼容。导入不执行代码，运行时按用户选择加载。
- Keychain 安全存储已用真实系统 API 验证；没有用用户真实的第三方 API key 验证每一家模型供应商。自定义端点需与所选 CLI / 提供商协议兼容；Codex 需要 OpenAI Responses 兼容接口。
- Codex 云模型需要联网。OpenCode 关闭网络会阻断全部网络，包括 HTTP 本地模型端点。macOS Keychain 或原生登录访问被系统拒绝时会显示执行失败，不生成伪成功结果。
- 运行图的分支和合并有效，本版不承诺分析器并发执行。推荐在桌面窗口编辑较复杂流程。

## 交付状态

正式入口：`./start.sh`，默认 `http://127.0.0.1:8710/`。

浏览器验收使用的合成资料、流程、Skill 与运行数据已完整归档到 `.backups/browser-qa-data-20260905/`；正式工作台以空数据目录启动。验收脚本和结果保留在 `acceptance/`。原始阶段截图中的失败记录保留用于追踪，以上 PASS 表仅引用最后通过的结果。
