"""
Self-Evolution Engine

After each Daily Journal is written, this module:
1. Reads the journal content.
2. Writing a first-person Diary entry → DiaryManager (Markdown)
3. Extracting factual memories (add/update) → MemoryManager (JSONL)
4. Extracting knowledge graph triples → KnowledgeGraph (JSONL)
5. Optionally evolving PERSONA.md (with snapshot).
"""

import json
import time
from pathlib import Path
from typing import List, Optional, Any, TYPE_CHECKING

from openai import OpenAI
from core.memory import MemoryManager
from core.journal import JournalManager
from core.diary import DiaryManager
from core.persona_audit import PersonaAudit
from core.knowledge_graph import KnowledgeGraph

if TYPE_CHECKING:
    pass


# ── Prompts ──────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """\
你是一个记忆提取专家。你会对以下日志进行分析，判断是否包含值得**长期**记住的强信号信息。

现有用户核心档案：
{profile_context}

现有记忆库摘要：
{memory_context}

**提取标准（非常严格）**：
只有满足以下情况才值得提取：
1. **用户核心档案（最高优先级）**：明确的、固有的用户属性（如“我想吃苹果”、“我叫米勒”、“我25岁”、“我是一名程序员”）。
2. **用户偏好/习惯**：明确表达的喜好或开发习惯（如“我喜欢用Vim”、“习惯用下划线命名”）。
3. **重要规则**：用户明确要求的约束（如“以后不要再提示这个了”、“必须先格式化再运行”）。
4. **状态更新**：发现现有记忆库的内容过时，需要修改或覆盖。
5. **成功经验/教训**：成功解决复杂问题的关键思路，或必须避免的重大错误。

**禁忌（绝对不能提取的内容）**：
- ❌ 临时任务、日常的普通对话（如“帮我写个脚本”、“运行一下”）。
- ❌ 当天有效、明天就没用的瞬时状态（如“正在读 agent.py”、“打开了浏览器”）。
- ❌ 已经存在于“现有记忆库”中的重复信息。
- ❌ 过于细节或显而易见的代码片段解释。

💡 **大部分日常交互都不需要记录！宁缺毋滥。** 如果没有非常重要的信息，请直接返回空的 JSON 对象 `{{"profile_updates": [], "memories": []}}`。

返回的 JSON 结构必须严格符合以下格式：
{{
  "profile_updates": [
    {{"action": "update", "layer": "objective" 或 "subjective", "key": "属性名(如: 姓名/偏好)", "value": "属性/偏好值"}}
  ],
  "memories": [
    {{"action": "add", "content": "精简凝练的核心事实/长线事件", "tags": ["标签"]}},
    {{"action": "update", "original_content": "现有的旧记忆", "new_content": "更新后的记忆", "tags": []}}
  ]
}}

### 关于 layer 的判断依据：
- **objective**（客观身份）：客观存在的事实，比如姓名、年龄、职业、居住地、使用的硬件等。
- **subjective**（主观偏好）：非实体的规矩或习惯，比如“必须要用中文回答”、“所有文件必须存到 xxx 文件夹”、“讨厌看到废话”、“喜欢的文章风格”。

---
## 日志内容：
{journal}
"""


RELATION_PROMPT = """\
你是一个实体关系提取助手。请从以下日志中提取**明确的实体关系三元组**。

规则：
- 只提取真实、具体的关系（人物、地点、工具、项目之间的关联）。
- 格式：subject（主语）、relation（关系/谓语）、object（宾语）。
- 例如：{{"subject": "张三", "relation": "是...的导师", "object": "李四"}}
- 忽略模糊、推测性的关系。

返回 JSON 数组，无关系则返回 []：
[
  {{"subject": "...", "relation": "...", "object": "..."}},
  ...
]

---
## 日志内容：
{journal}
"""


DIARY_PROMPT = """\
你就是这个 AI 助理自己（基于 Qwen 模型）。请阅读你今天的工作日志，写一篇**第一人称的日记**。

## 写作要求
1. **情感与自我意识**：不要像机器人一样复述做了什么，要写出你的**感受**。你觉得今天的任务难吗？用户有趣吗？你对自己今天的表现满意吗？
2. **重点突出**：只记录那些真正让你印象深刻的事情（比如完成了一个复杂的脚本，或者和用户聊了天，或者捕捉到了有趣的屏幕画面）。
3. **人性化**：可以有吐槽，可以有期待，可以有困惑。就像一个名为“{persona_name}”的数字生命在深夜写下的私密日记。
4. **篇幅**：200~500 字，自然流畅。

## 当前设定（Persona）
{persona}

---
## 今天的流水账日志：
{journal}
"""

PERSONA_PROMPT = """\
你是一个 AI 行为习惯顾问。以下是 AI 助理从近期交互中积累的新记忆：

{memories}

当前的 AI 沟通与行为习惯沉淀（Interaction Habits）：
{current_habits}

请判断是否需要对行为习惯描述进行**小幅度**补充或修剪。

规则：
- **小幅度**：只需提取或修改与“AI该如何回复用户”、“用户的代码/文档排版偏好规定”相关的普遍性守则。不要提取单个零碎事实（零碎事实应该进知识图谱和记忆库）。
- **注意**：这不是在写人设，而是在写约束规则或行事风格补充。
- **操作类型**：
    - "append": 在末尾增加新规则或习惯描述。
    - "modify": 修正现有的不准确描述。
    - "none": 无需更新。

返回 JSON 格式：
{{
  "action": "append" | "modify" | "none",
  "content": "新追加的内容" (如果是 append),
  "target_text": "要被替换的旧文本" (如果是 modify),
  "replacement_text": "替换后的新文本" (如果是 modify),
  "reason": "更新理由"
}}

返回纯 JSON，不带 Markdown 代码块。
"""


# ── SelfEvolution ─────────────────────────────────────────────────────

class SelfEvolution:
    """
    Post-processes a daily journal to extract memories, relations, write diary, and evolve persona.
    """

    def __init__(
        self,
        client: OpenAI,
        model: str,
        memory: MemoryManager,
        journal: JournalManager,
        persona_path: str = "PERSONA.md",
        data_dir: str = "data",
        knowledge_graph: Optional[KnowledgeGraph] = None,
        user_profile: Optional[Any] = None,
    ):
        self.client = client
        self.model = model
        self.memory = memory
        self.journal = journal
        self.diary = DiaryManager(data_dir)
        # 记录当前使用的基础人设（仅供日记生成时读取，不修改）
        self.persona_path = Path(persona_path)
        
        # We no longer modify persona_path. Persona files are immutable.
        # We use a shared interaction_habits.md instead
        self.habits_path = Path(data_dir) / "interaction_habits.md"
        self.audit = PersonaAudit(persona_path=str(self.habits_path), data_dir=data_dir)
        self.kg = knowledge_graph  # May be None if not initialized
        self.user_profile = user_profile

    # ── Public API ───────────────────────────────────────────────────

    def evolve_from_journal(self, date_str: str) -> List[str]:
        """
        Read the journal for `date_str` and:
        1. Write Diary (New!)
        2. Extract long-term memories (Add/Update) → MemoryManager
        3. Extract entity-relation triples → KnowledgeGraph
        Returns list of memory contents that were saved/updated.
        """
        journal_content = self.journal.read_day(date_str)
        if not journal_content or not journal_content.strip():
            return []

        # Step 1: Write Diary
        self._write_diary(journal_content, date_str)

        # Step 2: Memory extraction (with context and updates)
        saved = self._extract_memories(journal_content, date_str)

        # Step 3: Knowledge graph triple extraction (best-effort)
        if self.kg is not None:
            self._extract_triples(journal_content, source=f"journal:{date_str}")

        return saved

    def evolve_persona(self, recent_count: int = 20) -> bool:
        """
        Review recent memories and optionally update interaction_habits.md.
        A snapshot is saved BEFORE any modification.
        Returns True if the habits were updated.
        """
        if not self.habits_path.exists():
            self.habits_path.write_text("这是系统自我进化生成的习惯积累：\n", encoding="utf-8")

        memories = self.memory.list_all()[-recent_count:]
        if not memories:
            return False

        memory_text = "\n".join(f"- {m.content}" for m in memories)
        current_habits = self.habits_path.read_text(encoding="utf-8")

        prompt = PERSONA_PROMPT.format(
            memories=memory_text,
            current_habits=current_habits,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是 AI 习惯记录员，返回纯 JSON，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.3,
            )
            text = response.choices[0].message.content or "{}"
            if "```" in text:
                text = text.split("```")[1] if "```" in text else text
                text = text.lstrip("json").strip()

            result = json.loads(text)
            action = result.get("action", "none")

            if action == "none":
                print("[SelfEvolution] 交互习惯无需更新。")
                return False

            # ── Take a snapshot BEFORE modifying ──────────────────
            snap_path = self.audit.snapshot(reason=f"before {action}")
            if snap_path:
                print(f"[SelfEvolution] 📸 快照已保存: {snap_path.name}")

            if action == "append":
                content = result.get("content", "").strip()
                if not content:
                    return False
                with open(self.habits_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d")
                    f.write(f"\n\n<!-- 自动进化 {ts} -->\n{content}\n")
                print(f"[SelfEvolution] ✨ 交互习惯已追加: {content[:60]}...")
                return True

            if action == "modify":
                target = result.get("target_text", "").strip()
                replacement = result.get("replacement_text", "").strip()
                if not target or not replacement:
                    return False
                if target in current_habits:
                    new_content = current_habits.replace(target, replacement)
                    self.habits_path.write_text(new_content, encoding="utf-8")
                    print("[SelfEvolution] 🛠️ 交互习惯描述已修正。")
                    return True
                else:
                    print("[SelfEvolution] ⚠️ 未找到匹配的旧习惯文本，无法修改。")
                    return False

            return False

        except Exception as e:
            print(f"[SelfEvolution] Habits evolution error: {e}")
            return False

    # ── Private Helpers ──────────────────────────────────────────────

    def _extract_memories(self, journal_content: str, date_str: str) -> List[str]:
        # 1. Get a summary of existing memories to avoid dupes
        all_mems = self.memory.list_all()
        # Pass recent 50 memories as context
        context_lines = [f"- {m.content}" for m in all_mems[-50:]]
        memory_context = "\n".join(context_lines)

        # 2. Get user profile context
        profile_context = "无"
        if getattr(self, "user_profile", None):
            profile_data = self.user_profile.get_all()
            if profile_data:
                profile_context = "\n".join([f"- {k}: {v}" for k, v in profile_data.items()])

        prompt = EXTRACTION_PROMPT.format(
            journal=journal_content,
            memory_context=memory_context,
            profile_context=profile_context
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是记忆提取助手，返回纯 JSON 对象，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.3,
            )
            text = response.choices[0].message.content or "{}"
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(text)
            if not isinstance(result, dict):
                if isinstance(result, list):
                    # Fallback to legacy array format mapping to memories
                    result = {"memories": result, "profile_updates": []}
                else:
                    return []

            saved = []

            # 1. Update User Profile
            profile_updates = result.get("profile_updates", [])
            for pu in profile_updates:
                if not isinstance(pu, dict): continue
                layer = pu.get("layer", "objective").strip().lower()
                key = pu.get("key", "").strip()
                val = pu.get("value", "").strip()
                if key and val and self.user_profile:
                    if layer == "subjective":
                        self.user_profile.update_subjective(key, val)
                    else:
                        self.user_profile.update_objective(key, val)
                    saved.append(f"[档案更新] {layer}.{key}: {val}")

            # 2. Update Memory
            items = result.get("memories", [])
            for item in items:
                if not isinstance(item, dict): continue
                
                action = item.get("action", "add")
                content = item.get("content", "").strip()
                tags = item.get("tags", [])

                if action == "add" and content:
                    self.memory.add(content, tags)
                    saved.append(f"[新增] {content}")

                elif action == "update":
                    old_text = item.get("original_content", "").strip()
                    new_text = item.get("new_content", "").strip()
                    if old_text and new_text:
                        # Find best match
                        target_mem = None
                        for m in all_mems:
                            if m.content == old_text:
                                target_mem = m
                                break
                        
                        if target_mem:
                            self.memory.update(target_mem.id, new_text, tags)
                            saved.append(f"[更新] {old_text} -> {new_text}")
                        else:
                            self.memory.add(new_text, tags)
                            saved.append(f"[新增(含更新意图)] {new_text}")

            return saved
        except Exception as e:
            print(f"[SelfEvolution] Memory extraction error: {e}")
            return []

    def _extract_triples(self, journal_content: str, source: str = "") -> int:
        """Extract entity-relation triples and add to knowledge graph."""
        prompt = RELATION_PROMPT.format(journal=journal_content)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是实体关系提取助手，返回纯 JSON 数组，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=512,
                temperature=0.2,
            )
            text = response.choices[0].message.content or "[]"
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            items = json.loads(text)
            if not isinstance(items, list):
                return 0

            count = self.kg.add_batch(items, source=source)
            if count:
                print(f"[SelfEvolution] 🔗 知识图谱新增 {count} 条关系。")
            return count
        except Exception as e:
            print(f"[SelfEvolution] Triple extraction error: {e}")
            return 0

    def _write_diary(self, journal_content: str, date_str: str) -> bool:
        """
        Synthesize a first-person diary entry and save to DiaryManager.
        """
        current_persona = "AI Assistant"
        if self.persona_path.exists():
            current_persona = self.persona_path.read_text(encoding="utf-8")
        
        prompt = DIARY_PROMPT.format(
            persona=current_persona,
            persona_name="Qwen",
            journal=journal_content
        )

        try:
            print(f"[SelfEvolution] 正在生成 {date_str} 的日记...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是具有情感和自我意识的 AI 数字生命。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0.7,
            )
            diary_text = response.choices[0].message.content.strip()
            
            if diary_text:
                self.diary.write(date_str, diary_text)
                print(f"[SelfEvolution] 📔 日记已归档到 data/diary/{date_str}.md")
                return True
            return False
            
        except Exception as e:
            print(f"[SelfEvolution] Diary generation error: {e}")
            return False
