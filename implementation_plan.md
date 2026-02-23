# qwen_autogui 项目优化方案

## 分析与背景
结合现有系统的“每日整理器”和“日记功能”，参考 `openakita` 和 `memU` 的长处，制定以下优化计划，以解决 Token 消耗、记忆管理、多性格切换等问题。

## User Review Required
> [!IMPORTANT]
> 以下是为您量身定制的优化计划。请查看并告诉我您是否同意，或者有哪些部分需要调整。确认后，我将进入 EXECUTION 模式开始修改代码。

## Proposed Changes

### 1. 优化 Token 消耗 (Prompt 组装与日常归纳)
- **精简 System Prompt**：当前 [agent.py](file:///d:/qwen_autogui/agent.py) 每次对话都会全量加载 [PERSONA.md](file:///d:/qwen_autogui/PERSONA.md) 和完整的记忆向量库摘要。这在后期记忆增多时会造成严重的 Token 膨胀。
  - **优化**：引入类似 openakita 的 `PromptAssembler` 模式：系统提示词仅常驻“核心人设”与“User Profile”。只有触发特定关键词或工具时，才基于当前 `user_input` 实行 top-K 相关记忆的动态注入（而非全部塞入）。
  - **关于“动态注入”的解答**：动态注入指的是在每次用户发送消息时，将当前这句话（`user_input`）作为查询词，使用向量库搜索找出最相关的几条记忆（Top-3），并**临时**拼接到当次的系统提示词里。比如您说“我想吃水果”，AI会自动检索出“用户对芒果过敏”这条记忆片段临时注入，从而避免把所有不相关的记忆（如“喜欢蓝色”、“正在学Python”）全量塞进 Prompt 中，极大节省 Token 开销。
- **廉价模型分流**：[self_evolution.py](file:///d:/qwen_autogui/core/self_evolution.py) 中的日志总结（[_summarize_day_conversations](file:///d:/qwen_autogui/core/agent.py#719-782)）、知识图谱提取和记忆提取每天消耗大量 Token。
### 2. 引入 AI 性格切换功能 (Persona Manager) ✅ 已完成
- **实现状态**：已完成
- **实现方案**：
  - 新建 `data/identities/` 文件夹，将不同的性格规范定义为独立文件。
  - 在 `agent.py` 中增加 `/persona <name>` 命令，允许控制台热切换。
  - 增加 `interaction_habits.md` 全局文件记录进化成果。

### 3. 本地记忆分层架构 (Memory Stratification) - 借鉴 MemOS [新增计划]✅ 已完成
为了彻底解决“执行长计划时由于 Query 不包含关键字而遗忘用户偏好/规则”的现象，我们将对现有的扁平记忆与档案系统进行 **三层 (Objective, Subjective, Scene)** 架构深度改造。

#### A. 核心高优记忆区 (Core Working Memory) -> 常驻注入✅ 已完成
我们将把原先单一的 `user_profile.json` 拆分成符合 MemOS 哲学的两大块，并**无条件前置注入**到每次 LLM 轮次的 System Prompt 开头，充当不可阻挡的防遗忘底座：
- **Objective Memory (客观身份记忆)**：存放确定的事实。例如：`name`, `age`, `expertise`, `language_proficiency`。
- **Subjective Memory (主观偏好记忆)**：存放非实体的指导原则。例如：习惯 (`interaction_pace`), 偏好 (`preference`: 比如“不要把文件写在测试目录”), 回应风格 (`response_style`)。
- **机制改造**：修改 `core/agent.py` 的提示构建器，将 `data/user_profile.json` (现已升级为双层结构) 转化为 LLM 随时可见的“第一核心准则”。

#### B. 场景与碎片记忆区 (Scene & Episodic Memory) -> 按需检索✅ 已完成
- 过去的 `memory.jsonl` （包含海量日常琐碎事实、曾经的代码方案、过去发生的事件）将作为 **Scene Memory 的长期归档**。
- 由于它们数量庞大，依然保留目前的 **Top-K 向量检索动态注入**。这样既保证了长期回忆的能力，又不会造成 Prompt Token 爆炸。

#### C. 工具层统一操作 (Unified Operation)✅ 已完成
- 修改 `self_evolution.py` 或后台记忆提取流程：当大模型自行判定出用户的偏好（例如“不要用 gbk 编码”）时，直接以 JSON Patch 形式写入 `user_profile.json -> subjective_memory`。
- 保留 `search_memory` 工具，专用于在执行任务时，深度探查过去的 Scene/Episodic 记忆。这就是完美的“核心底线不可违 + 历史细节自由查”闭环。

### 4. 统一记忆搜索引擎 (Unified Search Tool) [计划新增]✅ 已完成
- **现状**：目前系统包含 `search_journal`、`recall` 和 `query_knowledge` 三个零碎的搜索工具，导致大模型在找寻信息时认知负荷大、频繁试错（API 来回调用耗时且消耗 Token）。
- **业界调研**：
  - `openakita`：使用统一的 `search_memory` 工具，通过传入 `type`（如 fact, preference 等）在底层进行路由并统一返回。
  - `memU`：提供单一的 `memu_memory` 查询接口，由底层的 `memory_service.retrieve` 去混编各分类的记忆结果。
  - `nanobot`：底层通过 `MemoryStore` 分层读取长短期记忆组合成上下文。
- **优化**：
  - 在 `agent.py` 中废弃原有的 3 个零碎工具，聚合为一个全能的 `search_memory(query: str, time_range: str = "all")`。
  - 后台使用 Python 的 `concurrent.futures.ThreadPoolExecutor` 并发查询日记（精确匹配）、短记忆片段（向量相似度检索）和知识图谱（关系扫描）。
  - 将三种结果聚合成一篇结构化的 Markdown 报告直接返回给 LLM，实现 1 次调用、3 倍信息密度的超高 QPS 优化。

### 5. 高阶核心技能拓展 (Advanced Skills Integration) [新计划]
为了将 `qwen_autogui` 从“记录者”升级为“行动派”，我们将按序（从易到难、从底层到高层）集成以下 4 个超级核心技能：

#### 阶段一：基础终端执行 (`execute_command`) ✅ 已完成
- **实现方案**：已在 `plugins/system.py` 实现安全的 `subprocess.run` 命令拦截与输出捕获。

#### 阶段二：定时间轴管理 (`schedule_task`) ✅ 已完成
- **实现方案**：已在 `plugins/scheduled.py` 实现。支持异步闹钟与控制台提醒。

#### 阶段三：动态技能自举系统 (`skill_creator`) ✅ 已完成
- **实现方案**：已在 `plugins/skill_creator.py` 实现。支持 AI 自主编写 Python 插件并热加载。

#### 阶段四：MCP 协议客户端网关 (Model Context Protocol) ✅ 已完成
- **实现状态**：✅ 已完成
- **实现文件**：
  - `core/mcp_client.py` - 异步 MCP 客户端实现
  - `plugins/mcp_gateway.py` - 同步网关和技能注册
  - `config/mcp_servers.json` - 配置文件示例
- **实现方案**：实现了完整的 JSON-RPC 2.0 生命周期管理，支持 Stdio MCP Client。
- **关键特性**：
  - **基于 `asyncio` 的核心客户端**：`MCPStdioClient` 类，通过 `asyncio.create_subprocess_exec` 启动外部 MCP Server。
  - **规范握手 (Handshake)**：严格遵守 MCP 协议，发送 `initialize` 请求，接收 `ServerCapabilities`，验证协议版本后发送 `initialized` 通知。
  - **工具发现 (Tool Discovery)**：实现 `tools/list` 方法，支持动态发现外部 Server 提供的工具。
  - **同步外壳 (Sync Wrapper)**：`mcp_gateway.py` 通过 `asyncio.run()` 进行事件循环隔离。
  - **安全与生命周期管理**：`atexit` 注册清理函数，进程结束时自动终止子进程。
  - **模板快捷方式**：内置 6 种常用 MCP 服务器模板（filesystem, github, brave-search, sequential-thinking, puppeteer, sqlite）。
  - **配置加载**：支持从 `config/mcp_servers.json` 加载服务器配置。
- **技能列表**：
  - `call_mcp_tool` - 调用 MCP 工具
  - `mcp_list_templates` - 列出可用模板
  - `mcp_list_active` - 列出活跃连接
  - `mcp_disconnect` - 断开连接

### 6. 终极自主性拓展 (Ultimate Autonomy Integration) [最新进阶计划]
基于前面的底层能力，我们将实现真正的 Agent 化控制：

#### 阶段一：安全状态沙箱 (`sandbox_repl`) ✅ 已完成
- **实现方案**：已在 `plugins/sandbox_repl.py` 实现。支持多轮变量持久化。

#### 阶段二：长链条多步任务规划器 (`plan_handler`) ✅ 已完成
- **实现方案**：已在 `plugins/plan_handler.py` 实现。支持任务流拆解、状态追踪与进度总结。

#### 阶段三：原生浏览器 DOM 控制器 (`browser_mcp` / `playwright`) ✅ 已完成
- **实现方案**：已在 `plugins/browser.py` 实现。通过 `agent-browser` 命令行工具实现了对 Chrome 的精准 DOM 操控。

### 7. 多功能文件上传与会话自动续接 ✅ 已完成
- **实现状态**：已完成
- **核心逻辑**：
  - **万能上传 (`/upload`)**：支持图片识别（代理路由）与文本文件（代码/MD）直接读取。
  - **视觉代理 (Vision Proxy)**：当主模型眼盲时，自动调用视觉模型生成“看图作文”并回馈给主中枢，保留其 Tool 能力。
  - **会话持久化 (Session Resume)**：系统启动时自动加载 `data/sessions/` 中修改时间 (mtime) 最晚的历史记录，实现无缝断点续传。支持 `/new` 命令强制开启新会话。
  - **Token 估算**：修正了对列表型消息内容的 Token 统计逻辑。

### 8. 系统核心架构准则与技术细节 (Core Architecture Principles) [核心文档]
为防止遗忘，我们将最近确立的关键技术方案沉淀如下：

#### A. 浏览器调度策略 (Browser Orchestration)
- **Edge 优先原则**：在 Windows 环境下，`ensure_browser_running` 会按照 `Edge (64位原生 -> x86) -> Chrome` 的顺序探测路径，并优先拉起 Microsoft Edge。
- **三层运行模式**：
  - `background` (默认)：无头模式，静默运行。
  - `headed`：显示独立 Chromium 窗口。
  - `system`：自动连接到系统的真实 Edge/Chrome 调试端口，允许 AI 操作用户已登录的网页。
- **进程隔离**：使用独立的 `--user-data-dir="D:\browser_debug"`，避免与用户日常开启的浏览器进程产生锁冲突。

#### B. 多模态代理路由 (Vision Proxy Routing)
- **“眼盲”补偿**：当主模型（如 Qwen3.5）无法直接处理图片时，系统会自动判断并将图片路由给 `image_analyzer` 专用视觉模型（如 Qwen-VL）。
- **结构化回馈**：视觉模型生成的详细描述会以 `【视觉代理反馈】` 前缀注入主模型的上下文，主模型基于文字描述执行后续 Tool 调用。

#### C. 会话与状态管理 (Session & State)
- **加载策略**：`SessionManager` 初始化时会扫描 `data/sessions/` 目录，通过比对文件修改时间戳自动锁定最后一次对话。
- **强制重置**：指令集中的 `/new` 关键词会清空 `_current` 对象并生成新 UUID，用户可在任何时候获得纯净上下文。

#### D. 安全与稳定性 (Safety & Stability)
- **子进程脱离**：调用 `subprocess.Popen` 时使用 `DETACHED_PROCESS` 标志，确保浏览器启动不阻塞主控制台，且在 Python 崩溃时浏览器仍能作为 Daemon 保持存活。
- **技能自举隔离**：`skill_creator` 编写的所有代码都会保存到 `plugins/` 独立文件，通过 `SkillManager` 动态 `importlib` 热加载，不污染核心代码库。

### 9. 3D Interaction System (Project N.E.K.O Reference) [New]

Implement interactive 3D companion features using Three.js and VRM.

#### [NEW] [vrm-interaction.js](file:///d:/qwen_autogui/static/js/vrm-interaction.js)
- **Camera/Input**: Handle orbit controls, scrolling zoom, and model repositioning.
- **Raycasting**: Implement precision hit-testing to detect which part of the model is interacted with.
- **Poke detection**: Distinguish between "drag" and "click". A click (short duration, no move) triggers a "poke".

#### [NEW] [vrm-expression.js](file:///d:/qwen_autogui/static/js/vrm-expression.js)
- **Expression Management**: Map high-level emotions (Happy, Angry) to VRM blendshapes.
- **Auto-Blink & Mood Recovery**: Handle physiological blinking and automatic return to `neutral` state after an interactive reaction.

#### [MODIFY] [app.js](file:///d:/qwen_autogui/static/js/app.js)
- **Event Linkage**: 
  - On Poke: 
    1.  Call `vrmExpression.setMood('happy')`.
    2.  Inject a system-level query into the chat stream: `*你轻轻地戳了戳[角色名]*`.
  - The AI will then generate a contextual verbal response ("Hey! Stop that~") which triggers TTS and LipSync.

---

## Verification Plan

### Automated Tests ✅ 已完成
1. 运行 `python main.py`，触发 `/persona` 切换命令，确保不同人设的热切换可以生效。
2. 运行 `python force_evolve.py <date>`，测试后台总结时 Token 模型的分流是否生效，并检查是否正常更新了 `user_profile` 和日记。
3. 在控制台要求大模型“帮我执行一下 `python --version` 命令”，验证 `execute_command` 的挂载和输出拦截。
4. 设定一个 1 分钟后的闹钟，验证 `schedule_task` 能否成功将消息传入队列并打断/提示用户。
5. **[新]** 启动带依赖环境的子进程沙箱，验证连续执行代码的变量持久化。
6. **[新]** 让 AI 创建一个 3 步骤的计划并观察其严格按照计划顺序执行。

### Manual Verification
1. **3D Loading**: Ensure the VRM model renders correctly in the new frontend.
2. **Orbit/Zoom**: Test manual camera controls and scrolling.
3. **Poke Reaction**: 
   - Click the model.
   - **Expectation**: Model changes to a "Happy" or "Surprised" expression.
   - **Expectation**: A chat message appears and voice output is triggered with LipSync.
4. **Voice Integration**: Click the mic, speak, and observe the AI's response and model animation.
