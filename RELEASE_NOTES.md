# kxy V17 发布说明

本版面向 macOS 15+ Apple Silicon（M1 及以后），提供本机研究画布、预构建前端和受限的 vendored SkillHub CLI/诊断桥接。

## 安装

1. 将 ZIP 完整解压到可写的长期目录，不要从 ZIP 预览或只读位置运行。
2. 先核对 ZIP 旁的外部 SHA-256。
3. 在解压后的包根目录运行 `python3 verify_package.py`，再运行 `./setup.sh`。
4. 安装完成后运行 `./start.sh`，然后在浏览器访问 `http://127.0.0.1:8710/`。

普通安装直接使用包内的 `frontend/dist`，不需要 Node.js/npm；只有主动重建前端时才需要 Node.js 20+。首次安装 Python 依赖需要联网。发布包不包含 `.venv`、运行数据、用户资料、缓存、登录态、API key、Keychain 内容、Agent CLI 或 native runtime；换设备后请自行安装、登录并配置所需 CLI。

## 本版变更

- 内置 SkillHub 固定更新至上游 commit `8ae72075fdafb1d9dda5f3a232fd9fd438d6e485`。
- 保留 KXY 的 full-snapshot、路径/marker、旧索引迁移、scan/sync、tombstone 和运行时/cache 门禁。
- kxy 不自动启动上游 SkillHub GUI；本次验证未启动 MCP 或调用真实模型。MCP 仅在用户配置、挂载并运行工作流时按现有权限规则使用，原生 Agent 全局配置不被改写。
- `THIRD_PARTY_FRONTEND_LICENSES.txt` 提供预构建前端运行时依赖的版本、来源和许可证文本。

## 验证边界

本文件描述发布包的安装使用，不替代独立安装验收。当前发布包未声称已在第二台实体 Mac、Finder 双击/Gatekeeper、真实模型推理或签名/公证流程中完成验证；Intel Mac、Windows、Linux 和首次离线安装不在支持范围内。
