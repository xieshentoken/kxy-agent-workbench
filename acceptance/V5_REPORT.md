# V5 登录态模型与分析器绑定验收

日期：2026-09-08。范围与实现契约见 [V5_PLAN.md](../docs/V5_PLAN.md)，使用方式见 [README.md](../README.md)。

由既有 GPT-5.6 Luna / max session `01a07774-30b2-7d60-b059-cbc66dc4617a` 落地；父任务规划、代码审查、编写独立检查及本机发布。未新增实现任务。

## 交付行为

- 新建来源“手动”改为“登录态（本机 CLI）”。原生目录、用户保存配置、API 与历史配置明确区分。
- 自动读取选中 Agent 的本机模型目录；模型用下拉选择，effort 只取当前模型声明的等级。没有声明时保留 CLI 默认；没有目录时提示检查 CLI 或使用 API，不创建虚构登录态模型。
- 后端新增可空的 `native_model_ref`。新登录态配置仍用 `source=manual` 保持兼容，由原生引用派生实际模型与能力，拒绝跨 Agent、模型不匹配、越界 effort 和 API 凭据混入。
- 同模型可创建多条独立 alias/默认 effort 配置；原生目录刷新不覆盖这些配置。编辑已创建登录态配置只修改 alias/默认 effort，模型绑定保持稳定。
- Inspector 的 Agent 下拉增加“已配置分析器”组合，选中时一起设置 CLI、Agent、模型记录、effort，并清除旧的模型、凭据及 variant 覆盖。保留 CLI 默认入口。
- 模型记录显示实际模型名，effort 按节点 effort、旧 variant、记录默认 effort 的顺序显示有效值；渲染不擅自重写节点。有效历史 native 绑定保留，删除记录明确提示重新绑定。

## 独立后端验收：45 个不同测试 PASS

| 检查 | 通过数 | 范围 |
|---|---:|---|
| `v5_supervisor_checks.py` | 14 | 创建与运行绑定、Codex 模型/effort 参数构建、同模型多配置、越界/跨 Agent/凭据拒绝、未知能力、目录刷新、编辑、删除、工作流持久化 |
| `v2_config_checks.py` 的 4 个相关用例 | 4 | 模型身份契约、原生模型/effort 解析、Hermes 允许字段、原生认证与显式凭据优先级 |
| `v2_runtime_checks.py` | 13 | 既有运行时与冻结模型绑定回归 |
| `v4_supervisor_checks.py` | 14 | 输出格式、JSON Schema、容器及连接测试回归 |

V2 配置检查本次选择的是 `test_model_identity_and_cli_id_payload_contract`、`test_documented_native_model_and_effort_parsers`、`test_hermes_reader_whitelists_model_fields_only`、`test_native_auth_references_are_local_and_explicit_binding_wins`，不声称整个历史配置测试套件通过。

所有后端测试均使用临时目录和合成输入；未调用真实模型。日志见 [v5-evidence](./v5-evidence/)，重复执行不增加通过数。

## 独立浏览器验收：17 组 PASS

- [主流程 13 组](./v5-evidence/browser/results.json)：自动发现、模型/effort 联动、未知能力、同模型多配置、编辑保存、快速切换 Agent 竞态、空目录、API 模式、组合原子绑定、节点局部 effort、保存刷新、删除提示、1280×720 可访问与无运行错误。
- [旧绑定兼容 3 组](./v5-evidence/compat-browser/results.json)：记录默认 effort、旧 variant、旧 native 绑定均显示实际值，并保持导出节点内容不被渲染隐式改写。
- [真实本机目录 1 组](./v5-evidence/native-browser/results.json)：在独立数据目录，用本机 Codex 的真实模型目录选择 `gpt-5.6-luna / max`，创建配置并在 Inspector 选用。没有绑定 API credential，运行记录为零。

父任务使用独立 Playwright/Edge 浏览器，并目视检查配置页、1280×720 页面及真实目录对应的 Inspector 截图。测试脚本等待页面异步资源完成后核对绑定；早期定位错误或中间构建失败截图仅作诊断，不代表最终状态。

## 本机数据与发布

- 实现前备份：`.backups/pre-v5-20260908-155726/`。
- 发布前备份：`.backups/pre-v5-publish-20260908-163252/`，包括旧 `frontend/dist` 和一致的 SQLite 备份。
- 本轮开始时正式 `8710` 服务未运行。发布前，数据库所有既有表的原列内容与修改前哈希一致。
- 发布使用验收的 `frontend/dist-v5`，先复制资源、最后替换 HTML。正式地址为 `http://127.0.0.1:8710/`。
- 正式服务启动与 HTTP 健康检查通过，发布时 PID 为 `9920`；15 张既有表的原列内容及 1199 个非数据库文件校验一致。最终资源为 `index-PYD1dEIN.js` 和 `index-CI7MBRjE.css`。
- 数据迁移只给 `agent_models` 增加可空引用列。发布后的原列内容、原资料文件及 HTTP 资源校验以 [formal-verification.json](./v5-evidence/formal-verification.json) 为准；构建和源码哈希见 [code-hashes.json](./v5-evidence/code-hashes.json)。
- 本轮没有重新制作或覆盖历史安装包，未修改全局 Agent 配置、登录态或 Keychain。

## 验证边界

“登录态”描述使用本机 CLI 配置的方式。模型目录可能来自 CLI 缓存、配置或帮助信息，不代表模型账号权限已逐一验证。实测只读发现中，Codex 返回 7 条、Claude Code 返回 5 条模型记录；来源详见 [native-discovery.json](./v5-evidence/native-discovery.json)。

本轮未进行真实模型推理、真实 API Keychain 写入、跨设备安装或并发负载验收。选择 CLI 默认且未声明 effort 时，界面不会编造具体思考等级。
