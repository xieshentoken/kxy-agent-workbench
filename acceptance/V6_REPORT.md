# V6：共享 AI 服务、提示词与输出验收

日期：2026-09-08。落地方案见 [V6_PLAN.md](../docs/V6_PLAN.md)，使用方式见 [README.md](../README.md)。本次范围的独立检查及本机发布已完成，真实提供商推理与 Keychain 写入未运行。

使用既有 GPT-5.6 Luna / max 任务 `01a07774-30b2-7d60-b059-cbc66dc4617a` 实现。父任务负责方案、源码审查、独立验收、问题复现和发布；未新增实现任务。

## 实际行为

- 全局设置新增独立“AI 服务”：服务预设、名称、Provider、协议、Endpoint、遮蔽密钥、目录连接测试、模型搜索/勾选和手工添加。保存后在“模型 / API”绑定到多个兼容 Agent，不必重复录入 key。
- 密钥仍存 macOS Keychain；原 `credentials` 六列不变，新增 `credential_metadata` 存服务名、协议及模型目录。空白 key 编辑保留引用，换 key 保持服务 ID；改变 Endpoint/协议等连接信息必须重填 key。元数据不接受密钥，工作流导出不携带密钥或本机目录授权。
- 协议分别为 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages、Google Generative AI。Codex 使用 Responses，Claude 使用 Messages，pi 支持四种已实现映射；OpenCode 支持前三种的任务级 provider 配置。其他 Agent 的未实现 API 映射明确拒绝，不回退到同名原生模型。
- 已确认此前 Kxy 会在节点提示词后隐藏追加上下文、输出格式等指令。[改动前实测](v6-evidence/prompt-before.json)捕获了真实子进程接收到的完整合成提示词。本版去除追加；可见默认提示词和“插入工作区提示”按钮仍让用户显式描述如何读取输入及生成文件。
- 默认“自动”保留正文原文，可为真正的 JSON 对象提供结构化条件路由。显式 JSON/Schema 只做本地校验，不再插入要求模型返回 JSON 的提示词。自动模式不额外生成 `answer.*`；只有文件、没有正文的有效运行也可成功。启动日志不会冒充正文。
- 输出容器直接显示正文。正文副本导出（txt/md/json）与接收真实生成文件的扩展名分别设置；空选项合法。只把 `outputs/` 中实际产生且被允许的文件复制到独立授权目录，未选文件留在运行记录并显示排除清单。没有将文本改名伪装为 PDF/DOCX 的转换逻辑。
- 初始化请求的旧结果不能覆盖期间刚保存的服务或刚创建/编辑/删除的 Agent 模型。

## 独立后端验收：68 项 PASS

| 检查 | 数量 | 核心覆盖 |
|---|---:|---|
| [V6](v6-evidence/backend-28.log) | 28 | 提示词逐字一致、空提示词、附件/Skill、自动 JSON、纯文件、日志与正文区分、真实文件白名单、符号链接拒绝、服务创建编辑复用、密钥轮换、协议兼容、目录请求及真实 argv/env 配置 |
| [V5](v6-evidence/v5-regression-14.log) | 14 | 登录态模型与 effort、alias、配置冻结、编辑删除、工作流保存、API 与登录态隔离 |
| [V2 runtime](v6-evidence/v2-runtime-13.log) | 13 | 黑盒、人工确认、条件、取消、嵌套输出授权与输入快照 |
| [V4 相关回归](v6-evidence/v4-selected-13.log) | 13 | 历史输出兼容、Schema、连接测试、跨源拒绝、重定向、密钥脱敏、条件数据类型 |

V4 的 `test_03_json_schema_and_content_export` 末项要求隐藏注入 Schema，已与本次用户要求相反，因此明确不运行该旧用例；V6 的 JSON/Schema 原样提示词和本地验证检查覆盖新契约。不把排除用例或重复运行累计为通过数量。

所有测试使用隔离临时数据、合成 CLI/HTTP 目录及内存 Keychain 替身，不调用真实模型或写入真实密钥。V6 CLI 映射检查执行实际命令构建/环境准备代码后由合成可执行文件捕获参数，不代表真实服务推理成功。

## 浏览器：14 组 PASS；本机 pi 目录加载 PASS

- [浏览器主流程 13 组](v6-evidence/browser/results.json)：服务测试/搜索/勾选/添加/保存/空 key 编辑，两个 Agent 复用服务，不兼容选项禁用，提示词与输出设置独立，导出不携带密钥或授权，执行后文本与授权文件一致，两个根层容器分别显示自身正文，与根层同名且完整路径超过 96 字符的黑盒内容器仍定位正确，无浏览器运行错误。
- [竞态复现与修复 1 组](v6-evidence/browser-race/results.json)：故意延迟初始资源请求，在期间新建服务和模型，旧请求完成后两者仍在界面中。该检查曾分别复现服务及模型消失，再验证修复。
- 在隔离 Edge/Playwright 页面检查 1440×900、1280×720 的服务页面与输出容器。截图见 [服务编辑器](v6-evidence/browser/service-1440.png)、[较小窗口](v6-evidence/browser/service-1280.png)、[正文与输出](v6-evidence/browser/container-reply.png)。合成 PDF 仅用于逐字节验证复制和扩展名筛选，不宣称 PDF 内容质量。
- [真实已安装 pi 的目录加载](v6-evidence/pi-local-catalog-native-path.json)：隔离 HOME 和 PI_CODING_AGENT_DIR、合成模型/key、离线目录命令成功列出四种协议配置。首次收窄 PATH 选到依赖缺失的另一 Node 失败；使用本机原 PATH 后通过。没有模型推理请求。
- 实现依据包括 [pi 官方模型配置](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)、[OpenCode providers](https://opencode.ai/docs/providers/)、[Anthropic API](https://platform.claude.com/docs/en/api/overview) 和 [Google 模型目录](https://ai.google.dev/api/models)。这些资料支持接口映射，不替代真实账号调用验收。

## 数据、构建与本机发布

实现前备份 `.backups/pre-v6-20260908-172143/`。正式数据基线包含 73 条模型配置、1 条 credential、3 条运行；发布前重新比对，15 张既有表原列内容及 1665 个非数据库文件均未变化。

- 父任务独立运行 TypeScript/Vite 构建，1743 个模块通过；`frontend/dist-v6-verified` 与 Luna 的 `frontend/dist-v6` 所有文件逐字节一致。最终 JS `index-C8I0_86b.js`，CSS `index-buIbN1wx.css`。[构建记录](v6-evidence/build-final.log)、[源码及验收脚本哈希](v6-evidence/code-hashes.json)。
- 发布前确认没有活动运行，备份旧前端和一致 SQLite 至 `.backups/pre-v6-publish-20260908-183925/`，停止旧服务，先替换资源、最后替换 HTML，并保留旧资源文件。[发布记录](v6-evidence/publish.json)。
- 正式服务 `http://127.0.0.1:8710/` 已启动，发布时 PID `20534`；健康检查通过，HTTP 实际返回的 HTML/JS/CSS 与已验收构建一致。
- 发布后 15 张原表的原列内容、1665 个原非数据库文件仍全部匹配；新增空的 `credential_metadata` 表，不产生正式测试服务、模型或运行。[正式数据与资源校验](v6-evidence/formal-verification.json)。
- 隔离测试服务 8722 及其目录服务已关闭；8720/8721 也无监听，正式 8710 保持运行。[清理记录](v6-evidence/cleanup.json)。

验收中复现并修复了密钥轮换时的公共元数据泄漏风险、文件型运行中日志误当正文、服务/模型初始加载竞态，以及多容器正文定位错误。`failure.*` 和 `*-before.*` 保留中间诊断，最终结果以 `results.json` 和本报告所链接的 final 日志为准。

## 验证边界

去除的是 Kxy 隐藏追加的指令；Agent CLI 自己的系统指令以及用户主动挂载的 Skill 仍然生效。目录连接测试不是推理测试，协议配置可加载也不是账号权限或模型效果保证。选择扩展名是接收许可，不是格式转换或内容真实性判断。

本次未执行真实提供商推理、真实 Keychain 写入、跨设备安装或并发负载验收；未重打包或覆盖历史安装 ZIP，未修改 WhatFa 或用户全局 Agent 配置。
