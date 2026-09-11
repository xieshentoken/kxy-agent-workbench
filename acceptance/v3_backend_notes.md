# kxy V3 后端实现记录

状态：后端实现完成；等待父任务汇总发布。

本次实现只修改 `backend/**`、`vendor/skillhub/**`、本文件和
`acceptance/v3_backend_checks.py`。接口合同以 `docs/V3_PLAN.md` 为准，V2
回归保持独立；不修改 frontend、父任务验收脚本、全局 CLI 配置或生产数据。

## 已完成

- 已读取 `AGENTS.md`、`docs/IMPLEMENTATION.md`、`docs/V2_PLAN.md`、
  `docs/V3_PLAN.md` 和 `acceptance/V2_REPORT.md`。
- 已对 `backend/` 做隔离 Graphify AST 扫描（315 nodes、1096 edges、14
  communities）；该分析不参与接口事实判定。
- 已将 `xieshentoken/skillhub` 固定提交
  `531ca63d3740fd2ac6f06eee531c1874ada01db2` 的官方包、MIT LICENSE 和
  provenance 放入 `vendor/skillhub/`。上游 Python 文件保持原样；KXY
  特有的完整快照哈希、冲突防护和兼容标准化放在 backend。
- Skill 扫描已增加来源 Agent 和最新包含文件修改时间字段。
- 外观 settings 已支持类型迁移、字体识别、范围校验和受限 PNG/JPEG/WebP
  背景资产；超大声明像素图片会 fail-closed，不进入 Pillow 解码流程。
- SkillHub 运行时使用冻结的完整内容哈希；跨 Agent 通过固定上游实际导入后
  生成 projection，WorkBuddy 使用有 ledger 记录的 copy 模式，源目录不被改写。
- MCP 仅从已知 native 位置只读发现，显式导入后保存统一无明文 secret 定义；
  目标配置只含选中 server。Codex HTTP 使用 `http_headers`/
  `env_http_headers`，stdio 使用 `env_vars`；Claude/OpenCode 使用各自的
  `${VAR}` / `{env:VAR}` 模板。Codex 选中的服务器只在 task-local overrides
  设置 `default_tools_approval_mode = "approve"`。
- 运行时从 run snapshot 重放 Skill/MCP；native endpoint/定义变化会阻止运行，
  复合认证值只在子进程环境内组装。Codex 使用 node-local `CODEX_HOME`，只短暂
 复制 0600 `auth.json`，不复制全局 config/skills/cache；worker/init 恢复路径
 仅清理 `run_root/workspace/nodes/*/.cli-state`，不会遍历 inputs/skills/exports。
- CLI 日志、结构化结果和产物统一使用本次运行的完整 redaction 值；发现凭据
  的产物会先删除再失败，`last-message` 也不会保留。

## 隔离验收结果

- `KXY_DATA_ROOT` 隔离运行 `acceptance/v3_backend_checks.py`：9/9 PASS。
- 父任务未修改的 `acceptance/v3_supervisor_checks.py`：11/11 PASS。
- V2 回归：`v2_config_checks.py` 10/10、`v2_runtime_checks.py` 13/13、
  `v2_supervisor_checks.py` 9/9 PASS；既有 runtime/supervisor 也分别为
  12/12、7/7 PASS。
- `keychain_checks.py` 在当前登录钥匙串状态返回既有 OSStatus 100001，按
  BLOCKED 记录；没有把该环境门禁误报为实现 PASS。

## 验收边界

- 所有 SkillHub 写入目标必须位于 `KXY_DATA_ROOT/skillhub` 或当前运行
  workspace；不使用 upstream `--force`，不覆盖来源 Skill。
- MCP 配置只保留环境变量引用，不保存或返回 secret；生成/parse 成功不
  等于服务器已连接。
- 测试只使用隔离 `KXY_DATA_ROOT` 和合成材料，不调用真实模型；完成后记录
  PASS、NOT RUN、BLOCKED 与限制。
- 本文件和自有 V3 脚本的 PASS 只证明后端合同与合成链路；真实模型额度、真实
  账号状态、生产服务重启和现场 MCP 业务语义不由这些 plumbing tests 证明。
