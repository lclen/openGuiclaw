# Agent 核心引擎

## 概述

Agent 是 OpenGuiclaw 的核心对话引擎，负责协调记忆系统、会话管理、技能调用和 LLM 交互。它实现了完整的 OpenAI Function Calling 工具链，支持多轮对话、上下文管理、Token 统计和自动进化。

## 架构

```
Agent
├── LLM Client (OpenAI SDK)
├── Memory System (长期记忆 + 向量检索)
├── Session Manager (会话历史)
├── Skills Manager (技能注册与执行)
├── Journal Manager (对话日志)
├── Diary Manager (AI 日记)
├── Knowledge Graph (知识图谱)
├── Identity Manager (人设管理)
├── Self Evolution (自我进化引擎)
└── Context Manager (视觉感知)
```

## 核心功能

### 1. 多模型配置

支持多个 LLM 端点配置，可独立指定：
- 主对话模型（chat_endpoints）
- 视觉分析模型（vision）
- 图片解析模型（image_analyzer）
- 进化专用模型（evolution_model，节省成本）

### 2. 工具调用（Function Calling）

```python
# 自动解析 LLM 返回的 tool_calls
for tool_call in response.tool_calls:
    result = await skills.execute(
        tool_call.function.name,
        json.loads(tool_call.function.arguments)
    )
```

支持：
- 并行工具调用
- 工具结果反馈
- 错误重试机制
- 工具调用日志记录

### 3. 上下文窗口管理

```python
# 自动检测 Token 超限并触发滚动摘要
if session.estimate_tokens() > (context_window * 0.8):
    pruned = session.prune_oldest(keep_last=20)
    summary = _generate_summary(pruned)
    session.summary = summary
```

特性：
- 动态 Token 估算（CJK 字符 1 token，ASCII 4 字符 1 token）
- 图片 Token 计算（每张约 1000 tokens）
- 滚动摘要生成（保留前情提要）
- 工具调用配对验证（防止孤立的 tool result）

### 4. 记忆系统集成

```python
# 并发搜索：长期记忆 + 日志 + 日记 + 知识图谱
def search_memory(query: str):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        journal_future = executor.submit(_search_journal)
        diary_future = executor.submit(_search_diary)
        vector_future = executor.submit(_search_vector)
        kg_future = executor.submit(_search_kg)
```

### 5. 自动记忆提取

```python
# 对话结束后自动提取记忆（带防抖）
if time.time() - self._last_message_time > 60:
    threading.Thread(
        target=self._extract_conversation_memory,
        daemon=True
    ).start()
```

### 6. Token 用量统计

```python
# SQLite 持久化 + 内存聚合
self._record_usage(response.usage, model)
# 支持按模型、按日期查询统计
```

## API 接口

### 初始化

```python
agent = Agent(
    config_path="config.json",
    persona_path="PERSONA.md",
    data_dir="data",
    auto_evolve=True  # 启用自动进化
)
```

### 对话接口

```python
# 同步对话
response = agent.chat(user_input, images=[])

# 流式对话（SSE）
for chunk in agent.chat_stream(user_input, images=[]):
    yield chunk
```

### 会话管理

```python
# 新建会话
agent.sessions.new_session()

# 加载历史会话
agent.sessions.load(session_id)

# 列出所有会话
sessions = agent.sessions.list_sessions()
```

### 人设切换

```python
# 切换人设
agent.switch_persona("assistant")

# 列出所有人设
personas = agent.list_personas()
```

## 配置

### config.json 结构

```json
{
  "active_chat_endpoint_id": "qwen",
  "chat_endpoints": [
    {
      "id": "qwen",
      "name": "通义千问",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
      "api_key": "sk-xxx",
      "model": "qwen-max",
      "evolution_model": "qwen-plus",
      "max_tokens": 8000,
      "temperature": 0.7,
      "context_window": 128000
    }
  ],
  "vision": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-xxx",
    "model": "qwen-vl-plus"
  },
  "image_analyzer": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-xxx",
    "model": "qwen3-vl-flash"
  },
  "embedding": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-xxx",
    "model": "text-embedding-v4"
  },
  "active_persona": "default",
  "journal": {
    "enable_diary": true
  }
}
```

## 最佳实践

### 1. 模型选择策略

- **主对话**：qwen-max（高质量推理）
- **进化任务**：qwen-plus（性价比）
- **视觉感知**：qwen-vl-plus（屏幕分析）
- **图片解析**：qwen3-vl-flash（快速响应）

### 2. 上下文管理

```python
# 设置合理的 context_window
"context_window": 128000  # Qwen 支持 128k

# 触发摘要的阈值（80%）
if tokens > context_window * 0.8:
    # 自动生成滚动摘要
```

### 3. 记忆提取时机

- 对话结束后 60 秒自动提取
- 避免频繁提取（防抖机制）
- 只提取有价值的长期记忆

### 4. 工具调用优化

```python
# 并行调用独立工具
tool_calls = [
    {"name": "read_file", "args": {"path": "a.py"}},
    {"name": "read_file", "args": {"path": "b.py"}}
]
# LLM 会自动并行执行
```

### 5. 错误处理

```python
try:
    response = agent.chat(user_input)
except Exception as e:
    # 记录错误到 error 类型记忆
    agent.memory.add(
        f"对话错误: {str(e)}",
        tags=["error", "chat"]
    )
```

## 故障排查

### 问题 1: Token 超限

**症状**：API 返回 400 错误，提示 Token 超出限制

**解决方案**：
```python
# 检查当前 Token 数
tokens = agent.sessions.current.estimate_tokens()
print(f"当前 Token 数: {tokens}")

# 手动触发摘要
if tokens > 100000:
    agent.sessions.current.prune_oldest(keep_last=20)
```

### 问题 2: 工具调用失败

**症状**：LLM 返回 tool_calls 但执行报错

**解决方案**：
```python
# 检查技能是否启用
skill = agent.skills.get("tool_name")
if not skill.enabled:
    agent.skills.enable("tool_name")

# 查看错误日志
# 日志会记录在 Session 的 debug_log 角色消息中
```

### 问题 3: 记忆提取不工作

**症状**：对话后没有自动提取记忆

**解决方案**：
```python
# 检查提取器状态
print(agent._extracting_conversation)  # 应为 False

# 手动触发提取
agent._extract_conversation_memory()

# 查看提取结果
memories = agent.memory.list_all()
print(f"记忆总数: {len(memories)}")
```

### 问题 4: 视觉感知不启动

**症状**：Context Manager 线程未运行

**解决方案**：
```python
# 检查配置
if agent.context is None:
    print("Context Manager 未初始化")

# 手动启动
if agent.context:
    agent.context.start()
```

## 性能优化

### 1. 向量索引预热

```python
# 启动时后台补全向量
# 已内置在 Agent.__init__ 中
threading.Thread(
    target=agent._backfill_vectors,
    daemon=True
).start()
```

### 2. 并发搜索

```python
# search_memory 已使用 ThreadPoolExecutor
# 同时搜索 4 个数据源，响应时间 < 2s
```

### 3. 延迟加载

```python
# 插件和后台任务延迟 10 秒启动
# 避开系统启动时的 API 高峰
agent.start_background_tasks()
```

## 未来优化方向

1. **流式工具调用**：支持工具执行过程中的实时反馈
2. **多 Agent 协作**：支持子 Agent 委托和结果聚合
3. **工具调用缓存**：相同参数的工具调用结果缓存
4. **上下文压缩**：使用专门的压缩模型减少 Token 消耗
5. **记忆分层**：短期/中期/长期记忆分层管理
6. **工具权限控制**：基于人设的工具访问权限
