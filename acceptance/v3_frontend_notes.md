# kxy V3 前端实现与验收记录

状态：前端实现完成，等待父任务合并后端验收结论。

本次只修改 `frontend/**` 与本文件、`acceptance/v3_browser_checks.cjs`。合同依据：`docs/V3_PLAN.md`；V2 行为基线：`acceptance/V2_REPORT.md`。后端接口按 V3 合同接入，未在前端伪造 SkillHub、MCP 或字体发现成功。

## 当前实现边界

- 外观设置扩展为本机字体列表、文本/code 分离字体与字号、背景图片上传/清除、动效开关、1..50 步撤回深度，并保留 V2 兼容字段。
- Skill 发现支持名称搜索、名称/修改日期双向排序、过滤后保留勾选；分析器勾选 Skill 会请求 SkillHub mount preview 并显示实际结果。
- MCP 发现只在用户明确点击时读取已配置元数据；导入与分析器勾选均是显式操作，默认不启用、不启动服务。
- 画布动效使用 `pointer-events: none` Canvas，帧循环不写 React state；根据 DOM 节点矩形跟随 viewport/zoom，支持减弱动态效果与用户开关。
- 撤回只记录图编辑快照，忽略选中、尺寸、viewport、运行状态；拖动按一次手势记录，文本输入按字段合并，历史只保存在当前会话。
- 选中粒子从矩形边缘沿外向射线生成；对 ReactFlow 异步布局做有限帧重试，且卸载、隐藏页面和减弱动态效果均清理动效。

## 验收证据

- `npm run build -- --outDir dist-v3`：PASS（TypeScript + Vite；产物位于 `frontend/dist-v3`，未覆盖正式 `frontend/dist`）。
- 字体 computedStyle 复测：显式 `PingFang SC` 覆盖设置标题、面板正文和文本控件；`SF Mono` 与 15px 代码字号独立生效，文本正文为 17px。
- 背景视觉复测：上传多色 `docs/reference.png` 并保存到同源 8713 后，`.flow-frame` computed style 为普通合成 + 35% 浅色遮罩；截图 `/private/tmp/kxy-v3-frontend-8713-flow-frame.png` 中黑字及紫/蓝/黄彩色块均可辨识。旧 backend 的 MCP 404 仅产生预期控制台噪声，不影响该截图。
- 背景清除复测：同源 8713 清除→保存→刷新后，computed 为 `linear-gradient(... .35), none`，预览显示“无背景图”，清除按钮禁用，PASS。
- 父任务隔离端口 8712 的独立浏览器结果：PASS 7 项，见 `acceptance/v3-evidence/independent-browser/results.json`；包括连续新增逐次撤回、历史截断、单次拖动撤回、删除恢复节点与边、黑盒内部编辑撤回、字体/字号默认保存刷新、实际网格/卡片外粒子与 reduced-motion。
- 当前 backend + 同源静态 `dist-v3` 的本分支隔离端口 8713 浏览器结果：PASS 11/11，见 `/private/tmp/kxy-v3-frontend-8713-full-pass3/results.json`；额外覆盖真实 SkillHub mount/MCP 显式发现、Meta+Z 原生文本撤回、撤回后重新选择节点/黑盒内部节点、背景上传响应等待与 390px 窄视口。
- 本分支定向浏览器检查：同源静态预览 8713 上 PASS Canvas 指针响应、字体/独立字号、背景上传/默认保存/刷新、Skill 名称搜索/日期排序/过滤保留勾选；随后在旧 backend 的 MCP 路由 404 处停止。另在 5179/8711 上验证新增卡片异步布局后选中粒子 alpha `18912`、reduced-motion 清空 PASS，但跨源连接产生 CORS 错误，因此不作为完整 V3 运行验收。
- 本次定向 UI 合同检查：隔离 8713 wrapper 将 Codex `_mcp_native_paths` 覆盖为 synthetic stdio 配置，并通过 picker stub 提供外部 Claude Skill 根目录；真实 UI 链路 PASS 5/5：Claude Skill 导入且 `metadata.skillhub.status=ready`；Codex MCP 发现/导入为只读元数据且默认不启动；分析器 Skill 勾选实际请求 `/api/skillhub/mount` 并返回 `ready/cross_agent=true`；分析器 MCP 勾选后导出 JSON 含 `mcp_ids=["synthetic-stdio"]`；无模型或 MCP 执行请求、无浏览器错误。结果与截图见 `acceptance/v3-evidence/frontend/v3-ui-contract-results.json`、`v3-ui-contract-claude-skill.png`、`v3-ui-contract-mcp.png`、`v3-ui-contract-skillhub-mount.png`、`v3-ui-contract-export.png`。临时 8713 服务已停止；该检查未启动任何模型或 MCP 进程。
- `acceptance/v3_browser_checks.cjs` 覆盖背景上传与默认样式刷新、Skill 搜索/日期排序/保留勾选、显式 SkillHub preview、显式 MCP 发现与导入、撤回、黑盒、动效和窄视口；应使用父任务 V3 后端和同源静态 `dist-v3` 执行。旧 8711 后端不支持全部 V3 API，不能据此判定这些合同项失败。
