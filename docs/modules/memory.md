# 记忆系统 (Memory)

## 概述

记忆系统负责长期存储和检索重要信息，支持关键词搜索和向量语义检索（RAG）。

**文件位置**: `core/memory.py`, `core/memory_extractor.py`, `core/vector_memory.py`

---

## 架构

```
┌─────────────────────────────────────────┐
│         MemoryManager                   │
│  (JSONL 存储 + 向量检索)                 │
└─────────────────────────────────────────┘
           ↓                    ↓
    ┌──────────┐         ┌──────────────┐
    │ JSONL 文件│         │ VectorStore  │
    │ 持久化    │         │ (numpy)      │
    └──────────┘         └──────────────┘
           ↑                    ↑
    ┌──────────────────────────────────┐
    │     MemoryExtractor              │
    │  (从对话中提取记忆)               │
    └──────────────────────────────────┘
```

---

## 记忆类型

```python
MEMORY_TYPES = {"fact", "skill", "error", "preference", "rule", "experience"}
```

| 类型 | 说明 | 示例 |
|-----|------|------|
| fact | 客观事实 | "用户使用 Windows 11" |
| skill | 技能模式 | "使用 pyautogui 控制鼠标" |
| error | 错误教训 | "DingTalk 连接超时需重启" |
| preference | 用户偏好 | "用户喜欢深色主题" |
| rule | 规则约束 | "不要修改 core/ 目录代码" |
| experience | 可复用经验 | "修复缓存错误先清理 data/cache/" |

---

## 核心功能

### 1. 添加记忆

```python
memory.add(
    content="用户喜欢深色主题",
    tags=["ui", "preference"],
    type="preference",
    source="conversation"
)
```

**去重机制**：
- 精确匹配：相同内容 + 相同类型 → 跳过
- 模糊去重：内容相似度 > 80% → 跳过

**内容限制**：最多 1200 字符

### 2. 搜索记忆

#### 语义搜索（优先）

使用 Qwen `text-embedding-v4` 模型：

```python
results = memory.search("如何修复缓存错误", top_k=5)
```

#### 关键词搜索（降级）

当向量搜索不可用时，使用关键词重叠评分：

```python
score = len(query_words & content_words) + 0.5 * len(query_words & tag_words)
```

### 3. 按类型筛选

```python
error_memories = memory.list_by_type("error")
```

### 4. 构建上下文

自动注入到 system prompt：

```python
context = memory.build_context("如何修复缓存错误", top_k=5)
# 输出：
# 【相关记忆】
#   - [2026-03-10 15:30] 修复缓存错误先清理 data/cache/
#   - [2026-03-09 10:20] 缓存损坏会导致启动失败
```

### 5. 更新 / 删除

```python
# 更新
memory.update(
    memory_id="mem_abc123",
    new_content="用户喜欢浅色主题",
    new_tags=["ui", "preference"],
    new_type="preference"
)

# 删除
memory.delete("mem_abc123")
```

---

## 记忆提取 (MemoryExtractor)

### 自动提取

从对话历史中自动提取记忆：

```python
extractor = MemoryExtractor(client, memory_manager)
new_items = extractor.extract_from_conversation(messages)
```

**提取时机**：
- 对话结束后（空闲 60 秒）
- 每日记忆整合任务（凌晨 03:00）

### 提取规则

LLM 根据以下规则提取：

1. **fact**: 客观事实、用户信息、系统状态
2. **skill**: 成功的操作模式、技能用法
3. **error**: 错误教训、失败经验
4. **preference**: 用户偏好、习惯
5. **rule**: 规则约束、禁止事项
6. **experience**: 可复用的经验、最佳实践

### 记忆审计

定期去重和优化记忆库：

```python
report = extractor.audit_memories()
# 返回：
# {
#   "deleted": 5,   # 删除重复记忆
#   "merged": 3,    # 合并相似记忆
#   "updated": 2,   # 更新过时记忆
#   "kept": 100     # 保留有效记忆
# }
```

---

## 向量存储 (VectorStore)

### 初始化

```python
from core.vector_memory import VectorStore

vector_store = VectorStore(
    data_dir="data/memory",
    embedding_client=embedding_client
)
```

### 添加向量

```python
vectors = embedding_client.embed_text("用户喜欢深色主题")
vector_store.add_vectors("mem_abc123", vectors)
```

### 搜索

```python
query_vec = embedding_client.embed("如何修复缓存错误")
results = vector_store.search(query_vec, top_k=5)
# 返回: [(memory_id, score), ...]
```

### 持久化

向量存储在 `data/memory/vectors.npz`：

```python
{
    "ids": ["mem_abc123", "mem_def456", ...],
    "vectors": [[0.1, 0.2, ...], [0.3, 0.4, ...], ...]
}
```

---

## 数据格式

### JSONL 文件

`data/memory/scene_memory.jsonl`：

```json
{"id": "mem_abc123", "content": "用户喜欢深色主题", "type": "preference", "tags": ["ui"], "source": "conversation", "timestamp": 1710123456.789, "created_at": "2026-03-10 15:30:56"}
{"id": "mem_def456", "content": "修复缓存错误先清理 data/cache/", "type": "experience", "tags": ["fix", "cache"], "source": "selfcheck", "timestamp": 1710123789.012, "created_at": "2026-03-10 16:23:09"}
```

### MemoryItem 结构

```python
class MemoryItem:
    id: str              # mem_{uuid}
    content: str         # 记忆内容（最多 1200 字符）
    type: str            # fact/skill/error/preference/rule/experience
    tags: List[str]      # 标签列表
    source: str          # manual/conversation/selfcheck/evolution
    timestamp: float     # Unix 时间戳
    created_at: str      # 可读时间 "2026-03-10 15:30:56"
```

---

## API 接口

### REST API

```
GET    /api/memory              # 列出所有记忆
POST   /api/memory              # 添加记忆
GET    /api/memory/search       # 搜索记忆
GET    /api/memory/types        # 按类型筛选
PUT    /api/memory/{id}         # 更新记忆
DELETE /api/memory/{id}         # 删除记忆
DELETE /api/memory/batch        # 批量删除
```

### 示例

```bash
# 添加记忆
curl -X POST http://localhost:8080/api/memory \
  -H "Content-Type: application/json" \
  -d '{"content": "用户喜欢深色主题", "type": "preference", "tags": ["ui"]}'

# 搜索记忆
curl "http://localhost:8080/api/memory/search?q=深色主题&top_k=5"

# 按类型筛选
curl "http://localhost:8080/api/memory/types?type=error"
```

---

## 配置

### 向量搜索配置

在 `config.json` 中配置：

```json
{
  "embedding_model": "text-embedding-v4",
  "embedding_api_key": "sk-xxx",
  "embedding_api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

### 记忆整合任务

在 `core/server.py` 中注册：

```python
await scheduler.add_task(ScheduledTask(
    id="system_memory_consolidate",
    name="记忆整合",
    cron_expr="0 3 * * *",  # 每日凌晨 03:00
    task_type=TaskType.SYSTEM,
    action="system:memory_consolidate"
))
```

---

## 最佳实践

1. **合理使用类型**：根据内容选择正确的记忆类型
2. **添加标签**：便于后续筛选和搜索
3. **定期审计**：每周运行一次记忆审计，清理重复记忆
4. **向量搜索优先**：配置 embedding API 以启用语义搜索
5. **记录来源**：标记记忆来源（conversation/selfcheck/manual）

---

## 故障排查

### 向量搜索不可用

1. 检查 `config.json` 中的 embedding 配置
2. 测试 API 连通性：`curl https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings`
3. 查看日志：`Vector generation failed`

### 记忆未自动提取

1. 检查 MemoryExtractor 是否初始化
2. 查看对话是否触发提取条件（空闲 60 秒）
3. 查看日志：`Memory extraction error`

### JSONL 文件损坏

1. 备份 `data/memory/scene_memory.jsonl`
2. 逐行解析，找出损坏行
3. 手动修复或删除损坏行

---

## 未来优化方向

1. **多模态记忆**：支持图片、音频记忆
2. **记忆重要性评分**：根据使用频率自动调整重要性
3. **记忆过期机制**：自动清理长期未使用的记忆
4. **记忆关联图谱**：构建记忆之间的关联关系
