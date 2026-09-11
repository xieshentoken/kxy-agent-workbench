# kxy V3 验收记录

日期：2026-09-07。实施目录：`kxy/`。父任务负责方案、独立验收与服务更新；代码由两个 GPT‑5.6 Luna / max session 分别完成后端和前端。方案见 [V3_PLAN.md](../docs/V3_PLAN.md)。

结论：V3 已更新到本机服务 [kxy](http://127.0.0.1:8710/)。下列功能通过验收；未验证和不支持的范围单列，不计入通过结论。

## 交付范围

- 实际调用固定提交的 SkillHub 中央库与映射逻辑，跨 Agent Skill 挂载保留附属文件及完整内容哈希。运行使用冻结快照，不改写原 Skill。
- 原生 MCP 只读发现、显式导入、分析器按需勾选，生成目标 CLI 的独立运行配置。扫描和导入不启动服务器。
- 本机字体识别；独立文本/代码字体与字号；PNG/JPEG/WebP 背景上传和清除；保存默认样式。
- Skill 名称搜索、名称/修改日期排序及过滤保留勾选。
- 网格拖尾、选中卡片外发散粒子、动态效果开关与系统减弱动态效果支持。
- 图编辑撤回：默认 5 步，可配置 1–50 步，支持拖动、连接、删除、导入和黑盒内编辑。撤回历史仅保留在当前页面会话，不能取消外部调用或文件写入。

## 独立验收

| 检查 | 结果与证据 |
|---|---|
| 上游包真实性 | PASS；9 个文件（含 LICENSE）逐一验证 Git blob 哈希，全部匹配固定提交。见 [vendor-verification.json](v3-evidence/vendor-verification.json) |
| V3 API 与中央映射 | PASS，11/11；包括附属文件冲突隔离、WorkBuddy copy 幂等、秘密排除、字体、默认样式、图片与范围校验。见 [v3_supervisor_checks.py](v3_supervisor_checks.py) |
| 独立浏览器 | PASS，7 组；连续撤回、历史截断、拖动、删除带边恢复、黑盒编辑、字体及字号保存刷新、实际 Canvas 绘制和 reduced-motion。追加验证标题字体与新建卡片粒子。见 [results.json](v3-evidence/independent-browser/results.json) |
| 生成的 MCP 配置 | Codex 原生解析所选服务器；OpenCode 原生客户端连接合成 MCP，均 PASS。此项未调用模型。见 [generated-mcp-final.log](v3-evidence/generated-mcp-final.log) |
| 前端完整与合同检查 | PASS，11 组浏览器检查及 5 组定向 UI 检查；实际点击外来 Skill 挂载、MCP 导入/勾选，导出保留对应 ID，未启动模型或 MCP。见 [完整结果](v3-evidence/frontend/full-results.json) 与 [UI 合同结果](v3-evidence/frontend/v3-ui-contract-results.json) |
| 真实 Codex 完整链路 | PASS；合成资料 → Claude 来源 Skill 及 references → 需要环境变量鉴权的 MCP → 真实 completed 工具事件 → 结果文件与授权导出/下载。检查原 Skill、原生 config/auth 不变，DB 和整个 run 文件树无测试凭据。见 [摘要](v3-evidence/real-cli-final/summary.json) 与 [日志](v3-evidence/real-cli-final.log) |
| 后端专项检查 | PASS，9/9；包含冻结定义、原生字段转换、认证隔离、结构化输出脱敏、凭据产物删除、启动前失败清理。见 [后端记录](v3_backend_notes.md) |
| 既有功能回归 | PASS，51/51；supervisor 7、runtime 12、V2 config 10、V2 runtime 13、V2 supervisor 9。本次父任务重新执行，日志为 `v3-evidence/regression-*.log` |

本机字体发现返回 872 个去重字体家族名称，其中 219 个含非 ASCII 字符；这不是对所有字体字形、字重或浏览器可渲染性的逐一测试。界面使用已安装字体，不上传字体文件。

## 运行验收中发现并处理的问题

- SkillHub 上游只对 SKILL.md 生成短哈希；同正文但不同 references 的包必须用完整快照 SHA-256 区分。
- 固定上游的 MCP 配置格式与当前 CLI 不完全兼容。kxy 在上游包之外做目标格式校正，不能仅凭 JSON/TOML 可解析就认定服务器鉴权成功。
- 首次真实 Codex 测试读到了跨 Agent Skill 引用，但 MCP 因 headless 交互审批返回 `user cancelled MCP tool call`；该次未计为 MCP 执行通过。模型最终完成与工具调用成功分别核验。
- 首次真实 Codex 启动时，原生 config.toml 的哈希及时间戳发生变化。未还原该文件，避免覆盖并发修改；进一步隔离 Codex 的运行状态以避免此类启动写入。Claude、OpenCode、WorkBuddy、Hermes 的所查配置哈希保持不变。
- 修复后的真实运行验证原生 Codex config/auth 哈希不变。CODEX_HOME 独立到节点 `.cli-state`，仅以 0600 权限临时读取必要认证副本，运行后清除；不带入原生 config、Skill 和模型缓存。
- Codex 的 `auto` 仍按工具声明决定是否交互审批，最终对用户明确勾选的服务器使用 `approve`；全局审批策略与原生执行沙盒保持原有配置。语义已核对 [官方实现](https://github.com/openai/codex/blob/main/codex-rs/core/src/mcp_tool_call.rs)。

## 使用边界

- SkillHub 是目录/配置映射工具，不会自动翻译 Agent 专用命令或工具语义。挂载成功不代表任意 Skill 在任何模型上都能正确执行。
- MCP 连接需要对应服务器、网络及授权可用。pi、Hermes、DeepSeek 的 MCP 目标格式本版未验证，界面明确标为不支持；仍可使用原有 Skill 功能。
- 本版只处理已支持的 stdio / HTTP 配置；不迁移 OAuth 登录会话或任意插件的私有配置格式。
- Codex 完整 Skill/MCP 模型链路已实测；OpenCode 的 MCP 原生连接已实测。Claude/WorkBuddy 的目标配置有程序检查，其真实模型调用 MCP 未在本次执行。
- 普通模型调用完成不代表每个工具调用都成功；执行事件保留具体工具返回状态。
- 原生 macOS 文件选择器完整人工操作，以及未实测 CLI 的真实模型推理，不属于本次通过结论。
- Keychain 原生回写检查本轮被当前钥匙串环境阻塞（OSStatus 100001），不计入通过项目；已有凭据引用保留，V3 没有修改 Keychain 写入逻辑。CLI 原生登录的真实 Codex 调用已另行验证通过。

## 数据与更新

更新前数据库备份及计数见 [rollout-before.json](v3-evidence/rollout-before.json)。更新前有资料 1、Skill 2、工作流 0、运行 3、凭据引用 1、模型记录 70，无正在执行或等待确认的运行。外观原有 mist 配色、自定义字体与颜色应在迁移后保留。

所有验收使用独立临时数据目录和合成资料；未把验收流程、测试图片或测试 MCP 写入正式数据。

正式更新后健康检查、SkillHub 固定版本/中央库可用性、字体发现及前端资源检查通过。资料 1、Skill 2、工作流 0、运行 3、凭据引用 1、模型记录 70 完整保留；既有 mist 配色、颜色和 SF Pro Display 设置保留。新开隔离浏览器只读检查确认界面无运行错误，未提交任何修改。详见 [更新后核对](v3-evidence/rollout-after.json)、[正式界面检查](v3-evidence/production-browser.json) 和 [源码/构建哈希](v3-evidence/code-hashes.json)。

正式服务为 8710；本次测试使用的 8711、8712、8713、5179 临时服务已关闭。旧页面未被刷新，旧版静态资源保留以便已打开页面继续使用。若需在旧页面载入新界面，请先保存当前流程，再刷新。

清理逻辑最终限定在 `run_root/workspace/nodes/*/.cli-state`，避免触及冻结输入、Skill 附属文件或导出中的同名目录；收紧范围后专项 9/9 仍通过。
