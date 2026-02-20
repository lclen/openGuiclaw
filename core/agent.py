"""
Agent: Main conversation loop.

Orchestrates Memory, Session, Skills, and the LLM.
Supports OpenAI function-calling (tool use) natively.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from openai import OpenAI

from core.memory import MemoryManager
from core.session import SessionManager
from core.skills import SkillManager
from core.journal import JournalManager
from core.diary import DiaryManager
from core.self_evolution import SelfEvolution
from core.vector_memory import EmbeddingClient, VectorStore
from core.knowledge_graph import KnowledgeGraph
from core.user_profile import UserProfileManager
import time
import threading



BUILTIN_SYSTEM_SUFFIX_BASE = """
---
# 内置技能 (Always available)
- **remember**: 将重要信息写入长期记忆。
- **recall**: 根据关键词查询长期记忆。
- **new_session**: 开启一个全新的对话（当前对话将被保存）。
- **list_sessions**: 列出所有历史会话。
- **web_fetch(url)**: 抓取指定网页 URL 的正文，用于阅读具体页面内容。
- **search_journal(query)**: 搜索过去的每日日志，回忆你以前做过什么。
- **query_knowledge(entity)**: 查询知识图谱，获取实体（人/事/物）之间的关系。
- **内置联网搜索**: 当你需要查询实时信息（天气、新闻、股价等），可以直接搜索，无需调用额外工具。
"""

_DISCIPLINE_AUTOPILOT = """
---
# 执行纪律：自驾模式 (Autopilot) [重要！！]
- 当你正在执行一个由 `create_plan` 制定的计划时，**严格禁止**在每个步骤之间停下来向用户询问"是否继续"、"需要我进行下一步吗"等待确认的话语。必须自主连续执行直到计划所有步骤完成。
- 只在以下情况才暂停并向用户报告：a) 某个步骤彻底失败且无法自行修复；b) 发现用户原始需求存在必须由用户澄清的歧义。
- 所有步骤完成后，**必须调用 `complete_plan` 工具**进行总结并正式结案任务，结案后不再追问。
"""

_DISCIPLINE_CONFIRM = """
---
# 执行纪律：确认模式 (Confirm)
- 每执行完一个计划步骤后，**必须暂停**，简短告知用户该步做了什么、结果如何，并明确询问："是否继续下一步？" 或写出下一步的描述等待确认。
- 只有用户明确说"继续"或类似肯定回复后，才执行下一步。
- 用户如果说"取消"或"停止"，立即停止并汇报当前计划进度。
- 所有步骤完成后，**必须调用 `complete_plan` 工具**进行最终总结并结案。
"""


def _build_builtin_suffix() -> str:
    """动态生成 system_prompt 的内置技能后缀，根据当前计划执行模式追加纪律规则。"""
    try:
        import __main__ as _main
        mode = _main.get_plan_mode() if hasattr(_main, "get_plan_mode") else "normal"
    except Exception:
        mode = "normal"

    if mode == "autopilot":
        return BUILTIN_SYSTEM_SUFFIX_BASE + _DISCIPLINE_AUTOPILOT
    elif mode == "confirm":
        return BUILTIN_SYSTEM_SUFFIX_BASE + _DISCIPLINE_CONFIRM
    else:
        return BUILTIN_SYSTEM_SUFFIX_BASE



class Agent:
    """
    Main Agent: ties together Persona, Memory, Session, Skills, and LLM.
    """

    def __init__(
        self,
        config_path: str = "config.json",
        persona_path: str = "PERSONA.md",
        data_dir: str = "data",
        auto_evolve: bool = True
    ):
        self.config_path = config_path
        # Load config
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.auto_evolve = auto_evolve

        api_cfg = self.config["api"]
        self.client = OpenAI(
            base_url=api_cfg["base_url"],
            api_key=api_cfg["api_key"],
        )
        self.model = api_cfg["model"]
        # New Feature: cheaper model for evolution (default to main model if missing)
        self.evolution_model = api_cfg.get("evolution_model", self.model)
        
        self.max_tokens = api_cfg.get("max_tokens", 4096)
        self.temperature = api_cfg.get("temperature", 0.7)

        # Load persona
        self.identities_dir = Path("data/identities")
        self.identities_dir.mkdir(parents=True, exist_ok=True)
        # Check if default.md exists, if not, copy from PERSONA.md if it exists
        default_persona = self.identities_dir / "default.md"
        if not default_persona.exists():
            old_persona = Path(persona_path)
            if old_persona.exists():
                default_persona.write_text(old_persona.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                default_persona.write_text("你是一个有帮助的 AI 助理。", encoding="utf-8")
        
        self.active_persona_name = self.config.get("active_persona", "default")
        self.persona_path = str(self.identities_dir / f"{self.active_persona_name}.md")
        if not Path(self.persona_path).exists():
            self.persona_path = str(default_persona)
            self.active_persona_name = "default"

        self.persona = self._load_persona(self.persona_path)

        # Load global interaction habits
        self.habits_path = Path(data_dir) / "interaction_habits.md"
        self._load_habits()

        # Vector memory (semantic search) — optional but enabled by default from config
        emb_cfg = self.config.get("embedding", {})
        emb_key = emb_cfg.get("api_key", "") or api_cfg.get("api_key", "")
        emb_url = emb_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        emb_model = emb_cfg.get("model", "text-embedding-v4")

        self._embedding_client = None
        self._vector_store = None
        if emb_key:
            try:
                self._embedding_client = EmbeddingClient(
                    api_key=emb_key, base_url=emb_url, model=emb_model
                )
                self._vector_store = VectorStore(data_dir)
                print(f"  [OK] 向量记忆已启用（{emb_model}）")
            except Exception as e:
                print(f"  [WARN] 向量记忆初始化失败: {e}")

        # Core modules
        self.memory = MemoryManager(
            data_dir,
            embedding_client=self._embedding_client,
            vector_store=self._vector_store,
        )
        self.sessions = SessionManager(data_dir)
        self.skills = SkillManager()
        self.journal = JournalManager(data_dir)
        self.diary = DiaryManager(data_dir)
        
        # New Feature: Knowledge Graph
        self.kg = KnowledgeGraph(data_dir)

        # New Feature: User Profile Manager
        self.user_profile = UserProfileManager(data_dir)

        self.evolution = SelfEvolution(
            self.client, self.evolution_model, self.memory, self.journal,
            persona_path=self.persona_path,
            data_dir=data_dir,
            knowledge_graph=self.kg,
            user_profile=self.user_profile,
        )
        # Hack: sync diary manager if needed, or let evolution use its own if designed that way.
        # Since they manipulate files, it's safe to have two instances pointing to same dir.

        # ContextManager (set by main.py after init)
        self.context = None  # type: Optional[Any]

        # Start built-in background tasks ONLY if auto_evolve is True
        self.last_interaction_date = time.strftime("%Y-%m-%d")
        if self.auto_evolve:
            # ── Startup: check if yesterday's journal needs processing ──
            self._startup_evolution()
        
        # Register built-in skills
        self._register_builtins()

        # Backfill vector embeddings for existing memories (background thread)
        if self._embedding_client and self._vector_store:
            threading.Thread(
                target=self._backfill_vectors, daemon=True, name="VectorBackfill"
            ).start()

        # ── Startup: check if yesterday's journal needs processing ──
        self._startup_evolution()

    def _load_persona(self, path: str) -> str:
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return "你是一个有帮助的 AI 助理。"
    
    def _load_habits(self) -> None:
        if self.habits_path.exists():
            self.interaction_habits = self.habits_path.read_text(encoding="utf-8")
        else:
            self.interaction_habits = ""
    
    def switch_persona(self, name: str) -> bool:
        """Switch to a different persona file in the identities directory."""
        target_path = self.identities_dir / f"{name}.md"
        if target_path.exists():
            self.active_persona_name = name
            self.persona_path = str(target_path)
            self.persona = self._load_persona(self.persona_path)
            
            # Update config
            self.config["active_persona"] = name
            with open("data/config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
                
            # Sync the new persona to evolution module so it writes diaries with the new identity
            self.evolution.persona_path = Path(self.persona_path)
            return True
        return False
        
    def list_personas(self) -> List[str]:
        """List all available personas."""
        return [p.stem for p in self.identities_dir.glob("*.md")]

    def _backfill_vectors(self) -> None:
        """
        Background: embed any memories that don't have a vector yet.
        Runs in batches of 10 to respect API rate limits.
        """
        memories = self.memory.list_all()
        missing = [m for m in memories if not self._vector_store.has(m.id)]
        if not missing:
            return

        print(f"[VectorMemory] 正在补全 {len(missing)} 条历史记忆的向量...")
        total = 0
        for m in missing:
            try:
                # Use embed_text to get chunked vectors (consistent with new add() logic)
                vectors = self._embedding_client.embed_text(m.content)
                if vectors:
                    self._vector_store.add_vectors(m.id, vectors)
                    total += 1
            except Exception as e:
                print(f"[VectorMemory] Backfill error for {m.id}: {e}")

        if total:
            print(f"[VectorMemory] ✅ 已补全 {total} 条记忆向量。")


    def _register_builtins(self) -> None:
        """Register built-in system skills."""

        @self.skills.skill(
            name="remember",
            description="将重要信息写入长期记忆，以便以后使用。",
            parameters={
                "properties": {
                    "content": {"type": "string", "description": "要记住的内容"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表，如 ['软件位置', '用户偏好']",
                    },
                },
                "required": ["content"],
            },
            category="memory",
        )
        def remember(content: str, tags: list = None):
            item = self.memory.add(content, tags or [])
            return f"✅ 已记住: {item.content}（ID: {item.id}）"

        @self.skills.skill(
            name="search_memory",
            description="【核心记忆搜索工具】一次性并发查询：日记本、长期记忆碎片、知识图谱。当你需要回忆过去的事件、聊天记录、用户偏好、关系网络等任何历史信息时优先使用此工具。使用精准关键词（如实体名）进行搜索。",
            parameters={
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如 '南京'、'写代码'、'苹果'"},
                },
                "required": ["query"],
            },
            category="memory",
        )
        def search_memory(query: str):
            import concurrent.futures

            def _search_diary():
                results = self.diary.search(query, top_k=3)
                if not results:
                    return "日记：无相关记录。"
                lines = [f"### {item['date']}\n{item['snippet']}" for item in results]
                return "【日记捕获】\n" + "\n\n".join(lines)

            def _search_vector():
                results = self.memory.search(query, top_k=5)
                if not results:
                    return "长期记忆碎片：无相关记录。"
                lines = [f"[{m.created_at}] {m.content}" for m in results]
                return "【长期记忆碎片】\n" + "\n".join(lines)

            def _search_kg():
                if not self.kg:
                    return "知识图谱：未启用。"
                context = self.kg.context_for_entity(query)
                return context if context else f"知识图谱：未找到与 '{query}' 的关联信息。"

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                f_diary = executor.submit(_search_diary)
                f_vector = executor.submit(_search_vector)
                f_kg = executor.submit(_search_kg)

                res_diary = f_diary.result()
                res_vector = f_vector.result()
                res_kg = f_kg.result()

            report = (
                f"### 统一搜索结果雷达：'{query}'\n\n"
                f"{res_diary}\n\n"
                f"---\n{res_vector}\n\n"
                f"---\n{res_kg}"
            )
            return report

        @self.skills.skill(
            name="new_session",
            description="保存当前对话并开启全新会话。",
            parameters={"properties": {}, "required": []},
            category="session",
        )
        def new_session():
            self.sessions.new_session()
            return "✅ 已开启新会话，历史对话已保存。"

        @self.skills.skill(
            name="list_sessions",
            description="列出所有历史会话。",
            parameters={"properties": {}, "required": []},
            category="session",
        )
        def list_sessions():
            sessions = self.sessions.list_sessions()
            if not sessions:
                return "没有历史会话。"
            lines = [
                f"[{s['session_id']}] {s['updated_at']} ({s['message_count']} messages)"
                for s in sessions
            ]
            return "\n".join(lines)



        @self.skills.skill(
            name="update_memory",
            description="更新或修正已被记录的长期记忆（Memory）。",
            parameters={
                "properties": {
                    "memory_id": {"type": "string", "description": "记忆的ID（可以通过 recall 搜索获得）"},
                    "new_content": {"type": "string", "description": "修正后的内容"},
                },
                "required": ["memory_id", "new_content"],
            },
            category="memory",
        )
        def update_memory(memory_id: str, new_content: str):
            success = self.memory.update(memory_id, new_content)
            if success:
                return f"✅ 记忆 {memory_id} 已更新。"
            return f"❌ 未找到 ID 为 {memory_id} 的记忆。"

        @self.skills.skill(
            name="delete_memory",
            description="删除某条不再需要的长期记忆。",
            parameters={
                "properties": {
                    "memory_id": {"type": "string", "description": "记忆的ID"},
                },
                "required": ["memory_id"],
            },
            category="memory",
        )
        def delete_memory(memory_id: str):
            success = self.memory.delete(memory_id)
            if success:
                return f"✅ 记忆 {memory_id} 已删除。"
            return f"❌ 未找到 ID 为 {memory_id} 的记忆。"

        @self.skills.skill(
            name="query_knowledge",
            description="查询知识图谱，获取实体（人、事、物）之间的关联关系。",
            parameters={
                "properties": {
                    "entity": {"type": "string", "description": "要查询的实体名称"},
                },
                "required": ["entity"],
            },
            category="memory",
        )
        def query_knowledge(entity: str):
            if not self.kg:
                return "❌ 知识图谱未启用。"
            
            triples = self.kg.query(entity)
            if not triples:
                return f"知识图谱中没有关于 '{entity}' 的记录。"
            
            lines = [f"【{entity} 的关联】"]
            for t in triples:
                lines.append(f"  · {t.subject} --[{t.relation}]--> {t.object}")
            return "\n".join(lines)

    def register_skill_module(self, module) -> None:
        """
        Register all skills defined in an external module.
        The module must expose a `register(manager: SkillManager)` function.
        """
        module.register(self.skills)

    def _build_system_prompt(self, user_query: str = "") -> str:
        """Build the full system prompt: Persona + User Profile + Dynamic Memory + Skill Summary."""
        import time
        current_time_str = time.strftime("%Y-%m-%d %H:%M:%S")
        weekday_str = time.strftime("%A")
        time_awareness = f"# 当前系统时间\n现在是 {current_time_str}，星期{weekday_str}。请在理解用户的“今天”、“昨天”等相对时间概念时，以此时间为基准。"

        parts = [time_awareness, self.persona]

        # Inject Global Interaction Habits
        self._load_habits()  # Refresh before building prompt in case it was evolved
        if self.interaction_habits.strip():
            parts.append(f"# 全局交往习惯与规则 (Interaction Habits)\n{self.interaction_habits}")

        # Inject User Profile
        profile_ctx = self.user_profile.build_prompt()
        if profile_ctx:
            parts.append(profile_ctx)

        # Dynamic Memory Injection (Top-K related memories based on user query)
        if user_query and self.memory._vector_store:
            # Instead of injecting the entire memory database, we only inject contextually relevant facts.
            try:
                related_mems = self.memory.search(user_query, top_k=3)
                if related_mems:
                    mem_lines = [f"- {m.content}" for m in related_mems]
                    mem_ctx = "# 相关长期记忆 (Context)\n" + "\n".join(mem_lines)
                    parts.append(mem_ctx)
            except Exception as e:
                pass
        elif user_query and not self.memory.vector_store:
            # Fallback to standard context if no vector store (which just takes the last N memories)
            mem_ctx = self.memory.build_context(user_query)
            if mem_ctx:
                parts.append(mem_ctx)

        # Inject active plan status (if any) — ensures agent never forgets its roadmap
        try:
            import plugins.plan_handler as _ph
            plan_md = _ph._manager.get_status_markdown()
            if plan_md and "当前没有任何活跃" not in plan_md:
                parts.append(
                    "# 当前活跃任务计划 (Active Plan)\n"
                    "> 以下是你正在执行的多步任务进度。每完成一步后必须立即调用 `update_plan_step` 更新状态。\n"
                    "> 如果所有步骤均已处理完成，你必须调用 `complete_plan` 来全盘总结并结案。\n\n"
                    + plan_md
                )
        except Exception:
            pass

        # Inject skill list
        skill_summary = self.skills.summary()
        parts.append(f"# 可用技能 (Skills)\n{skill_summary}")

        parts.append(_build_builtin_suffix())
        return "\n\n---\n\n".join(parts)

    def chat(self, user_input: str) -> str:
        """
        Process a single user turn.
        Supports multi-step tool calling.
        """
        session = self.sessions.current
        system_prompt = self._build_system_prompt(user_input)

        # Notify context manager that user replied (resets cooldown)
        if self.context is not None:
            self.context.notify_user_replied()

        # Build full message list for LLM
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(session.get_history())
        messages.append({"role": "user", "content": user_input})

        tools = self.skills.get_tool_definitions()
        
        max_tool_rounds = 15
        # 如果有活跃的计划，放宽工具调用轮次上限，让自驾模式能一口气跑完
        try:
            import plugins.plan_handler as _ph
            if _ph._manager.active_plan:
                max_tool_rounds = 40
        except Exception:
            pass
            
        final_response = None

        for _ in range(max_tool_rounds):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                extra_body={"enable_search": True},  # Qwen built-in web search
            )

            msg = response.choices[0].message

            if msg.tool_calls:
                # --- Fix: sanitize tool_call arguments before appending ---
                # Some models may return non-JSON arguments; patch them to "{}"
                # so the API doesn't reject the subsequent request with 400.
                assistant_dict = msg.model_dump(exclude_unset=True)
                for tc_dict in assistant_dict.get("tool_calls") or []:
                    raw_args = tc_dict.get("function", {}).get("arguments", "{}")
                    try:
                        json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        tc_dict["function"]["arguments"] = "{}"
                messages.append(assistant_dict)

                # Execute each tool call
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        params = json.loads(tc.function.arguments)
                        if not isinstance(params, dict):
                            params = {}
                    except Exception:
                        params = {}

                    print(f"  [Tool] {name}({params})")
                    result = self.skills.execute(name, params)
                    # Ensure result is a plain string and not excessively long
                    if not isinstance(result, str):
                        result = str(result)
                    print(f"  [Result] {result[:120]}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": result,
                    })
                # Continue loop so LLM sees tool results
                continue

            # No tool calls — final text response
            final_response = msg.content or ""
            break

        if final_response is None:
            final_response = "（已完成工具操作，无额外回复。）"

        # Persist to session
        session.add_message("user", user_input)
        session.add_message("assistant", final_response)
        self.sessions.save()

        # Check triggers
        self._check_all_triggers()

        return final_response

    def _startup_evolution(self) -> None:
        """
        On startup, check recent days for un-processed journals.
        If yesterday (or earlier) has a journal but no diary, trigger evolution.
        This fixes the bug where last_interaction_date is always set to today
        on startup, making the cross-day detection in _check_all_triggers
        never fire.
        """
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        # Look back up to 7 days to find unprocessed journals
        for days_back in range(1, 8):
            check_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            journal_content = self.journal.read_day(check_date)

            if not journal_content or not journal_content.strip():
                continue  # No journal for this day, keep looking further back

            # Has journal — but was it already processed?
            if self.diary.has_diary(check_date):
                # Already processed (diary exists). Earlier days presumably also done.
                break

            # Found an un-processed journal!
            print(f"[System] 🔍 发现 {check_date} 的日志尚未总结，已将其加入后台自我进化队列...")
            
            def _run_evolution(d=check_date):
                try:
                    # Step 1: 汇总当天所有聊天记录写入 journal
                    self._summarize_day_conversations(d)

                    # Step 2: 基于完整 journal (视觉日志 + 聊天总结) 生成 diary + 提取记忆
                    new_mems = self.evolution.evolve_from_journal(d)
                    if new_mems:
                        print(f"\n[System] ✨ {d} 后台进化完成！习得了 {len(new_mems)} 条新记忆。\n> ", end="", flush=True)
                    else:
                        print(f"\n[System] {d} 后台进化完成，未发现新知识。\n> ", end="", flush=True)

                    # Step 3: 尝试人设微调
                    self.evolution.evolve_persona()
                except Exception as e:
                    import traceback
                    print(f"\n[System] ⚠️ {d} 后台进化出错: {e}\n{traceback.format_exc()}\n> ", end="", flush=True)

            # Start thread and don't block
            threading.Thread(target=_run_evolution, daemon=True, name=f"Evo_{check_date}").start()

        # Set to today so _check_all_triggers works correctly for future cross-day
        self.last_interaction_date = today

    def _check_all_triggers(self) -> None:
        """Check and execute maintenance triggers."""
        # 1. Date change -> Daily Summary + Evolution
        current_date = time.strftime("%Y-%m-%d")
        if current_date != self.last_interaction_date:
            prev_date = self.last_interaction_date
            print(f"[System] 检测到跨天 ({prev_date} -> {current_date})，后台自我进化已启动。")

            def _run_daily_evo(d=prev_date):
                try:
                    # Step 1: 汇总昨天所有聊天记录写入 journal
                    self._summarize_day_conversations(d)

                    # Step 2: 基于完整 journal (视觉日志 + 聊天总结) 生成 diary + 提取记忆
                    print(f"\n[System] 🧠 开始后台自我进化：分析 {d} 日志...\n> ", end="", flush=True)
                    new_mems = self.evolution.evolve_from_journal(d)
                    if new_mems:
                        print(f"\n[System] ✨ 后台进化完成！习得了 {len(new_mems)} 条新记忆。\n> ", end="", flush=True)
                    else:
                        print(f"\n[System] 后台进化完成，未通过日志发现新知识。\n> ", end="", flush=True)

                    # Step 3: 尝试人设微调
                    self.evolution.evolve_persona()
                except Exception as e:
                    print(f"\n[System] ⚠️ 跨天后台进化出错: {e}\n> ", end="", flush=True)

            threading.Thread(target=_run_daily_evo, daemon=True, name=f"DailyEvo_{prev_date}").start()

            self.last_interaction_date = current_date

        # 2. Token pressure -> Rolling Summary
        # Limit: 80% of max_tokens (approximate)
        # We assume 1 token ~ 3 chars. 
        # Reserve 1000 tokens for generation.
        SAFE_LIMIT = (self.max_tokens - 1000) * 0.8
        est_tokens = self.sessions.current.estimate_tokens()
        
        if est_tokens > SAFE_LIMIT:
            print(f"[System] 上下文压力 ({est_tokens} > {SAFE_LIMIT})，触发滚动总结...")
            self._consolidate_rolling()


    def _consolidate_rolling(self) -> None:
        """
        Rolling Summary:
        1. Prune oldest messages.
        2. Summarize them.
        3. Append to Daily Journal.
        4. Update Session.summary.
        """
        session = self.sessions.current
        # Prune ~10 messages at a time or enough to free 20%
        pruned = session.prune_oldest(keep_last=10)
        if not pruned:
            return

        # Format for summarization
        text_block = "\n".join([f"{m['role']}: {m['content']}" for m in pruned])
        
        # 1. Summarize
        try:
            prompt = f"请总结以下对话片段，提取关键信息（意图、操作、结果），作为'前情提要'。保留关键事实，去除闲聊。\n\n{text_block}"
            resp = self.client.chat.completions.create(
                model=self.evolution_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            summary_text = resp.choices[0].message.content
        except Exception as e:
            print(f"[System] 总结失败: {e}")
            summary_text = "(Summary failed)"

        # 2. Update Session Summary (append new summary to old)
        if session.summary:
            session.summary += f"\n- {summary_text}"
        else:
            session.summary = summary_text

        # 3. Append to Journal
        journal_entry = f"**[Rolling Summary]**\n{text_block}\n\n**[AI Summary]**: {summary_text}"
        self.journal.append(journal_entry)
        
        print(f"[System] 滚动总结完成。已归档 {len(pruned)} 条消息到日志。")
        self.sessions.save()

    def _summarize_day_conversations(self, date_str: str) -> None:
        """
        收集指定日期所有 session 中的对话内容，用 LLM 总结后追加到当天 journal。
        这样 evolve_from_journal 就能同时看到 [视觉日志 + 聊天总结]。
        """
        # 1. 遍历所有 session 文件，收集该日期的对话
        all_conversations = []
        for path in sorted(self.sessions.sessions_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                messages = data.get("messages", [])
                # 筛选该日期的消息
                day_msgs = [
                    m for m in messages
                    if m.get("timestamp", "").startswith(date_str)
                ]
                if day_msgs:
                    all_conversations.extend(day_msgs)
            except Exception:
                continue

        if not all_conversations:
            print(f"[System] {date_str} 没有找到聊天记录，跳过对话总结。")
            return

        # 2. 格式化对话内容 (截断过长的单条消息)
        lines = []
        for m in all_conversations:
            role = "用户" if m["role"] == "user" else "AI"
            content = m.get("content", "")
            if len(content) > 500:
                content = content[:500] + "...(截断)"
            ts = m.get("timestamp", "").split(" ")[-1] if " " in m.get("timestamp", "") else ""
            lines.append(f"[{ts}] {role}: {content}")

        conversation_text = "\n".join(lines)

        # 3. 用 LLM 总结
        print(f"[System] 📝 正在总结 {date_str} 的 {len(all_conversations)} 条聊天记录...")
        try:
            prompt = (
                f"请总结以下一天的人机聊天记录，提取关键信息：用户提了哪些问题/任务、"
                f"AI 做了什么、有哪些重要的结论或决定。保留具体事实，去除无意义的寒暄。\n"
                f"用简洁的要点形式总结，300字以内。\n\n"
                f"## {date_str} 聊天记录\n{conversation_text}"
            )
            resp = self.client.chat.completions.create(
                model=self.evolution_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[System] ⚠️ 聊天总结失败: {e}")
            # Fallback: 直接把原始对话截断写入
            summary = conversation_text[:2000]

        # 4. 写入 journal
        journal_entry = f"**[聊天总结]** 共 {len(all_conversations)} 条消息\n{summary}"
        self.journal.append(journal_entry, date_str=date_str)
        print(f"[System] ✅ {date_str} 聊天总结已写入日志。")
