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

群记忆是首轮核心能力，但必须与 CowAgent 全局记忆隔离。

阶段一不建议先大改 `agent/memory/storage.py` 现有 `chunks` 主表，也不把微信群消息直接塞进 CowAgent 通用 `MemoryManager`。原因是现有记忆模型面向 `shared` / `user` / `session`，如果直接扩展为群聊承载层，容易影响 Web、CLI、私聊和 Agent 既有记忆行为。阶段一采用“微信群专用存储 + 复用 CowAgent 记忆能力组件”的方式：数据隔离由微信群专用表保证，embedding、chunker、关键词检索和摘要提取思路可以复用，但所有写入和查询入口必须由 `WechatGroupMemoryService` 管控。

记忆分层：

1. 原始群消息归档
   - 保存群 ID、群名、发送人 ID、发送人昵称、消息类型、规范化文本、原始元数据、是否 @ 机器人和时间戳。
   - 只允许按当前 `room_id` 查询。
   - 原始闲聊不直接写入长期记忆。

2. 群永久记忆
   - 保存当前群长期稳定信息，例如群规、群偏好、长期项目、共同背景、群内约定。
   - 主键隔离维度：`room_id`。
   - 只在当前群回复中召回。

3. 群友永久记忆
   - 保存某个群内成员的长期事实、偏好和身份信息。
   - 主键隔离维度：`room_id + sender_id`。
   - 同一个 sender ID 出现在不同群时，默认视为不同记忆空间，除非后续做明确身份合并。

4. 与 CowAgent 全局记忆的关系
   - 微信群记忆优先由 `WechatGroupMemoryService` 管理。
   - 可以复用 CowAgent 的 embedding provider、chunker、FTS 思路，但存储表和查询接口必须显式携带 `room_id`。
   - 只有用户或管理员明确要求“写入全局记忆”的稳定知识，才允许提升到 CowAgent 通用 `MemoryManager`。
   - 阶段一不改造 `MemoryStorage` 的 `chunks` schema 作为前置条件，避免为了微信群通道牵动所有通用记忆调用方。
   - 后续如果多个渠道都需要作用域记忆，再统一把 CowAgent 记忆模型升级为 `scope_type + scope_id + channel_type`，并提供迁移脚本和兼容层。

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

### 任务五：新增群记忆服务

新增：

- `channel/wechat_group/wechat_group_memory.py`

职责：

- 管理群永久记忆和群友永久记忆。
- 强制所有查询携带 `room_id`。
- 群友记忆强制使用 `room_id + sender_id`。
- 支持手动写入、自动提取、检索召回和删除/停用。
- 可复用 CowAgent embedding provider、文本切分、摘要提取和 FTS 检索思路，但不能直接污染全局 shared memory。
- 阶段一只新增微信群专用 schema，不修改 `agent/memory/storage.py` 的 `chunks` 表作为前置条件。
- 后续需要统一多渠道记忆时，再规划通用 `scope_type + scope_id + channel_type` 记忆模型升级。

建议表：

- `wechat_group_memory_items`
- `wechat_group_member_memory_items`
- `wechat_group_member_identities`

建议字段：

- `wechat_group_memory_items`：`id`、`room_id`、`room_name`、`content`、`summary`、`keywords`、`embedding`、`source_message_ids`、`status`、`created_at`、`updated_at`。
- `wechat_group_member_memory_items`：`id`、`room_id`、`sender_id`、`sender_nickname`、`content`、`summary`、`keywords`、`embedding`、`source_message_ids`、`status`、`created_at`、`updated_at`。
- `wechat_group_member_identities`：`id`、`room_id`、`sender_id`、`current_nickname`、`alias_names`、`last_seen_at`、`created_at`、`updated_at`。

索引要求：

- `wechat_group_memory_items(room_id, status, updated_at)`。
- `wechat_group_member_memory_items(room_id, sender_id, status, updated_at)`。
- `wechat_group_member_identities(room_id, sender_id)` 唯一索引。

写入策略：

- 原始群消息先进入 `wechat_group_messages`，不自动等同为长期记忆。
- 管理员或明确指令写入的稳定事实可以直接进入群记忆或群友记忆。
- `wechat_group_memory_auto_extract` 首轮默认关闭；后续开启时也只能从当前 `room_id` 的消息窗口中提取，并保留来源消息 ID。
- 群友记忆必须落在“当前群 + 当前成员”空间内，不按昵称合并，不跨群合并。

召回策略：

- 群记忆检索必须传入 `room_id`。
- 群友记忆检索必须传入 `room_id + sender_id`。
- embedding 相似度、关键词匹配和时间衰减可以组合使用，但过滤条件必须先执行隔离约束，再执行相关性排序。
- 返回给提示词装配层的每条记忆必须标注来源类型：`group_memory` 或 `member_memory`。

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
- `desktop/src/renderer/src/i18n.ts`
- 后端渠道管理接口对应字段。

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

不做群记忆编辑器、群友记忆编辑器、战报、图库、备份导入 UI。

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
