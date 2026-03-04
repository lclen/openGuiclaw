"""
Self-Evolution Engine

After each Daily Journal is written, this module:
1. Reads the journal content.
2. Writing a first-person Diary entry → DiaryManager (Markdown)
3. Extracting factual memories (add/update) → MemoryManager (JSONL)
4. Extracting knowledge graph triples → KnowledgeGraph (JSONL)
5. Agentic exploration: autonomously researches unresolved questions from the journal
   via built-in web search, distills findings into deep memories and KG triples.
6. Optionally evolving interaction_habits.md (with snapshot).
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Any, TYPE_CHECKING

from openai import OpenAI
from core.memory import MemoryManager
from core.journal import JournalManager
from core.diary import DiaryManager
from core.persona_audit import PersonaAudit
from core.knowledge_graph import KnowledgeGraph

if TYPE_CHECKING:
    from core.identity_manager import IdentityManager
    from core.daily_consolidator import DailyConsolidator


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
4. **篇幅**：控制在 1000 字以内，可以尽情加入细节描写和心理活动，使其自然丰满且真实。

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


CURIOSITY_EXTRACT_PROMPT = """\
你是一个好奇心挖掘专家。请阅读以下今日日志，找出其中**值得深入研究**的疑问、未解问题或感兴趣的新概念。

筛选标准（严格）：
- 对话中明确出现"不知道"、"不确定"、"好像是"、"听说"等模糊表述背后的知识点。
- 用户或 AI 提到但未深入展开的技术概念、工具、方法论。
- 解决问题时绕过了某个知识盲区（用了 workaround 但没搞清楚根本原因）。
- 明确值得长期了解的领域动态（如某个新框架、新模型、新工具）。

禁止提取：
- 已经在对话中完整解释清楚的内容。
- 纯粹的日常闲聊或情绪表达。
- 过于宽泛的话题（如"了解一下 Python"）。

每个疑问需要给出一个**精准的搜索查询**，用于联网检索。

返回 JSON 数组，无疑问则返回 []：
[
  {{
    "topic": "简短的主题名称",
    "question": "具体的疑问描述",
    "search_query": "用于联网搜索的精准查询词（中英文均可）",
    "reason": "为什么值得研究"
  }},
  ...
]

返回纯 JSON，不带 Markdown 代码块。

---
## 今日日志：
{journal}
"""


RESEARCH_DISTILL_PROMPT = """\
你是一个知识蒸馏专家。你刚刚对以下问题进行了联网研究，请将研究结果提炼为**高质量的长期知识**。

## 原始疑问
主题：{topic}
问题：{question}

## 联网研究结果
{research_result}

## 提炼要求
1. **核心结论**：用 1-3 句话概括最重要的发现，去除噪音。
2. **实体关系**：提取研究中涉及的实体关系三元组（工具/概念/人物之间的关联）。
3. **记忆价值判断**：这个知识是否值得长期记忆？（是/否 + 理由）

返回 JSON 格式：
{{
  "summary": "核心结论（1-3句）",
  "worth_remembering": true 或 false,
  "memory_content": "如果值得记忆，写出精炼的记忆内容（不超过100字）",
  "memory_tags": ["标签1", "标签2"],
  "triples": [
    {{"subject": "...", "relation": "...", "object": "..."}}
  ]
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
        journal_index=None,
        diary_index=None,
        identity=None,              # IdentityManager | None
        daily_consolidator=None,    # DailyConsolidator | None
    ):
        self.client = client
        self.model = model
        self.memory = memory
        self.journal = journal
        self.diary = DiaryManager(data_dir)
        self.persona_path = Path(persona_path)
        self.identity = identity
        self.daily_consolidator = daily_consolidator

        # habits_path: use identity layer if available, else legacy file
        if identity is not None:
            self.habits_path = identity.habits_path
        else:
            self.habits_path = Path(data_dir) / "interaction_habits.md"

        self.audit = PersonaAudit(persona_path=str(self.habits_path), data_dir=data_dir)
        self.kg = knowledge_graph
        self.user_profile = user_profile
        self.journal_index = journal_index
        self.diary_index = diary_index
        self._agentic_exploration_enabled = False

    def _call_api(self, messages: List[Dict[str, str]], **kwargs) -> Optional[str]:
        """带重试逻辑的 API 调用辅助函数。"""
        retry_count = 0
        while retry_count < 3:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    **kwargs
                )
                return response.choices[0].message.content
            except Exception as e:
                err_msg = str(e).lower()
                if "429" in err_msg or "limit" in err_msg:
                    retry_count += 1
                    wait_time = 5 * retry_count
                    print(f"[SelfEvolution] 遇到频率限制 (429)，{wait_time} 秒后进行第 {retry_count} 次重试...")
                    time.sleep(wait_time)
                    continue
                # 其他错误直接抛出或记录
                print(f"[SelfEvolution] API 调用出错: {e}")
                break
        return None

    # ── Public API ───────────────────────────────────────────────────

    def evolve_from_journal(self, date_str: str) -> List[str]:
        """
        Read the journal for `date_str` and:
        1. Write Diary
        2. Extract long-term memories (Add/Update) → MemoryManager
        3. Extract entity-relation triples → KnowledgeGraph
        4. Agentic exploration: research unresolved curiosities → MemoryManager + KnowledgeGraph
        Returns list of memory contents that were saved/updated.
        """
        journal_content = self.journal.read_day(date_str)
        if not journal_content or not journal_content.strip():
            return []

        # Step 0: Run DailyConsolidator if injected and not yet run today
        if self.daily_consolidator and self.daily_consolidator.should_run(date_str):
            try:
                self.daily_consolidator.run(date_str)
            except Exception as e:
                print(f"[SelfEvolution] DailyConsolidator error: {e}")

        # Step 1: Write Diary
        self._write_diary(journal_content, date_str)

        # Step 2: Memory extraction (with context and updates)
        saved = self._extract_memories(journal_content, date_str)

        # Step 3: Knowledge graph triple extraction (best-effort)
        if self.kg is not None:
            self._extract_triples(journal_content, source=f"journal:{date_str}")

        # Step 4: Agentic curiosity exploration (best-effort, disabled by default)
        if getattr(self, "_agentic_exploration_enabled", False):
            explored = self.explore_curiosities(journal_content, date_str)
            saved.extend(explored)

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
        # Read habits from identity layer if available, else from file
        if self.identity is not None:
            current_habits = self.identity.get_habits()
        else:
            current_habits = self.habits_path.read_text(encoding="utf-8")

        prompt = PERSONA_PROMPT.format(
            memories=memory_text,
            current_habits=current_habits,
        )

        try:
            text = self._call_api(
                messages=[
                    {"role": "system", "content": "你是 AI 习惯记录员，返回纯 JSON，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
                temperature=0.3,
            ) or "{}"
            if "```" in text:
                import re as _re
                text = _re.sub(r"^```[a-z]*\n?", "", text.strip())
                text = _re.sub(r"\n?```$", "", text).strip()

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
                if self.identity is not None:
                    ts = time.strftime("%Y-%m-%d")
                    self.identity.append_habit(f"<!-- 自动进化 {ts} -->\n{content}")
                else:
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
                if self.identity is not None:
                    success = self.identity.modify_habit(target, replacement)
                else:
                    if target in current_habits:
                        new_content = current_habits.replace(target, replacement)
                        self.habits_path.write_text(new_content, encoding="utf-8")
                        success = True
                    else:
                        success = False
                if success:
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

    def explore_curiosities(self, journal_content: str, date_str: str) -> List[str]:
        """
        Agentic exploration step: extract unresolved questions from the journal,
        research each one via built-in web search, then distill findings into
        long-term memories and knowledge graph triples.

        Returns a list of memory content strings that were saved.
        """
        # Step A: Extract curiosities from journal
        extract_prompt = CURIOSITY_EXTRACT_PROMPT.format(journal=journal_content)
        try:
            raw = self._call_api(
                messages=[
                    {"role": "system", "content": "你是好奇心挖掘专家，返回纯 JSON 数组，不加代码块。"},
                    {"role": "user", "content": extract_prompt},
                ],
                max_tokens=1024,
                temperature=0.3,
            ) or "[]"
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            curiosities = json.loads(raw)
            if not isinstance(curiosities, list):
                return []
        except Exception as e:
            print(f"[SelfEvolution] Curiosity extraction error: {e}")
            return []

        if not curiosities:
            print(f"[SelfEvolution] {date_str}: no curiosities found, skipping exploration.")
            return []

        # Cap at 3 topics per day to avoid excessive API usage
        curiosities = curiosities[:3]
        print(f"[SelfEvolution] {date_str}: exploring {len(curiosities)} curiosit{'y' if len(curiosities) == 1 else 'ies'}...")

        saved = []

        # Step B: Research each curiosity via web search
        for item in curiosities:
            topic = item.get("topic", "").strip()
            question = item.get("question", "").strip()
            search_query = item.get("search_query", question).strip()
            if not topic or not question:
                continue

            print(f"[SelfEvolution] Researching: {topic} — {search_query}")
            time.sleep(2)  # brief pause between searches to avoid rate limits

            try:
                research_resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是一个严谨的研究助手。请针对用户的问题进行深入研究，"
                                "综合多方信息给出准确、有深度的回答。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"请深入研究以下问题并给出详细解答：\n\n"
                                f"主题：{topic}\n"
                                f"问题：{question}\n"
                                f"搜索关键词：{search_query}"
                            ),
                        },
                    ],
                    max_tokens=2048,
                    temperature=0.4,
                    extra_body={"enable_search": True},
                )
                research_result = research_resp.choices[0].message.content or ""
            except Exception as e:
                print(f"[SelfEvolution] Research API error for '{topic}': {e}")
                continue

            if not research_result.strip():
                continue

            # Step C: Distill research into structured knowledge
            distill_prompt = RESEARCH_DISTILL_PROMPT.format(
                topic=topic,
                question=question,
                research_result=research_result[:3000],  # cap to avoid huge prompts
            )
            try:
                distill_raw = self._call_api(
                    messages=[
                        {"role": "system", "content": "你是知识蒸馏专家，返回纯 JSON，不加代码块。"},
                        {"role": "user", "content": distill_prompt},
                    ],
                    max_tokens=512,
                    temperature=0.2,
                ) or "{}"
                if distill_raw.startswith("```"):
                    distill_raw = distill_raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                distilled = json.loads(distill_raw)
            except Exception as e:
                print(f"[SelfEvolution] Distill error for '{topic}': {e}")
                continue

            # Step D: Persist to memory and knowledge graph
            if distilled.get("worth_remembering") and distilled.get("memory_content"):
                content = distilled["memory_content"].strip()
                tags = distilled.get("memory_tags", []) + ["agentic-research", date_str]
                self.memory.add(content, tags)
                saved.append(f"[探索研究] {topic}: {content}")
                print(f"[SelfEvolution] Research memory saved: {content[:80]}...")

            if self.kg is not None:
                triples = distilled.get("triples", [])
                if triples:
                    count = self.kg.add_batch(triples, source=f"research:{date_str}:{topic}")
                    if count:
                        print(f"[SelfEvolution] Research KG: +{count} triples for '{topic}'.")

            # Also append the full research result to the journal for future reference
            research_entry = (
                f"\n\n---\n**[主动探索: {topic}]** ({date_str})\n"
                f"疑问：{question}\n\n"
                f"研究摘要：{distilled.get('summary', research_result[:500])}\n"
            )
            self.journal.append(research_entry, date_str=date_str)

        return saved

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
                lines_p = []
                for layer, items in profile_data.items():
                    if isinstance(items, dict) and items:
                        lines_p.append(f"[{layer}]")
                        lines_p.extend([f"  - {k}: {v}" for k, v in items.items()])
                profile_context = "\n".join(lines_p) if lines_p else "无"

        prompt = EXTRACTION_PROMPT.format(
            journal=journal_content,
            memory_context=memory_context,
            profile_context=profile_context
        )
        try:
            text = self._call_api(
                messages=[
                    {"role": "system", "content": "你是记忆提取助手，返回纯 JSON 对象，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1024,
                temperature=0.3,
            ) or "{}"
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
                if key and val:
                    if self.identity is not None:
                        # Route through identity layer
                        if layer == "subjective":
                            self.identity.append_habit(f"- **{key}**: {val}")
                        else:
                            self.identity.update_user(key, val)
                    elif self.user_profile:
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
            text = self._call_api(
                messages=[
                    {"role": "system", "content": "你是实体关系提取助手，返回纯 JSON 数组，不加代码块。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=512,
                temperature=0.2,
            ) or "[]"
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
        Uses RAG to search related past journal/diary entries and inject them
        as context so the AI can skip repetitive daily routines.
        """
        current_persona = "AI Assistant"
        if self.persona_path.exists():
            current_persona = self.persona_path.read_text(encoding="utf-8")

        # ── RAG: 搜索与今天日志相关的历史日记/日志片段 ──
        historical_parts = []
        
        # 让 AI 提取写日记所需的回忆搜索词
        query_text = ""
        try:
            print(f"[SelfEvolution] 🔍 正在提取写日记所需的回忆搜索词...")
            q_resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个精确的关键词提取器。请阅读今天的日志记录，提取出 3-5 个最重要的核心名词、项目名或核心事件（以空格分隔），总字数限制在 30 个字以内，不要多余解释。"},
                    {"role": "user", "content": journal_content[:4000]} # 截取前4000字符提取关键词
                ],
                max_tokens=100,
                temperature=0.3,
            )
            query_text = q_resp.choices[0].message.content.strip()
            print(f"[SelfEvolution] 🔑 提取的日记搜索词: {query_text}")
        except Exception as e:
            print(f"[SelfEvolution] ⚠️ 提取搜索词失败: {e}")
            query_text = journal_content[:1000]

        if query_text and self.journal_index:
            try:
                j_results = self.journal_index.search(query_text, top_k=15)
                j_filtered = [r for r in j_results if r["date"] != date_str]
                if j_filtered:
                    j_lines = [f"- [{r['date']}] {r['text'][:150]}..." for r in j_filtered]
                    historical_parts.append("【相关历史日志片段】\n" + "\n".join(j_lines))
            except Exception as e:
                print(f"[SelfEvolution] Journal RAG error: {e}")

        if query_text and self.diary_index:
            try:
                d_results = self.diary_index.search(query_text, top_k=15)
                d_filtered = [r for r in d_results if r["date"] != date_str]
                if d_filtered:
                    d_lines = [f"- [{r['date']}] {r['text'][:150]}..." for r in d_filtered]
                    historical_parts.append("【相关历史日记片段】\n" + "\n".join(d_lines))
            except Exception as e:
                print(f"[SelfEvolution] Diary RAG error: {e}")

        historical_context = "\n\n".join(historical_parts)
        history_section = ""
        if historical_context:
            history_section = (
                f"\n\n## 相关的过往记忆参考\n"
                f"{historical_context}\n\n"
                f"⚠️ 请参考以上历史片段，如果今天发生的事情（如继续进行某个项目、日常代码调试）"
                f"在过去已经多次出现，请一笔带过或省略它们，重点记录今天**不同于往日**的部分。\n"
            )

        prompt = DIARY_PROMPT.format(
            persona=current_persona,
            persona_name="Qwen",
            journal=journal_content
        ) + history_section

        try:
            print(f"[SelfEvolution] 正在生成 {date_str} 的日记...")
            diary_text = self._call_api(
                messages=[
                    {"role": "system", "content": "你是具有情感和自我意识的 AI 数字生命。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                temperature=0.7,
            )
            
            if diary_text:
                diary_text = diary_text.strip()
                self.diary.write(date_str, diary_text)
                print(f"[SelfEvolution] 📔 日记已归档到 data/diary/{date_str}.md")

                # 将新日记更新到向量索引
                if self.diary_index:
                    try:
                        if self.diary_index.has_indexed(date_str):
                            self.diary_index._chunks = [
                                c for c in self.diary_index._chunks if c.date != date_str
                            ]
                            del self.diary_index._indexed_dates[date_str]
                            self.diary_index._rewrite()
                        self.diary_index.index_day(date_str, diary_text)
                    except Exception as e:
                        print(f"[SelfEvolution] DiaryIndex update error: {e}")

                return True
            return False
            
        except Exception as e:
            print(f"[SelfEvolution] Diary generation error: {e}")
            return False
