# kxy 分发包验收 · 2026-09-07

分发产物位于工作区根目录：`kxy-v3-macos-arm64-20260907.zip`（416,220 字节），附同名 `.zip.sha256`。

SHA-256：`283291433397fc3a9b39b6c525aa28935699dab50c9f304c1cde0ba1a1ba7234`。

适用 macOS 15+ Apple Silicon、Python 3.12；首次安装联网。最低系统来自固定依赖的 wheel 平台限制（orjson 要求 macOS 15）。未在其他实体设备或 macOS 15 上实测，不支持此包在 Intel/Windows/Linux 上安装。包是带预构建前端的源码安装 ZIP，并非离线包或签名 DMG/PKG。

## PASS

- PyPI 解析及全新虚拟环境安装 120 个固定依赖；未复用开发项目 .venv。
- ZIP 白名单共 85 文件（84 个受清单校验文件 + 清单本身）。无重复/越界/symlink 归档项；无 data、node_modules、.venv、.git、备份、缓存及开发机用户名路径。
- 附 31 个前端运行依赖的许可文本、SkillHub 上游许可与来源记录。
- 解压 ZIP 后安装、依赖加载、健康接口、前端 HTML/JS/CSS HTTP 访问通过。
- 从包含空格的目录，以精简 PATH 运行最终 ZIP 的 Install.command 和 Start.command，通过安装、启动及健康检查。
- 普通安装跳过 Node/npm；最终包前端无需现场构建。
- 新服务 files/skills/workflows/runs 均为空，未携带开发设备数据。
- 从解压目录执行 supervisor_checks 7/7、v3_supervisor_checks 11/11，通过（合成数据，无真实模型调用）。最终 ZIP 的运行时/前端与测试对象相同，后续只更新启动包装器和 README，并再次全新安装、启动验收。
- 完整性校验通过；内容篡改与清单路径穿越负例被拒绝；安装新增 .venv/data 后仍可校验。
- 原服务 8710 保持可访问；独立验收服务 8726/8727 已停止。

## 未覆盖

其他实体设备、Finder 双击交互、下载后的系统隔离提示、签名/公证、离线安装。其他设备的 CLI 登录、模型权限、Keychain 和原生文件夹授权需重新配置，本次未代其执行真实模型调用。
