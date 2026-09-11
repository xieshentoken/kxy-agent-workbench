# SkillHub 上游升级：531ca63 → 48b6919c

升级日期：2026-09-07
上游仓库：https://github.com/xieshentoken/skillhub
许可证：MIT（未变更）

## 1. 版本差异

| 项 | 升级前 | 升级后 |
|---|---|---|
| commit | `531ca63d3740fd2ac6f06eee531c1874ada01db2`（2026-09-04） | `48b6919c9d0b39aa488f682d7ddcf2838cbaedee`（2026-09-07） |
| 落后 commit 数 | — | 3 |
| pyproject version | 0.1.x | **0.3.0** |

落后的 3 个 commit：

| commit | 时间 | 内容 |
|---|---|---|
| `7f6c6eeb` | 09-07 03:16 | `link` 支持批量投影 `--all` / `--all-missing`，整批单次备份 |
| `d3495629` | 09-07 08:36 | 接入 grok agent；修复 symlink 模式 agent 扫描恒为 0 |
| `48b6919c` | 09-07 08:55 | 新增本地 Web GUI（`skillhub gui`，只读） |

## 2. 文件级变更

| 文件 | 状态 | 说明 |
|---|---|---|
| `skillhub/adapters.py` | 变更 | 新增 `apply_link_batch`（批量投影，整批一次备份） |
| `skillhub/cli.py` | 变更 | 新增 `gui` 子命令；`link` 增加 `--all`/`--all-missing` |
| `skillhub/config.py` | 变更 | `AGENTS` 增加 `grok`（`~/.grok/skills`，symlink 模式） |
| `skillhub/mcp.py` | 变更 | grok 走 `~/.grok/config.toml` 的 `[[mcp_servers.<id>]]`（与 codex 同构）；修复 `_render_toml` 多 header/env 时重复输出子表头导致非法 TOML |
| `skillhub/scan.py` | 变更 | **重要修复**：`Path.rglob` 不进入 symlink 目录，导致 symlink 模式 agent（pi/claude/grok）扫描恒返回 0 条；改为手动下钻 + realpath 集合做环路保护 |
| `skillhub/gui.html` | 新增 | Web GUI 前端（315 行） |
| `skillhub/webgui.py` | 新增 | Web GUI 后端（230 行） |
| `LICENSE` / `__init__.py` / `__main__.py` / `store.py` | 未变 | — |

## 3. 安全审计

- `webgui.py` 只绑定 `127.0.0.1`、只实现 GET、无任何写操作（投影/导入仍走 CLI），默认端口 8317，仅用标准库 `http.server`。
- 无新增第三方依赖、无网络外发、无凭据读写。
- 结论：**P2（可接受）**。

## 4. 兼容性分析（KXY 侧）

| 检查点 | 结果 |
|---|---|
| `link <skill_id> --agents a,b` | ✅ 保留（`skill` 改为 `nargs="?"`，`--agents` 仍 `required=True`），批量是**新增**能力 |
| `mcp._render_toml(definition, resolve=None)` | ✅ 签名未变（仅修 bug） |
| `mcp._render_json_block(definition, syntax, type_name, resolve=None)` | ✅ 签名未变 |
| `mcp._import_from_source(source, path, servers, ...)` | ✅ 签名未变 |
| KXY bridge script（agent_config.py 3389 / 3705-3711） | ✅ 调用方式不受影响 |

## 5. 已修改的 KXY 文件

| 文件 | 改动 |
|---|---|
| `vendor/skillhub/skillhub/*.py` | 5 个变更 + 2 个新增 |
| `vendor/skillhub/UPSTREAM_PROVENANCE.json` | commit + 11 个文件 git blob sha1 |
| `backend/agent_config.py` | `SKILLHUB_UPSTREAM_COMMIT` → `48b6919c...`；`_SKILLHUB_UPSTREAM_BLOBS` 更新 5 项 + 新增 2 项（gui.html / webgui.py） |
| `acceptance/v3-evidence/vendor-verification.json` | commit + 11 个文件 sha256 |
| `THIRD_PARTY_NOTICES.md` | vendored commit 声明 |

⚠️ `_SKILLHUB_UPSTREAM_BLOBS` 是**硬校验**（`_skillhub_vendor_check()` 失败即 `raise AgentConfigError`），
必须与 vendor 文件同步，否则所有 skillhub 调用直接报错。

**未改**（历史记录，改动会失真）：`docs/V3_PLAN.md`、`acceptance/v3_backend_notes.md`、
`acceptance/v3-evidence/rollout-after.json`、`acceptance/v3-evidence/real-cli-final/evidence.json`。

## 6. 验证结果

```
_skillhub_vendor_check()  → True
skillhub_status()         → upstream.available=true, commit=48b6919c9d0b..., index_valid=true
skillhub --help           → 子命令含 gui
skillhub config AGENTS    → ['pi','codex','opencode','workbuddy','claude','grok','hermes']
skillhub link --help      → 含 --all / --all-missing，且 [skill] 位置参数保留
```

上游自带 `tests/test_projection.py` 未跑通：该测试要求真实 `~/.agents/skills` 目录存在
（本机未创建，且被 WorkBuddy 沙箱拦截 lstat），非代码问题。

## 7. 待办

1. **KXY 后端未接入 grok**：`SKILLHUB_SUPPORTED_AGENTS = {pi, codex, opencode, workbuddy, claude, hermes}`
   不含 `grok`，所以上游新增的 grok 能力在 KXY UI 里不可见。
   接入需要：在 `AGENT_PRESETS` 加 grok 条目（`~/.grok/skills`、headless 命令等）+ 补齐
   `SKILLHUB_MCP_GENERATORS` 与验收用例。
2. **Web GUI 未接入 KXY**：`skillhub gui` 会监听本地端口，KXY 若要集成需考虑端口冲突与生命周期管理。
3. 上游 pyproject 已到 0.3.0，KXY vendor 不含 pyproject，版本声明未同步（不影响功能）。

## 8. 回滚

```bash
# 升级前完整备份
/Users/<localuser>/Documents/Codex/DeeSear workflow/kxy/.backups/skillhub-vendor-531ca63-20260907-231728/
# 回滚时把该目录内容拷回 vendor/skillhub/，并把 backend/agent_config.py 的两个常量改回 531ca63 对应值
```
