# CHANGES

## 2026-07-03

### Agent 模式生图请求直连图像生成脚本
- 修复微信群 `@小灯 画个兔子` 在 Agent 模式下没有真正生图的问题：`ContextType.IMAGE_CREATE` 现在会直接调用 `skills/image-generation/scripts/generate.py`，不再依赖 LLM 自行决定是否读取技能并拼接 `bash` 命令。
- 图像生成脚本调用改为 Python `subprocess.run([...])` 参数列表传入 JSON，避免 Windows shell 引号处理导致 `Invalid JSON`。
- 继续只在 `agent=true` 时启用该确定性分支；非 Agent 模式保留原有 Bot 生图路径。
- 扩展 `tests/test_wechat_group_channel.py`，覆盖 Agent 模式生图绕过通用 Agent 文本回复、脚本参数使用 JSON 且不走 shell。
验证记录：
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_image_create_in_agent_mode_uses_deterministic_script_runner tests.test_wechat_group_channel.WechatGroupChannelTest.test_image_create_script_runner_uses_json_argument_without_shell tests.test_wechat_group_channel.WechatGroupChannelTest.test_image_create_success_records_hourly_usage`
- `python -B -c "from pathlib import Path; paths=['channel/channel.py','tests/test_wechat_group_channel.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]; print('syntax ok')"`
- `python -m unittest tests.test_wechat_group_channel tests.test_models_handler tests.test_image_generation_custom_provider`

### 图像生成支持自定义厂商
- 更新 `channel/web/web_channel.py`：图像生成能力下拉框展开 `custom:<id>` 自定义厂商，保存时校验自定义厂商存在、`api_key`、`api_base` 与模型名，并移除已完成路由后的 `router_pending` 状态。
- 更新 `skills/image-generation/scripts/generate.py`：显式选择 `custom:<id>` 时，从 `custom_providers` 读取凭据和默认模型，并复用 OpenAI-compatible `/images/generations` / `/images/edits` 接口。
- 更新 `skills/image-generation/SKILL.md`：将 `SKILL_IMAGE_GENERATION_PROVIDER` 纳入技能可用性判断，避免只配置自定义图像生成厂商时技能被隐藏。
- 扩展 `tests/test_models_handler.py` 并新增 `tests/test_image_generation_custom_provider.py`，覆盖图像生成自定义厂商下拉、保存校验、默认模型回填、运行时请求 URL/Header/Payload 和错误路径。
验证记录：
- `python -m unittest tests.test_models_handler tests.test_image_generation_custom_provider`
- `python -m unittest tests.test_custom_provider tests.test_custom_provider_handlers tests.test_models_handler tests.test_image_generation_custom_provider`
- `python -m py_compile channel\web\web_channel.py skills\image-generation\scripts\generate.py tests\test_models_handler.py tests\test_image_generation_custom_provider.py`
- `git diff --check`

### 微信群图片理解与生图限流
- 新增 `plans/wechat_group_image_multimodal_plan_20260703.md`，记录微信群图片理解、生图限流和 Web 配置方案，并在开发完成后回写实际改动、验证结果和剩余事项。
- 更新 `channel/wechat_group/sidecar/wechaty-sidecar-core.mjs`、`wechaty-sidecar.mjs` 与 sidecar 测试：识别图片消息、规整媒体文件名、下载媒体到外部目录，并向 Python 上报 `message_type` 与 `file_path`。
- 修复真实 wechat4u 链路中文本消息 `MessageType.Text = 7` 被误判为文件的问题，避免普通文本消息触发 `toFileBox()` 并报 `text message no file`。
- 修复“回复引用图片并 @ 机器人识别这张图”的实际群聊链路：直接触发的文本识图请求会优先使用引用消息指向的图片；引用 ID 查不到时按引用发送者匹配当前群最近图片，最后才回退到当前群 10 分钟内最近图片。
- 更新 `channel/wechat_group/wechat_group_channel.py` 与 `wechat_group_archive.py`：直接触发的图片消息复用既有 `Vision` 工具生成视觉摘要并注入 `<wechat-group-image>` 上下文，增加摘要缓存；微信群生图请求按群统计最近 1 小时成功受理次数并超额拒绝。
- 更新 `config.py`、`config-template.json`、`channel/web/web_channel.py` 与 `channel/web/static/js/console.js`：新增图片理解开关、纯图片评论开关、视觉摘要缓存分钟数、生图每小时上限，并在 Web 控制台“群聊 -> 图片与生图”中配置。
- 扩展 `tests/test_wechat_group_channel.py`、`tests/test_wechat_group_web.py` 和 sidecar Node 测试，覆盖图片理解上下文注入、非 @ 图片跳过回复、摘要缓存、生图限流记录、配置保存和媒体路径安全。
验证记录：
- `python -m unittest tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_channel`
- `python -m unittest tests.test_wechat_group_context`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `npm test`（在 `channel/wechat_group/sidecar` 目录）
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_at_text_image_request_uses_recent_group_image`
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_at_text_image_request_prefers_quoted_image`
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_at_text_image_request_uses_quoted_sender_when_quote_id_missing`
- 未执行真实微信群手动验证；仍需扫码登录后在目标群验证 @ 图片评论、生图返回和超额拒绝。

### 微信群引用机器人消息触发
- 新增 `plans/wechat_group_quote_self_trigger_20260703.md`，记录引用机器人消息按被 @ 处理的实现方案、风险与验证结果。
- 更新 `channel/wechat_group/sidecar/wechaty-sidecar-core.mjs` 与 `wechaty-sidecar.mjs`：通过 wechat4u raw `appmsg type=57` 解析 `refermsg.fromusr`，当引用发送者等于当前机器人 ID 时上报 `is_quote_self` 和引用摘要。
- 更新 `channel/wechat_group/wechat_group_message.py`、`channel/wechat_group/wechat_group_channel.py` 与 `channel/chat_channel.py`：保存引用元数据，并将引用机器人消息纳入微信群直接回复链路，同时保留普通引用消息跳过逻辑。
- 扩展 `channel/wechat_group/sidecar/wechaty-sidecar-core.test.mjs`、`tests/test_wechat_group_message.py` 和 `tests/test_wechat_group_channel.py`，覆盖引用机器人、引用他人、引用文本过滤绕过和自由回复绕过场景。
验证记录：
- `node --test .\wechaty-sidecar-core.test.mjs`
- `node --check .\wechaty-sidecar.mjs`
- `node --check .\wechaty-sidecar-core.mjs`
- `python -m py_compile channel\chat_channel.py channel\wechat_group\wechat_group_message.py channel\wechat_group\wechat_group_channel.py`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- 未执行真实微信群手动验证；仍需扫码登录后在目标群引用机器人消息确认真实链路。

## 2026-07-03

### 同步上游 master 更新
- 新增 `upstream = git@github.com:zhayujie/CowAgent.git` 远端并合并 `upstream/master` 的 6 个提交。
- 吸收上游 Claude 默认模型更新：新增 `claude-sonnet-5` 常量，更新 Claude 推荐模型、视觉工具默认候选、Web 控制台模型列表及多语言模型文档。
- 吸收桌面端更新：新增 macOS 签名/公证相关 `desktop/electron-builder.js`、`desktop/build/entitlements.mac.plist`、静态资源类型声明和桌面端品牌 logo；保留本 fork 的微信群、记忆、搜索与日志改动。
- 新增 `plans/upstream_sync_20260703.md` 记录本次同步分析、执行步骤与验证结果。
验证记录：
- `npm run build`（在 `desktop/` 目录）
- `python -m unittest tests.test_models_handler tests.test_web_search_providers tests.test_chat_gpt_logging`
- `python -m unittest tests.test_security_ssrf_web_fetch`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `python -m py_compile common\const.py channel\web\web_channel.py agent\tools\vision\vision.py models\claudeapi\claude_api_bot.py models\chatgpt\chat_gpt_bot.py`
- `git diff --check`
- 全量 `python -m unittest discover -s tests` 未通过：291 个测试中失败 5、错误 5；失败项为合并前已存在的测试环境/历史断言问题，包括缺少 `pytest`、Windows 默认 GBK 读取 UTF-8 文件、Qianfan 文档断言、Web console cache buster 旧断言，以及测试导入顺序导致的 `requests` stub 污染。

### ChatGPT query 日志摘要精简
- 更新 `models/chatgpt/chat_gpt_bot.py`：将 `[CHATGPT] query=` 从完整打印用户输入改为单行摘要；对微信群自由回复 LLM 判定 prompt 仅记录 `room`、`sender`、`text`、本地得分、阈值、原因、字符数和行数，避免整段判定器说明刷屏。
- 新增 `tests/test_chat_gpt_logging.py`：覆盖自由回复判定 prompt 不泄露完整说明文本，并保留普通短 query 原样打印。
验证记录：
- `python -B -m unittest tests.test_chat_gpt_logging tests.test_wechat_group_free_reply_judge`
- `python -B -c "from pathlib import Path; paths=['models/chatgpt/chat_gpt_bot.py','tests/test_chat_gpt_logging.py']; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in paths]; print('syntax ok')"`
- `git diff --check`

### 联网搜索支持 Serper 与 Jina
- 更新 `agent/tools/web_search/web_search.py`：新增 `serper` 与 `jina` 搜索 Provider，分别读取 `tools.web_search.serper_api_key` / `SERPER_API_KEY` 与 `tools.web_search.jina_api_key` / `JINA_API_KEY`，并按统一结果格式返回标题、链接和摘要。
- 更新 `channel/web/web_channel.py` 与 `channel/web/static/js/console.js`：在「模型管理 -> 联网搜索 -> 添加厂商」中加入 Serper、Jina；Bocha/Serper/Jina 复用搜索专用 API Key 弹窗，并在弹窗中展示对应申请链接。
- 更新 `config.py`、`config-template.json` 与 `docs/*/tools/web-search.mdx`：补充 `tools.web_search` 默认结构、Serper/Jina 配置键、申请入口和自动路由顺序说明。
- 新增 `tests/test_web_search_providers.py` 并扩展 `tests/test_models_handler.py`：覆盖 Serper/Jina Provider 识别、专用凭证保存、Serper 请求归一化和 Jina 文本结果解析。

验证记录：
- `python -m unittest tests.test_models_handler tests.test_web_search_providers`
- `node --check D:\JiangShuai\SourceCode\CowAgent\channel\web\static\js\console.js`
- `python -m py_compile agent\tools\web_search\web_search.py channel\web\web_channel.py config.py tests\test_models_handler.py tests\test_web_search_providers.py`
- `python -m json.tool config-template.json`

### 微信群自由回复评分与发送链路修复
- 参考 `BaiLongmaPro/src/social/wechat-ambient-reply.js` 的接话评分思路，扩展 `channel/wechat_group/wechat_group_free_reply.py`：普通群问题支持“哪里/啥意思/能不能/看看”等口语问法，结合当前群近期消息补充 `unanswered_question` 加分；低信息闲聊和梗类文本按更接近群聊语境的规则判断。
- 修复 XML / 表情 / 图片原始 payload 因包含 `?` 被误判为群问题的问题，新增 `media_payload` 抑制，避免非文本内容误入自由回复 LLM 复核。
- 更新 `channel/wechat_group/wechat_group_channel.py` 与 `channel/chat_channel.py`：自由回复本地评分时读取当前群最近消息；LLM 复核通过后用 `wechat_group_force_reply` 绕过通用群聊非 @ 过滤，确保进入最终 LLM 回复与微信群发送链路，同时仍保留自由回复不 mention 发送者的行为。
- 更新 `channel/web/static/js/console.js`：切换自由回复活跃档位时同步刷新阈值、间隔和上限输入框，避免把 normal 档参数误保存到 active/crazy 等档位。
- 扩展 `tests/test_wechat_group_free_reply.py`、`tests/test_wechat_group_channel.py`、`tests/test_wechat_group_web.py`：覆盖口语问法 active 档触发、XML payload 抑制、worker 通过后进入最终回复队列，以及 Web 档位切换同步逻辑。

验证记录：
- `python -m unittest tests.test_wechat_group_free_reply tests.test_wechat_group_free_reply_judge tests.test_wechat_group_free_reply_worker tests.test_wechat_group_channel tests.test_wechat_group_web`
- `node --check D:\JiangShuai\SourceCode\CowAgent\channel\web\static\js\console.js`
- `python -m py_compile channel\chat_channel.py channel\wechat_group\wechat_group_free_reply.py channel\wechat_group\wechat_group_channel.py tests\test_wechat_group_free_reply.py tests\test_wechat_group_channel.py tests\test_wechat_group_web.py`

### Agent turn start 日志摘要优化
- 更新 `agent/protocol/agent_stream.py`：Agent 入口日志改为 `[Agent] turn start` 结构化摘要，只展示模型、thinking 状态、真实用户问题预览和微信群增强块规模。
- 微信群增强上下文只记录块类型和统计信息，例如 `wechat_context=persona, recent_transcript, memory`、`recent_transcript_messages`、`recent_transcript_window`、`memory_chars`，不再打印最近群聊逐条内容、人设正文或群记忆正文。
- 扩展 `tests/test_agent_stream_logging.py`：覆盖微信群人设、最近群聊 transcript 和群记忆均不会泄露到入口日志，同时保留用户真实问题预览。

验证记录：
- `python -m unittest tests.test_agent_stream_logging`
- `python -m py_compile agent\protocol\agent_stream.py tests\test_agent_stream_logging.py`

### 微信群与 Agent 请求日志可读性优化
- 更新 `channel/wechat_group/wechat_group_channel.py`：收到微信群消息时记录群名、发送人、消息类型、是否 @ 和截断文本；未 @ 文本进入自由回复判定后记录入队/跳过、得分、阈值、档位、命中原因和抑制原因。
- 更新 `channel/wechat_group/wechat_group_free_reply_worker.py`：自由回复 LLM 复核通过或拒绝时记录置信度、错误码/原因和消息预览，便于定位“为什么接话或沉默”。
- 更新 `agent/protocol/agent_stream.py`：将 LLM 请求摘要压缩为单行，保留 system 来源、历史角色/字数和工具名称，去掉工具 schema 展开，降低日志噪声。
- 扩展 `tests/test_agent_stream_logging.py`、`tests/test_wechat_group_channel.py`、`tests/test_wechat_group_free_reply_worker.py`：覆盖新的 Agent 请求摘要、微信群入站消息日志、自由回复本地判定日志和 LLM 复核拒绝日志。

验证记录：
- `python -m unittest tests.test_agent_stream_logging tests.test_wechat_group_free_reply_worker`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `python -m py_compile agent\protocol\agent_stream.py channel\wechat_group\wechat_group_channel.py channel\wechat_group\wechat_group_free_reply_worker.py tests\test_agent_stream_logging.py tests\test_wechat_group_channel.py tests\test_wechat_group_free_reply_worker.py`

### 微信群回复真实 @ 提问人
- 更新 `channel/wechat_group/sidecar/wechaty-sidecar-core.mjs`：在 wechat4u runtime internals 可用时，优先通过 `webwxsendmsg` 的 `MsgSource.atuserlist` 发送带协议元数据的群聊 @；失败或 internals 不可用时继续降级为可见 `@昵称` 文本，保留原有兼容行为。
- 更新 `channel/wechat_group/sidecar/wechaty-sidecar-core.mjs`：`MsgSource.atuserlist` 允许写入真实群成员 `wxid_...`，不再只接受 `@...` Web 微信 ID，避免实际发言人 ID 被过滤后降级为普通文本。
- 扩展 `channel/wechat_group/sidecar/wechaty-sidecar-core.test.mjs`：覆盖 `sendText` 在 wechat4u runtime 可用时不再只调用 `room.say('@昵称 文本')`，而是写入 `MsgSource.atuserlist`；同时覆盖 `wxid_...` 成员 ID 的真实 @ 元数据。

验证记录：
- `node --test .\wechaty-sidecar-core.test.mjs`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`

### web_fetch 代理配置透传
- 更新 `agent/tools/web_fetch/web_fetch.py`：`web_fetch` 请求优先读取 `tools.web_fetch.proxy`，未配置时复用全局 `proxy`，并将代理透传给 `requests.get`；未配置代理时保留 `requests` 默认环境变量代理行为。
- 扩展 `tests/test_security_ssrf_web_fetch.py`：覆盖工具专用代理和全局代理都会传入请求，同时保留 SSRF 跳转校验路径。

验证记录：
- `python -m unittest tests.test_security_ssrf_web_fetch.TestWebFetchProxy`
- `python -m unittest tests.test_security_ssrf_web_fetch`

### 微信群群友画像向量检索
- 更新 `agent/memory/manager.py`：修复混合检索合并结果时丢失 `id`、`scope_type`、`scope_id`、`channel_type`、`subject_id`、metadata 和来源消息的问题，保证向量命中后的作用域信息可继续用于安全过滤。
- 更新 `agent/memory/scope.py` 与 `agent/memory/storage.py`：新增当前微信群所有群友画像的作用域检索能力，允许按 `room_id` 强过滤后跨 `subject_id` 做语义召回，不放宽跨群边界。
- 更新 `channel/wechat_group/wechat_group_memory.py`：群友画像在无明确 @ 且昵称/别名不命中时，按当前群画像执行向量/关键词混合检索并注入 `matched_by="semantic"`；若昵称/别名存在歧义则保持不注入，避免误选成员。
- 更新 `channel/wechat_group/wechat_group_memory_tools.py`：`wechat_group_profile_get` 增加 `query`、`max_results`、`min_score` 参数，支持 Agent 在当前群内按自然语言搜索群友画像，仍不暴露 `room_id`。
- 扩展 `tests/test_wechat_group_memory.py` 与 `tests/test_wechat_group_memory_tools.py`：覆盖群友画像向量召回、跨群隔离、当前发言人/机器人排除和工具语义搜索。

验证记录：
- `python -m unittest tests.test_wechat_group_memory.WechatGroupMemoryServiceTest.test_preview_uses_vector_search_for_related_member_profile tests.test_wechat_group_memory_tools.WechatGroupMemoryToolsTest.test_profile_get_tool_can_vector_search_current_room_profiles`
- `python -m unittest tests.test_wechat_group_memory tests.test_wechat_group_memory_tools tests.test_wechat_group_channel`
- `python -m unittest tests.test_memory_scope tests.test_wechat_group_context tests.test_wechat_group_agent_bridge_tools tests.test_wechat_group_web`
- `python -m py_compile agent\memory\scope.py agent\memory\storage.py agent\memory\manager.py channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_memory_tools.py channel\wechat_group\wechat_group_channel.py tests\test_wechat_group_memory.py tests\test_wechat_group_memory_tools.py`

### 浏览器工具缺失 Playwright 依赖提示
- 更新 `agent/tools/browser/browser_service.py`：在启动 Playwright 前显式检查依赖是否可用，缺少 `playwright` 时返回明确安装提示，避免报 `sync_playwright` 未定义。
- 新增 `tests/test_browser_service_dependency.py`：覆盖缺少 Playwright 时浏览器服务应给出可执行安装指引。

验证记录：
- `python -m unittest tests.test_browser_service_dependency`
- `python -m unittest tests.test_security_ssrf_browser_navigate`

### 微信群记忆复用向量供应商
- 更新 `channel/wechat_group/wechat_group_memory.py`：新增微信群记忆服务创建函数，创建 `MemoryManager` 时复用全局 `create_default_embedding_provider()`，避免已配置向量供应商时仍降级为关键词检索。
- 更新 `channel/wechat_group/wechat_group_channel.py` 与 `channel/web/web_channel.py`：微信群运行时上下文注入和 Web 群记忆管理入口统一使用上述服务创建函数，不再直接裸创建 `MemoryManager()`。
- 扩展 `tests/test_wechat_group_channel.py` 与 `tests/test_wechat_group_web.py`：覆盖两条懒加载入口会把配置解析出的 embedding provider 传入 `MemoryManager`。

验证记录：
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_memory_service_uses_configured_embedding_provider tests.test_wechat_group_web.WechatGroupWebTest.test_wechat_group_memory_service_uses_configured_embedding_provider`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_memory`
- `python -m py_compile channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_channel.py channel\web\web_channel.py tests\test_wechat_group_channel.py tests\test_wechat_group_web.py`

### 微信群定时任务投递复用运行通道
- 更新 `agent/tools/scheduler/integration.py`：调度器投递到 `wechat_group` 时优先复用 `ChannelManager` 中已启动的微信群通道实例，避免新建未 `startup()` 的通道导致 `wechat group sidecar is not started`；其它渠道仍保持原有创建通道逻辑。
- 新增 `tests/test_scheduler_wechat_group_delivery.py`：覆盖 Agent 定时任务结果发送到微信群时必须使用运行中的微信群 sidecar 通道。

验证记录：
- `python -m unittest tests.test_scheduler_wechat_group_delivery`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_scheduler_wechat_group_delivery`
- `python -m unittest tests.test_agent_stream_scheduler_guard tests.test_prompt_scheduler_guidance tests.test_scheduler_ui`

### 微信群自由回复
- 新增 `channel/wechat_group/wechat_group_free_reply.py`、`wechat_group_free_reply_judge.py`、`wechat_group_free_reply_worker.py`：支持自由回复配置归一化、按群范围启用、本地规则评分与强抑制、每群冷却/上限状态、独立 worker 池、TTL 丢弃和轻量 LLM JSON 二次判定。
- 更新 `channel/wechat_group/wechat_group_channel.py`：未 @ 普通文本先进入自由回复本地判定，命中后只入 worker 队列；@ 机器人原必回链路不进入自由回复；worker 判定通过后复用原 `_compose_context()` / `produce()` 回复链路，并默认不真实 mention 发言人。
- 更新 `config.py`、`config-template.json`、`channel/web/web_channel.py`、`channel/web/static/js/console.js` 与 `channel/web/chat.html`：新增自由回复默认配置、Web API 读写与边界归一化、群聊页自由回复配置面板、worker/最近判定展示和脚本缓存版本。
- 新增 `tests/test_wechat_group_free_reply.py`、`tests/test_wechat_group_free_reply_judge.py`、`tests/test_wechat_group_free_reply_worker.py`，并扩展 `tests/test_wechat_group_channel.py`、`tests/test_wechat_group_web.py`：覆盖默认关闭、评分命中/抑制、冷却/上限、JSON 判定、worker 回调/丢弃、通道分流、不 mention 和 Web 配置读写。

验证记录：
- `python -m unittest tests.test_wechat_group_free_reply tests.test_wechat_group_free_reply_judge tests.test_wechat_group_free_reply_worker`
- `python -m unittest tests.test_wechat_group_channel`
- `python -m unittest tests.test_wechat_group_web`
- `node --check .\channel\web\static\js\console.js`
- `python -m unittest tests.test_wechat_group_free_reply tests.test_wechat_group_free_reply_judge tests.test_wechat_group_free_reply_worker tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `python -m py_compile channel\wechat_group\wechat_group_free_reply.py channel\wechat_group\wechat_group_free_reply_judge.py channel\wechat_group\wechat_group_free_reply_worker.py channel\wechat_group\wechat_group_channel.py channel\web\web_channel.py tests\test_wechat_group_free_reply.py tests\test_wechat_group_free_reply_judge.py tests\test_wechat_group_free_reply_worker.py tests\test_wechat_group_channel.py tests\test_wechat_group_web.py`

### 微信群当前群记忆工具
- 新增 `channel/wechat_group/wechat_group_memory_tools.py`：提供 `wechat_group_memory_search` 与 `wechat_group_profile_get` 两个只绑定当前微信群的 Agent 工具，工具参数不暴露 `room_id`，避免模型或用户跨群指定作用域。
- 更新 `channel/wechat_group/wechat_group_channel.py`：在微信群上下文中写入 `wechat_group_room_id`、`wechat_group_sender_id`、`wechat_group_bot_sender_id`，供 AgentBridge 安全创建当前 turn 的 scoped 工具。
- 更新 `bridge/agent_bridge.py`：微信群 turn 临时挂载当前群记忆/画像工具，并追加 scoped memory 使用提示；运行结束后恢复原工具列表和 `extra_system_suffix`，避免污染后续 turn。
- 更新 `agent/prompt/builder.py`：在工具摘要中展示微信群 scoped memory 工具。
- 新增 `tests/test_wechat_group_memory_tools.py`、`tests/test_wechat_group_agent_bridge_tools.py`，并扩展 `tests/test_wechat_group_context.py`：覆盖当前群记忆检索、群友画像读取、工具 schema 不暴露 room、AgentBridge 临时挂载与恢复、真实通道元数据注入。

验证记录：
- `python -m unittest tests.test_wechat_group_memory_tools tests.test_wechat_group_agent_bridge_tools tests.test_wechat_group_context tests.test_wechat_group_memory`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_wechat_group_memory_tools tests.test_wechat_group_agent_bridge_tools tests.test_wechat_group_context tests.test_wechat_group_memory`
- `python -m py_compile channel\wechat_group\wechat_group_memory_tools.py channel\wechat_group\wechat_group_channel.py bridge\agent_bridge.py agent\prompt\builder.py tests\test_wechat_group_memory_tools.py tests\test_wechat_group_agent_bridge_tools.py tests\test_wechat_group_context.py`
- `git diff --check`

### 微信群群友画像别名匹配
- 更新 `channel/wechat_group/wechat_group_memory.py`：群友画像新增 `aliases` 字段，写入 metadata 和画像正文；运行时画像召回从只匹配 `sender_nickname` 扩展为匹配 `sender_nickname + aliases`，命中别名时注入 `matched_by="alias"`，同别名命中多个 `sender_id` 时跳过注入并返回歧义诊断，保持当前群作用域隔离。
- 更新 `channel/wechat_group/wechat_group_memory_distiller.py`：自动蒸馏候选 schema 支持 `aliases`，自动应用群友画像时保留别名。
- 更新 `channel/web/web_channel.py`、`channel/web/static/js/console.js` 与 `channel/web/chat.html`：Web 控制台群友画像表单增加“别名”字段，保存画像时透传到服务层，画像列表展示已维护别名，并刷新控制台脚本缓存版本。
- 更新 `tests/test_wechat_group_memory.py`、`tests/test_wechat_group_memory_distiller.py`、`tests/test_wechat_group_web.py`、`tests/test_wechat_group_memory_ui.py`：覆盖“大力是谁”通过别名命中群友画像、别名歧义不注入、蒸馏保存别名、Web API 与 UI 入口。

验证记录：
- `python -m unittest tests.test_wechat_group_memory tests.test_wechat_group_memory_distiller tests.test_wechat_group_web tests.test_wechat_group_memory_ui tests.test_wechat_group_message tests.test_wechat_group_channel`
- `node --check .\channel\web\static\js\console.js`
- `python -m py_compile channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_memory_distiller.py channel\web\web_channel.py tests\test_wechat_group_memory.py tests\test_wechat_group_memory_distiller.py tests\test_wechat_group_web.py tests\test_wechat_group_memory_ui.py`

## 2026-07-02

### 微信群运行时群友画像昵称兜底
- 更新 `channel/wechat_group/wechat_group_memory.py`：在真实 `at_list` 过滤后没有群友 ID 时，按当前群 active 群友画像的 `sender_nickname` 做唯一精确兜底；唯一命中时注入 `matched_by="nickname"`，同名歧义时不注入并返回诊断原因。参考 BaiLongmaPro 后修正 `at_list` 为空的真实链路，避免 `message.mentionList()` 未返回成员时跳过昵称画像召回。
- 更新 `tests/test_wechat_group_memory.py`：覆盖“只 @ 机器人但正文包含群友昵称”可注入画像、`at_list` 为空但正文包含群友昵称仍可注入画像，以及同昵称多画像时跳过注入。
- 新增 `plans/wechat_group_runtime_member_profile_lookup_20260702.md`：记录本次运行时昵称兜底方案、BaiLongmaPro 对照结论、边界、验证结果和剩余真实链路手动验证项。

验证记录：
- `python -m unittest tests.test_wechat_group_memory.WechatGroupMemoryServiceTest.test_preview_injects_unique_profile_by_nickname_when_only_bot_is_mentioned tests.test_wechat_group_memory.WechatGroupMemoryServiceTest.test_preview_skips_nickname_profile_when_match_is_ambiguous`
- `python -m unittest tests.test_wechat_group_memory.WechatGroupMemoryServiceTest.test_preview_injects_unique_profile_by_nickname_when_at_list_is_empty`
- `python -m unittest tests.test_wechat_group_memory`
- `python -m unittest tests.test_wechat_group_context`
- `python -m py_compile channel\wechat_group\wechat_group_memory.py tests\test_wechat_group_memory.py`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`

### 微信群群友画像手动录入支持成员检索
- 更新 `channel/wechat_group/wechat_group_archive.py`：新增按当前 `room_id` 检索归档群成员能力，聚合 `sender_id`、昵称、最近发言时间和消息数，并支持按 `sender_id`、昵称及元数据中的微信 ID 字段过滤。
- 更新 `channel/web/web_channel.py`：新增 `/api/wechat-group/memories/members` 查询分支，供 Web 控制台在当前群内检索群友并避免跨群返回成员。
- 更新 `channel/web/static/js/console.js` 与 `channel/web/chat.html`：在群友画像手动表单上方增加“检索群友”输入、结果列表和一键回填 `sender_id` / 昵称；同步更新脚本缓存版本。
- 修复检索结果点击回填：结果项改用 `data-sender-id` / `data-sender-nickname` 保存值，并由点击元素读取，避免内联 `onclick` 参数转义导致不回填。
- 更新 `tests/test_wechat_group_context.py`、`tests/test_wechat_group_web.py`、`tests/test_wechat_group_memory_ui.py`：覆盖归档成员检索、Web API 和 UI 入口。

验证记录：
- `python -m unittest tests.test_wechat_group_context.WechatGroupRecentContextTest.test_archive_lists_members_by_room_and_query`
- `python -m unittest tests.test_wechat_group_web.WechatGroupWebTest.test_wechat_group_memory_members_api_uses_archive`
- `python -m unittest tests.test_wechat_group_memory_ui.WechatGroupMemoryUiTest.test_groups_page_exposes_memory_management_section`
- `python -m unittest tests.test_wechat_group_context tests.test_wechat_group_web tests.test_wechat_group_memory_ui`
- `node --check .\channel\web\static\js\console.js`
- `python -m py_compile channel\wechat_group\wechat_group_archive.py channel\web\web_channel.py tests\test_wechat_group_context.py tests\test_wechat_group_web.py tests\test_wechat_group_memory_ui.py`
- `python -m unittest tests.test_wechat_group_web`
- `python -m py_compile channel\web\web_channel.py`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_context tests.test_wechat_group_web tests.test_wechat_group_memory_ui`
- `python -m unittest tests.test_wechat_group_memory_ui.WechatGroupMemoryUiTest.test_groups_page_exposes_memory_management_section`
- `python -m unittest tests.test_wechat_group_memory_ui`
- `python -m unittest tests.test_wechat_group_context tests.test_wechat_group_web tests.test_wechat_group_memory_ui`
- `python -m py_compile tests\test_wechat_group_memory_ui.py`

## 2026-07-02

### Web 定时任务目标群展示
- 更新 `channel/web/static/js/console.js`：定时任务卡片展示目标群名，使用已有 `action.receiver_name`，不暴露 room ID。
- 更新 `channel/web/chat.html`：刷新 `console.js` 缓存版本，避免浏览器继续使用旧脚本。
- 新增 `tests/test_scheduler_ui.py`，并更新 `tests/test_wechat_group_memory_ui.py` 的脚本版本断言。
验证记录：
- `python -m unittest tests.test_scheduler_ui`
- `python -m unittest tests.test_wechat_group_memory_ui.WechatGroupMemoryUiTest.test_groups_page_cache_buster_changes_for_memory_ui`
- `python -m unittest tests.test_wechat_group_memory_ui`
- `python -m unittest tests.test_scheduler_ui tests.test_wechat_group_memory_ui`
- `node --check .\channel\web\static\js\console.js`

### 定时任务假确认拦截与微信群调度意图标记

- 更新 `agent/protocol/agent_stream.py`：识别定时/提醒/周期任务请求，记录本轮是否成功执行 `scheduler.create`；当模型未成功创建任务却回复“已设置/定好了/会准时”等确认语义时，替换为未创建成功提示，并同步修正会话历史中的最后一条 assistant 文本。
- 更新 `agent/protocol/agent.py`、`bridge/agent_bridge.py`、`agent/chat/service.py`：将当前 `Context` 透传给 `AgentStreamExecutor`，供执行层读取 `intent_requires_scheduler` 等上下文标记。
- 更新 `channel/wechat_group/wechat_group_channel.py`：微信群消息去除 @ 后若匹配定时/提醒/每日播报等调度意图，则设置 `intent_requires_scheduler=True`，避免人设和群聊上下文稀释原始任务。
- 更新 `agent/prompt/builder.py`：当 `scheduler` 工具可用时，在工具调用提示中明确要求定时任务必须调用 `scheduler`，不能只口头确认。
- 新增 `tests/test_agent_stream_scheduler_guard.py`、`tests/test_prompt_scheduler_guidance.py`，并扩展 `tests/test_wechat_group_channel.py`，覆盖假确认拦截、真实 `scheduler.create` 后允许确认、澄清回复不拦截、微信群调度意图标记和 prompt 规则。

验证记录：
- `python -m unittest tests.test_agent_stream_scheduler_guard`
- `python -m unittest tests.test_wechat_group_channel.WechatGroupChannelTest.test_wechat_group_scheduler_request_sets_scheduler_intent`
- `python -m unittest tests.test_prompt_scheduler_guidance`
- `python -m unittest tests.test_agent_stream_scheduler_guard tests.test_prompt_scheduler_guidance tests.test_wechat_group_channel`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`
- `python -m py_compile agent\protocol\agent_stream.py agent\protocol\agent.py agent\chat\service.py bridge\agent_bridge.py channel\wechat_group\wechat_group_channel.py agent\prompt\builder.py tests\test_agent_stream_scheduler_guard.py tests\test_prompt_scheduler_guidance.py tests\test_wechat_group_channel.py`

## 2026-07-02

### Agent 流式工具调用解析错误降级

- 更新 `agent/protocol/agent_stream.py`：当上游 OpenAI-compatible 流式接口在带 tools 请求下返回 `Value looks like object, but can't find closing '}' symbol` / `bad_response_status_code` 这类 400 解析错误时，仅重试一次不带 tools 的请求，避免整轮 Agent 直接失败。
- 更新 `channel/wechat_group/wechat_group_channel.py`：微信群通道将 `ReplyType.INFO` / `ReplyType.ERROR` 按文本消息发送，并沿用真实 `mention_ids` @ 触发用户，避免 Agent 错误回复落入 `unsupported reply type: ERROR`。
- 更新 `tests/test_agent_stream_logging.py` 与 `tests/test_wechat_group_channel.py`：补充上游 object 解析错误无工具降级、微信群错误回复发送的回归测试。

验证记录：
- `python -m unittest tests.test_agent_stream_logging tests.test_wechat_group_channel`
- `python -m py_compile agent\protocol\agent_stream.py channel\wechat_group\wechat_group_channel.py tests\test_agent_stream_logging.py tests\test_wechat_group_channel.py`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web`

### 个人微信群 4.3.7 聊天记录自动蒸馏

- 修复自动生成结果展示：`distill/run` 返回 `disabled` / `failed` 时 Web API 不再包装成成功；前端在没有自动写入和候选时显示 distiller 返回的原因，避免“自动生成已完成但没有任何记忆”的假阳性。
- 补充空候选诊断：当 LLM 返回 `group_memories: []` 且 `member_profiles: []` 时，运行结果会显示 `LLM returned no memory candidates`，便于区分“失败”和“模型认为没有稳定记忆可提取”。
- 修复 `channel/wechat_group/wechat_group_memory_distiller.py` 默认 LLM 调用路径：不再访问不存在的 `AgentBridge.llm_model`，改为直接通过 `AgentLLMModel(Bridge()).call()` 调用当前模型适配层，避免 Web 控制台点击“从最近聊天生成记忆”时报 `'AgentBridge' object has no attribute 'llm_model'`。
- 新增 `channel/wechat_group/wechat_group_memory_distiller.py`：实现从当前群归档消息手动蒸馏群记忆与群友画像，支持严格 JSON 解析、证据消息校验、画像 `sender_id` 可证明校验、置信度分流、高置信度自动写入、低置信度候选、批准和驳回。
- 更新 `channel/wechat_group/wechat_group_archive.py`：新增蒸馏消息读取、运行记录表和候选表，运行与候选查询均按 `room_id` 强过滤。
- 更新 `channel/wechat_group/wechat_group_memory.py`：群记忆/画像写入增加来源标记；自动画像更新只合并非空字段，避免清空旧画像。
- 更新 `channel/web/web_channel.py`、`config.py`、`config-template.json`：新增自动蒸馏配置返回/保存和 `/api/wechat-group/memories/distill/*` 手动运行、运行列表、候选列表、批准、驳回、来源消息查询接口。
- 更新 `channel/web/static/js/console.js` 与 `channel/web/chat.html`：在 Web 控制台“群聊 -> 永久记忆”当前群详情中新增“自动生成”标签页，提供配置保存、手动运行、运行记录和候选审核入口，并更新脚本缓存版本。
- 新增 `tests/test_wechat_group_memory_distiller.py`，扩展 `tests/test_wechat_group_web.py`：覆盖置信度分流、跨群证据拒绝、非法成员拒绝、自动写入、候选审核和 Web API。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：回写 4.3.7 首个手动触发切片的完成进度、验证结果和剩余第二切片事项。

验证记录：

- `python -m unittest tests.test_wechat_group_memory_distiller tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_memory_distiller.DefaultLlmClientTest`
- `python -m unittest tests.test_wechat_group_web.WechatGroupWebTest.test_wechat_group_distill_run_api_reports_disabled_status`
- `python -m unittest tests.test_wechat_group_memory_distiller.WechatGroupMemoryDistillerTest.test_empty_llm_candidates_return_diagnostic_reason`
- `node --check .\channel\web\static\js\console.js`
- `python -m unittest tests.test_wechat_group_memory_ui tests.test_wechat_group_web tests.test_wechat_group_memory_distiller`
- `python -m py_compile channel\wechat_group\wechat_group_archive.py channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_memory_distiller.py channel\web\web_channel.py tests\test_wechat_group_memory_distiller.py tests\test_wechat_group_web.py tests\test_wechat_group_memory_ui.py`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_context tests.test_wechat_group_memory tests.test_wechat_group_web tests.test_wechat_group_memory_ui tests.test_wechat_group_memory_distiller`

### 微信群人设日志脱敏

- 更新 `agent/protocol/agent_stream.py`：调用 LLM 前的用户消息日志会将 `<wechat-group-persona>...</wechat-group-persona>` 内容替换为 `微信群聊人设提示词`，避免日志打印完整微信群人设提示词；真实传给模型的上下文不变。
- 更新 `tests/test_agent_stream_logging.py`：覆盖微信群人设块只打印标签、不泄露原始人设内容，同时保留用户真实问题日志。

验证记录：
- `python -m unittest tests.test_agent_stream_logging`

### OpenAI 兼容 Agent 消息格式修复

- 更新 `models/openai_compatible_bot.py`：修复 Agent 内部 Claude text blocks 转 OpenAI 兼容消息时，普通 `user` 消息仍保留数组 `content` 的问题，避免严格网关报 `cannot unmarshal array into ... content of type string`。
- 新增 `tests/test_openai_compatible_messages.py`：覆盖普通 `user` text blocks 必须转换为字符串 `content` 的回归场景。

验证记录：
- `python -m unittest tests.test_openai_compatible_messages`
- `python -m unittest tests.test_openai_compatible_messages tests.test_custom_provider`
- `python -m py_compile models\openai_compatible_bot.py tests\test_openai_compatible_messages.py`

### 个人微信群 4.3 群记忆完整闭环

- 更新 `channel/web/static/js/console.js` 与 `channel/web/chat.html`：在 Web 控制台“群聊”页新增“永久记忆”子菜单，支持按已选 `room_id` 管理群记忆、群友画像和注入预览；包含当前群搜索、摘要数量、停用、画像 revision 只读查看和脚本缓存版本更新。
- 更新 `agent/memory/storage.py` 与 `channel/wechat_group/wechat_group_memory.py`：补齐 scoped chunk 软停用、群记忆摘要、按群摘要列表、群记忆停用和群友画像停用能力。
- 更新 `channel/web/web_channel.py`：补齐 `/api/wechat-group/memories/summary`、`groups` 和 `disable` 后端分支，形成列表、搜索、新增、更新、停用、版本查看和预览的 API 闭环。
- 更新 `tests/test_wechat_group_memory.py`、`tests/test_wechat_group_web.py`、`tests/test_wechat_group_memory_ui.py`：覆盖停用隔离、按群摘要、summary/disable Web API、Web 控制台永久记忆入口、搜索、停用和 revision 入口。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：回写 4.3.2/4.3.3/4.3.6 最新完成进度、实际改动、验证结果与剩余手动验证事项。

验证记录：

- `python -m unittest tests.test_wechat_group_memory`
- `python -m unittest tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_memory_ui`
- `node --check .\channel\web\static\js\console.js`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_wechat_group_context tests.test_wechat_group_memory tests.test_memory_scope tests.test_wechat_group_memory_ui`
- `python -m py_compile agent\memory\scope.py agent\memory\storage.py agent\memory\manager.py channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_channel.py channel\web\web_channel.py tests\test_memory_scope.py tests\test_wechat_group_memory.py tests\test_wechat_group_context.py tests\test_wechat_group_web.py tests\test_wechat_group_memory_ui.py`

### 个人微信群 4.3 群记忆后端基础

- 新增 `agent/memory/scope.py`：定义 `MemoryScope`，统一表达 shared/user/session 与微信群 `room_id`、`room_id + sender_id` 作用域。
- 更新 `agent/memory/storage.py` 与 `agent/memory/manager.py`：为长期记忆索引兼容新增 `scope_type`、`scope_id`、`channel_type`、`subject_id`、`status`、`source_message_ids` 字段，支持按 `MemoryScope` 强过滤检索和写入；旧 `scope` / `user_id` 路径保持兼容。
- 新增 `channel/wechat_group/wechat_group_memory.py`：提供 `WechatGroupMemoryService`，支持群永久记忆、群友画像 active profile、画像 revision 审计和 `<wechat-group-memory>` 预览装配。
- 更新 `channel/wechat_group/wechat_group_channel.py`：在最近群聊上下文之后、用户真实问题之前注入 `<wechat-group-memory>`，配置关闭、无命中或异常时不注入空块。
- 更新 `channel/web/web_channel.py`：新增 `/api/wechat-group/memories/(.*)` 后端 handler，完成 group、profiles、profiles/revisions 与 preview 的最小 API 闭环。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：回写 4.3.1 和 4.3.2 已完成进度、实际改动、验证结果与剩余事项。

验证记录：

- `python -m unittest tests.test_memory_scope`
- `python -m unittest tests.test_wechat_group_memory`
- `python -m unittest tests.test_wechat_group_context`
- `python -m unittest tests.test_wechat_group_web`
- `python -m unittest tests.test_wechat_group_message tests.test_wechat_group_channel tests.test_wechat_group_web tests.test_wechat_group_context tests.test_wechat_group_memory tests.test_memory_scope`
- `python -m py_compile agent\memory\scope.py agent\memory\storage.py agent\memory\manager.py channel\wechat_group\wechat_group_memory.py channel\wechat_group\wechat_group_channel.py channel\web\web_channel.py tests\test_memory_scope.py tests\test_wechat_group_memory.py tests\test_wechat_group_context.py tests\test_wechat_group_web.py`
- 未完成：`python -m pytest tests/test_knowledge_service.py` 因当前环境未安装 `pytest`，无法验证该 pytest 风格测试文件。

### 个人微信群 4.3 开发计划与 UI 设计细化

- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：在 4.3 群永久记忆与群友画像章节新增待确认细化方案，覆盖通用作用域记忆升级、`WechatGroupMemoryService` 适配层、上下文注入链路、后端 Web API、配置边界和不做项。
- 细化 4.3 UI 设计：明确“永久记忆”入口放在群聊管理页子菜单，采用按群分组的信息架构，并拆分群记忆、群友画像、诊断预览三个面板；补充加载、错误、空状态、长 ID 展示、loading/disabled 和可访问性约束。
- 补充 4.3 待确认点：包括 Web 控制台与桌面端交付范围、群友画像表单形态、API 路径命名和画像 revision 存储方式。

验证记录：

- 文档变更，已静态检查计划文件包含 `4.3.1` 至 `4.3.5` 小节、建议 API 形态、UI 设计细化和待确认点。

### New API 自定义渠道计划修正

- 更新 `plans/newapi_capability_routing_plan_20260702.md`：将方案从“新增独立 `newapi` provider”修正为“把 QuantumNous/new-api 作为现有 `custom:<id>` 自定义 OpenAI-compatible 渠道使用”。
- 明确不新增 `newapi_api_key` / `newapi_api_base`，改为增强现有自定义渠道覆盖图像理解、图像生成、语音识别、语音合成和向量五类能力。

验证记录：

- 已核对 QuantumNous/new-api 项目定位为统一 AI 模型网关，支持 OpenAI-compatible 及 Chat/Image/Audio/Embeddings 等接口。
- 文档变更，已静态检查计划文件包含 `custom:<id>` 路由、五类能力任务、配置示例、风险回退和验证命令。

### 个人微信群 4.3 记忆上下文链路文档

- 更新 `AGENTS.md`：将个人微信群 LLM 请求上下文链路扩展为 4.3 目标结构，明确 `<wechat-group-memory>` 应注入当前群记忆、当前发言人群友画像和本轮被 @ 群友画像，并补充 `room_id` / `sender_id` 隔离规则。
- 更新 `plans/wechat_group_robot_migration_plan_20260701.md`：在 4.3 群永久记忆与群友画像章节列出下一步开发任务，覆盖 `WechatGroupMemoryService` 装配入口、通道注入位置、被 @ 群友画像召回和测试要求。

验证记录：

- 文档变更，已检查 `AGENTS.md` 与 4.3 开发计划中的上下文注入顺序和隔离规则一致。

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
