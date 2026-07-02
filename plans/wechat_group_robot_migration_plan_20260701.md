# 微信群聊机器人迁移开发计划

> 日期：2026-07-01
> 范围：参考 `D:\JiangShuai\SourceCode\BaiLongmaPro` 的微信群聊机器人实现，在 CowAgent 中以低风险、可验证、可回退的方式接入微信群聊机器人。

## 1. 目标定位

微信群聊机器人在 CowAgent 中应被定位为**一个消息通道**，而不是一套独立 Agent。

核心原则：

- Wechaty 侧车只负责微信登录、群列表、群消息收发、文件/图片/语音传输和 Wechaty 运行细节。
- Python 侧把微信群消息转换为 CowAgent 现有 `Context` / `ChatMessage`，继续复用 `ChatChannel`、`Bridge`、Agent、插件、模型、语音、图像和记忆能力。
- 不在微信群通道里重写一套模型调用、工具调用或 Agent 执行逻辑，避免后续能力分叉。
- 首轮核心体验不是“能在群里机械回复”，而是结合当前群最近上下文、群永久记忆和群友永久记忆，让回复更像长期参与群聊的人。

## 2. 当前调研结论

CowAgent 已具备可复用基础：

- `channel/channel_factory.py` 负责按 `channel_type` 创建渠道实例。
- `channel/chat_channel.py` 已有群聊通用语义，包括 `isgroup`、`is_at`、`actual_user_id`、`at_list`、群白名单、群共享会话和群回复装饰。
- `channel/chat_message.py` 定义了群聊渠道需要填充的统一消息字段。
- `bridge/` 和 `agent/` 已承接文本、Agent、工具、模型路由等核心能力。
- `voice/`、`bridge` 和现有回复类型已具备语音识别/语音合成接入基础。
- 图像理解和图像生成应优先走现有 `ContextType.IMAGE`、`ContextType.IMAGE_CREATE`、`ReplyType.IMAGE` / `IMAGE_URL` 等路径。
- `agent/memory` 已有 SQLite + FTS5 + embedding 的长期记忆基础，但默认 `scope` 语义是 `shared` / `user` / `session`，不能直接表达微信群和群友隔离。

CowAgent 现有 `channel/weixin/` 是 iLink 私聊通道：

- 当前支持微信 iLink 长轮询、扫码登录、媒体发送/下载和私聊处理。
- `channel/weixin/weixin_message.py` 明确设置 `is_group = False`，因此不能直接满足微信群聊。

BaiLongmaPro 的微信群助手主要集中在 `src/social/`：

- `wechaty-duty-group.js`：Wechaty 连接、扫码登录、群列表、已选群路由、@ 触发、文本/文件/图片发送、离线二维码通知和 worker 状态。
- `wechat-groups.js`：微信群外部 ID、唤醒规则、最近群消息归档和群提示词构造。
- `wechat-group-memory.js`：群消息、群记忆条目、群友永久记忆和记忆上下文召回。
- `wechat-group-stats.js`：本地群活跃记录、成员名称、群统计、记录导出/导入和战报发送标记。
- `wechat-command-guard.js`：微信群入口安全守卫。
- `wechat-file-reply.js`：按明确格式要求生成附件回复。
- `wechat-image-vision.js`、`wechat-video-analysis-skill.js`、战报与备份模块：属于更重的媒体理解、摘要、备份和 UI 支撑能力。

已通过 Context7 对 Wechaty 当前文档做最小核验。Wechaty 仍以 `scan`、`login`、`message` 事件为核心，群发消息使用 `room.say()` 或 `message.say()`，媒体发送使用 `FileBox`。

## 3. 推荐迁移路线

采用“Node.js Wechaty 侧车进程 + Python CowAgent 渠道适配器”。

理由：

- BaiLongmaPro 当前微信群实现实际依赖 Node/npm 生态，包括 `wechaty`、`wechaty-puppet-wechat4u`、`file-box`、`qrcode` 等。
- 该路线能最大化复用 BaiLongmaPro 已验证的 Wechaty 行为。
- CowAgent 保持 Python 主体，只需要把 Wechaty 消息适配为现有渠道消息。
- Python Wechaty 可作为后续预研选项，但首轮不优先采用，避免引入 Puppet Service Token / gRPC 服务等额外不确定性。

职责边界：

- Node 侧车：扫码、登录态、群列表、群消息监听、媒体下载/发送、room/contact 元数据。
- Python 渠道：侧车进程管理、消息去重、`ChatMessage` 转换、群白名单、上下文构造、回复发送、安全拦截。
- CowAgent 核心：模型回复、Agent、工具、图像理解、图像生成、语音识别、语音合成、长期记忆召回。

## 4. 首轮核心能力

### 4.1 微信群通道闭环

状态：已完成 4.1 首轮闭环。当前实现包含扫码登录、状态/二维码接口、群列表刷新、目标群 room ID 与群名兜底选择、@ 触发、真实发送人身份保留、回复发回原群并携带 mention 元数据、消息去重、自发消息过滤、人设预设/自定义保存与 `<wechat-group-persona>` 注入。管理员配置/诊断类请求会跳过普通人设注入，但仍不绕过程序安全边界。后续 4.2 及之后的最近上下文、群记忆、安全守卫完整实现仍按后续阶段推进。

1. 扫码登录与连接状态
   - 启动、停止和重新登录 Wechaty 侧车。
   - 登录态持久化到仓库外的数据目录，避免写入 Git 跟踪内容。
   - 暴露状态：`idle`、`starting`、`qr_ready`、`logged_in`、`connected`、`error`。

2. 群列表发现与目标群选择
   - 获取当前微信号加入的群列表。
   - 支持按稳定 room ID 配置目标群，同时保留群名兜底。
   - 兼容 CowAgent 现有 `group_name_white_list` 行为。

3. 群内触发规则
   - 默认支持 @ 机器人触发回复。
   - 兼容 CowAgent 现有 `group_chat_prefix`、`group_chat_keyword`。
   - 非 @ 主动接话首轮默认关闭，后续在防刷屏和安全策略稳定后再启用。

4. 真实身份与回复目标
   - 保留真实发送人身份：`actual_user_id`、`actual_user_nickname`、`at_list`。
   - 回复必须发回同一个微信群。
   - 尽可能通过 Wechaty `Contact` @ 真实发送人，而不是只拼接昵称文本。
   - 不允许模型输出改变本轮要 @ 的目标成员。

5. 重复消息与自发消息过滤
   - 按消息 ID 去重。
   - 默认跳过机器人自己发送的消息，除非 CowAgent 现有配置显式允许自触发。

6. 人设设定与生效规则
   - 参考 BaiLongmaPro 微信群助手的 `personaPrompt` / `personaPresetId` 设计，在 CowAgent 微信群通道中支持“预设人设 + 自定义人设”的最小闭环。
   - 首轮内置 3 个人设预设：`owner-digital-twin`（主人数字分身）、`tech-duty`（技术值班助手）、`social-fun`（幽默社交助手）。预设只作为默认提示词模板，不引入 BaiLongmaPro 的旧 UI、网页微信 DOM 或独立 Agent 流程。
   - 配置层保存当前生效的 `wechat_group_persona_prompt` 和 `wechat_group_persona_preset_id`；当提示词与任一内置预设完全匹配时使用对应 preset ID，否则标记为 `custom`。
   - 自定义人设提示词用于约束微信群回复的身份、语气、风格、回复长度和边界，最大长度建议限制为 6000 字符，保存时做换行归一化和首尾空白裁剪。
   - 人设只影响微信群回复风格，不得绕过安全守卫、管理员权限校验、群白名单、目标群限制、回复目标锁定和记忆隔离。
   - 普通群友不能通过群消息修改长期人设；修改人设只能来自本地控制台/桌面 UI，或后续明确设计的已验证管理员配置入口。
   - 进入提示词时使用独立块，例如 `<wechat-group-persona>...</wechat-group-persona>`，并放在群最近上下文和群记忆之前，作为风格约束而不是事实来源。
   - 已验证管理员发出的配置/诊断类请求可以临时降低普通人设优先级，避免人设覆盖管理员意图；但管理员请求仍不能绕过程序实际权限和高风险安全边界。

### 4.2 当前群最近上下文

状态：已完成 4.2 最小闭环。当前实现新增微信群专用 SQLite 归档与最近上下文格式化服务，按 `room_id` 隔离记录入站群消息，并在微信群文本请求进入 CowAgent 回复链路前注入 `<recent-wechat-group-transcript>`。注入窗口受 `wechat_group_recent_context_enabled`、`wechat_group_recent_context_limit`、`wechat_group_recent_context_minutes` 控制；最近上下文只作为本轮提示词素材，不写入 CowAgent 全局长期记忆。出站助手回复已进入 `wechat_group_assistant_replies` 表，为后续记忆与审计阶段保留基础数据。

架构论证：4.2 的“最近上下文”不是长期记忆，而是微信群通道的短期事件归档与提示词素材。它需要按时间窗口读取当前 `room_id` 的原始聊天流水，写入频率高、语义价值不稳定、生命周期短；如果直接塞进 CowAgent 现有 `MemoryManager`，会把普通闲聊提升为全局/用户/会话记忆，增加 embedding 与检索噪声，并且现有 `shared` / `user` / `session` scope 不能天然表达 `room_id` 和 `room_id + sender_id` 隔离。当前专用归档表的定位是低风险地复用 BaiLongmaPro 的 recent transcript 思路，先保证群隔离、时间窗查询和可审计流水。CowAgent 的长期记忆能力保留到 4.3 通过 `WechatGroupMemoryService` 复用：可以复用 embedding、chunker、FTS 和摘要提取思路，但写入与召回入口必须显式携带 `room_id` / `sender_id`，避免污染 Web、CLI、私聊和 Agent 全局记忆。后续如多渠道都需要作用域记忆，再统一规划 `scope_type + scope_id + channel_type` 的通用记忆模型升级，而不是在 4.2 为最近上下文提前改动全局 schema。

回复前注入当前群最近上下文，让模型知道群里刚刚发生了什么。

设计要求：

- 原始消息按 `room_id` 强隔离。
- 每次只查询当前 `room_id` 最近 N 条消息或最近 M 分钟消息。
- 上下文格式要简洁，包含发送人昵称、消息类型、时间和文本摘要。
- 不把其他群的最近消息注入当前群。
- 最近上下文只作为本轮提示词素材，不等同于永久记忆。

建议默认：

- `wechat_group_recent_context_enabled = true`
- `wechat_group_recent_context_limit = 20`
- `wechat_group_recent_context_minutes = 60`

### 4.3 群永久记忆与群友永久记忆

群记忆是首轮核心能力。经方案确认，4.3 不再把群永久记忆做成微信群专用长期记忆孤岛，而是把 CowAgent 原本记忆升级为“通用作用域记忆”，让群记忆、群友记忆进入统一记忆管理体系，同时通过 `room_id` / `sender_id` 作用域约束保证隔离。

阶段一不直接把微信群消息塞进现有 `shared` / `user` / `session` 语义里，也不使用独立微信群长期记忆表绕开 CowAgent 记忆系统。推荐做法是对 `agent/memory/storage.py` 的 `chunks` 表做兼容扩展：保留旧字段与旧调用路径，同时新增 `scope_type`、`scope_id`、`channel_type`、`subject_id` 等 nullable 字段。旧记忆继续按原行为运行；微信群 4.3 通过新的作用域字段进入统一 `MemoryManager`，并由 `WechatGroupMemoryService` 做强校验和提示词装配适配。

记忆分层：

1. 原始群消息归档
   - 保存群 ID、群名、发送人 ID、发送人昵称、消息类型、规范化文本、原始元数据、是否 @ 机器人和时间戳。
   - 只允许按当前 `room_id` 查询。
   - 原始闲聊不直接写入长期记忆。

2. 群永久记忆
   - 保存当前群长期稳定信息，例如群规、群偏好、长期项目、共同背景、群内约定。
   - 统一记忆作用域：`scope_type = wechat_group`，`scope_id = room_id`，`channel_type = wechat_group`。
   - 只在当前群回复中召回。

3. 群友永久记忆
   - 保存某个群内成员的长期事实、偏好和身份信息。
   - 统一记忆作用域：`scope_type = wechat_group_member`，`scope_id = room_id`，`subject_id = sender_id`，`channel_type = wechat_group`。
   - 同一个 sender ID 出现在不同群时，默认视为不同记忆空间，除非后续做明确身份合并。

4. 与 CowAgent 全局记忆的关系
   - 微信群长期记忆写入 CowAgent 统一记忆索引，但必须携带明确作用域。
   - `WechatGroupMemoryService` 只作为微信群通道适配层：负责校验 `room_id` / `sender_id`、组装作用域、调用通用 `MemoryManager`、生成 `<wechat-group-memory>`。
   - embedding provider、chunker、FTS、向量检索和后续统一记忆管理能力复用 CowAgent 原本组件。
   - 只有用户或管理员明确要求“写入全局记忆”的稳定知识，才允许提升到 CowAgent 通用 `MemoryManager`。
   - 旧 `shared` / `user` / `session` 调用方必须保持兼容，不能因为新增作用域字段影响 Web、CLI、私聊和 Agent 既有记忆行为。

通用作用域映射：

```text
旧 shared memory:
scope_type = shared
scope_id = ""
channel_type = ""
subject_id = ""

旧 user memory:
scope_type = user
scope_id = user_id
channel_type = ""
subject_id = user_id

旧 session memory:
scope_type = session
scope_id = session_id
channel_type = ""
subject_id = user_id 或空

微信群群永久记忆:
scope_type = wechat_group
scope_id = room_id
channel_type = wechat_group
subject_id = ""

微信群群友永久记忆:
scope_type = wechat_group_member
scope_id = room_id
channel_type = wechat_group
subject_id = sender_id
```

召回顺序：

```text
当前群最近消息
→ 当前群群永久记忆
→ 当前群当前发言人的群友记忆
→ 当前群被 @ / 被提到成员的群友记忆
→ CowAgent 全局 shared memory
```

安全原则：

- 任何群记忆召回都必须带 `room_id`。
- 群友记忆必须带 `room_id + sender_id`。
- 不允许把 A 群的人设、隐私、聊天结论带到 B 群。
- 全局 shared memory 只能作为通用背景，不允许反向泄露其他群信息。

首轮实现边界：

- 先实现“手动写入 + 隔离召回 + 上下文注入 + 最小 UI 运维”，不默认开启自动提取。
- `wechat_group_memory_auto_extract` 首轮继续默认关闭；即使配置打开，也必须只从当前 `room_id` 的最近消息窗口提取，并保留 `source_message_ids`，不得把普通闲聊直接提升为长期记忆。
- 手动写入采用明确语义入口：
  - 群永久记忆：管理员在 UI 中选择目标群后写入，或后续通过群内管理命令写入。
  - 群友永久记忆：管理员在 UI 中选择目标群和成员后写入；普通成员自助写入只允许落到“当前群 + 自己 sender_id”空间。
- 召回上下文使用独立 `<wechat-group-memory>` 块，和 `<wechat-group-persona>`、`<recent-wechat-group-transcript>` 分开，避免模型把人设、短期聊天和长期事实混为一类。
- 群记忆 UI 只做运维型能力：开关状态、按群/群友分类展示、手动新增、列表/搜索、停用、来源查看和诊断预览；不做完整社交工作台、批量导入、跨群身份合并、记忆自动提取审核流或可视化战报。

建议注入顺序：

```text
<wechat-group-persona>
...
</wechat-group-persona>

<recent-wechat-group-transcript>
...
</recent-wechat-group-transcript>

<wechat-group-memory>
[group_memory] ...
[member_memory sender_id="..."] ...
</wechat-group-memory>

用户本轮真实问题
```

`<wechat-group-memory>` 最多注入当前群命中的群记忆、当前发言人的群友记忆和被 @ / 被明确提到成员的群友记忆。每条必须带来源类型，内部检索结果必须先按 `room_id` / `room_id + sender_id` 过滤，再排序。

### 4.4 多模态能力

首轮需要支持文本、图片理解、图片生成、语音识别和语音合成，但实现上应复用 CowAgent 现有能力。

1. 文本回复
   - 群消息映射为 `ContextType.TEXT`。
   - 回复使用 `ReplyType.TEXT`，超长文本按微信发送限制拆分。

2. 图像理解
   - Wechaty 下载图片到 CowAgent 工作区临时目录。
   - 消息映射为 `ContextType.IMAGE`，或文本消息附带图片路径引用。
   - 优先复用 CowAgent 现有图片理解链路，不在微信群通道里单独调用视觉模型。

3. 图像生成
   - 命中现有 `image_create_prefix` 或 CowAgent 现有图像生成路由时，使用 `ContextType.IMAGE_CREATE`。
   - 生成结果通过 Wechaty `FileBox` 或图片 URL 发送到当前群。

4. 语音识别
   - Wechaty 下载语音文件到临时目录。
   - 映射为 `ContextType.VOICE`，复用 CowAgent 现有 voice-to-text 流程。

5. 语音合成
   - 当上下文要求语音回复或配置开启语音回复时，复用 CowAgent text-to-speech。
   - 如果微信原生语音发送不稳定，首轮以音频文件附件形式发送。

6. 文件/视频基础处理
   - 文件和视频先作为 `ContextType.FILE` 处理。
   - 视频理解不进入首轮必交付，只保留文件传输和提示能力。

### 4.5 安全守卫

微信群入口必须有前置安全守卫。

首轮迁移 `wechat-command-guard.js` 的核心高风险分类：

- 读取/列出本机文件。
- 读取密钥、token、cookie、环境变量、登录态。
- 执行 Shell、脚本、代码或安装依赖。
- 控制浏览器、桌面、摄像头、麦克风、屏幕。
- 支付、转账、下单、金融交易。
- 群管理操作，例如踢人、拉人、改群名、群发刷屏。
- 破坏性 Git / 文件操作。
- 绕过安全规则或冒充管理员。

规则：

- 只对微信群来源生效。
- 在模型和工具执行前拦截。
- 普通群成员不允许绕过。
- 管理员身份只基于精确 sender ID，不接受昵称、自称或模型推断。

## 5. 首轮暂缓迁移的功能

以下能力暂不进入首轮：

- 完整 Brain UI 社交指挥中心。
- 群备份/导入中心。
- 群统计战报和海报渲染。
- 图片视觉库、图片标签和图库召回。
- 视频解析 Skill。
- 表情包搜索和公开图片搜索。
- ClawBot 私聊控制通道。
- 企业微信应用离线二维码通知。
- 非 @ 主动接话默认开启。

这些能力有价值，但会显著扩大依赖面和验证成本，建议在核心微信群通道、记忆隔离和多模态基础能力稳定后逐项迁移。

## 6. 文件级开发计划

### 任务一：定义侧车通信协议

新增：

- `channel/wechat_group/README.md`
- `channel/wechat_group/protocol.py`

侧车发给 Python 的事件：

- `status`
- `qr`
- `rooms`
- `message`
- `media_ready`
- `send_result`
- `error`

Python 发给侧车的命令：

- `start`
- `stop`
- `relogin`
- `list_rooms`
- `send_text`
- `send_file`
- `send_image`
- `send_audio`

协议建议使用 stdio JSON Lines；只有确有必要时再考虑 HTTP loopback。stdio 暴露面更小，也更符合本项目安全边界。

### 任务二：新增 Node Wechaty 侧车

新增：

- `channel/wechat_group/sidecar/package.json`
- `channel/wechat_group/sidecar/wechaty-sidecar.mjs`

职责：

- 使用配置的 puppet 初始化 Wechaty。
- 输出二维码、状态、群列表和群消息事件。
- 将 Wechaty 群消息规范化为 CowAgent 可消费的 JSON。
- 下载图片、语音、文件到指定临时目录，并回传本地路径。
- 接收 Python 发送命令。
- 支持文本、图片、文件、音频文件发送。

### 任务三：新增 Python 渠道适配器

新增：

- `channel/wechat_group/wechat_group_channel.py`
- `channel/wechat_group/wechat_group_message.py`
- `channel/wechat_group/wechat_group_client.py`

修改：

- `channel/channel_factory.py`
- `common/const.py`
- `config.py`
- `config-template.json`

职责：

- 启动并监督侧车进程。
- 将侧车消息 JSON 转换为 `ChatMessage`。
- 调用 `_compose_context(..., isgroup=True, msg=...)` 进入 CowAgent 群聊链路。
- 复用 CowAgent 现有群白名单、前缀、关键词、会话、插件和回复流水线。
- 将回复通过侧车命令发回微信群。
- 在 `config.py` 和 `config-template.json` 中加入微信群人设配置项：`wechat_group_persona_prompt`、`wechat_group_persona_preset_id`。
- 在 Python 配置读取层提供默认人设与预设解析，保存配置时对 prompt 做长度限制、换行归一化和空白裁剪。

### 任务四：新增群归档与最近上下文服务

新增：

- `channel/wechat_group/wechat_group_archive.py`
- `channel/wechat_group/wechat_group_context.py`

职责：

- 懒加载创建 SQLite schema。
- 记录群内入站消息和助手回复。
- 支持按 `room_id` 查询最近消息。
- 生成可注入提示词的最近上下文摘要。
- 媒体路径相对配置的数据目录或工作区保存。

建议表：

- `wechat_group_messages`
- `wechat_group_assistant_replies`

### 任务五：升级通用作用域记忆并新增微信群记忆适配层

修改：

- `agent/memory/storage.py`
- `agent/memory/manager.py`
- `agent/memory/service.py`
- `agent/memory/config.py`

新增：

- `agent/memory/scope.py`
- `channel/wechat_group/wechat_group_memory.py`

职责：

- 将 CowAgent 原本记忆升级为通用作用域记忆，支持 `shared` / `user` / `session` / `wechat_group` / `wechat_group_member`。
- 保持旧 `scope` / `user_id` 调用兼容，旧调用方不需要一次性改造。
- `WechatGroupMemoryService` 管理群永久记忆和群友永久记忆的通道适配。
- 强制所有查询携带 `room_id`。
- 群友记忆强制使用 `room_id + sender_id`。
- 支持手动写入、自动提取、检索召回和删除/停用。
- 复用 CowAgent embedding provider、文本切分、摘要提取、FTS 和向量检索能力，但不能把群记忆写入全局 shared memory。
- 原始群消息仍保留在 `wechat_group_messages`，不进入长期记忆，除非通过明确手动写入或后续受控自动提取。

建议 schema 兼容扩展：

- `chunks` 新增 nullable 字段：
  - `scope_type TEXT`
  - `scope_id TEXT`
  - `channel_type TEXT`
  - `subject_id TEXT`
  - `status TEXT NOT NULL DEFAULT 'active'`
  - `source_message_ids TEXT`
- 迁移脚本或初始化迁移逻辑必须把旧数据映射到新字段：
  - `scope = shared` -> `scope_type = shared`
  - `scope = user` -> `scope_type = user`，`scope_id = user_id`，`subject_id = user_id`
  - `scope = session` -> `scope_type = session`
- 旧字段 `scope`、`user_id` 暂不删除，所有旧 API 继续可读可写。

建议索引：

- `chunks(scope_type, scope_id, channel_type, status, updated_at)`。
- `chunks(scope_type, scope_id, subject_id, channel_type, status, updated_at)`。
- 保留原有 `idx_chunks_user`、`idx_chunks_scope`、FTS 和 trigram FTS 索引。

可选辅助表：

- `wechat_group_member_identities`：只记录 `room_id`、`sender_id`、`current_nickname`、`alias_names`、`last_seen_at`、`created_at`、`updated_at`，用于 UI 显示昵称变化和成员选择，不承载长期记忆正文。
- `wechat_group_member_identities(room_id, sender_id)` 唯一索引。

写入策略：

- 原始群消息先进入 `wechat_group_messages`，不自动等同为长期记忆。
- 管理员或明确指令写入的稳定事实可以直接进入群记忆或群友记忆。
- `wechat_group_memory_auto_extract` 首轮默认关闭；后续开启时也只能从当前 `room_id` 的消息窗口中提取，并保留来源消息 ID。
- 群友记忆必须落在“当前群 + 当前成员”空间内，不按昵称合并，不跨群合并。
- UI 写入必须经过字段校验：`room_id` 必填；群友记忆还要求 `sender_id` 必填；`content` 去除首尾空白后不能为空，首轮建议限制在 1000 字以内。
- 所有删除操作首轮采用软删除/停用：把 `status` 更新为 `disabled`，不物理删除原始记录，方便审计和回滚。

召回策略：

- 群记忆检索必须传入 `room_id`。
- 群友记忆检索必须传入 `room_id + sender_id`。
- embedding 相似度、关键词匹配和时间衰减可以组合使用，但 SQL 查询必须先按 `scope_type`、`scope_id`、`channel_type`、`subject_id` 和 `status` 过滤，再执行相关性排序。
- 返回给提示词装配层的每条记忆必须标注来源类型：`group_memory` 或 `member_memory`。
- embedding provider 不可用时必须降级到 FTS/LIKE 关键词检索；不能因为 embedding 初始化失败阻断微信群正常回复。
- 召回默认条数保持保守：群记忆最多 5 条，当前发言人群友记忆最多 5 条，被提到成员群友记忆最多 3 条。

建议服务接口：

- `add_group_memory(room_id, room_name, content, source_message_ids=None, created_by="ui")`
- `add_member_memory(room_id, sender_id, sender_nickname, content, source_message_ids=None, created_by="ui")`
- `search_group_memories(room_id, query, limit=5)`
- `search_member_memories(room_id, sender_id, query, limit=5)`
- `list_group_memories(room_id, status="active", limit=50, offset=0)`
- `list_member_memories(room_id, sender_id=None, status="active", limit=50, offset=0)`
- `disable_memory(memory_type, memory_id, room_id, sender_id=None)`
- `preview_prompt_memories(room_id, sender_id, query, mentioned_sender_ids=None)`

建议通用记忆接口：

- `MemoryScope(scope_type, scope_id="", channel_type="", subject_id="")`
- `MemoryManager.add_text(text, memory_scope, metadata=None)`
- `MemoryManager.search(query, memory_scope, limit=10)`
- `MemoryManager.list_by_scope(memory_scope, status="active", limit=50, offset=0)`
- `MemoryManager.disable(chunk_id, memory_scope)`

### 任务六：新增微信群提示词上下文装配

新增：

- `channel/wechat_group/wechat_group_prompt.py`

职责：

- 把微信群人设、最近群消息、群永久记忆、当前发言人记忆、被提到成员记忆拼成紧凑上下文。
- 将当前生效人设作为独立 `<wechat-group-persona>` 块注入，只影响回复风格和边界，不作为群事实或记忆证据。
- 当本轮请求来自已验证管理员且属于配置/诊断语义时，可以跳过或降低普通人设块优先级，避免人设覆盖管理员意图。
- 控制 token 长度和条数。
- 标明每段上下文来源，避免模型把其他群信息当作当前群事实。
- 在进入 CowAgent 现有回复链路前追加到当前用户消息或 context metadata。
- 在 `WechatGroupChannel._compose_context()` 中按顺序追加人设、最近上下文和长期记忆块；当前实现已有前两者，4.3 只补充长期记忆块和统一装配帮助函数，不改 Agent 主链路。
- 当 `wechat_group_memory_enabled` 与 `wechat_group_member_memory_enabled` 都关闭时，不生成 `<wechat-group-memory>`。
- 当长期记忆检索失败时记录 warning 并继续原回复链路，不能因为记忆服务异常导致群消息不可回复。
- 建议长期记忆块格式：

```text
<wechat-group-memory>
[group_memory] 群规：工作日不刷屏。
[member_memory sender_id="wxid_alice" nickname="Alice"] Alice 偏好简短结论。
</wechat-group-memory>
```

### 任务七：新增多模态适配

修改：

- `channel/wechat_group/wechat_group_message.py`
- `channel/wechat_group/wechat_group_channel.py`
- `channel/wechat_group/wechat_group_client.py`

职责：

- 图片消息映射为 `ContextType.IMAGE` 或文本附带图片路径。
- 图像生成请求映射为 `ContextType.IMAGE_CREATE`。
- 语音消息映射为 `ContextType.VOICE`。
- 文件/视频消息映射为 `ContextType.FILE`。
- 回复中的图片、文件、音频通过侧车发送。

### 任务八：新增安全守卫

新增：

- `channel/wechat_group/wechat_group_guard.py`

修改：

- `channel/wechat_group/wechat_group_channel.py`

职责：

- 用 Python 实现 BaiLongmaPro 高风险规则的核心版本。
- 命中风险时返回普通文本拒绝，不进入模型和工具执行。
- 支持管理员 sender ID 精确匹配。
- 支持屏蔽成员 sender ID。

### 任务九：新增最小 UI 与配置

修改或新增：

- `desktop/src/renderer/src/pages/ChannelsPage.tsx` 或设置页相关子页。
- `desktop/src/renderer/src/pages/GroupsPage.tsx`
- `desktop/src/renderer/src/api/client.ts`
- `desktop/src/renderer/src/types.ts`
- `desktop/src/renderer/src/i18n.ts`
- 后端渠道管理接口对应字段。
- `channel/web/web_channel.py`
- `channel/web/static/js/console.js`

首轮 UI 只包含：

- 启用/停用微信群机器人。
- 扫码状态和二维码。
- 刷新群列表。
- 选择目标群。
- 保存配置。
- 最近事件和错误提示。
- 安全守卫、管理员 ID、屏蔽 ID 的最小配置入口。
- 微信群人设设定：显示 3 个内置预设卡片、自定义人设文本框、当前生效人设、已生效/有未保存修改状态和“保存人设并生效”按钮。
- 人设设置文案明确说明：点击预设只填入文本，不会立即生效；保存后才写入配置；人设不能绕过安全守卫。
- 群记忆运维入口：放在已有“群聊”管理页中新增“永久记忆”子菜单，不放回通道卡片，避免通道接入页承载过多运维细项。
- 群永久记忆面板：
  - 显示 `wechat_group_memory_enabled` 开关、召回条数说明和当前选中群。
  - 提供“新增群记忆”表单：目标群只允许从已选群列表中选择，正文为多行文本，保存时按钮 loading/disabled。
  - 展示当前群 active 记忆列表：内容摘要、更新时间、来源类型、来源消息 ID、停用按钮。
  - 提供关键词搜索框，查询只调用当前 `room_id`，结果区域显示命中分数或匹配方式。
- 群友永久记忆面板：
  - 显示 `wechat_group_member_memory_enabled` 开关。
  - 先选择目标群，再选择或输入稳定 `sender_id`；昵称只作辅助显示，不作为隔离键。
  - 提供“新增群友记忆”表单和成员记忆列表，停用时二次确认。
  - 明确提示“同一成员在不同群默认是不同记忆空间”。
- 诊断预览：
  - 提供只读“本轮将注入的记忆预览”：输入模拟问题、当前发言人 sender ID、可选被提到 sender IDs，展示 `<wechat-group-memory>` 预览块。
  - 预览接口只读，不触发模型调用，不写入记忆。
- Web 控制台与桌面端保持同一信息架构：基础设置 / 群聊开关 / 人设设定 / 永久记忆。桌面端沿用现有 `GroupsPage.tsx` 左侧子菜单；Web 控制台沿用现有群聊管理页子菜单。
- UI 使用现有语义 token、表单控件和 `lucide-react` 图标；不新增 UI 框架，不使用 emoji 图标。所有按钮要有 loading/disabled 状态，长 `room_id` / `sender_id` 使用 `font-mono`、`truncate` 或 `break-words` 防止撑破布局。
- 后端 API 首轮建议沿用 `/api/channels` 返回 `wechat_group.extra.memory` 作为开关与摘要状态；记忆列表、写入、停用和预览使用独立接口，例如 `/api/wechat-group/memories`，避免把复杂 CRUD 塞进通道配置保存接口。

不做完整富文本记忆编辑器、跨群身份合并 UI、自动提取审核台、战报、图库、备份导入 UI。

### 任务十：新增测试

新增测试文件建议：

- `tests/test_wechat_group_message.py`
- `tests/test_wechat_group_channel.py`
- `tests/test_wechat_group_archive.py`
- `tests/test_wechat_group_context.py`
- `tests/test_wechat_group_persona.py`
- `tests/test_wechat_group_memory.py`
- `tests/test_wechat_group_guard.py`
- `tests/test_wechat_group_multimodal.py`

最低覆盖：

- 群消息能映射到正确 `ChatMessage` 字段。
- @ 机器人消息能触发群上下文。
- 非白名单群会被忽略。
- 最近上下文只返回当前 `room_id`。
- 默认人设能注入 `<wechat-group-persona>`，自定义人设保存后能替换默认人设。
- `wechat_group_persona_preset_id` 能区分内置预设和 `custom`，未保存修改不会被误标记为已生效。
- 已验证管理员的配置/诊断请求不会被普通人设覆盖，但仍会经过安全守卫。
- 群永久记忆只按当前 `room_id` 召回。
- 群友记忆只按 `room_id + sender_id` 召回。
- A 群记忆不会泄漏到 B 群。
- 图片、语音、文件消息能映射到正确 `ContextType`。
- 高风险命令在模型执行前被拒绝。
- 出站回复使用 room ID 和稳定发送人 @ 元数据。
- Web API 能返回微信群记忆开关与摘要状态。
- Web API 写入群记忆时必须校验 `room_id`，写入群友记忆时必须校验 `room_id + sender_id`。
- Web API 查询和停用不得跨 `room_id` 操作。
- 桌面端和 Web 控制台“永久记忆”页能保存开关、写入记忆、搜索当前群记忆、停用记忆，并在加载/失败/空状态下给出明确反馈。

## 7. 建议配置项

新增保守默认值：

```json
{
  "wechat_group_enabled": false,
  "wechat_group_puppet": "wechaty-puppet-wechat4u",
  "wechat_group_sidecar_node": "node",
  "wechat_group_sidecar_memory_path": "",
  "wechat_group_names": [],
  "wechat_group_room_ids": [],
  "wechat_group_ambient_names": [],
  "wechat_group_admin_sender_ids": [],
  "wechat_group_blocked_sender_ids": [],
  "wechat_group_record_messages": true,
  "wechat_group_media_dir": "",
  "wechat_group_guard_enabled": true,
  "wechat_group_sidecar_start_timeout": 60,
  "wechat_group_persona_preset_id": "owner-digital-twin",
  "wechat_group_persona_prompt": "",
  "wechat_group_recent_context_enabled": true,
  "wechat_group_recent_context_limit": 20,
  "wechat_group_recent_context_minutes": 60,
  "wechat_group_memory_enabled": true,
  "wechat_group_member_memory_enabled": true,
  "wechat_group_memory_auto_extract": false,
  "wechat_group_memory_context_limit": 5,
  "wechat_group_member_memory_context_limit": 5,
  "wechat_group_voice_reply_enabled": false
}
```

继续兼容 CowAgent 现有配置：

- `group_name_white_list`
- `group_chat_prefix`
- `group_chat_keyword`
- `group_shared_session`
- `group_chat_in_one_session`
- `nick_name_black_list`
- `image_create_prefix`
- `always_reply_voice`
- `voice_reply_voice`

## 8. 验证计划

首轮实现后运行：

```powershell
python -m unittest tests.test_wechat_group_message
python -m unittest tests.test_wechat_group_channel
python -m unittest tests.test_wechat_group_archive
python -m unittest tests.test_wechat_group_context
python -m unittest tests.test_wechat_group_persona
python -m unittest tests.test_wechat_group_memory
python -m unittest tests.test_wechat_group_guard
python -m unittest tests.test_wechat_group_multimodal
```

涉及桌面 UI 后运行：

```powershell
Set-Location -LiteralPath .\desktop
npm run build
```

交付前运行：

```powershell
python -m unittest discover -s tests
```

需要真实微信登录的手动验证：

- 使用包含 `wechat_group` 的 `channel_type` 启动 CowAgent。
- 扫码登录。
- 确认群列表可获取。
- 只选择一个测试群。
- 非 @ 消息默认不回复。
- @ 机器人，确认回复会结合最近上下文。
- 在 UI 中切换“技术值班助手”预设但不保存，确认状态显示有未保存修改且实际回复仍沿用旧人设。
- 点击“保存人设并生效”后再次 @ 机器人，确认回复风格体现新的人设设定。
- 输入自定义人设并保存，确认配置标记为 `custom`，且人设只影响回复风格，不影响安全拦截和记忆隔离。
- 写入一条当前群群记忆，确认只在当前群召回。
- 写入一条当前群某成员记忆，确认只在该群该成员相关问题中召回。
- 切换到另一个测试群，确认不会召回前一个群的记忆。
- 发送图片，确认能进入图片理解或图片路径上下文。
- 触发图片生成，确认生成图能发回当前群。
- 发送语音，确认能进入语音识别链路。
- 开启语音回复时，确认 TTS 结果能以音频文件或可支持形式发回。
- 停止并重启，确认没有把登录态写入仓库跟踪文件。

## 9. 推荐首轮交付边界

首轮交付包含：

- Node Wechaty 侧车。
- Python `wechat_group` 渠道。
- 扫码登录、群列表、目标群选择。
- @ 触发文本回复。
- 微信群助手人设设定：内置预设、自定义 prompt、当前生效状态和保存后注入。
- 当前群最近上下文注入。
- 群永久记忆和群友永久记忆的基础写入、隔离、召回。
- 文本、图片理解、图片生成、语音识别、语音合成的基础通路。
- 微信群入口安全守卫。
- 最小 UI 运维面板。

首轮不追求：

- 完整社交工作台。
- 精美战报。
- 复杂群记忆管理 UI。
- 复杂人设市场、分群独立人设、群友可在线改人设。
- 图片库检索。
- 视频理解。
- 备份迁移中心。

交付判断标准：

- 能稳定作为 CowAgent 的一个微信群消息通道运行。
- 回复能结合当前群最近上下文。
- 人设设定能通过 UI 保存并注入当前微信群回复，且不能绕过安全守卫。
- 群记忆和群友记忆不会跨群泄漏。
- 多模态请求能复用 CowAgent 现有能力。
- 安全守卫能在模型和工具执行前阻断高风险请求。
