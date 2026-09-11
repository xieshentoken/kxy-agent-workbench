# kxy V4 交互、输出格式与连接测试

2026-09-07；用户已授权规划后交给 session 实现，沿用既有 React/XYFlow + FastAPI/LFX。只改 kxy，保持原数据/全局 CLI 配置及历史分发 ZIP；先备份。父任务规划、监督、独立验收，复用既有 Luna max session。

## 需求与选型

1. 框选：工具栏“移动/框选”互斥，aria-pressed/title；框选完成显示数量与“新建黑盒”。复用 packSelection/unpack/历史，不新造分组数据模型。XYFlow selectionOnDrag 被 panOnDrag=true 抑制，框选时显式禁左键平移；空格/中键仍能移动，保留 Shift 多选，黑盒内同样生效。选择操作本身不消耗撤回；封装一次记一步。
2. 输出：分析器 output_format=markdown|text|json（旧 expect_json=true 映射 json），output_schema 为可选 JSON Schema 对象；增加格式下拉、每项悬停说明、schema 编辑/校验/导入/导出。prompt 传递格式要求，实际输出扩展名和解析相符，json 必須合法对象；schema 用已安装 jsonschema 校验。拒绝远程 $ref、超限/无效 schema，不能因 schema 自动联网。schema 不放执行命令。设置随流程/预设保存及撤回。
3. 容器：export_formats 可选 markdown/text/json，旧流程默认 markdown+json；json_mode=content|full 明确说明正文结构化内容与包含来源/状态等完整记录的差别。默认兼容旧 result.json/result.md/provenance.json 行为；provenance 始终保留。UI 预览正文/结构化内容/文件，运行后 JSON 可编辑/校验/导入/下载为副本，不改已完成运行和原始资料。无数据/类型不匹配明确反馈，不把磁盘路径字符串当正文。
4. 网格：复用 XYFlow 背景的 gap=24、size=1.3 与 viewport 原点/缩放；选中扩散及鼠标拖尾只提高对应格点亮度，不添加自由移动粒子。位置必须等同背景圆点中心；支持 pan/zoom/resize/DPR/黑盒/多选，低开销、空闲停止、尊重关闭动效及 reduced motion。
5. 模式：manual 是发现不到时手动填实际模型ID/effort，默认复用 CLI 登录；api 必须绑定 Keychain 凭据，仍通过所选CLI运行。当前后端 manual 也能显式绑定 credential，所以文案要忠实说明“绑定后也会使用该凭据”，不能虚构二者互斥。原生记录只由 discovery 产生。
6. API测试：全局凭据表单增加测试按钮，支持未保存输入只存内存测试，以及已保存 credential_id 测试。后端 POST /api/credentials/test 复用 validate_endpoint 和 Keychain，只请求用户选定 endpoint 的 /models（provider默认地址明确显示），OpenAI Bearer / Anthropic x-api-key+anthropic-version。禁止重定向携带密钥；限制超时/响应长度，错误不反射密钥或响应正文；返回可读分类(鉴权/不可达/超时/限流/协议不支持)、耗时，2xx合法models才视为接口通过，明确不等于模型推理/CLI通过。不持久化测试输入/密钥，不发送资料；不主动测试用户已保存真实凭据。

## 接口与验收

在现有 App.tsx/v2.tsx/v3.tsx/styles.css 和 backend/app.py/agent_config.py 的直接路径增改，无新框架或抽象层。优先 jsonschema/httpx 现有依赖。

验收：前端构建；合成CLI验证三格式/schema与错误/旧工作流兼容、容器文件/元信息/授权/黑盒；mock服务验证鉴权头、/v1重复拼接、401/429/超时/重定向/非JSON/超限响应/脱敏，跨源拒绝；浏览器真实框选→封装→撤回、schema导入导出、结果副本编辑、模式说明及连接测试；多缩放网格坐标验收和窄屏检查。必须区分合成服务PASS与真实供应商调用未测。

## 研究依据与复用边界

本地 @xyflow/react 实现的 FlowRenderer/Pane/Background 已核对，直接使用 selectionOnDrag/panOnDrag/SelectionMode 及其缩放坐标公式。仓库 graphify 索引只覆盖 WhatFa，不能作为 kxy 当前代码证据，因此以 kxy 源码核验。

- https://reactflow.dev/examples/interaction/interaction-props
- https://developers.openai.com/api/reference/ruby/resources/models
- https://platform.claude.com/docs/en/api/overview

不增加通用输出模板语言、在线 schema 引用、自动模型计费探测或改写历史运行。历史安装包本轮保持原样，完成后 README 写明新用法。
