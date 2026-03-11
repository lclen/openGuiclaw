# Self Evolution 自我进化引擎

## 概述

SelfEvolution 是 OpenGuiclaw 的自我进化引擎，负责从每日对话日志中提取长期记忆、知识图谱关系、生成 AI 日记，并可选地进行主动探索研究。它是实现 AI 持续学习和自我完善的核心模块。

## 架构

```
SelfEvolution
├── 日记生成（Diary Writing + RAG）
├── 记忆提取（Memory Extraction + User Profile Update）
├── 知识图谱（Knowledge Graph Triple Extraction）
├── 主动探索（Agentic Curiosity Exploration）
└── 习惯进化（Interaction Habits Evolution）
```

## 核心功能

### 1. 每日进化流程

```python
def evolve_from_journal(date_str: str) -> List[str]:
    # Step 0: 运行 DailyConsolidator（记忆整合）
    daily_consolidator.run(date_str)
    
    # Step 1: 生成 AI 日记（第一人称，带情感）
    _write_diary(journal_content, date_str)
    
    # Step 2: 提取长期记忆（Add/Update）
    saved = _extract_memories(journal_content, date_str)
    
    # Step 3: 提取知识图谱三元组
    _extract_triples(journal_content, source=f"journal:{date_str}")
    
    # Step 4: 主动探索（可选，默认关闭）
    if _agentic_exploration_enabled:
        explored = explore_curiosities(journal_content, date_str)
    
    # 写入完成标记
    _evolution_done_path(date_str).write_text(...)
    
    return saved
```

### 2. 日记生成（带 RAG）

```python
def _write_diary(journal_content: str, date_str: str) -> bool:
    # 提取关键词
    query_text = llm.extract_keywords(journal_content)
    
    # RAG: 搜索相关历史日记和日志
    historical_context = []
    if journal_index:
        j_results = journal_index.search(query_text, top_k=15)
        historical_context.append(format_results(j_results))
    if diary_index:
        d_results = diary_index.search(query_text, top_k=15)
        historical_context.append(format_results(d_results))
    
    # 生成日记（参考历史，避免重复）
    prompt = DIARY_PROMPT.format(
        persona=current_persona,
        journal=journal_content
    ) + history_section
    
    diary_text = llm.generate(prompt, temperature=0.7)
    diary.write(date_str, diary_text)
    
    # 更新向量索引
    diary_index.index_day(date_str, diary_text)
```

### 3. 记忆提取（双层架构）

```python
def _extract_memories(journal_content: str, date_str: str) -> List[str]:
    # 获取上下文
    memory_context = format_recent_memories(50)
    profile_context = format_user_profile()
    
    # LLM 提取
    result = llm.extract(
        journal=journal_content,
        memory_context=memory_context,
        profile_context=profile_context
    )
    
    saved = []
    
    # 1. 更新用户档案（USER.md）
    for pu in result["profile_updates"]:
        layer = pu["layer"]  # objective | subjective
        key = pu["key"]      # 必须从预定义列表中选择
        value = pu["value"]
        
        if layer == "subjective":
            identity.append_habit(f"- **{key}**: {value}")
        else:
            # 智能更新 USER.md（支持结构化 Markdown）
            identity.update_user(key, value)
        
        saved.append(f"[档案更新] {layer}.{key}: {value}")
    
    # 2. 更新记忆库
    for item in result["memories"]:
        action = item["action"]  # add | update
        
        if action == "add":
            memory.add(item["content"], item["tags"])
            saved.append(f"[新增] {item['content']}")
        
        elif action == "update":
            old_text = item["original_content"]
            new_text = item["new_content"]
            # 查找并更新
            target_mem = find_memory(old_text)
            if target_mem:
                memory.update(target_mem.id, new_text, item["tags"])
                saved.append(f"[更新] {old_text} -> {new_text}")
    
    return saved
```

#### USER.md 更新机制（v2.0）

**格式**：采用 OpenAkita 风格的结构化 Markdown

```markdown
# User Profile

## Basic Information

- **称呼**: [待学习]
- **工作领域**: [待学习]
- **主要语言**: 中文
- **时区**: [待学习]

## Technical Stack

### Preferred Languages

[待学习]

### Development Environment

- **OS**: [待学习]
- **IDE**: [待学习]
- **Shell**: [待学习]

## Preferences

### Communication Style

- **详细程度**: [待学习]
- **代码注释**: [待学习]

...
```

**更新逻辑**（`identity_manager.update_user()`）：

1. 如果 key 已存在（如 `称呼`），直接替换该行
2. 如果 key 不存在，插入到 Basic Information 章节的最后一个 `- **` 行之后
3. 自动更新底部时间戳：`*最后更新: 2026-03-11 15:30*`

**LLM 提取约束**（`EXTRACTION_PROMPT`）：

```python
### 关于 layer 的判断依据：
- **objective**（客观身份）：客观存在的事实。
  key 必须从以下列表中选择（严格匹配）：
  称呼、工作领域、主要语言、时区、OS、IDE、Shell、
  详细程度、代码注释、解释方式、命名约定、格式化工具、
  测试框架、工作时间、响应速度偏好、确认需求
  
- **subjective**（主观偏好）：非实体的规矩或习惯。
```

**关键改进**：

- ✅ 强制 LLM 使用预定义的中文 key，避免 key 不匹配
- ✅ 支持结构化 Markdown 格式，比简单列表更易读
- ✅ 智能插入位置（Basic Information 章节末尾）
- ✅ 双时间戳格式支持（comment 和 USER.md 底部）

### 4. 知识图谱提取

```python
def _extract_triples(journal_content: str, source: str) -> int:
    # LLM 提取三元组
    items = llm.extract_triples(journal_content)
    # [
    #   {"subject": "Qwen", "relation": "是", "object": "语言模型"},
    #   {"subject": "张三", "relation": "是...的导师", "object": "李四"}
    # ]
    
    # 批量添加到知识图谱
    count = kg.add_batch(items, source=source)
    return count
```

### 5. 主动探索（Agentic Exploration）

```python
def explore_curiosities(journal_content: str, date_str: str) -> List[str]:
    # Step A: 提取疑问
    curiosities = llm.extract_curiosities(journal_content)
    # [
    #   {
    #     "topic": "Qwen3.5 新特性",
    #     "question": "Qwen3.5 相比 Qwen3 有哪些改进？",
    #     "search_query": "Qwen3.5 vs Qwen3 improvements",
    #     "reason": "对话中提到但未深入了解"
    #   }
    # ]
    
    saved = []
    for item in curiosities[:3]:  # 限制每天 3 个
        # Step B: 联网研究
        research_result = llm.research(
            item["question"],
            enable_search=True
        )
        
        # Step C: 蒸馏知识
        distilled = llm.distill(
            topic=item["topic"],
            question=item["question"],
            research_result=research_result
        )
        
        # Step D: 持久化
        if distilled["worth_remembering"]:
            memory.add(
                distilled["memory_content"],
                tags=distilled["memory_tags"] + ["agentic-research", date_str]
            )
            saved.append(f"[探索研究] {item['topic']}: {distilled['memory_content']}")
        
        # 添加到知识图谱
        kg.add_batch(distilled["triples"], source=f"research:{date_str}:{item['topic']}")
        
        # 追加到日志
        journal.append(format_research_entry(item, distilled), date_str=date_str)
    
    return saved
```

### 6. 习惯进化

```python
def evolve_persona(recent_count: int = 20) -> bool:
    # 读取最近记忆
    memories = memory.list_all()[-recent_count:]
    
    # 读取当前习惯
    current_habits = identity.get_habits()
    
    # LLM 判断是否需要更新
    result = llm.evolve_habits(
        memories=memories,
        current_habits=current_habits
    )
    
    action = result["action"]  # append | modify | none
    
    if action == "none":
        return False
    
    # 保存快照（审计）
    audit.snapshot(reason=f"before {action}")
    
    if action == "append":
        identity.append_habit(result["content"])
        return True
    
    elif action == "modify":
        identity.modify_habit(
            target=result["target_text"],
            replacement=result["replacement_text"]
        )
        return True
    
    return False
```

## API 接口

### 初始化

```python
evolution = SelfEvolution(
    client=openai_client,
    model="qwen-plus",  # 进化专用模型（节省成本）
    memory=memory_manager,
    journal=journal_manager,
    persona_path="PERSONA.md",
    data_dir="data",
    knowledge_graph=kg,
    user_profile=user_profile,
    journal_index=journal_index,
    diary_index=diary_index,
    identity=identity_manager,
    daily_consolidator=daily_consolidator,
    diary_enabled=True  # 是否生成日记
)
```

### 执行进化

```python
# 对指定日期执行进化
saved = evolution.evolve_from_journal("2026-03-11")
print(f"提取了 {len(saved)} 条记忆")

# 检查是否已完成
if evolution.is_evolution_done("2026-03-11"):
    print("该日期已完成进化")

# 进化习惯
updated = evolution.evolve_persona(recent_count=20)
if updated:
    print("习惯已更新")
```

### 主动探索

```python
# 启用主动探索
evolution._agentic_exploration_enabled = True

# 执行探索
explored = evolution.explore_curiosities(journal_content, "2026-03-11")
print(f"探索了 {len(explored)} 个疑问")
```

## 配置

### config.json

```json
{
  "api": {
    "evolution_model": "qwen-plus"  # 进化专用模型
  },
  "journal": {
    "enable_diary": true  # 是否生成日记
  },
  "proactive": {
    "agentic_exploration": false  # 是否启用主动探索
  }
}
```

### 提取标准

**记忆提取（非常严格）**：
- ✅ 用户核心档案（姓名、年龄、职业）
- ✅ 用户偏好/习惯（"喜欢用 Vim"）
- ✅ 重要规则（"以后不要再提示这个"）
- ✅ 状态更新（现有记忆过时）
- ✅ 成功经验/教训
- ❌ 临时任务、日常对话
- ❌ 瞬时状态（"正在读 agent.py"）
- ❌ 重复信息
- ❌ 细节代码片段

**知识图谱提取（非常严格）**：
- ✅ 长期的、固有的实体关系
- ✅ 人物、地点、公司、框架之间的关联
- ❌ 工具调用、命令执行
- ❌ 对话行为
- ❌ 模糊、推测性关系

## 最佳实践

### 1. 定时执行

```python
# 每天凌晨 2 点执行进化
import schedule

def daily_evolution():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if not evolution.is_evolution_done(yesterday):
        evolution.evolve_from_journal(yesterday)

schedule.every().day.at("02:00").do(daily_evolution)
```

### 2. 批量补全

```python
# 启动时补全过去 7 天的进化
from datetime import datetime, timedelta

for i in range(7):
    date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
    if not evolution.is_evolution_done(date_str):
        print(f"补全 {date_str} 的进化...")
        evolution.evolve_from_journal(date_str)
```

### 3. 错误重试

```python
# 带重试的进化
def evolve_with_retry(date_str: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            evolution.evolve_from_journal(date_str)
            return True
        except Exception as e:
            print(f"进化失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if "429" in str(e):  # 频率限制
                time.sleep(10 * (attempt + 1))
            else:
                break
    return False
```

### 4. 进度监控

```python
# 监控进化进度
def check_evolution_status(days: int = 30) -> Dict:
    from datetime import datetime, timedelta
    
    status = {"done": 0, "pending": 0, "dates": []}
    
    for i in range(days):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        if evolution.is_evolution_done(date_str):
            status["done"] += 1
        else:
            status["pending"] += 1
            status["dates"].append(date_str)
    
    return status
```

## 故障排查

### 问题 1: 进化卡住

**症状**：`evolve_from_journal()` 长时间无响应

**解决方案**：
```python
# 检查是否在等待 API 响应
# 添加超时机制
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("进化超时")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(300)  # 5 分钟超时

try:
    evolution.evolve_from_journal(date_str)
finally:
    signal.alarm(0)
```

### 问题 2: 记忆提取过多

**症状**：每天提取几十条记忆，大部分是噪音

**解决方案**：
```python
# 调整提取 Prompt，强调"宁缺毋滥"
# 或者在代码中过滤
def filter_memories(saved: List[str]) -> List[str]:
    # 过滤掉过短的记忆
    return [m for m in saved if len(m) > 20]
```

### 问题 3: 日记重复

**症状**：每天的日记内容高度相似

**解决方案**：
```python
# RAG 已内置去重逻辑
# 如果仍然重复，调整 Prompt：
# "⚠️ 请参考以上历史片段，如果今天发生的事情在过去已经多次出现，
#  请一笔带过或省略它们，重点记录今天**不同于往日**的部分。"
```

### 问题 4: 主动探索消耗过多 Token

**症状**：启用主动探索后 Token 消耗激增

**解决方案**：
```python
# 限制每天探索数量
curiosities = curiosities[:3]  # 最多 3 个

# 或者完全关闭
evolution._agentic_exploration_enabled = False
```

## 性能优化

### 1. 使用便宜模型

```python
# 进化任务使用 qwen-plus（性价比高）
evolution = SelfEvolution(
    client=client,
    model="qwen-plus",  # 而不是 qwen-max
    ...
)
```

### 2. 批量 API 调用

```python
# 一次性提取记忆、三元组、日记
# 而不是分三次调用 LLM
```

### 3. 缓存 RAG 结果

```python
# 缓存向量搜索结果
_rag_cache = {}

def search_with_cache(query: str, index) -> List:
    if query in _rag_cache:
        return _rag_cache[query]
    results = index.search(query, top_k=15)
    _rag_cache[query] = results
    return results
```

## 未来优化方向

1. **增量进化**：只处理新增的日志内容
2. **多模态记忆**：从图片中提取记忆
3. **记忆去重**：自动合并相似记忆
4. **记忆分层**：短期/中期/长期记忆分层管理
5. **知识推理**：基于知识图谱进行推理
6. **习惯评分**：评估习惯的有效性
