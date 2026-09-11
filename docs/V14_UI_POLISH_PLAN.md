# V14 首页界面修正

用户已授权 Luna max 实现、父任务验收。最小修改现有前端/后端，无新架构层。先备份；不改资料、流程、凭据或 CLI 配置。

1. 顶栏导出 Download、导入 Upload，保留文字/title/可访问名称。
2. 新 input 卡后黑框来自 XYFlow .react-flow__node-input 默认 padding/width/border/background（自定义 input 类型重名）。在 kxy 画布范围覆盖外层默认样式及 hover/selected 外层 shadow，使边界随自定义卡内容，保留 .kxy-node 的边框/选中/键盘可见提示及 handles。不改 workflow type，不改第三方源码。
3. Inspector 的 Skill、MCP 分别增加独立收起/展开按钮（aria-expanded）及名字搜索框；trim/大小写不敏感子串过滤，空结果提示，显示总数/已选数。折叠/筛选不清空挂载选择、不启动 MCP、不触发挂载调用；切节点状态逻辑清晰。用户图指 Inspector，勿顺便重做全局列表。
4. 动效强度只控制已有网格点的高亮颜色/透明度对比，不用数量/半径/时长模拟增强。设置上限扩展为500（旧100强度驱动的5倍），前后端范围/默认样式保存同步；现有数值保持可读，不静默改用户设置。参数驱动可提高到5倍，实际alpha限制0..1，深浅背景都可见；说明物理颜色有上限，不声称实际亮度线性5倍。保留格点绑定、卡片遮挡排除、0/关闭/reduced-motion及帧数量边界。选择波和鼠标拖尾同样应用对比度控制，几何使用固定原标准参数。
5. 左上用 img logo 代替文字，初始图片只写 kxy。选择简单固定可替换文件方案（如 kxy/branding/logo.svg，允许同目录 logo.png/webp 优先使用，README说明优先级）；后端专用只读固定路径 endpoint 每次请求从磁盘读取，Cache-Control no-store，刷新后更换图即生效，无需重建或重启。无任意路径参数，不执行SVG，img失败回退kxy。保持现有尺寸比例object-fit。默认SVG用简单静态文字即可，不必调用图像模型。发布包需包含branding默认图，若现有打包脚本有文件白名单则同步最少项。

验证以编译 + 一次隔离UI验证为主，不增加大测试矩阵，不调用模型。父验证黑框computed style/连接点、独立搜索折叠不丢选择、强度设置持久化上限、替换Logo刷新读取。README写用户替图路径及使用方法。Luna build到frontend/dist-v14，禁止覆盖正式dist或重启8710；父验收发布。不写验收报告。
