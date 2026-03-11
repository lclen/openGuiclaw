# Knowledge Graph 知识图谱

## 概述

KnowledgeGraph 是 OpenGuiclaw 的轻量级知识图谱系统，使用 JSONL 存储实体关系三元组（subject → relation → object），支持实体查询、关系检索和上下文生成。

## 架构

```
KnowledgeGraph
├── 三元组存储（data/memory/knowledge_graph.jsonl）
├── 实体查询（query by entity）
├── 关系检索（query between entities）
├── 上下文生成（context_for_entity）
└── 批量添加（add_batch）
```

## 核心功能

### 1. 三元组结构

```python
class Triple:
    subject: str    # 主语（实体）
    relation: str   # 关系（谓语）
    object: str     # 宾语（实体）
    source: str     # 来源（如 "journal:2026-03-11"）
    ts: str         # 时间戳
```

**示例**：
```python
{
    "subject": "Qwen",
    "relation": "是",
    "object": "语言模型",
    "source": "journal:2026-03-11",
    "ts": "2026-03-11 14:30:00"
}
```

### 2. 添加三元组

```python
# 单个添加
kg.add("张三", "是...的导师", "李四", source="journal:2026-03-11")

# 批量添加（从 LLM 提取）
triples = [
    {"subject": "Qwen", "relation": "是", "object": "语言模型"},
    {"subject": "OpenGuiclaw", "relation": "使用", "object": "Qwen"}
]
count = kg.add_batch(triples, source="journal:2026-03-11")
```

### 3. 实体查询

```python
# 查询与实体相关的所有三元组
triples = kg.query("Qwen")
# [
#   <Triple: Qwen → 是 → 语言模型>,
#   <Triple: OpenGuiclaw → 使用 → Qwen>
# ]

# 支持模糊匹配（空格归一化）
triples = kg.query("Qwen3.5")  # 可以匹配 "Qwen 3.5"
```

### 4. 关系检索

```python
# 查询两个实体之间的关系
triples = kg.query_between("张三", "李四")
# [<Triple: 张三 → 是...的导师 → 李四>]
```

### 5. 上下文生成

```python
# 生成实体的关系摘要
context = kg.context_for_entity("Qwen")
# 【知识关联: Qwen】
#   · Qwen  是  语言模型
#   · OpenGuiclaw  使用  Qwen
#   · Qwen  支持  Function Calling
```

### 6. 统计信息

```python
# 获取统计信息
stats = kg.stats()
# "42 条关系，28 个实体"
```

## API 接口

### 初始化

```python
from core.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph(data_dir="data")
```

### 添加三元组

```python
# 单个添加
triple = kg.add(
    subject="Qwen",
    relation="是",
    obj="语言模型",
    source="journal:2026-03-11"
)

# 批量添加
triples = [
    {"subject": "张三", "relation": "是...的导师", "object": "李四"},
    {"subject": "李四", "relation": "学习", "object": "Python"}
]
count = kg.add_batch(triples, source="conversation")
print(f"添加了 {count} 条关系")
```

### 查询三元组

```python
# 查询实体
triples = kg.query("Qwen")
for t in triples:
    print(f"{t.subject} → {t.relation} → {t.object}")

# 查询关系
triples = kg.query_between("张三", "李四")

# 生成上下文
context = kg.context_for_entity("Qwen")
print(context)

# 列出所有三元组
all_triples = kg.list_all()
```

## 配置

### 存储格式（JSONL）

```jsonl
{"subject": "Qwen", "relation": "是", "object": "语言模型", "source": "journal:2026-03-11", "ts": "2026-03-11 14:30:00"}
{"subject": "张三", "relation": "是...的导师", "object": "李四", "source": "conversation", "ts": "2026-03-11 15:00:00"}
{"subject": "OpenGuiclaw", "relation": "使用", "object": "Qwen", "source": "journal:2026-03-11", "ts": "2026-03-11 16:00:00"}
```

### 提取 Prompt

```python
RELATION_PROMPT = """
你是一个实体关系提取助手。请从以下日志中提取**明确的实体关系三元组**。

规则（非常严格）：
- 目标：只提取长期的、固有的、真实具体的实体间关系
- 格式：subject（主语）、relation（关系/谓语）、object（宾语）
- 例子：{"subject": "张三", "relation": "是...的导师", "object": "李四"}
- 禁忌：
  ❌ 工具调用、命令执行、程序运行状态
  ❌ 对话行为
  ❌ 模糊、推测性关系
- 宁缺毋滥，无关系则返回 []

返回 JSON 数组：
[
  {"subject": "...", "relation": "...", "object": "..."},
  ...
]
"""
```

## 最佳实践

### 1. 关系命名规范

```python
# 好的关系命名
"是"                    # Qwen 是 语言模型
"是...的导师"           # 张三 是李四的导师
"使用"                  # OpenGuiclaw 使用 Qwen
"支持"                  # Qwen 支持 Function Calling
"位于"                  # 公司 位于 北京

# 避免的关系命名
"调用"                  # 临时动作
"正在使用"              # 瞬时状态
"可能是"                # 模糊关系
```

### 2. 去重策略

```python
# 添加前检查是否已存在
for t in kg._triples:
    if (t.subject == subject and 
        t.relation == relation and 
        t.object == obj):
        return t  # 已存在，跳过
```

### 3. 实体归一化

```python
# 统一实体名称
entity_aliases = {
    "Qwen3.5": "Qwen",
    "通义千问": "Qwen",
    "qwen": "Qwen"
}

def normalize_entity(entity: str) -> str:
    return entity_aliases.get(entity, entity)

# 添加时归一化
kg.add(
    normalize_entity("Qwen3.5"),
    "是",
    normalize_entity("语言模型")
)
```

### 4. 来源追踪

```python
# 记录三元组来源
kg.add("Qwen", "是", "语言模型", source="journal:2026-03-11")
kg.add("张三", "是...的导师", "李四", source="conversation")
kg.add("Python", "是", "编程语言", source="research:2026-03-11:Python")

# 查询时可以过滤来源
triples = [t for t in kg.list_all() if t.source.startswith("journal:")]
```

### 5. 集成到对话

```python
# 在对话中使用知识图谱
@skills.skill(
    name="query_knowledge",
    description="查询知识图谱，获取实体关系",
    parameters={
        "properties": {
            "entity": {"type": "string", "description": "实体名称"}
        },
        "required": ["entity"]
    },
    category="memory"
)
def query_knowledge(entity: str) -> str:
    context = kg.context_for_entity(entity)
    if not context:
        return f"知识图谱中没有关于 '{entity}' 的信息。"
    return context
```

## 故障排查

### 问题 1: 三元组重复

**症状**：相同的三元组被多次添加

**解决方案**：
```python
# 检查去重逻辑
def add(self, subject: str, relation: str, obj: str, source: str = "") -> Triple:
    # 去重检查
    for t in self._triples:
        if (t.subject == subject and 
            t.relation == relation and 
            t.object == obj):
            return t  # 已存在
    
    # 添加新三元组
    triple = Triple(subject, relation, obj, source)
    self._triples.append(triple)
    self._save_one(triple)
    return triple
```

### 问题 2: 查询无结果

**症状**：`query()` 返回空列表

**解决方案**：
```python
# 检查实体名称（大小写、空格）
print(kg.list_all())  # 查看所有三元组

# 使用模糊匹配
entity_lower = entity.lower()
entity_nospace = entity_lower.replace(" ", "")

def _matches(field: str) -> bool:
    fl = field.lower()
    return entity_lower in fl or entity_nospace in fl.replace(" ", "")
```

### 问题 3: 文件损坏

**症状**：加载时 JSON 解析错误

**解决方案**：
```python
# 备份并修复
import shutil
kg_file = Path("data/memory/knowledge_graph.jsonl")
backup = kg_file.with_suffix(".jsonl.bak")
shutil.copy2(kg_file, backup)

# 逐行解析，跳过损坏行
valid_triples = []
with open(kg_file, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        try:
            data = json.loads(line)
            valid_triples.append(Triple.from_dict(data))
        except json.JSONDecodeError as e:
            print(f"第 {i+1} 行损坏: {e}")

# 重写文件
with open(kg_file, "w", encoding="utf-8") as f:
    for t in valid_triples:
        f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
```

### 问题 4: 提取噪音过多

**症状**：LLM 提取了大量无用三元组

**解决方案**：
```python
# 调整提取 Prompt，强调"宁缺毋滥"
# 或者在代码中过滤
def filter_triples(triples: List[Dict]) -> List[Dict]:
    # 过滤掉临时动作
    action_verbs = ["调用", "执行", "运行", "打开", "关闭"]
    return [
        t for t in triples
        if not any(v in t["relation"] for v in action_verbs)
    ]
```

## 性能优化

### 1. 索引加速

```python
# 构建实体索引
_entity_index = {}  # entity -> [triple_indices]

def _build_index():
    for i, t in enumerate(kg._triples):
        _entity_index.setdefault(t.subject, []).append(i)
        _entity_index.setdefault(t.object, []).append(i)

# 查询时使用索引
def query_fast(entity: str) -> List[Triple]:
    indices = _entity_index.get(entity, [])
    return [kg._triples[i] for i in indices]
```

### 2. 批量写入

```python
# 累积三元组后批量写入
_pending_triples = []

def add_pending(subject: str, relation: str, obj: str):
    _pending_triples.append(Triple(subject, relation, obj))

def flush():
    with open(kg_file, "a", encoding="utf-8") as f:
        for t in _pending_triples:
            f.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")
    kg._triples.extend(_pending_triples)
    _pending_triples.clear()
```

### 3. 延迟加载

```python
# 只在需要时加载三元组
_loaded = False

def _ensure_loaded():
    global _loaded
    if not _loaded:
        kg._load()
        _loaded = True

def query(entity: str):
    _ensure_loaded()
    # 查询逻辑...
```

## 未来优化方向

1. **图数据库**：迁移到 Neo4j 或 SQLite 图扩展
2. **关系推理**：基于已知关系推导新关系
3. **实体消歧**：区分同名实体（如"苹果"公司 vs 水果）
4. **关系权重**：为三元组添加置信度分数
5. **时间维度**：支持时间范围查询（如"2026年的关系"）
6. **可视化**：生成知识图谱可视化图表
7. **导出/导入**：支持 RDF、GraphML 等标准格式
