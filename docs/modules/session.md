# Session 会话管理

## 概述

SessionManager 负责管理对话会话的生命周期，包括消息历史、上下文窗口、滚动摘要和持久化存储。每个会话以 JSON 格式保存在 `data/sessions/` 目录。

## 架构

```
SessionManager
├── 当前会话（current: Session）
├── 会话持久化（data/sessions/*.json）
├── 消息管理（messages: List[Dict]）
├── 滚动摘要（summary: str）
└── Token 估算（estimate_tokens）
```

## 核心功能

### 1. 会话结构

```python
class Session:
    session_id: str              # 唯一标识
    messages: List[Dict]         # 消息历史
    created_at: str              # 创建时间
    updated_at: str              # 更新时间
    summary: str                 # 滚动摘要
```

### 2. 消息格式

```python
{
    "role": "user" | "assistant" | "tool" | "visual_log" | "debug_log",
    "content": str | List[Dict],  # 文本或多模态内容
    "timestamp": "2026-03-11 14:30:00",
    "tool_calls": [...],          # 工具调用（assistant 角色）
    "tool_call_id": "...",        # 工具结果 ID（tool 角色）
    "name": "..."                 # 工具名称（tool 角色）
}
```

### 3. 多模态支持

```python
# 文本消息
session.add_message("user", "你好")

# 图片消息
session.add_message("user", [
    {"type": "text", "text": "这是什么？"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
])
```

### 4. 工具调用记录

```python
# Assistant 发起工具调用
session.add_message("assistant", "", tool_calls=[
    {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"path": "test.py"}'
        }
    }
])

# Tool 返回结果
session.add_message("tool", "文件内容...", 
                   tool_call_id="call_123", 
                   name="read_file")
```

### 5. Token 估算

```python
# 自动估算当前会话的 Token 数
tokens = session.estimate_tokens()

# 估算规则：
# - CJK 字符: 1 char = 1 token
# - ASCII/Latin: 4 chars = 1 token
# - 图片: 1000 tokens/张
# - 工具调用: JSON 字符串长度 / 4
```

### 6. 滚动摘要

```python
# 当 Token 超限时，裁剪旧消息并生成摘要
if session.estimate_tokens() > context_window * 0.8:
    pruned = session.prune_oldest(keep_last=20)
    summary = generate_summary(pruned)
    session.summary = summary

# 摘要会作为前情提要注入到历史中
history = session.get_history()
# [
#   {"role": "user", "content": "[前情提要请求] ..."},
#   {"role": "assistant", "content": "[前情提要]\n{summary}\n\n已了解..."},
#   ... 最近 20 条消息 ...
# ]
```

### 7. 工具调用配对验证

```python
# 自动清理孤立的 tool 消息
# 场景：prune_oldest 裁剪了 assistant 的 tool_calls，
#      但保留了后续的 tool 结果消息
history = session.get_history()
# 会自动移除没有对应 tool_call 的 tool 消息
```

## API 接口

### 初始化

```python
from core.session import SessionManager

sessions = SessionManager(data_dir="data")
```

### 会话操作

```python
# 获取当前会话
current = sessions.current

# 新建会话
new_session = sessions.new_session()

# 加载历史会话
session = sessions.load("session_1234567890")

# 列出所有会话
all_sessions = sessions.list_sessions()
# [
#   {
#     "session_id": "session_123",
#     "created_at": "2026-03-11 10:00:00",
#     "updated_at": "2026-03-11 14:30:00",
#     "message_count": 42
#   },
#   ...
# ]
```

### 消息操作

```python
# 添加消息
session.add_message("user", "你好")
session.add_message("assistant", "你好！有什么可以帮你的吗？")

# 获取历史（LLM 格式）
history = session.get_history(max_messages=200)

# 清空会话
session.clear()
```

### 持久化

```python
# 保存当前会话
sessions.save()

# 保存指定会话
sessions.save(session)

# 自动保存（每次 add_message 后）
# SessionManager 会在每次消息添加后自动保存
```

## 配置

### 会话文件格式

```json
{
  "session_id": "session_1234567890",
  "created_at": "2026-03-11 10:00:00",
  "updated_at": "2026-03-11 14:30:00",
  "summary": "用户询问了 Python 异步编程的问题...",
  "messages": [
    {
      "role": "user",
      "content": "如何使用 asyncio？",
      "timestamp": "2026-03-11 10:00:00"
    },
    {
      "role": "assistant",
      "content": "asyncio 是 Python 的异步 I/O 库...",
      "timestamp": "2026-03-11 10:00:15"
    }
  ]
}
```

## 最佳实践

### 1. 上下文窗口管理

```python
# 定期检查 Token 数
tokens = session.estimate_tokens()
context_window = 128000  # Qwen 支持 128k

if tokens > context_window * 0.8:
    # 触发滚动摘要
    pruned = session.prune_oldest(keep_last=20)
    summary = agent._generate_summary(pruned)
    session.summary = summary
```

### 2. 视觉日志去重

```python
# 添加视觉日志
session.add_message("visual_log", "用户正在编辑 agent.py")

# 更新最后一条视觉日志的持续时间
session.update_last_visual_log("14:35:00")
# 结果: "用户正在编辑 agent.py（持续至 14:35:00）"
```

### 3. 调试日志

```python
# 添加调试日志（不会传递给 LLM）
session.add_message("debug_log", "工具调用耗时: 1.2s")

# get_history() 会自动过滤 debug_log
history = session.get_history()
# debug_log 不会出现在 history 中
```

### 4. 多模态消息

```python
# 用户上传图片
session.add_message("user", [
    {"type": "text", "text": "这段代码有什么问题？"},
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
])

# LLM 返回分析
session.add_message("assistant", "这段代码的问题在于...")
```

### 5. 会话恢复

```python
# 启动时自动恢复最近的会话
latest_session_id = None
latest_mtime = 0

for path in Path("data/sessions").glob("*.json"):
    mtime = path.stat().st_mtime
    if mtime > latest_mtime:
        latest_mtime = mtime
        latest_session_id = path.stem

if latest_session_id:
    sessions.load(latest_session_id)
```

## 故障排查

### 问题 1: Token 估算不准确

**症状**：实际 Token 数与估算值差异较大

**解决方案**：
```python
# 调整估算规则
def estimate_tokens(text: str) -> int:
    import re
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
    other = len(text) - cjk
    return cjk + (other // 4)

# 或者使用 tiktoken 库（更准确）
import tiktoken
enc = tiktoken.encoding_for_model("gpt-4")
tokens = len(enc.encode(text))
```

### 问题 2: 工具调用配对失败

**症状**：LLM 返回错误 "tool result without tool call"

**解决方案**：
```python
# 检查 tool_calls 和 tool 消息的配对
history = session.get_history()
declared_ids = set()
for msg in history:
    if msg["role"] == "assistant" and msg.get("tool_calls"):
        for tc in msg["tool_calls"]:
            declared_ids.add(tc["id"])

# 验证所有 tool 消息都有对应的 tool_call
for msg in history:
    if msg["role"] == "tool":
        assert msg["tool_call_id"] in declared_ids
```

### 问题 3: 会话文件损坏

**症状**：`load()` 失败，JSON 解析错误

**解决方案**：
```python
# 备份并修复
import json
import shutil

session_file = Path("data/sessions/session_123.json")
backup = session_file.with_suffix(".json.bak")
shutil.copy2(session_file, backup)

try:
    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    print(f"JSON 解析错误: {e}")
    # 手动修复或删除文件
```

### 问题 4: 滚动摘要丢失上下文

**症状**：摘要后 LLM 忘记了之前的对话

**解决方案**：
```python
# 生成更详细的摘要
def generate_summary(messages: List[Dict]) -> str:
    # 提取关键信息
    key_points = []
    for msg in messages:
        if msg["role"] == "user":
            key_points.append(f"用户: {msg['content'][:100]}")
        elif msg["role"] == "assistant":
            key_points.append(f"助手: {msg['content'][:100]}")
    
    # 调用 LLM 生成摘要
    summary_prompt = "请总结以下对话的关键内容:\n" + "\n".join(key_points)
    summary = llm.generate(summary_prompt)
    return summary
```

## 性能优化

### 1. 延迟保存

```python
# 批量添加消息后再保存
session.add_message("user", "消息1")
session.add_message("assistant", "回复1")
session.add_message("user", "消息2")
session.add_message("assistant", "回复2")
sessions.save()  # 一次性保存
```

### 2. 消息压缩

```python
# 压缩旧消息（移除冗余信息）
def compress_message(msg: Dict) -> Dict:
    compressed = {
        "role": msg["role"],
        "content": msg["content"][:500]  # 截断长内容
    }
    if "tool_calls" in msg:
        compressed["tool_calls"] = msg["tool_calls"]
    return compressed
```

### 3. 分页加载

```python
# 只加载最近的消息
def get_recent_history(session_id: str, limit: int = 50) -> List[Dict]:
    with open(f"data/sessions/{session_id}.json", "r") as f:
        data = json.load(f)
    return data["messages"][-limit:]
```

## 未来优化方向

1. **会话分支**：支持从历史消息创建分支会话
2. **会话合并**：合并多个相关会话
3. **会话搜索**：全文搜索历史会话
4. **会话标签**：为会话添加标签和分类
5. **会话导出**：导出为 Markdown/PDF 格式
6. **会话分析**：统计会话时长、消息数、Token 消耗
