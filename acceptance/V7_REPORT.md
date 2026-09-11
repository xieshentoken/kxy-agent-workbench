# V7 验收：Keychain、批量选择、分析器预设和动效强度

日期：2026-09-08。方案见 [V7_PLAN.md](../docs/V7_PLAN.md)，操作说明已写入 [README.md](../README.md)。产品代码由既有 GPT-5.6 Luna / max 任务实现，父任务负责诊断、独立验收、问题复核与本机发布。

## Keychain 100001 的原因与修复

`/usr/bin/security error 100001` 在本机解释为 `UNIX[Operation not permitted]`。同一个 Security.framework 写入调用，在受限执行环境返回 100001；以正常本机权限执行时，唯一随机测试条目的新增、读取匹配和删除都成功。[受限结果](v7-evidence/keychain-sandbox-before.json)、[正常权限结果](v7-evidence/keychain-native-before.json)。

因此，修复的关键是把正式 kxy 后端从继承的受限环境重新启动为正常本机进程，并保留分析器原有的文件和网络沙盒。没有采用明文存储、修改 Keychain ACL、自动提权或隐藏失败。代码对 100001 给出“服务启动环境受限”的准确说明，不再要求用户反复解锁。Keychain 列表/状态接口在受限时返回可解释的 503，目录测试给出 `environment_restricted`。

[受限 API 实测](v7-evidence/keychain-restricted-api.json)返回正确说明，失败后不产生 credential 数据行。[真实 Keychain API 实测](v7-evidence/keychain-api-native.json)通过保存、原生读取、列表状态、留空编辑保留 key、换 key 后保持服务身份、已保存 key 的本地目录认证以及数据库不含 key。每次 API 检查仅用随机合成密钥，创建两条测试记录并删除两条，没有真实模型推理。

正式服务已用正常本机权限启动，`/api/credentials` 返回 200，原有一条配置显示已配置；未读取其密钥本体。[正式 Keychain 状态](v7-evidence/formal-keychain-status.json)。

## 交付行为

- 新发现模型默认不选，已保存和用户主动选择的模型保持不变。“全选当前 / 反选当前”只作用于搜索可见模型，不改隐藏选择；无搜索结果时按钮禁用。
- 输出容器分别提供正文副本格式与真实文件扩展名的全选/反选，空选择有效，两组设置互不影响，工作流 JSON 保留结果。
- 组件库列出全部保存的分析器预设，可滚动查看、展开配置、明确应用和删除。展开不改画布；新保存预设不再因配置中的旧 id 覆盖另一个快照。初始列表尚未返回时新增预设，仍保留原有和新建记录。全局模型记录仍与分析器预设区分。
- 外观增加 0–100 强度滑块，默认 100 保留原效果；强度影响拖尾亮度、范围和寿命，以及选中扩散的范围和寿命。0 清除高亮并跳过计算；关闭动效或系统 reduced-motion 优先。高亮继续沿实际 SVG 网格分布。

## 独立验收

| 检查 | 结果 |
|---|---|
| [V7 后端](v7-evidence/backend-9.log) | 9 项 PASS：默认/零值、范围、旧设置、部分更新、多个预设、删除隔离、保存失败不落库、敏感字段拒绝、Keychain 成功结果不误报 |
| [V6 回归](v7-evidence/v6-regression-28.log) | 28 项 PASS：原样提示词、输出接收、共享服务、Keychain 轮换与协议映射等 |
| [V5 回归](v7-evidence/v5-regression-14.log) | 14 项 PASS：登录态模型、effort、别名与绑定等 |
| [浏览器](v7-evidence/browser/results.json) | 11 组 PASS：五预设延迟初始化/保存/展开/应用/刷新、1280×720 可访问、默认不选/搜索批量、真实 Keychain 保存/复测、两组输出格式、强度持久化/强弱差异/网格对齐/系统减弱效果、无运行错误 |
| [独立构建](v7-evidence/build-final.log) | TypeScript + Vite 通过，1743 模块；与 Luna 候选构建逐字节一致 |

浏览器使用正常本机权限的独立服务，仅其 Keychain 调用是真实系统调用，模型目录是本机合成 HTTP 服务，没有向真实提供商发送密钥或推理。父任务目视检查[预设列表](v7-evidence/browser/presets-1280.png)、[服务模型](v7-evidence/browser/keychain-service.png)、[强度滑块](v7-evidence/browser/motion-strength.png)。

首轮动效测试把选中扩散的峰值透明度误当作线性强度指标；产品实际按范围与持续时间调整扩散。修正验收为观察弱档脉冲消失而强档仍可见，同时测量拖尾亮度，最终通过。诊断 `failure.*` 不代表最终状态，最终以 `results.json` 和 final 日志为准。

## 发布与数据

- 实现备份：`.backups/pre-v7-20260908-193450/`。其中遗漏了后来修改的 `v3.tsx`；父任务逆向移除仅本轮新增项，复原文件与已留存的 V4 SHA-256 完全一致，保存至 `.backups/v7-recovered-v3-baseline/` 并记录还原来源，没有冒称事前备份。
- 发布前备份旧前端和一致 SQLite：`.backups/pre-v7-publish-20260908-195750/`。[发布记录](v7-evidence/publish.json)。
- 正式地址 `http://127.0.0.1:8710/`，发布时 PID `26232`，以正常本机权限启动。HTML/JS/CSS 实际 HTTP 响应与验收版本一致：`index-Ck2iQGFk.js`、`index-CJSzuTWk.css`。
- 16 张原表的原有行及 1665 个非数据库文件保持一致，仅增加 `settings.motion_intensity=100` 默认项。原有 75 条模型记录、1 条 credential、3 条运行保留，没有向正式库加入测试预设或服务。[数据校验](v7-evidence/formal-verification.json)、[源码哈希](v7-evidence/code-hashes.json)。
- 浏览器验收的两条合成 Keychain 记录已删除，并通过正常本机权限下查询确认不存在。[删除确认](v7-evidence/browser-keychain-cleanup.json)。测试夹具最初的外层 finally 在 Uvicorn 重发 SIGTERM 前未执行，因此父任务做了定向清理，并把夹具清理移入 lifespan；另建一条合成记录验证退出时自动删除成功。[退出清理验证](v7-evidence/fixture-shutdown-cleanup.json)。
- 8720–8723 及本轮两个合成目录端口均无监听，正式 8710 保持运行。[清理记录](v7-evidence/cleanup.json)。所有本轮创建的随机/合成 Keychain 测试条目均已清理。

本轮未进行真实提供商推理、跨设备安装、负载验收或重新打包历史安装 ZIP。使用者日后应从本机 Terminal 启动 `./start.sh`，或双击 `Start.command`；不要在受限 agent 子进程里启动需要访问 Keychain 的长期后端。
