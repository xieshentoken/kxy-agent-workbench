# kxy 研究画布

kxy 是一个本机运行的研究流程画布：React/XYFlow 负责编辑自有 `kxy.workflow.v1` JSON，FastAPI 负责文件、技能、凭据引用、运行快照和产物，运行时使用已固定的 `lfx==1.12.0` `Graph` API。Agent 通过本机 CLI 子进程执行；kxy 不依赖外部 Langflow checkout，也不修改全局 CLI 配置。

V2 增加全局 Agent / 模型 / API 配置、按 Agent 扫描 Skill、原生路径选择、人工确认断点和可编辑的黑盒子工作流。配置页内置 Codex、Claude Code、OpenCode、pi、Hermes、WorkBuddy、DeepSeek Harness；模型发现会注明原生目录或帮助信息来源，发现成功不代表账号已登录或具有模型权限。

V3 实际接入 SkillHub 中央库：跨 Agent 挂载 Skill 时，自动映射所选快照及附属文件；MCP 可从原生配置按需导入，并在分析器中单独勾选。增加本机字体识别、独立文本/代码字体与字号、图片背景、默认样式保存、网格拖尾、选中卡片粒子，以及默认 5 步、最多 50 步的撤回。

V4 收紧画布交互和输出契约：工具栏的移动/框选模式互斥，框选结果可直接建立真实可进入的黑盒子；空格和中键保持平移，Shift 支持多选，嵌套黑盒沿用同一规则。分析器支持 Markdown、纯文本和单对象 JSON，旧的 `expect_json=true` 自动映射为 JSON；可选 JSON Schema 只允许本地引用、在本机校验且不会作为命令执行。输出容器可分别导出 `.md`、`.txt`、`.json`，JSON 可选完整记录或仅内容模式，历史默认仍保留 `result.json`、`result.md` 和 `provenance.json`。

V5 将本机 CLI 的登录态模型目录与可保存配置分开：打开“模型 / API”会自动发现当前 Agent，模型下拉只接受该 Agent 目录中的真实模型，effort 由每个模型声明。可以为同一个模型保存多个独立 alias 和默认 effort；刷新目录不会覆盖这些配置。分析器的 Agent 下拉同时提供 CLI 默认和“Agent · alias · model · effort”已配置组合，选择组合会原子写入 `cli`、`agent_id`、`model_ref` 和 `effort`。登录态记录不保存 API credential，删除配置后节点保持明确的“需重新绑定”状态；API 与旧版手动记录继续兼容。

V6 将分析器提示词改为逐字传给所选 CLI：输入清单、附件和 Skill 仍在隔离工作区可达，不再隐藏追加上下文或格式指令；“自动”保留真实原文，真正的 JSON 仅额外提供结构化路由，显式 JSON 只做本地对象/Schema 校验。全局“AI 服务”独立于模型记录，保存服务名、协议、模型目录和 Keychain 不透明引用；按 Agent 的已验证映射严格拒绝不兼容组合，并为 pi/OpenCode 写入任务级 provider 映射。输出容器现在分别控制正文副本与真实生成文件扩展名，界面会显示正文、上游归因以及实际接收/排除文件；空正文但有真实生成文件是合法文件型运行。

V7 收紧配置编辑的边界：服务目录测试成功后不会自动选中全部新模型，保存的/手动选中的模型保持不变；“全选当前”和“反选当前”只作用于搜索可见模型。输出容器对正文副本格式和生成文件扩展名分别提供当前范围的全选/反选，空选择仍合法。分析器预设可展开查看已保存配置，应用、展开和删除分开操作；预设快照使用新 ID，不会因节点配置中的旧 `id` 覆盖已有记录。外观增加 0–100 的点动效强度，0 会跳过高亮计算，现有动效开关和系统减弱动态效果优先，网格高亮仍对齐实际 XYFlow 网格。

V8 增加可审计的显式运行恢复和通用组件预设。点动效刻度为 0–100：30% 是标准强度（与 V7 的完整效果相同），100% 是标准强度的 3 倍，0% 关闭高亮；已有 V7 外观设置只在首次启动时按旧百分比 × 0.3 迁移，之后不会重复迁移。文件、文字、输入、分析器、容器、条件、人工确认和黑盒子都可以在检查器中保存为命名预设；内部黑盒边界标记不单独保存。组件库按类别分组，组内可切换最新日期/名称排序，展开、应用和删除彼此独立。黑盒预设保留内部节点、边和输入/输出映射，应用时递归生成新 ID 并重映射连线；缺失的本机资料、Skill、模型、凭据引用、授权或 MCP 会显示并禁用应用，凭据只保留不透明引用，不保存密钥内容。

### 可迁移工作流包

顶部“工作流包”入口提供 ZIP 导出和导入。导出会组合当前完整的顶层画布，即使正在编辑黑盒内部，也会把最新内部内容写回根工作流；普通 JSON 导出使用同一份根画布。ZIP 至少包含经过清理的 `manifest.json` 和 `workflow.json`，可选携带用户明确勾选的附件原始内容与完整 Skill 快照/依赖声明。未勾选的原始内容只保留内容哈希与绑定摘要；勾选的附件和 Skill 原始内容按原样写入，不做自动脱敏，分享前请先检查其中的密钥、个人信息和内部路径。

工作流包不会携带 KXY 管理的 API key、Keychain、CLI 登录态、MCP secret/config、模型 credential、源设备的 output 授权 ID 或源 output 目录路径；这不等于用户自己写入附件或 Skill 原始内容的敏感字段会被清理。目标设备必须在本地先配置可用模型/effort 与 MCP，再在导入预览中逐项选择目标模型、MCP 和 output（默认 output、已有授权目录，或用户明确授权的新目录）；缺失附件/Skill 必须复用匹配资源、导入包内副本或显式补齐。提交只创建并载入一个新工作流，不会自动运行，也不会静默跳过缺失绑定。目标设备的凭据留在目标设备本地，目标模型/API 是否可用仍需按目标 Agent 的实际登录和权限验证。

导入预览与导出均有固定上限：ZIP 不超过 100 MB，单个成员不超过 50 MB，展开后的成员总量不超过 100 MB，manifest 不超过 1 MB，workflow 不超过 5 MB，最多 800 个 payload 文件；单个 Skill 最多 400 个文件、20 MB。生成包使用有界的 stored ZIP，压缩率高的文本不会因为压缩比被误拒绝。上限是防止内存、磁盘和解压炸弹风险，不代表真实模型推理、MCP handshake 或目标设备部署已通过验收。当前发布/安装验收目标为 macOS 15+ Apple Silicon；Linux 不在本迁移发布支持范围内。

失败或服务重启中断的运行会在运行面板显示“从检查点恢复”。恢复使用原始运行快照中的输入、Skill 快照和模型选择：已成功节点先验证 durable checkpoint 后复用，未完成节点从头重跑，条件分支和黑盒内部恢复保持原路由；这是同一运行的新尝试，不是 token 流续传。人工节点仍须当前有效的确认；已拒绝的决定不能绕过，中断时未决定的确认会重新呈现。输出授权在恢复前重新验证，授权撤销、路径变化或 checkpoint/产物校验失败会阻止恢复；导出 receipt 用于复用已完成输出并拒绝覆盖不一致的旧目录。每次恢复都会留下尝试审计，服务重启或旧 worker 尚未退出时不会并发启动另一尝试，也不会自动无限重试。没有 V8 checkpoint 的历史运行会明确显示为不支持安全恢复。

运行面板中的正文和 JSON 是可编辑、可导入、可下载的副本，不会改写已完成运行、原始输入或运行快照。画布动效只点亮实际 XYFlow SVG 网格上的点，随 pan/zoom/resize 对齐；关闭动效或系统偏好减少动态效果时不运行帧循环。模型来源说明区分原生发现、手动模型记录和 Keychain API 绑定；API 连接测试由用户手动触发，只请求本地/指定 Endpoint 的 `/models`，不会保存密钥、跟随重定向或声称完成推理。

## 安装与启动

### 分发包安装

本发布包明确要求 macOS 15+ Apple Silicon（M1 及以后）；Intel Mac、Windows、Linux 不支持本发布包。请先将压缩包完整解压到可写的固定目录（不要直接从 ZIP 预览或只读位置运行）。发布包根目录应包含 `frontend/dist`、`branding/logo.svg`、`package-manifest.json`、`RELEASE_NOTES.md`、`verify_package.py`、`THIRD_PARTY_NOTICES.md`、`THIRD_PARTY_FRONTEND_LICENSES.txt` 和安装/启动脚本。

前置条件：Python 3.12（必须，推荐 `brew install uv`；没有 uv 时可用 `brew install python@3.12` 或 python.org 的 Python 3.12 安装包，并确保 `python3.12`/`python3` 指向 3.12）。首次安装 Python 依赖需要联网。运行时是否需要联网取决于所选 CLI、模型、MCP server 和远程 endpoint。发布包已经带 `frontend/dist`，kxy 安装不会带 Node.js、Agent CLI 或 native runtime；若所选 Agent CLI 需要 Node.js，请用户按该 CLI 的官方要求另行安装对应版本，并自行安装/登录 CLI。只有源码开发或主动重建前端时才需要 Node.js 20+ / npm。拿到压缩包后，先按发布说明核对包旁提供的外部 SHA-256，再运行下面的清单校验。

在本目录执行：

```bash
python3 verify_package.py
./setup.sh
./start.sh
```

也可以双击 `Install.command` 安装，再双击 `Start.command` 启动。`verify_package.py` 只校验 `package-manifest.json` 列出的源码文件；安装后新增的 `.venv/`、`data/` 不要求为空，也不应放入清单。

源码开发需要显式重建前端时才运行：

```bash
./setup.sh --build-frontend
```

该模式会执行 `npm ci` 和 `npm run build`；npm 失败会以失败退出，不会打印安装成功。普通 `./setup.sh` 不会调用 Node/npm。安装脚本优先使用 `backend/requirements-lock.txt`，缺失时才回退到 `backend/requirements.txt`。

如果界面显示 `100001 / Operation not permitted`，表示 macOS 拒绝了当前受限启动环境的 Keychain 访问，不表示 API key 错误，也不应通过反复解锁来解决。请在本机 Terminal 进入 kxy 根目录后执行 `./start.sh`（或 `Start.command`）；kxy 不提供明文文件回退、不自动修改 ACL，也不要求 sudo 或测试密钥绕过。

生产模式由 FastAPI 直接提供 `frontend/dist`，然后打开 <http://127.0.0.1:8710/>。服务只监听本机回环地址；在终端按 Ctrl-C 停止。端口冲突时可使用 `KXY_PORT=9000 ./start.sh`，再访问对应端口。安装脚本不会安装 Codex、Claude Code、OpenCode 等 CLI，也不会打包登录态、全局配置、MCP secret 或 Keychain；换设备后请自行安装、登录并配置它们。

文件从画布界面导入；Skill 在“Agent 配置”中扫描并导入快照；MCP 使用“发现 MCP（仅读取配置）”后按需导入，并在具体分析器中勾选。原生全局配置不会被安装脚本改写。

### 升级、迁移与卸载

升级必须先停止旧服务并备份旧目录的 `data/`，再把新发布包解压到新目录、重新执行 `python3 verify_package.py` 和 `./setup.sh`，让新目录重建 `.venv`。不要跨目录搬运 `.venv`，也不要直接覆盖正在运行的旧目录；确认新版本可用后再切换入口。需要保留研究数据时，只在停服并完成备份后迁移旧 `data/`。

迁移到新设备或新目录后，要重新登录/授权 CLI，重新选择并授权输出目录，重新建立需要的 MCP/API 配置；Keychain 不随包、不随 `data/` 备份自动迁移。卸载前先停服，并把 `data/` 复制到发布包目录之外的独立备份位置，再删除发布包目录；本项目不会自动删除研究数据。安装脚本会拒绝非 macOS 15+ Apple Silicon 环境。

检查服务：

```bash
curl http://127.0.0.1:8710/api/health
```

## 测试与验收

前端类型检查和生产构建：

```bash
cd frontend && npm run build
```

V4 开发验收可将构建隔离到 `frontend/dist-v4`，不会覆盖已打包的生产静态文件：

```bash
cd frontend && npm run build -- --outDir dist-v4
```

V5 前端构建输出到独立目录，供隔离 fixture 服务和浏览器验收使用：

```bash
cd frontend && npm run build -- --outDir dist-v5
```

V6 前端构建输出到独立目录，不覆盖 V5 或分发包静态文件：

```bash
cd frontend && npm run build -- --outDir dist-v6
```

V7 前端构建输出到独立目录，不覆盖 V5、V6 或分发包静态文件：

```bash
cd frontend && npm run build -- --outDir dist-v7
```

V8 前端构建输出到独立目录，不覆盖 V7 或分发包静态文件：

```bash
cd frontend && npm run build -- --outDir dist-v8
```

V8 后端恢复与预设检查使用临时数据目录和合成 CLI，不代表真实模型质量或真实推理：

```bash
cd ..
.venv/bin/python acceptance/v8_supervisor_checks.py
```

使用多 Agent 循环：从组件库加入“有界循环”，连接“资料/输入 → 有界循环 → 授权输出”。双击循环卡片进入内部，分别为执行器和审阅器选择已保存的 Agent / 模型 / effort，并编辑各自提示词；返回上级设置原始目标、轮数、活动时间和需要传回下一轮的字段。默认审阅器返回 `passed`、`issues`、`next_action`，也可修改字段映射。运行面板可选择轮次查看输入、结果、审阅与变化预览；达到上限后可增加 1 轮 / 5 分钟，或停止且不接受。网络或额度错误后使用“从检查点恢复”，已完成轮次及当前轮成功节点会复用。最终通过的执行器结果交给循环外的授权输出，逐轮文件仍保存在运行目录。

V9 有界多 Agent 循环使用自有黑盒 schema：`blackbox.data.workflow` 保存 `subflow_input → executor analyzer → reviewer analyzer → subflow_output`，`blackbox.data.loop` 只保存 `executor_id`、`reviewer_id`、目标/输入字段、反馈选择、JSON 字段映射和预算边界。审阅 prompt 只存在选中的内部 analyzer 上；循环配置不会再保存第二份可执行 prompt。每轮的原始输入、实际审阅输入、执行器/审阅器结果、解析后的 `passed/issues/next_action`、活动耗时、节点 checkpoint 和暂停控制持久化到 `loop_rounds`。轮数上限为 1–50，活动预算为 1–86400 秒，历史摘要为 0–20000 字符；不允许循环嵌套，也不允许循环内部直接声明输出授权容器。轮数或活动预算耗尽会暂停，只有显式继续才增加边界；停止不会自动接受未通过结果。

V9 后端集中检查（临时数据目录；第一项使用本地合成 CLI 子进程，全部不代表真实模型质量或真实推理）：

```bash
cd ..
.venv/bin/python acceptance/v9_loop_checks.py
```

V9 候选前端构建到独立目录，不覆盖 `dist-v8` 或分发包静态文件：

```bash
cd frontend && npm run build -- --outDir dist-v9
```

V10 设置增加了“检查并刷新”与“检查并刷新全部”。每个 Agent 的版本、模型目录和 effort 仍由已有 discovery 只读探测提供；登录态单独记录，当前只有已确认命令的 Codex / Claude Code 可以给出“已确认登录/未登录”，其他 Agent 保持“未知（未验证）”。不会执行登录、登出、浏览器授权或模型推理，也不会返回命令原文、账户信息或凭据。模型目录暂时失败时保留上次有效目录和已保存绑定；可选的“打开设置时自动检查”默认关闭。

“新建默认值”只影响之后新建的分析器、输出容器，以及新建有界循环内部的执行器/审阅器，不覆盖导入流程、已有节点、显式模板绑定或自定义预设。默认分析器可以保存精确的 Agent + alias + model + effort 绑定，也可以只保存某个 Agent 的 CLI 默认模型；绑定缺失时会明确显示并要求重新绑定或清除，不会静默换成其他模型。普通新建分析器还可以编辑默认提示词，并从“当前内置默认提示词”模板恢复；空字符串会原样保存。循环执行器和审阅器继续使用各自的专用协议 prompt。输出默认值可以分别配置正文副本 `result.txt` / `result.md` / `result.json`、生成文件扩展名和 JSON 的 `content` / `full` 模式。

授权输出的实际目录是：

```text
data/runs/<run_id>/workspace/exports/<flatid>/
data/runs/<run_id>/workspace/output-manifest.json
```

其中 `result.txt` / `result.md` 是选中的正文副本，`result.json` 是完整记录或仅内容，`files/` 只接收选中扩展名的真实生成文件，`provenance.json` 保存本次输入、模型、提示词和 Skill 快照，`export-receipt.json` 保存完成状态与哈希以防止错误覆盖，`output-manifest.json` 是运行级索引和下载路径。清单与 receipt 始终生成，旧节点和历史运行保持原选择；`data/outputs` 仅作为兼容目录创建，不是导出目的地，也不由设置页授予路径权限。

V10 后端聚焦检查使用临时数据目录和合成 CLI 响应，不代表真实模型质量、账号权限或真实推理：

```bash
cd ..
.venv/bin/python acceptance/v10_settings_checks.py
```

V10 prompt 候选前端构建到独立目录，不覆盖正式 `frontend/dist`、V9/V10 候选或 8710 服务：

```bash
cd frontend && npm run build -- --outDir dist-v11-prompt
```

V12 资料格式候选补齐 HTML（只提取可读正文，不执行脚本或加载外链）与 YAML（按原文保留格式，不构造对象），并保留 Markdown/纯文本的原有路径。文件上传、画布拖入和资料文件夹导入共用同一内容寻址与预览限制；旧数据库中同 SHA 的 HTML/YAML 若曾标为 `unsupported-retained`，再次按同扩展名导入时只重新解析预览/状态/元数据，不改写原文件或历史运行快照。输出容器已有的 `result` 文本、结构化内容和真实 `artifacts` 会继续递归复制到后续分析器的隔离 `inputs/`，结束阶段的授权目录不是运行中输入。

V12 资料候选前端构建到独立目录，不覆盖正式 `frontend/dist`、既有候选或 8710 服务：

```bash
cd frontend && npm run build -- --outDir dist-v12-materials
```

V13 将文件、文字和文件夹导入统一为一个“输入”节点；每个附件同时保留 `file_id`、输入引用的 `name`、`relative_path` 和实际快照路径。同一 SHA 的不同输入命名不会改写数据库资料名。过滤器只决定传给下游的活动附件：`basename` 匹配输入逻辑文件名，`relative_path` 匹配输入相对路径；glob/regex、扩展名、批量 regex 超时和排除摘要均在运行前校验。过滤不会删除、移动或改写原始资料、上游 checkpoint 或排除文件，排除内容不会通过 `content`、`structured`、`items`、`upstream` 或产物正文泄漏。

人工节点支持显式“有界循环（人工审阅）”闸门。合法拓扑必须是 `reviewer → human(review_gate) → subflow_output`；审批输入包含当前轮已完成的 executor 正文/附件以及 reviewer 意见，暂停期间可按当前审批白名单下载已校验附件。退回可以只提交修订正文（包括明确的空字符串）而不填写备注；修订会进入下一轮的 `latest_result`/human revision context，原始执行器正文只保留在审批与 checkpoint 审计中，附件和真实产物引用继续可执行。普通“有界循环”默认不增加人工闸门；需要时从组件库显式选择人工审阅 preset。条件节点对缺失字段提供 `error`、`false`、`true` 三种策略。

V13 聚焦验收使用隔离数据目录和合成 CLI，不调用真实模型、Pi 或付费推理：

```bash
./.venv/bin/python acceptance/v13_focus_checks.py
(cd frontend && npx tsc -b)
(cd frontend && npx vite build --outDir dist-v13)
```

四个后端场景应全部 PASS：统一输入与过滤无副作用、批量 regex 超时 fail-closed、条件缺失与修订传输、当前轮人工闸门的退回/空修订/终止及无自动重放。候选静态文件位于 `frontend/dist-v13`；独立复核构建位于 `frontend/dist-v13-verified`。验收通过后将静态文件更新至 `frontend/dist` 并重启本地服务；打开 http://127.0.0.1:8710 后刷新页面即可使用。

V14 UI polish 保持工作流 schema 和第三方画布类型不变：顶部导出/导入分别使用 Download/Upload 图标；输入节点只清除 XYFlow 外层默认黑框，内部 `kxy-node` 的边框、选中态和 handles 保留。分析器检查器中的 Skill 与 MCP 列表各自支持展开/收起、按名称 trim 后大小写不敏感搜索、空结果提示和总数/已选数统计；过滤或收起不会改变已有选择，也不会触发 mount preview。

动效强度统一为 `0–500`，默认 `30` 保持标准强度，旧 `0–100` 值不静默改写；`100` 保留旧上限，`500` 将对比系数扩展到旧上限的 5 倍。强度只调整选中波纹和指针轨迹的颜色/透明度对比，几何范围、网格绑定、节点遮挡、关闭/减弱动态和帧边界保持不变；实际 alpha 始终限制在 `0..1`，因此这不是线性物理亮度保证。

左上角品牌图从固定只读端点 `/api/branding/logo` 加载，同目录替换优先级为 `branding/logo.png`、`branding/logo.webp`、`branding/logo.svg`；默认包提供静态 `branding/logo.svg`，替换后刷新即可生效，无需重建或重启。端点不接受任意路径并发送 `Cache-Control: no-store`；图像加载失败时回退为文本 `kxy`。SVG 仅作为静态 `<img>` 资源提供，不在后端执行或解析。

V14 候选前端构建到独立目录，不覆盖正式 `frontend/dist`、既有候选或 8710 服务：

```bash
cd frontend && npm run build -- --outDir dist-v14
```

V15 增加固定版本 SkillHub 依赖诊断与 Agent runtime 闭环。分析器检查器可编辑并保存 Skill 的 `tools`、`env`、`services`、`network` 声明；本地导入且没有旧 `upstream_id` 的 Skill 会在首次保存声明时纳入 KXY 的中央 immutable snapshot，不会改写原始 Skill 目录。检查只做上游静态诊断和少量可信工具/CLI `--version` 探针，不执行 `SKILL.md`、用户脚本、npm 安装、MCP handshake 或模型调用；服务、网络和 inferred 项会明确标为人工确认。声明的缺失依赖或 Agent runtime 失败会在实际运行前阻止启动。

Agent 设置中的 runtime interpreter 是本地 profile 绑定，版本探测、实际 CLI 启动和快照恢复使用同一 argv/env 规则。Node CLI 会优先尝试已有的本机可执行解释器；不会下载 Node、修改全局 PATH、安装全局包或复制凭据。解释器路径、CLI 版本、工具路径身份、模型/凭据配置身份和 Skill 内容/声明变化会使依赖检查缓存失效；缓存不保存密钥、完整环境或原始诊断输出。静态检查默认开启，也可在设置中关闭后手动检查、强制重查或清理缓存。

V15 候选前端构建到独立目录，不覆盖正式 `frontend/dist`、V14 候选或 8710 服务：

```bash
cd frontend && npm run build -- --outDir dist-v15
```

V15 合成 focused 检查只验证运行时失败分类、固定解释器复用、本地 Skill 首次纳入中央库、依赖声明保存、缓存命中/强制重查/清理和实际运行 gate；不代表真实模型质量、真实 Pi 推理、MCP handshake 或生产部署。候选静态文件位于 `frontend/dist-v15`，需由独立验收确认后才可更新正式 `frontend/dist`。

V16 index-fix 增加了左侧“中央索引同步”面板。扫描只读比较 KXY 快照、中央索引和副本；扫描结果默认全部不选，“全选普通更新”只包含可修复映射和待纳入副本，已删除 Skill 的恢复项必须单独明确选择。同步提交带扫描 fingerprint、manifest 摘要和 ledger 关联校验，扫描后数据变化会要求重新扫描。技能列表支持全选、反选和批量删除；服务返回“记录已删除但快照清理失败”时，界面会移除实际已删除记录、清理画布引用并单独提示清理失败，完全失败的记录仍保留并保持可选。删除只作用于 KXY 技能记录与快照，不改写 Agent 原始目录、中央库或历史运行快照。

V17 更新内置 SkillHub 到上游 commit `8ae72075fdafb1d9dda5f3a232fd9fd438d6e485`。上游修复本地 GUI 的 Origin/HttpOnly 会话边界，增加只读模式、服务端确认短语、写操作审计、中央库目录 `0700` 收紧，并修正中央库漂移在无投影目标时的状态判断与 link/apply 双重门禁。kxy 当前仍只通过受限 CLI/diagnostic/dependency bridge 使用 vendored package；KXY 自己的 full-snapshot、path/marker、旧索引迁移、scan/sync、tombstone 和运行时/cache 门禁继续生效，不启动上游 SkillHub GUI，也不改原生 Agent 目录或全局配置。上游 provenance 和 blob 校验见 `vendor/skillhub/UPSTREAM_PROVENANCE.json` 与 `backend/agent_config.py`。

V16 候选前端构建到独立目录，不覆盖正式 `frontend/dist` 或既有候选：

```bash
cd frontend && npm run build -- --outDir dist-index-fix
```

V6 隔离验收使用合成 fixture，不代表真实模型质量、真实推理或生产部署：

```bash
cd ..
.venv/bin/python acceptance/v6_supervisor_checks.py
```

后端独立检查使用临时数据目录。`supervisor_checks.py`、`runtime_checks.py` 使用合成输入和标记过的 fixture CLI，不代表真实模型质量：

```bash
cd ..
.venv/bin/python acceptance/supervisor_checks.py
.venv/bin/python acceptance/runtime_checks.py
```

macOS Seatbelt 检查应在没有更外层沙盒的宿主终端执行：

```bash
.venv/bin/python acceptance/sandbox_checks.py
```

真实 CLI 检查是显式 opt-in，只使用脚本生成的合成资料，并要求本机已有对应登录和模型权限：

```bash
KXY_SMOKE_CLI=codex KXY_SMOKE_MODEL=gpt-5.4-mini .venv/bin/python acceptance/real_cli_smoke.py
KXY_SMOKE_CLI=opencode KXY_SMOKE_MODEL=opencode/big-pickle .venv/bin/python acceptance/real_cli_smoke.py
KXY_SMOKE_CLI=claude KXY_SMOKE_MODEL=sonnet .venv/bin/python acceptance/real_cli_smoke.py
```

## 使用边界

- 支持 HTML/HTM（只提取可读正文）、文本/Markdown、YAML/YML（原文文本）、原生文本 PDF、CSV/XLSX、JPEG/PNG；原文件按内容 SHA-256 保存，不覆盖输入。HTML 不执行脚本、不加载外链，YAML 不做对象构造。扫描 PDF、空 PDF、不可解析或未支持格式会保留并明确标记，不会伪装成已解析。
- 技能导入只保存快照，检查 `SKILL.md` 元数据并拒绝路径穿越、逃逸 symlink 和超限压缩包；运行时挂载的是每次运行的快照，不执行导入包里的代码。
- 默认使用用户已经配置好的 Codex/OpenCode CLI 登录。API 服务在“设置 → AI 服务”中单独保存名称、协议、模型目录和 Keychain 不透明引用；数据库和流程 JSON 不保存密钥。协议决定对应的密钥环境变量（OpenAI、Anthropic 或 Google），不提供任意环境变量选择。连接测试只请求用户指定服务的模型目录接口，未保存的密钥只用于本次测试；服务端不会返回或记录密钥。远程 endpoint 必须 HTTPS，本机 loopback 模型可使用 HTTP。
- 每个运行和节点有独立工作目录、输入清单、技能快照和输出目录。Codex 使用 CLI 的 workspace sandbox；OpenCode 使用 macOS OS sandbox。关闭网络时若当前 CLI/平台无法提供实际隔离会 fail-closed，不把提示词当作安全边界。
- 输出文件夹必须由用户明确授权；授权可撤销，运行时重新检查 canonical path 和 symlink 边界。导出流程不会携带凭据或文件系统授权。
- 条件节点只做结构化字段比较；缺失字段会在比较时失败；无效句柄、悬空边和环会在运行前失败。分支使用 LFX 原生 branch exclusion，合并只接收活动分支结果。

## 复用边界与数据位置

工作流 schema、SQLite 表、文件/技能/运行目录和 CLI 适配逻辑均属于 kxy。仅复用 LFX 1.12.0 的图组件/准备/运行机制以及 XYFlow 的画布组件；没有复制 Langflow providers、账号系统或其外部数据模型。第三方许可说明见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。

默认运行数据位于 `data/`，可用 `KXY_DATA_ROOT` 指向临时目录做测试。不要将真实密钥、私有资料或 CLI 登录文件纳入源码和工作流导出；`.gitignore` 已忽略运行数据库、输入、输出、虚拟环境和前端构建缓存。Codex 使用节点独立的 CODEX_HOME，仅临时读取必要认证副本（0600 权限），执行后清除，不带入原生配置、Skill 或模型缓存。

## 上手顺序

1. 选择“资料提取”模板，或直接拖入附件；从资料节点右侧端口连到分析器左侧。
2. 打开“设置 → Agent 配置”，选择 CLI 后发现模型和 effort。可选择可执行文件和 Skill 文件夹，扫描并勾选导入；导入的是快照，原目录保持不变。
3. 如使用 API 服务，先在“设置 → AI 服务”保存服务名、协议、Endpoint、模型目录和 Keychain 引用，并可在那里测试模型目录；再到“模型 / API”把已验证兼容的服务模型绑定到 Agent。CLI 模式选择本机发现的模型，设置 alias 与默认 effort；分析器的 Agent 下拉可直接选择已配置的 alias / model / effort 或服务绑定组合，“保存为分析器预设”可复用此绑定。
4. 容器默认保存在本地运行目录；如需额外保存，使用弹窗选择并授权一个已存在的文件夹。
5. 运行后在底部查看状态、正文、文件下载和保存位置。条件组件使用上游字段（如 `structured.route`）选择真/假分支。
6. 打开“全局设置 → 外观”，可搜索本机字体、分别设置文本和代码字体/字号，上传 PNG/JPEG/WebP 背景（最多 10 MB），点击“保存为默认样式”后刷新仍保留。可关闭点动效或设置撤回步数。流程需要另行点击“保存”；“打开流程”可载入保存版本。
7. 加入“人工确认”后填写确认说明和按钮文字。运行暂停时在执行面板查看上游数据，再确认或拒绝；刷新网页后可从运行历史重新打开。服务重启会将未完成运行标为中断，不会自动重新执行已完成的模型调用。
8. 选中节点后可封装为黑盒，双击进入内部画布，返回上级保存修改，也可解包保留连线。第一版为单输入、单输出，不能无损封装的选择会给出提示；允许最多四层嵌套。
9. “Agent 配置”中的 Skill 列表支持名称搜索、名称/修改日期排序，过滤不会清除已勾选项。分析器挂载其他 Agent 的 Skill 时自动调用 SkillHub；映射不改写原 Skill，也不自动翻译其中的 Agent 专用工具语义。
10. 点击“发现 MCP（仅读取配置）”，勾选并导入所需服务器，再在分析器中勾选使用。扫描和导入不会启动 MCP；运行时只加载所选配置，原生全局配置保持不变。目标 CLI 不支持的条目会明确禁用。凭据保留为原生配置或环境变量引用，不随工作流导出。
11. 使用工具栏“撤回”或非文本输入状态下的 Cmd/Ctrl+Z 撤回图编辑。一次拖动算一步，黑盒内编辑也可撤回。历史保存在当前页面会话，刷新清空；撤回不能取消已发生的模型调用或文件输出。
12. 切换到画布工具栏的“框选”，在背景拖出选区，再点击“新建黑盒”。切回“移动”可拖动画布；空格或中键也可平移。选区仍需满足黑盒的单输入、单输出规则。
13. 选中分析器，在检查器中设置“自动”、Markdown、纯文本或 JSON 输出；“自动”逐字保留 CLI 正文，显式 JSON 只做本地对象/Schema 校验。选中输出容器后分别选择正文副本格式和真实生成文件扩展名及 JSON 内容范围；扩展名选项不会把正文转换成文件。悬停选项可查看说明。运行完成后，检查器和底部运行面板都会显示正文与上游归因，并列出实际接收/排除的文件；编辑或下载的是副本，原运行记录保持不变。
14. 在“全局设置 → AI 服务”新建或编辑服务，选择 Custom、OpenAI、Anthropic、Google 或 OpenRouter 预设，协议会决定密钥环境变量；连接测试仅验证模型目录接口，不代表推理调用成功。再到“模型 / API”选择与 Agent 兼容的服务和模型。Codex 仅接受 OpenAI Responses，Claude 仅接受 Anthropic Messages，pi 支持已验证的 OpenAI/Anthropic/Google 映射，OpenCode 使用隔离 provider 映射；不兼容组合会禁用或拒绝。旧版 credential 记录仍可读取，编辑时空白密钥保留原 Keychain 引用，改 Endpoint/协议后必须重新录入密钥。

`data/` 是独立数据目录；从 WhatFa 移动整个 kxy 文件夹后重新执行 `./setup.sh` 即可。自建 Python 环境不可直接跨目录搬迁。

当前 Codex 云模型需要开启网络；关闭网络会明确报错。OpenCode 的关闭网络会阻断全部出入网络，因此 HTTP 本地模型端点也会被阻断。界面选择开启网络时仍有文件写入沙盒。原生 CLI 登录能否使用指定模型，以实际执行结果为准。

分发包验收以根目录 `RELEASE_NOTES.md` 和 `package-manifest.json` 为准。`docs/V3_PLAN.md`、`acceptance/V3_REPORT.md`、`acceptance/V2_REPORT.md`、`acceptance/REPORT.md` 仅保留在开发仓库，不作为分发包依赖。

V2 隔离检查：`.venv/bin/python acceptance/v2_config_checks.py`、`.venv/bin/python acceptance/v2_runtime_checks.py`、`.venv/bin/python acceptance/v2_supervisor_checks.py`。V5 配置检查使用 `acceptance/v5_supervisor_checks.py` 的合成目录和临时数据；浏览器检查使用 `acceptance/v5_fixture_server.py` 与 `frontend/dist-v5`。原生选择器依赖本机 macOS 图形会话；DeepSeek Harness 需要实际存在并通过协议检查的 headless profile，web profile 不会被当作可执行替代品。旧版手动记录仍可读取，但新建登录态配置必须来自当前 Agent 的发现目录。

浏览器验收脚本（仅开发仓库，分发包不包含）：`acceptance/browser_checks.cjs` 和 `acceptance/browser_component_checks.cjs`（需要 Playwright / Chromium）。Keychain 原生往返检查：`.venv/bin/python acceptance/keychain_checks.py`，仅使用新建的合成条目并在测试后删除。
