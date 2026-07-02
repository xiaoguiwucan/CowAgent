# CHANGES

## 2026-07-02

### AGENTS UI 默认修改目标规则

- 更新 `AGENTS.md`：补充 UI 修改默认目标规则，明确用户要求修改 UI、页面、布局、交互或样式但未指定端时，只修改 Web 控制台相关文件，不默认联动修改桌面端；仅在用户明确指定桌面端、Electron 或 `desktop/` 时才修改桌面端 UI。

验证记录：

- 文档变更，已检查 `AGENTS.md` 包含 UI 默认修改 Web 控制台规则。

### AGENTS 开发计划回写规则

- 更新 `AGENTS.md`：在“修改原则”中补充跟进开发计划文档开发时的收尾要求，明确开发完成后必须回写对应计划文档，更新已完成进度、实际改动、验证结果与剩余事项。

验证记录：

- 文档变更，已检查 `AGENTS.md` 包含开发计划回写规则，`CHANGES.md` 已记录本次修改。

### 桌面端群聊页宽度调整

- 更新 `desktop/src/renderer/src/pages/GroupsPage.tsx`：移除右侧详情面板的 `max-w-4xl` / `max-w-5xl` 宽度限制，使群聊页主内容区与知识库页一样覆盖可用窗口宽度。
- 调整群聊页内部布局：基础设置改为更适合宽屏的三列比例；群聊开关页扩大已选群列表和群名兜底编辑区；人设设定编辑器改为随右侧空间撑开并保留内部滚动。
- 更新 `channel/web/chat.html` 与 `channel/web/static/js/console.js`：同步 Web 控制台群聊页宽度，外层对齐知识库页 `max-w-[1600px]`，并扩大动态渲染的群聊开关、人设编辑内部空间。

验证记录：

- 静态布局断言：确认 `GroupsPage.tsx` 不再包含 `max-w-4xl` / `max-w-5xl` 详情宽度限制，并包含新的宽屏群聊布局。
- 静态布局断言：确认 Web 控制台 `view-groups` 外层已对齐知识库页 `max-w-[1600px]`，且动态群聊详情面板不再包含窄宽度限制。
- `node --check .\channel\web\static\js\console.js`
- `Set-Location -LiteralPath .\desktop`
- `npm run build`

### Agent LLM 请求上下文日志

- 更新 `agent/protocol/agent_stream.py`：在每次调用 LLM 前只打印请求上下文来源与概要，包括 system prompt 字符数、加载来源文件、顶层章节、messages 角色/块类型/字符统计和 tools 名称/schema 概况，避免完整打印 system prompt、历史消息正文和 tool schema。
- 更新 `tests/test_agent_stream_logging.py`：覆盖日志包含来源与概要信息，同时不泄露完整上下文正文、历史消息正文和长用户消息尾部内容。

验证记录：

- `python -m unittest tests.test_agent_stream_logging`
- `python -m py_compile agent/protocol/agent_stream.py tests/test_agent_stream_logging.py`

### 桌面端群聊页与 4.3 计划补充

- 新增 `desktop/src/renderer/src/pages/GroupsPage.tsx`：提供桌面端独立“群聊”管理页，支持“基础设置 / 群聊开关 / 人设设定”三段式左侧子菜单、4.2 最近上下文配置、群名检索多选和自定义人设保存。
- 更新 `desktop/src/renderer/src/App.tsx` 与 `desktop/src/renderer/src/layout/NavRail.tsx`：新增 `/groups` 路由和左侧“群聊”菜单入口。
- 更新 `desktop/src/renderer/src/pages/ChannelsPage.tsx`：个人微信群通道卡片不再展示群聊细项设置，仅保留接入、扫码、连接和断开入口。
- 更新 `desktop/src/renderer/src/types.ts` 与 `desktop/src/renderer/src/i18n.ts`：补充微信群最近上下文配置类型和群聊管理页中英文文案。
- 更新 `AGENTS.md`：补充个人微信群通道请求 LLM 前的实际上下文链路，明确其是在原 `ChatChannel` / Agent 主链路基础上叠加 `<wechat-group-persona>` 与 `<recent-wechat-group-transcript>`。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：细化 4.3 群永久记忆与群友画像的首轮边界、上下文注入格式、服务接口、UI 运维范围和测试要求。
- 继续补充 4.3 记忆方案：明确微信群群记忆与群友画像进入 CowAgent 通用作用域记忆体系，通过 `scope_type`、`scope_id`、`channel_type`、`subject_id` 兼容扩展保持旧记忆行为不变。
- 细化 4.3 UI 展示要求：永久记忆页必须按群分类展示记忆内容；选中某个群后再区分群记忆与按成员展示的群友画像，并补充对应测试要求。
- 根据通用作用域记忆方案修订 4.3 任务五、任务六与相邻章节：明确群友画像采用单份 active profile + revision 审计模型，提示词装配必须通过 `WechatGroupMemoryService` / `MemoryScope` 获取已过滤结果，UI 分类数据必须来自统一记忆 API 的 scope 聚合结果，并补充作用域记忆验证命令。

验证记录：

- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `Set-Location -LiteralPath .\desktop`
- `npm run build`
- 文档变更，已检查 4.3 方案与当前微信群 4.2 上下文注入边界一致。

### 群聊管理页与 4.2 配置 UI

- 更新 `channel/web/chat.html` 与 `channel/web/static/js/console.js`：在 Web 控制台管理目录新增“群聊”入口和独立群聊管理页，支持“基础设置 / 群聊开关 / 人设设定”三段式左侧子菜单。
- Web 群聊页新增 4.2 最近上下文三个配置项、群名检索下拉多选、自定义人设设置；个人微信群通道卡片不再展示群聊细项设置。
- 为 Web 控制台 `console.js` 引用增加版本参数，避免浏览器缓存旧脚本导致重启后看不到新 UI。
- 修复 Web 群聊页状态提示误引用不存在的 `TRANSLATIONS` 对象导致的运行时异常，并补齐移除最后一个已选群后的空状态提示。
- 新增 `plans/wechat_group_ui_management_plan_20260702.md`：记录群聊管理页双栏紧凑布局、三个左侧子菜单和 4.2 配置迁移范围。
- 更新 `channel/web/web_channel.py`：`wechat_group.extra` 返回 `recent_context`，并支持保存 `wechat_group_recent_context_enabled`、`wechat_group_recent_context_limit`、`wechat_group_recent_context_minutes`。
- 更新 `tests/test_wechat_group_web.py`：覆盖最近上下文配置返回与保存。

验证记录：

- `python -m unittest tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `node --check .\channel\web\static\js\console.js`

### 4.2 当前群最近上下文

- 新增 `channel/wechat_group/wechat_group_archive.py`：使用微信群专用 SQLite 数据库记录 `wechat_group_messages` 与 `wechat_group_assistant_replies`，入站消息按 `room_id` 隔离，避免污染 CowAgent 全局长期记忆。
- 新增 `channel/wechat_group/wechat_group_context.py`：生成 `<recent-wechat-group-transcript>` 最近群聊上下文块，包含时间、消息类型、发送人昵称和简洁文本摘要。
- 更新 `channel/wechat_group/wechat_group_channel.py`：在微信群消息进入 CowAgent 回复链路前按配置注入当前群最近上下文，并在发送回复后记录助手出站内容。
- 更新 `channel/wechat_group/wechat_group_message.py`：保留 `message_type`、原始文本和媒体路径字段，供归档与后续多模态阶段复用。
- 新增 `tests/test_wechat_group_context.py`：覆盖按 `room_id` 查询隔离、上下文块格式和通道注入/归档闭环。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：标记 4.2 最小闭环完成并记录当前实现边界。
- 补充 4.2 架构论证：明确专用 SQLite 表是微信群通道短期归档/最近上下文，不等同于 CowAgent 长期记忆；4.3 再通过 `WechatGroupMemoryService` 在 `room_id` / `sender_id` 隔离前提下复用 CowAgent 记忆能力组件。
- 消除微信群 4.2 回归测试中的环境 warning：`ChatChannel` 改用 `thread.daemon = True`，并把 `voice.audio_convert.any_to_wav` 改为语音分支懒加载，避免文本测试导入链路触发 pydub 的 ffmpeg 探测 warning。

验证记录：

- `python -m unittest tests.test_wechat_group_context`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_wechat_group_persona tests.test_wechat_group_context`
- 文档论证变更，已检查 4.2 与 4.3 边界描述一致。
- `python -W error -c "from channel.wechat_group.wechat_group_channel import WechatGroupChannel; print('imported')"`
- `python -W error::DeprecationWarning -m unittest tests.test_wechat_group_context`

## 2026-07-01

### 微信群迁移计划

- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：在 4.1 微信群通道闭环中补充“人设设定与生效规则”，参考 BaiLongmaPro 的 `personaPrompt` / `personaPresetId` 方案，明确内置预设、自定义人设、保存生效、prompt 注入和管理员优先级边界。
- 同步补充文件级任务、建议配置项、UI 范围、测试覆盖、手动验证和首轮交付边界，确保人设功能进入开发计划但不进入本次实际实现。

验证记录：

- 文档变更，已检查计划中包含人设配置、提示词注入、UI、测试与交付边界。

### 4.1 微信群通道闭环

- 新增 `wechat_group` 渠道常量、工厂注册、默认配置与配置模板，支持通过 `channel_type` 启动个人微信群通道。
- 新增 `channel/wechat_group/` Python 通道层和 Node.js Wechaty sidecar，完成扫码登录、状态/二维码事件、群消息标准化、群列表刷新、文本/图片/文件/音频发送命令。
- 在 Web 控制台与桌面端通道管理中加入“个人微信群”接入入口，支持从“通道管理 -> 接入通道 -> 个人微信群”展示二维码并轮询登录状态。
- 为 `wechat_group` 增加二维码状态接口 `/api/wechat_group/qrlogin`，用于通道管理界面展示二维码和连接状态。
- 修复微信群回复真实 @ 问题：`wechat_group` 回复不再使用公共群聊装饰层拼接普通文本 `@昵称`，改为只把发送者 ID 传给 Wechaty 原生 mention。
- 修复 Wechaty `room.say` 调用参数：使用 `room.say(text, ...mentions)`，避免把 mention 数组作为单个参数导致 sidecar 报错。
- 修复 sidecar 按发送人 ID 解析真实 @ 目标的问题：不再把 `sender_id` 当作 `room.member(name)` 的名称查询，改为通过 `Contact.find({ id })` 获取联系人并用 `room.has(contact)` 确认其仍在当前群内，再传给 `Room.say(text, contact)`。
- 参考 BaiLongMaPro 的微信群 @ 实现后继续修复 sidecar 发送路径：优先从当前 `room.memberAll()` 按真实 `sender_id/contact.id` 精确命中成员，避免群成员不在联系人缓存时解析不到 @ 目标。
- 针对默认 `wechaty-puppet-wechat4u` 链路改为稳定可见 @ 文本兜底：按真实群昵称发送 `@昵称\u2005正文`，并清理模型可能自己拼出的开头 @；保留 `MsgSource/atuserlist` 实验函数测试，但生产默认不依赖该方案。
- 明确边界：Web 微信 / `wechaty-puppet-wechat4u` 不能稳定触发微信系统级「有人@我」提醒，本次保证的是回复发回同一群且文本中可见 @ 到真实发送人的群昵称；非 wechat4u puppet 仍优先尝试 Wechaty Contact mention，失败时降级为可见 @ 文本。
- 补齐 4.1 人设闭环：新增 `channel/wechat_group/wechat_group_persona.py`，直接复用 BaiLongmaPro 的三组初始化人设文本，并在 CowAgent 中映射为 `owner-digital-twin`、`tech-duty`、`social-fun` 三个预设。
- 新增微信群人设配置项 `wechat_group_persona_preset_id`、`wechat_group_persona_prompt`，支持 6000 字符限制、换行归一化、内置预设识别与 `custom` 标记。
- 在微信群文本上下文进入 CowAgent 回复链路前注入独立 `<wechat-group-persona>` 块；已验证管理员的配置/诊断类请求会跳过普通人设注入，避免人设覆盖管理员意图。
- 补齐目标群选择闭环：支持 `wechat_group_room_ids` 精确选择和 `wechat_group_names` 群名兜底过滤，二维码状态接口返回当前群列表，`refresh` 会触发 sidecar 刷新群列表。
- 扩展 `/api/channels` 的 `wechat_group.extra`，向 Web 控制台和桌面端暴露群列表、当前选中群、人设预设与当前生效人设，并支持保存目标群和人设配置。
- 在 Web 控制台与桌面端通道卡片中增加个人微信群最小运维面板：刷新群列表、选择目标群、填写群名兜底、切换预设人设、自定义人设并保存生效。
- 新增 `tests/test_wechat_group_message.py`、`tests/test_wechat_group_channel.py`、`tests/test_wechat_group_web.py`，覆盖消息解析、通道发送、二维码 API 与真实 @ 回归场景。
- 新增 `tests/test_wechat_group_persona.py`，覆盖人设预设、归一化、preset ID 解析、prompt 注入和管理员配置请求跳过人设。
- 新增 `channel/wechat_group/sidecar/wechaty-sidecar-core.mjs` 与 `wechaty-sidecar-core.test.mjs`，覆盖 sidecar 发送命令到 Wechaty Contact mention 的转换逻辑。

验证记录：

- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_wechat_group_persona`
- `node --test .\channel\wechat_group\sidecar\wechaty-sidecar-core.test.mjs`
- `node --check .\channel\web\static\js\console.js`
- `node --check .\channel\wechat_group\sidecar\wechaty-sidecar.mjs`
- `node --check .\channel\wechat_group\sidecar\wechaty-sidecar-core.mjs`
- `desktop` 目录下执行 `npm run build`

### 协作规则

- 新增本文件作为项目变更记录入口。
- 更新 `AGENTS.md`：明确以后每次代码、配置或文档修改都必须同步记录到根目录 `CHANGES.md`。
- 完善 `AGENTS.md` 中个人微信群通道说明，补充 sidecar 职责、通道管理扫码入口、真实 @ 规则、JSON Lines 协议同步要求、运行数据目录约束和最小验证命令。
