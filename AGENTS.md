# CowAgent 项目协作指南

本文件面向在本仓库内工作的 AI Agent 与开发者。目标是先理解项目边界，再用最小改动完成需求，并保留可验证、可回退的交付路径。

## 项目概览

CowAgent 是一个以 Python 为主的多渠道 Agent Harness 项目，包含：

- 后端运行入口：`app.py`
- 配置中心：`config.py`、`config-template.json`
- 消息渠道层：`channel/`
- 模型、语音、翻译路由：`bridge/`、`models/`、`voice/`、`translate/`
- Agent 核心协议、工具、技能、记忆、知识库：`agent/`
- 插件系统：`plugins/`
- CLI：`cli/`
- Electron + Vite + React 桌面端：`desktop/`
- 文档站内容：`docs/`
- 回归测试：`tests/`

项目核心数据流：

1. `app.py` 加载配置并启动 `ChannelManager`。
2. `channel/channel_factory.py` 根据 `channel_type` 创建 Web、IM 或终端渠道。
3. 渠道把消息包装为 `bridge.context.Context`。
4. `bridge/bridge.py` 根据配置选择聊天模型、语音、翻译或 Agent 模式。
5. Agent 模式通过 `bridge/agent_bridge.py` 进入 `agent/`，按工具、技能、记忆与知识库上下文执行任务。
6. 回复通过原渠道发送回用户。

## 主要目录职责

- `agent/protocol/`：Agent 执行协议、流式执行、动作与结果模型。
- `agent/tools/`：内置工具实现。新增工具时优先继承 `BaseTool`，并确认 `agent/tools/__init__.py` 与 `ToolManager` 加载路径。
- `agent/tools/mcp/`：MCP 客户端与动态工具注册。修改时注意并发加载、热更新和子进程生命周期。
- `agent/skills/`：技能加载、过滤、启停配置与 prompt 格式化。内置技能在根目录 `skills/`，用户技能通常在 workspace 的 `skills/`。
- `agent/memory/`、`agent/knowledge/`：长期记忆、向量/关键词索引、知识库服务。
- `bridge/`：模型、语音、翻译、Agent 模式的统一路由层。改动这里会影响所有渠道。
- `channel/`：不同平台渠道。公共逻辑在 `channel/channel.py`、`channel/chat_channel.py`；新增渠道需接入 `channel/channel_factory.py`。
- `channel/wechat_group/`：个人微信群通道实现。Python 层负责 CowAgent 渠道适配、配置读取、上下文包装和回复发送；`sidecar/` 下的 Node.js Wechaty 进程负责扫码登录、群列表、群消息事件和微信侧真实发送。
- `models/`：不同 LLM Provider 的 Bot 与 Session。新增 Provider 要同步 `common/const.py`、`models/bot_factory.py` 和相关配置/文档。
- `plugins/`：聊天命令插件与插件管理器。不要把 Agent 工具和插件混为一类。
- `voice/`、`translate/`：ASR/TTS 与翻译 Provider。
- `desktop/`：Electron 主进程、React 渲染端和桌面打包配置。桌面后端默认由 `desktop/src/main/python-manager.ts` 管理。
- `docs/`：英文、中文、日文文档。涉及用户可见能力变更时，优先补充对应文档。
- `tests/`：`unittest` 风格回归测试，很多测试通过 stub/mocking 避免真实网络和外部服务。

## 本地运行与验证

默认在 Windows PowerShell 中工作。不要使用 `&&` 串联命令。

后端依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
python -m pip install -e .
```

启动后端：

```powershell
python app.py
```

或安装 CLI 后：

```powershell
cow start
cow status
cow logs
```

运行全部 Python 测试：

```powershell
python -m unittest discover -s tests
```

运行单个测试文件：

```powershell
python -m unittest tests.test_models_handler
```

桌面端：

```powershell
Set-Location -LiteralPath .\desktop
npm install
npm run build
npm run dev
```

桌面端热开发：

```powershell
Set-Location -LiteralPath .\desktop
npm run dev:hot
```

## 修改原则

- 修改前先读当前文件，禁止凭记忆改代码。
- 遵守最小修改原则：只改让当前需求成立的必要文件。
- 不顺手重构无关代码；发现无关问题时在回复里单独说明。
- 用户要求修改 UI、页面、布局、交互或样式但未明确指定端时，默认只修改 Web 控制台（`channel/web/chat.html`、`channel/web/static/js/console.js`、`channel/web/static/css/console.css` 等）；不要同时修改桌面端 `desktop/`。只有用户明确要求“桌面端”“Electron”“桌面应用”或指定 `desktop/` 文件时，才修改桌面端 UI。
- 仅在新增或修改代码并提交/交付代码变更时，才同步更新根目录 `CHANGES.md`，记录本次修改日期、任务背景、关键改动文件和验证结果；纯文档、计划、规则、配置说明等非代码变更不更新 `CHANGES.md`。
- 提交 Git 代码变更时，必须将根目录 `AGENTS.md` 与 `CHANGES.md` 纳入同一次提交范围；提交前检查两者状态，确保规则说明与变更记录不会遗漏。
- 面向本项目的开发计划、迁移计划、实施方案和阶段性任务文档必须使用简体中文编写；如需引用英文 API、命令、路径或错误信息，保留原文即可。
- 跟进开发计划文档进行开发时，开发完成后必须回写对应开发计划文档，更新已完成进度、实际改动、验证结果与剩余事项，确保计划状态与代码交付一致。
- 优先沿用现有工厂、单例、配置读取和日志模式。
- 不要把真实密钥、token、cookie、部署 ID 写入仓库。
- 修改跨渠道逻辑时，评估 Web、IM、CLI、桌面端是否都会受影响。
- 修改 `config.py` 默认配置时，同步检查 `config-template.json`、Web 设置页、文档和相关测试。
- 修改模型路由时，同步检查 `Bridge`、`models/bot_factory.py`、`common/const.py`、Web 模型管理接口和测试。
- 修改 Agent 工具时，同步检查工具注册、工具 schema、异常返回格式、文档和安全测试。
- 修改桌面后端启动逻辑时，特别注意端口、数据目录、打包后路径和 Windows 行为。

## 安全边界

本项目直接触达文件系统、Shell、浏览器、网络、MCP 子进程和外部消息平台，安全改动必须保守。

- `agent/tools/web_fetch/`、`agent/tools/browser/`、`agent/tools/bash/`、`agent/tools/read/`、`agent/tools/write/`、`agent/tools/edit/` 是高风险区域。
- SSRF、路径穿越、任意命令执行、任意文件读写、重定向到内网地址等问题必须有测试覆盖。
- 已有安全回归测试包括 `test_security_ssrf_web_fetch.py`、`test_security_ssrf_path_traversal.py`、`test_security_ssrf_browser_navigate.py`。
- 不要默认放宽 URL、文件路径、命令执行或 Web 文件服务根目录限制。
- `web_file_serve_root`、`agent_workspace`、`mcp_servers`、`mcpServers` 等配置可能扩大访问面，改动时要明确风险。

## 编码与风格

- Python 代码保持现有风格，优先小函数、明确异常处理和 `common.log.logger` 日志。
- 仓库贡献规范要求 issue、PR、代码注释和 commit message 尽量使用英文；新增代码注释也应优先英文。
- 用户对话可以使用中文，但写入项目代码和面向国际社区的文档时遵循仓库既有语言策略。
- 避免引入新的全局依赖；确需新增依赖时，同步更新 `requirements.txt`、`requirements-optional.txt` 或 `desktop/package.json`，并说明原因。
- README 或文档中如出现编码异常，先确认文件实际编码，不要盲目整体重写。

## 常见开发路径

新增或修改渠道：

1. 查看 `channel/channel.py`、`channel/chat_channel.py` 和相邻渠道实现。
2. 修改具体 `channel/<name>/`。
3. 必要时更新 `channel/channel_factory.py`、`common/const.py`、配置模板和文档。
4. 用 mock/stub 覆盖消息解析、鉴权、回复发送和异常路径。

修改个人微信群通道：

1. 优先查看 `channel/wechat_group/wechat_group_channel.py`、`wechat_group_client.py`、`wechat_group_message.py`、`protocol.py` 和 `channel/wechat_group/sidecar/wechaty-sidecar.mjs`。
2. 扫码入口必须在通道管理中完成：`通道管理 -> 接入通道 -> 个人微信群`，由界面展示二维码；不要把“看日志扫码”作为主要交互路径。
3. Web 控制台入口涉及 `channel/web/web_channel.py` 与 `channel/web/static/js/console.js`；桌面端入口涉及 `desktop/src/renderer/src/pages/ChannelsPage.tsx`、`components/QrLoginModal.tsx`、`api/client.ts` 和 `i18n.ts`。
4. 微信群回复 @ 用户时，正文不要手工拼接普通文本 `@昵称` 或 `@@id`；应将发送者 ID 作为 `mention_ids` 传给 sidecar，并由 Wechaty `room.say(text, ...mentions)` 执行真实 mention。
5. sidecar 与 Python 之间只通过 JSON Lines 协议通信。新增事件或命令时，先更新 `protocol.py`，再同步 Python client、channel 和 `wechaty-sidecar.mjs`，并补充对应测试。
6. Wechaty 登录态、媒体目录等运行数据必须放在仓库外的数据目录，不能写入 Git 跟踪内容；新增 npm 依赖时同步检查 `channel/wechat_group/sidecar/package.json` 与 lock 文件。
7. 涉及群选择时优先使用 `wechat_group_room_ids` 做精确限制；`group_name_white_list: ["ALL_GROUP"]` 只适合开发测试，不应作为长期生产默认。
8. 修改后至少运行 `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`。涉及桌面二维码、连接状态或通道页时，还要在 `desktop` 目录运行 `npm run build`。
9. 外部真实链路仍需手动验证：启动后打开通道管理，选择“个人微信群”，扫码登录，在目标群 @ 机器人确认能收到回复，并确认回复真实 @ 到发送者。

### 个人微信群 LLM 请求上下文链路

当前个人微信群通道不是替代 CowAgent 原有 Agent 主链路，而是在通用 `ChatChannel` 上下文构造之后叠加微信群专属上下文，再进入 `Channel.build_reply_content()` 和 `Bridge.fetch_agent_reply()`。

核心路径：

1. `WechatGroupChannel.handle_text()` 把 sidecar 消息包装为 `Context`。
2. `WechatGroupChannel._compose_context()` 先调用 `super()._compose_context()`，继续执行原 `ChatChannel` 群白名单、触发词、@ 去除、`session_id`、`receiver` 和插件事件逻辑。
3. 微信群通道随后在 `context.content` 前追加微信群专属上下文。4.2 阶段包括 `<wechat-group-persona>` 与 `<recent-wechat-group-transcript>`；4.3 完成后还应追加 `<wechat-group-memory>`。
4. `ChatChannel._generate_reply()` 调用 `super().build_reply_content(context.content, context)`。
5. 当 `agent` 配置为 `true` 时，`Channel.build_reply_content()` 进入 `Bridge.fetch_agent_reply()`，由 Agent 模式请求 LLM。

因此 LLM 最终看到的是“通用 Agent 系统上下文 + Agent 会话历史 + 微信群增强后的当前用户消息”：

```text
system:
  Agent 工具、技能、记忆规则、知识库规则、工作空间说明、
  AGENT.md / USER.md / RULE.md / MEMORY.md、运行时信息等。

messages:
  同一 session_id 下恢复的历史 user / assistant / tool 消息。

current user message:
  <wechat-group-persona>
  当前微信群人设。来自 wechat_group_persona_prompt；
  为空时使用 wechat_group_persona_preset_id 对应的默认人设。
  </wechat-group-persona>

  <recent-wechat-group-transcript>
  当前 room_id 最近群聊归档，默认最近 60 分钟、最多 20 条。
  </recent-wechat-group-transcript>

  <wechat-group-memory>
  [group_memory]
  当前 room_id 的群永久记忆，例如群规、长期项目、群偏好、群内约定。

  [speaker_profile sender_id="..."]
  本次发言人在当前 room_id 下的一份当前生效群友画像。

  [mentioned_profile sender_id="..."]
  本次发言中被 @ 的群友在当前 room_id 下的一份当前生效群友画像。
  可有多份；首轮只注入本轮明确 @ 到的成员画像。
  </wechat-group-memory>

  用户本次去掉开头 @ 后的真实问题
```

4.3 群永久记忆与群友画像的注入规则：

- 当前群记忆按 `scope_type = wechat_group`、`scope_id = room_id`、`channel_type = wechat_group` 召回，只允许进入当前群回复。
- 当前发言人的群友画像按 `scope_type = wechat_group_member_profile`、`scope_id = room_id`、`subject_id = sender_id`、`channel_type = wechat_group` 召回。
- 本次发言被 @ 的群友画像从 `at_list` 中排除机器人自身和当前发言人后召回；首轮只处理明确 @ 到的成员，不把普通文本昵称匹配作为强需求。
- 群友画像不是多条零散记忆拼接；每个 `room_id + sender_id` 最多注入一份当前生效画像，历史版本和来源只用于审计。
- 所有群记忆和画像召回必须先按 `room_id` 或 `room_id + sender_id` 强过滤，再排序；不允许跨群泄露。
- CowAgent 全局 shared memory 仍属于通用 Agent 记忆能力，不放进 `<wechat-group-memory>`；全局 shared memory 只能作为通用背景，不能反向泄露其他群信息。

通用 CowAgent 能力仍然生效：

- `MEMORY.md` 会作为工作空间上下文自动加载；每日记忆和完整记忆按需通过 `memory_search` / `memory_get` 工具检索。
- `knowledge` 开启时，知识库规则和 `knowledge/index.md` 会进入系统提示词；具体知识页按需通过 `read` 或 `memory_search` 查询。
- 技能、工具 schema、运行时信息和上下文压缩逻辑仍由 Agent 主链路处理。
- 自主进化仍会记录微信群用户轮次并参与 idle evolution；群聊场景通常不设置主动推送 `receiver`，避免进化结果主动打扰群。

当前实现边界：

- 4.3 完成前，当前微信群 `_compose_context()` 直接注入链路只明确使用人设块和最近群聊 transcript；不要假设已经有独立的 room/member 长期记忆块被自动拼进当前消息。
- 4.3 完成后，`<wechat-group-memory>` 必须通过 `WechatGroupMemoryService` 或等价适配层装配，统一从 CowAgent 作用域记忆读取已过滤结果，不允许在通道层绕过 `room_id` / `sender_id` 校验直接拼接原始记忆。
- Agent 模式会预持久化传入的 `query`；微信群增强后的 `context.content` 可能进入 Agent 会话历史。后续如需避免 prompt 块污染长期会话，应单独设计 no-persist 或原文/增强 prompt 分离机制。

新增或修改模型 Provider：

1. 查看相近 Provider 的 Bot 与 Session。
2. 在 `models/<provider>/` 实现最小必要适配。
3. 更新 `models/bot_factory.py`、`bridge/bridge.py` 的路由规则和 `config.py` 配置键。
4. 覆盖模型选择、参数持久化、错误返回和兼容模式测试。

新增或修改 Agent 工具：

1. 查看 `agent/tools/base_tool.py` 和现有工具实现。
2. 保持工具输入 schema、返回状态和错误文本稳定。
3. 更新 `agent/tools/__init__.py` 或相关动态加载配置。
4. 高风险工具必须补充安全回归测试。

新增或修改技能：

1. 内置技能放在根目录 `skills/<skill-name>/SKILL.md`。
2. 保持 frontmatter 元数据清晰，避免把大量业务逻辑塞进 prompt。
3. 如果提供脚本，放在技能目录下的 `scripts/`。
4. 可用 `skills/skill-creator/scripts/quick_validate.py` 做最小校验。

修改桌面端：

1. 主进程在 `desktop/src/main/`，渲染端在 `desktop/src/renderer/src/`。
2. 后端端口和启动流程集中在 `desktop/src/main/python-manager.ts`。
3. UI 状态优先沿用现有 Zustand store 和组件风格。
4. 修改后至少运行 `npm run build`。

## 前端 UI 开发规则

默认界面修改目标是 Web 控制台。除非用户明确指定桌面端，所有 UI 需求优先落在 `channel/web/chat.html`、`channel/web/static/js/console.js` 与 `channel/web/static/css/console.css`；桌面端规则仅在任务明确涉及 Electron / `desktop/` 时适用。

本项目桌面端当前技术栈是 Electron + Vite + React 18 + TypeScript + Tailwind CSS + Zustand + `lucide-react`。新增或修改 UI 时必须优先贴合现有实现，不要引入新的 UI 框架、组件库或设计系统，除非需求明确且已说明必要性。

### 结构与复用

- 渲染端代码位于 `desktop/src/renderer/src/`，按现有目录拆分：`pages/` 放页面、`components/` 放通用组件、`layout/` 放框架布局、`store/` 放 Zustand 状态、`api/` 放后端请求封装。
- 设置页能力优先复用 `desktop/src/renderer/src/pages/settings/primitives.tsx` 中的 `Card`、`Field`、`Dropdown`、`Toggle`、`TextInput`、`SaveRow`、`Modal`、`Btn`，不要为同类表单控件重复造一套样式。
- 渠道相关 UI 优先参考 `ChannelsPage.tsx` 的 `ChannelCard`、`ChannelDropdown`、`QrLoginModal` 交互模式；模型/配置类 UI 优先参考 `SettingsPage.tsx`、`BasicSettings.tsx`、`ModelsTab.tsx`。
- 图标优先使用 `lucide-react`，只有项目已有自定义图标如 `components/icons.tsx` 不足时才新增；不要使用 emoji 作为结构性图标或按钮图标。
- 文案必须走现有 `i18n.ts` 的 `t()` / `localizedLabel()` 体系；新增可见文案要同步补充中英文键值，避免硬编码在组件里。

### 视觉与主题

- 必须使用 `index.css` 中已有语义 token 和 Tailwind 语义类，例如 `bg-base`、`bg-surface`、`bg-surface-2`、`bg-elevated`、`bg-inset`、`text-content`、`text-content-secondary`、`text-content-tertiary`、`border-default`、`border-strong`、`bg-accent`、`text-accent`。
- 不要在组件里随意新增硬编码颜色；确需新增颜色时，优先在 `index.css` 中定义语义变量，并同时考虑 `.dark` 主题。
- 保持当前克制、工具型、信息密度适中的桌面应用风格。设置页和运维面板应使用清晰表单、状态徽标、列表/表格和少量卡片，不做营销式 hero、大面积插画、装饰性渐变或复杂动效。
- 圆角、间距和层级沿用现有约定：`rounded-btn`、`rounded-card`、`border-default`、`shadow-lg`、`px-6`、`py-5`、`space-y-*` 等。不要在同一页面混用一套新的圆角/阴影体系。
- 组件必须同时适配浅色和深色主题；不能只在当前主题下看起来正常。

### 布局与交互

- 桌面端页面优先采用现有框架：外层 `flex-1`、`min-h-0`、必要区域 `overflow-y-auto`，内容宽度通常控制在 `max-w-3xl` 或与相邻页面一致。
- 表单字段必须有可见 label，不要只靠 placeholder 表达含义；复杂字段应提供短 hint。
- 按钮、开关、下拉、图标按钮必须有明确 hover / disabled / loading 状态；异步操作期间按钮应禁用并显示 `Loader2` 或等价反馈。
- 弹窗沿用现有 `Modal` 或 `QrLoginModal` 模式，必须有明确关闭路径；涉及破坏性操作时使用 danger 样式并二次确认。
- 状态展示要可诊断：连接中、成功、失败、空状态、加载中都要有明确 UI，不允许静默失败或只写 `console.error`。
- 长文本、路径、room ID、模型名等必须可换行或截断，使用 `min-w-0`、`truncate`、`break-words`、`font-mono` 等现有模式，避免撑破布局。
- 动画只用于状态反馈或内容出现，沿用 `transition-colors`、`animate-spin`、`animate-reveal`、`skeleton` 等轻量模式，并尊重 `prefers-reduced-motion`。

### 可访问性与质量

- 交互控件必须使用语义元素：按钮用 `<button>`，输入用 `<input>` / `<textarea>`，开关保留 `role="switch"` 和 `aria-checked`。
- 图标按钮需要 `title` 或 `aria-label`；图片需要有意义的 `alt`。
- 颜色不能是唯一状态表达，重要状态需要结合文本或图标。
- 正文和表单文字保持可读对比度，优先使用现有 `text-content*` token，不要使用低对比灰色。
- 修改 UI 后至少运行 `Set-Location -LiteralPath .\desktop` 再运行 `npm run build`。涉及窗口布局、二维码、连接状态、设置页或渠道页时，还应启动 `npm run dev` 或 `npm run dev:hot` 做手动验证；如无法验证必须说明原因。

### 微信群机器人 UI 边界

- 阶段一只做最小运维面板：启用/停用、扫码状态、二维码、刷新群列表、选择目标群、保存配置、最近事件和错误提示。
- 阶段一的二维码必须嵌入通道接入流程，不再要求用户从后端日志复制扫码链接。
- 不在阶段一实现完整社交工作台、群统计、群记忆编辑、群友记忆编辑、战报、图片库或备份导入 UI。
- 微信群机器人设置应优先复用渠道页/设置页现有模式；如果 UI 改动范围过大，先保证配置文件、状态接口和日志可用，再单独规划 UI 小阶段。

## 验证策略

优先运行与改动直接相关的最小测试，再按风险扩大范围。

- 纯文档：检查文档是否能直接指导开发，无需运行测试。
- 配置/路由：运行对应 `tests/test_*` 单测。
- 微信群通道：运行 `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`；如改动桌面通道接入或二维码弹窗，再运行 `Set-Location -LiteralPath .\desktop` 后执行 `npm run build`。
- 安全相关：运行相关安全回归测试，必要时新增测试。
- 桌面端：运行 `npm run build`，涉及启动流程时再手动启动验证。
- 跨模块核心逻辑：运行 `python -m unittest discover -s tests`。

如果无法运行测试，必须在交付说明中写明原因和未验证风险。

## 交付说明要求

最终回复应说明：

- 改了哪些文件。
- 为什么这样改。
- 做了什么验证。
- 如果存在未验证项，明确列出原因。

不要声称“已修复”“已通过”而没有对应命令或检查结果。
