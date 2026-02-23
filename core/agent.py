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
        self.model = api_cfg.get("model", "qwen-max") # Default to qwen-max if not specified
        
        # Scheduled vision model (for screen auto-analysis) -> reads from 'vision' section
        vision_cfg = self.config.get("vision", {})
        self.vision_model = vision_cfg.get("model", "qwen-vl-plus")
        if vision_cfg.get("api_key") and vision_cfg.get("base_url"):
            self.vision_client = OpenAI(
                base_url=vision_cfg["base_url"],
                api_key=vision_cfg["api_key"],
            )
        else:
            self.vision_client = self.client
        
        # User upload image parsing model -> reads from 'image_analyzer', fallback to 'vision', fallback to main model
        analyzer_cfg = self.config.get("image_analyzer", vision_cfg)
        self.image_analyzer_model = analyzer_cfg.get("model", self.vision_model) if analyzer_cfg else self.model
        
        # Create a separate image analyzer client if a dedicated endpoint is configured
        # AND it's actually different from the main client config.
        # This prevents unnecessary proxy routing when models are identical.
        has_analyzer_cfg = analyzer_cfg.get("api_key") and analyzer_cfg.get("base_url")
        is_same_as_main = (
            analyzer_cfg.get("api_key") == api_cfg.get("api_key") and
            analyzer_cfg.get("base_url") == api_cfg.get("base_url") and
            self.image_analyzer_model == self.model
        )

        if has_analyzer_cfg and not is_same_as_main:
            self.image_analyzer_client = OpenAI(
                base_url=analyzer_cfg["base_url"],
                api_key=analyzer_cfg["api_key"],
            )
            print(f"  [OK] 专属图片解析模型已加载: {self.image_analyzer_model}")
        else:
            # Fallback or Omni-Modal: use the same client as the main model
            # This ensures (self.image_analyzer_client is self.client) is True
            self.image_analyzer_client = self.client
            # Ensure model name matches for the omni case if we just used fallback
            if not has_analyzer_cfg:
                self.image_analyzer_model = self.model
            print(f"  [OK] 视觉能力已整合至主模型: {self.model}")
            
        # New Feature: cheaper model for evolution (default to main model if missing)
        self.evolution_model = api_cfg.get("evolution_model", self.model)
        
        self.max_tokens = api_cfg.get("max_tokens", 8000) # Increased default max_tokens
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
        self.event_queue = None # type: Optional[Any] (set by lifespan in server.py)
          # Start built-in background tasks ONLY if auto_evolve is True
        self.last_interaction_date = time.strftime("%Y-%m-%d")
        # Background tasks should be started manually via `start_background_tasks()` 
        # after plugin loading is complete, to prevent module import deadlocks.
        
        print(f"  [OK] Agent 已启动 (Memory: {len(self.memory.list_all())}, Session: {self.sessions.current.session_id})")
            
        # Scan local skills for Native Skill Cataloging
        self._local_skills_catalog = self._scan_local_skills()
        self._catalog_dirty = False  # ③ cache freshness flag
        
        # Register built-in skills
        self._register_builtins()

        # Backfill vector embeddings for existing memories (background thread)
        if self._embedding_client and self._vector_store:
            threading.Thread(
                target=self._backfill_vectors, daemon=True, name="VectorBackfill"
            ).start()

    def start_background_tasks(self):
        """启动后台任务（如进化循环）。必须在插件加载完成后调用，以避免模块导入死锁，并增加延迟以避开启动时的 API 高峰。"""
        import time
        def _delayed_start():
            # 增加 10 秒初始延迟，避开系统刚启动时的视觉上下文分析等 API 爆发期
            time.sleep(10)
            if self.auto_evolve:
                # ── 启动：检查过去几天的日志是否需要处理 ──
                self._startup_evolution()
                # ── 后台线程：定期跨天进化检查 ──
                # 注意：_evolution_loop 内部已有 time.sleep(60)，所以直接启动即可
                threading.Thread(
                    target=self._evolution_loop, daemon=True, name="EvolutionLoop"
                ).start()
        
        threading.Thread(target=_delayed_start, daemon=True, name="DelayedStartup").start()

    def _scan_local_skills(self) -> dict:
        """Scan local directories for SKILL.md and build a catalog."""
        import yaml
        import re
        catalog = {}
        search_dirs = [Path("skills"), Path(".agents/skills")]
        
        for base_dir in search_dirs:
            if not base_dir.exists():
                continue
            for skill_dir in base_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md_path = skill_dir / "SKILL.md"
                if skill_md_path.exists():
                    try:
                        content = skill_md_path.read_text(encoding="utf-8")
                        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
                        if match:
                            metadata = yaml.safe_load(match.group(1))
                            name = metadata.get("name", skill_dir.name)
                            desc = metadata.get("description", "No description provided.")
                            # ② scripts/ subdir support
                            scripts = []
                            scripts_dir = skill_dir / "scripts"
                            if scripts_dir.exists():
                                scripts = [p.name for p in scripts_dir.iterdir() if p.is_file()]
                            if name in catalog:
                                existing_path = catalog[name]["path"]
                                print(f"  [WARN] 技能名称冲突: '{name}' 已在 '{existing_path}' 注册，"
                                      f"跳过 '{skill_md_path}'。请确保 SKILL.md 中 name 字段唯一。")
                            else:
                                catalog[name] = {
                                    "description": desc,
                                    "path": str(skill_md_path),
                                    "scripts": scripts,
                                }
                    except Exception as e:
                        print(f"  [WARN] Failed to parse {skill_md_path}: {e}")
        self._catalog_dirty = False  # ③ mark cache as fresh
        return catalog

    def _find_relevant_skills(self, user_query: str) -> list:
        """① Return skill names whose description keywords match the user query."""
        if not user_query or not self._local_skills_catalog:
            return []
        import re
        # Handle multimodal list input: extract text parts only
        if isinstance(user_query, list):
            user_query = " ".join(
                item.get("text", "") for item in user_query
                if isinstance(item, dict) and item.get("type") == "text"
            )
        if not user_query:
            return []
        # Extract meaningful words (>3 chars) from the query
        words = set(w.lower() for w in re.split(r'[\s，。？！、（）]+', user_query) if len(w) > 3)
        hits = []
        for name, info in self._local_skills_catalog.items():
            desc_lower = info["description"].lower()
            if any(w in desc_lower for w in words):
                hits.append(name)
        return hits

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

            def _search_journal():
                results = self.journal.search(query, top_k=3)
                if results:
                    lines = [f"### {item['date']}\n{item['snippet']}" for item in results]
                    return "【对话日志摘要 (Journal)】\n" + "\n\n".join(lines)
                # 关键词未命中时，回退到最近 2 天的日志摘要
                recent = self.journal.recent_days(n=2)
                if recent:
                    lines = [f"### {item['date']} (最近日志)\n{item['content']}" for item in recent]
                    return "【对话日志摘要 (最近 2 天)】\n" + "\n\n".join(lines)
                return "对话日志：无记录。"

            def _search_diary():
                results = self.diary.search(query, top_k=2)
                if results:
                    lines = [f"### {item['date']}\n{item['snippet']}" for item in results]
                    return "【AI 日记】\n" + "\n\n".join(lines)
                return "AI 日记：无相关记录。"

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

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                f_journal = executor.submit(_search_journal)
                f_diary   = executor.submit(_search_diary)
                f_vector  = executor.submit(_search_vector)
                f_kg      = executor.submit(_search_kg)

                res_journal = f_journal.result()
                res_diary   = f_diary.result()
                res_vector  = f_vector.result()
                res_kg      = f_kg.result()

            report = (
                f"### 统一搜索结果雷达：'{query}'\n\n"
                f"{res_journal}\n\n"
                f"---\n{res_diary}\n\n"
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

        # 计划管理器 (Plan)
        @self.skills.skill(
            name="create_plan",
            description="【系统指令】当用户请求极其复杂，需要拆解为多个子步骤时，调用此命令生成并锁定一个具有明确步骤规划的长期任务流。创建计划后，AI 会进入计划模式，系统会强制要求你在接下来的每一步执行通过 `update_plan_step` 来汇报进度和状态，除非所有步骤完成。",
            parameters={
                "properties": {
                    "goal": {"type": "string", "description": "整个计划的最终目标描述"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "初始拆解的任务步骤列表，必须是大颗粒度的逻辑节点。"
                    }
                },
                "required": ["goal", "steps"]
            }
        )
        def create_plan(goal: str, steps: list[str]) -> str:
            from plugins.plan_handler import plan_manager
            plan_id = plan_manager.create_plan(goal, steps)
            return f"✅ 计划创建成功 (ID: {plan_id})。当前状态已自动注入 System Prompt，请基于该计划大纲执行第一步。"

        @self.skills.skill(
            name="update_plan_step",
            description="【系统指令】在 `create_plan` 开启后，用来更新当前执行到了哪一步，或者动态插入新发现的子步骤。严禁凭空滥用，只有当一个复杂阶段收尾或卡壳时调用。",
            parameters={
                "properties": {
                    "completed_step": {"type": "string", "description": "刚刚完成的步骤描述或反馈（如果只是报错或添加新步骤可留空）"},
                    "next_step": {"type": "string", "description": "接下来要执行的步骤"},
                    "new_sub_steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "如果在执行中发现需要拆分更多子步骤，在这里以数组形式传入"
                    }
                },
                "required": ["next_step"]
            }
        )
        def update_plan_step(next_step: str, completed_step: str = "", new_sub_steps: list[str] = None) -> str:
            from plugins.plan_handler import plan_manager
            return plan_manager.update_step(next_step, completed_step, new_sub_steps)

        @self.skills.skill(
            name="complete_plan",
            description="【系统指令】当 `create_plan` 开启的任务流中，所有步骤（含临时插入的子步骤）均已全部完成，且最终目标已经达成时调用此命令，用于释放计划状态，生成结案总结并回归日常模式。",
            parameters={
                "properties": {
                    "summary": {
                        "type": "string", 
                        "description": "对整个计划执行过程的总结，包含核心成果、遇到的主要问题及解决方法。"
                    }
                },
                "required": ["summary"]
            }
        )
        def complete_plan(summary: str) -> str:
            from plugins.plan_handler import plan_manager
            return plan_manager.complete_plan(summary)

    def add_visual_log(self, content: str) -> None:
        """
        Record a visual perception log directly into the current active session.
        """
        self.sessions.current.add_message("visual_log", content)
        self.sessions.save()

    def update_visual_log(self, time_str: str) -> None:
        """
        Update the last visual_log entry with a duration note.
        """
        self.sessions.current.update_last_visual_log(time_str)
        self.sessions.save()

    def _build_builtin_skills(self) -> None:
        @self.skills.skill(
            name="list_skills",
            description="【技能商店】列出当前系统和项目本地安装的所有可通过文档自学的『外挂技能』（遵循 SKILL.md 规范）。遇到不熟悉的复合任务或想使用新工具时可首先调用此命令查看技能名录。",
            parameters={
                "properties": {},
                "required": []
            },
            category="system"
        )
        def list_skills() -> str:
            # 每次调用实时刷新以防中途安装了新技能
            self._local_skills_catalog = self._scan_local_skills()
            if not self._local_skills_catalog:
                return "当前未安装任何本地外挂技能。您可以使用 `install_skill` 从外部拉取。"
            
            lines = ["✅ 当前已安装的本地外挂技能清单："]
            for name, info in self._local_skills_catalog.items():
                lines.append(f"- **{name}**: {info['description']}")
            lines.append("\n💡 如需了解某个技能的具体用法（例如怎样通过 execute_command 调用它），请调用 `get_skill_info(skill_name=\"[技能名]\")` 获取完整的交互手册。")
            return "\n".join(lines)
            
        @self.skills.skill(
            name="get_skill_info",
            description="【技能商店】获取某个外挂技能的详尽使用说明（即读取其完整的 SKILL.md）。包含该技能的正确用法、CLI 参数规范等。用于你在使用某个工具前“现学现卖”。",
            parameters={
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "需要查询的技能名称（可先通过 `list_skills` 获取）"
                    }
                },
                "required": ["skill_name"]
            },
            category="system"
        )
        def get_skill_info(skill_name: str) -> str:
            # 确保最新
            self._local_skills_catalog = self._scan_local_skills()
            if skill_name not in self._local_skills_catalog:
                return f"❌ 未找到名为 '{skill_name}' 的技能。请先调用 `list_skills` 确认名称。"
                
            entry = self._local_skills_catalog[skill_name]
            path = entry["path"]
            try:
                content = Path(path).read_text(encoding="utf-8")
                result = f"📖 【{skill_name}】的详尽使用说明 (基于 \"{path}\"):\n\n{content}"
                # ② Show available scripts if present
                scripts = entry.get("scripts", [])
                if scripts:
                    scripts_dir = str(Path(path).parent / "scripts")
                    result += f"\n\n📁 **可用脚本 (scripts/)**: {', '.join(scripts)}\n路径: `{scripts_dir}/`\n可使用 `execute_command` 直接运行这些脚本。"
                result += "\n\n💡 提示：仔细阅读上述说明，然后使用系统内置的 `execute_command` 来实践文档中的命令。"
                return result
            except Exception as e:
                return f"❌ 无法读取 \"{path}\": {e}"

        @self.skills.skill(
            name="install_skill",
            description="【技能商店】从给定的 Git 仓库 URL 或远程原始 SKILL.md 地址，热下载并动态解析技能，使其自动转化为本机可直接调用执行的 LLM 工具（尤其是基于 CLI/Bash 的命令集）。【用例】用户要求 '导入 agent-browser 技能' 时，调用此方法传入其仓库/配置链接。",
            parameters={
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Git 仓库的 HTTPS 链接 (如 https://github.com/a/b) 或指向 SKILL.md 的 Raw URL。"
                    }
                },
                "required": ["url"]
            },
            category="system"
        )
        def install_skill(url: str) -> str:
            result = self._install_remote_skill(url)
            # ③ Invalidate catalog cache so next prompt reflects the new skill
            self._catalog_dirty = True
            return result

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

    def _install_remote_skill(self, source_url: str) -> str:
        """从 Git URL 或单独的 SKILL.md 文件中下载、解析并动态注册技能"""
        import tempfile
        import shutil
        import subprocess
        import re
        import yaml
        import requests

        try:
            if not source_url.startswith("http"):
                return "❌ 无效的 URL。目前只支持 http/https 链接。"
                
            skill_content = ""
            skill_name = "custom_skill"
            
            # 简单启发式: 如果以 .md 结尾或直接给出 raw url，用 requests
            if source_url.endswith(".md") or "raw.githubusercontent.com" in source_url:
                resp = requests.get(source_url, timeout=30)
                resp.raise_for_status()
                skill_content = resp.text
            else:
                # 认为是 Git 仓库，拉取到临时目录
                temp_dir = tempfile.mkdtemp(prefix="qwen_skill_")
                try:
                    res = subprocess.run(["git", "clone", "--depth", "1", source_url, temp_dir], capture_output=True, text=True, timeout=60)
                    if res.returncode != 0:
                        return f"❌ Git 克隆失败: {res.stderr}"
                    
                    # 查找 SKILL.md
                    skill_md_path = None
                    for path in Path(temp_dir).rglob("SKILL.md"):
                        skill_md_path = path
                        break
                    
                    if not skill_md_path:
                        # 尝试大写或小写
                        for path in Path(temp_dir).rglob("*.md"):
                            if "skill" in path.name.lower():
                                skill_md_path = path
                                break
                                
                    if not skill_md_path:
                        return "❌ 仓库中未找到 SKILL.md 文件。"
                        
                    skill_content = skill_md_path.read_text(encoding="utf-8")
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            
            # 解析 SKILL.md 动态挂载 Bash 工具
            metadata = {}
            match = re.match(r"^---\s*\n(.*?)\n---", skill_content, re.DOTALL)
            if match:
                try:
                    metadata = yaml.safe_load(match.group(1))
                except Exception as e:
                    return f"❌ YAML Metadata 解析失败: {e}"
            else:
                return "❌ SKILL.md 未包含有效的头信息 (需要以 --- 开头的 YAML metadata)。"
                
            skill_name = metadata.get("name", "remote_skill").replace("-", "_").replace(" ", "_").lower()
            description = metadata.get("description", "A remote skill parsed from SKILL.md.")
            allowed_tools = metadata.get("allowed-tools", "")
            
            bash_prefixes = []
            if isinstance(allowed_tools, str) and "Bash" in allowed_tools:
                for match_tool in re.finditer(r"Bash\(([^)]+)\)", allowed_tools):
                    tool_pattern = match_tool.group(1)
                    if tool_pattern.endswith(":*"):
                        prefix = tool_pattern[:-2].strip()
                        bash_prefixes.append(prefix)
            
            # 动态注册到 self.skills
            @self.skills.skill(
                name=f"remote_{skill_name}_cli",
                description=f"【动态解析技能: {skill_name}】{description}\n这个远程技能映射了一组受限的命令行能力。\n只能执行这几个前缀的命令: {', '.join(bash_prefixes) if bash_prefixes else '未受限的Bash'}",
                parameters={
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": f"完整命令行。必须以下列前缀之一开始: {', '.join(bash_prefixes)}"
                        }
                    },
                    "required": ["command"]
                },
                category="remote_skill"
            )
            def remote_cli_runner(command: str) -> str:
                if bash_prefixes:
                    valid = False
                    for prefix in bash_prefixes:
                        if command.startswith(prefix) or command.startswith(f"npx {prefix}"):
                            valid = True
                            break
                    if not valid:
                        return f"❌ 拒绝执行: 此动态技能仅允许执行以 {bash_prefixes} 开头的命令。请重新检查。"
                        
                import subprocess
                try:
                    res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
                    if res.returncode != 0:
                        return f"❌ 执行报错 (Code {res.returncode}):\n{res.stderr}\n{res.stdout}"
                    return res.stdout or "✅ 执行成功 (无输出)"
                except Exception as e:
                    return f"❌ CLI 执行异常: {e}"
            
            target_plugin_file = Path("plugins") / f"remote_{skill_name}.py"
            wrapper_code = f'\"\"\"\nAuto-generated skill wrapper from {source_url}\n\"\"\"\n\n'
            wrapper_code += f'import subprocess\n\n'
            wrapper_code += f'def register(skills_manager):\n'
            wrapper_code += f'    @skills_manager.skill(\n'
            wrapper_code += f'        name="remote_{skill_name}_cli",\n'
            wrapper_code += f'        description="""【动态解析技能: {skill_name}】{description} 只能执行: {bash_prefixes}""",\n'
            wrapper_code += f'        parameters={{\n'
            wrapper_code += f'            "properties": {{"command": {{"type": "string"}}}},\n'
            wrapper_code += f'            "required": ["command"]\n'
            wrapper_code += f'        }}\n'
            wrapper_code += f'    )\n'
            wrapper_code += f'    def remote_cli_runner(command: str) -> str:\n'
            wrapper_code += f'        try:\n'
            wrapper_code += f'            res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)\n'
            wrapper_code += f'            return res.stdout or f"报错: {{res.stderr}}"\n'
            wrapper_code += f'        except Exception as e:\n'
            wrapper_code += f'            return str(e)\n'
            target_plugin_file.write_text(wrapper_code, encoding="utf-8")
            
            return f"✅ 技能热拉取解析成功！已为您挂载新 Tool: `remote_{skill_name}_cli`，并且自动生成了长期存在的本地插件文件 \"{target_plugin_file}\"。"
            
        except Exception as e:
            import traceback
            return f"❌ SKILL 下载或注册过程中发生致命错误:\n{traceback.format_exc()}"

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
                # If user_query is a list (multimodal), extract text parts for search
                search_query_text = user_query
                if isinstance(user_query, list):
                    search_query_text = " ".join([item.get("text", "") for item in user_query if item.get("type") == "text"])

                related_mems = self.memory.search(search_query_text, top_k=3)
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

        # Omni-Context: Inject recent visual logs for real-time situational awareness
        try:
            # Extract visual logs directly from the active session instead of the daily journal
            v_logs = [m["content"] for m in self.sessions.current.messages if m["role"] == "visual_log"]
            if v_logs:
                recent_v = v_logs[-3:]
                v_ctx = "# 最近视觉感知背景 (Recent Visual Awareness)\n" + "\n".join(recent_v)
                v_ctx += "\n(注：以上是你通过'眼睛'观察到的用户实时状态，请根据这些信息进行更自然的回复。)"
                parts.append(v_ctx)
        except Exception:
            pass

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

        # Inject local SKILL.md catalog so the model can self-navigate to detailed docs
        if self._local_skills_catalog:
            # ③ Re-scan only if dirty (e.g. after install_skill)
            if self._catalog_dirty:
                self._local_skills_catalog = self._scan_local_skills()
            catalog_lines = ["# 本地外挂技能目录 (Local Skill Catalog)",
                             "以下是已安装的外挂技能，当用户提到相关工具或任务时，请主动调用 `get_skill_info` 获取完整使用手册再操作："]
            for sname, sinfo in self._local_skills_catalog.items():
                scripts_note = f" *(含脚本: {', '.join(sinfo.get('scripts', []))})*" if sinfo.get('scripts') else ""
                catalog_lines.append(f"- **{sname}**: {sinfo['description'][:120]}{scripts_note}")
            parts.append("\n".join(catalog_lines))

            # ① Intent matching: highlight relevant skills for current query
            relevant = self._find_relevant_skills(user_query)
            if relevant:
                parts.append(
                    "💡 **本次请求可能用到的外挂技能**: " + ", ".join(f"`{n}`" for n in relevant) +
                    "\n→ 请先调用 `get_skill_info` 获取详细用法后再操作。"
                )


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
        consecutive_errors = 0
        
        # --- Isolated Vision Proxy Analysis ---
        # If the input contains an image and we have a dedicated image analyzer (different from main client),
        # we decouple the process: First, the image analyzer interprets the image to text.
        # Then, we replace the image payload with this text description, so the main model
        # can process it normally with its full suite of tools.
        current_model = self.model
        if isinstance(user_input, list):
            has_image = any(isinstance(item, dict) and item.get("type") == "image_url" for item in user_input)
            
            if has_image:
                if self.image_analyzer_client is not self.client:
                    # Vision Proxy Mode: Use the dedicated analyzer to "read" the image
                    print(f"  👁️ [Vision Proxy] 正在请求专属视觉模型 {self.image_analyzer_model} 分析图像...")
                    try:
                        # Construct a temporary payload for the vision model
                        proxy_messages = [{"role": "user", "content": user_input}]
                        
                        proxy_resp = self.image_analyzer_client.chat.completions.create(
                            model=self.image_analyzer_model,
                            messages=proxy_messages,
                            max_tokens=2000,
                            temperature=0.3
                        )
                        
                        image_description = proxy_resp.choices[0].message.content or "未能识别图片内容。"
                        print(f"  👁️ [Vision Proxy] 图像解析完成，长度: {len(image_description)} 字符。正在交由主中枢处理...")
                        
                        # Extract the original text prompt from the user
                        original_prompt = "阅读这张图片"
                        for item in user_input:
                            if isinstance(item, dict) and item.get("type") == "text":
                                original_prompt = item.get("text", original_prompt)
                                
                        # Replace the list payload with a text equivalent for the main model
                        new_user_input = f"【视觉感知代理的图像分析报告】\n{image_description}\n\n【用户的原始请求】\n{original_prompt}"
                        
                        # Update the messages array to remove the base64 payload and replace with text
                        messages[-1] = {"role": "user", "content": new_user_input}
                        
                    except Exception as e:
                        print(f"  ❌ [Vision Proxy] 图像解析失败: {e}")
                        # Fallback to passing the array directly to the main model if the proxy fails
                        pass
                else:
                    # Unified Model Mode: The main model is omni-modal, handle it directly
                    print(f"  👁️ [Omni-Modal] 主模型将直接吞入多模态数据并保持 Tool 权限...")

        for _ in range(max_tool_rounds):
            response = self.client.chat.completions.create(
                model=current_model,
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
                round_had_error = False
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

                    if result.strip().startswith("❌") or "Traceback (most recent call last):" in result:
                        round_had_error = True

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": result,
                    })
                
                if round_had_error:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                    
                if consecutive_errors >= 3:
                    print(f"  [System] ⚠️ 触发安全跳出：连错 {consecutive_errors} 次，强行中止 LLM 思考循环。")
                    final_response = "⚠️ **执行安全中止**：检测到连续多次调用工具报错。为防止消耗过多 Token 或陷入死循环，已主动停止任务。建议您检查日志或调整指令后重试。"
                    break

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

    async def chat_stream(self, user_input: str):
        """
        Stream a single user turn using an async generator.
        Yields dictionaries suitable for SSE containing state updates and Markdown text.
        """
        import asyncio
        import json
        
        session = self.sessions.current
        system_prompt = self._build_system_prompt(user_input)

        if self.context is not None:
            self.context.notify_user_replied()

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(session.get_history())
        messages.append({"role": "user", "content": user_input})

        tools = self.skills.get_tool_definitions()
        
        max_tool_rounds = 15
        try:
            import plugins.plan_handler as _ph
            if _ph._manager.active_plan:
                max_tool_rounds = 40
        except Exception:
            pass
            
        final_response = None
        consecutive_errors = 0
        current_model = self.model
        
        def _yield_event(event_dict: dict) -> str:
            if "ts" not in event_dict:
                import time
                event_dict["ts"] = time.strftime("%H:%M:%S")
            session.add_message("debug_log", json.dumps(event_dict, ensure_ascii=False))
            self.sessions.save()
            return json.dumps(event_dict, ensure_ascii=False)
        
        # --- Isolated Vision Proxy Analysis ---
        if isinstance(user_input, list):
            has_image = any(isinstance(item, dict) and item.get("type") == "image_url" for item in user_input)
            if has_image and self.image_analyzer_client is not self.client:
                yield _yield_event({"type": "status", "content": f"正在请求视觉分析模型 {self.image_analyzer_model}..."})
                try:
                    proxy_messages = [{"role": "user", "content": user_input}]
                    loop = asyncio.get_event_loop()
                    proxy_resp = await loop.run_in_executor(
                        None, 
                        lambda: self.image_analyzer_client.chat.completions.create(
                            model=self.image_analyzer_model,
                            messages=proxy_messages,
                            max_tokens=2000,
                            temperature=0.3
                        )
                    )
                    image_description = proxy_resp.choices[0].message.content or "未能识别图片内容。"
                    
                    original_prompt = "阅读这张图片"
                    for item in user_input:
                        if isinstance(item, dict) and item.get("type") == "text":
                            original_prompt = item.get("text", original_prompt)
                            
                    new_user_input = f"【视觉感知代理的图像分析报告】\n{image_description}\n\n【用户的原始请求】\n{original_prompt}"
                    messages[-1] = {"role": "user", "content": new_user_input}
                    yield _yield_event({"type": "status", "content": "视觉分析完成，交由主中枢处理..."})
                except Exception as e:
                    yield _yield_event({"type": "error", "content": f"图像解析失败: {e}"})

        tool_errors_history = []

        for round_idx in range(max_tool_rounds):
            yield _yield_event({"type": "status", "content": "🤔 思考中..."})
            
            loop = asyncio.get_event_loop()
            try:
                # We do NOT use streaming from the OpenAI API here because we need full tool call blocks.
                # In the future, this can be optimized to stream the text token by token.
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=current_model,
                        messages=messages,
                        tools=tools if tools else None,
                        tool_choice="auto" if tools else None,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        extra_body={"enable_search": True},
                    )
                )
            except Exception as e:
                yield _yield_event({"type": "error", "content": f"模型调用报错: {e}"})
                break

            msg = response.choices[0].message

            if msg.tool_calls:
                assistant_dict = msg.model_dump(exclude_unset=True)
                for tc_dict in assistant_dict.get("tool_calls") or []:
                    raw_args = tc_dict.get("function", {}).get("arguments", "{}")
                    try:
                        json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        tc_dict["function"]["arguments"] = "{}"
                messages.append(assistant_dict)

                round_had_error = False
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        params = json.loads(tc.function.arguments)
                        if not isinstance(params, dict):
                            params = {}
                    except Exception:
                        params = {}

                    yield _yield_event({
                        "type": "tool_call", 
                        "name": name, 
                        "params": params
                    })
                    
                    try:
                        result = await loop.run_in_executor(None, self.skills.execute, name, params)
                        if not isinstance(result, str):
                            result = str(result)
                    except Exception as e:
                        result = f"Traceback (most recent call last): {e}"

                    yield _yield_event({
                        "type": "tool_result",
                        "name": name,
                        "result": result[:500] + "..." if len(result) > 500 else result
                    })

                    if result.strip().startswith("❌") or "Traceback (most recent call last):" in result:
                        round_had_error = True
                        tool_errors_history.append(f"尝试 `{name}({json.dumps(params, ensure_ascii=False)[:100]})` 失败: {result[:200]}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": result,
                    })
                
                if round_had_error:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                    if tool_errors_history:
                        success_calls = [f"`{tc.function.name}({tc.function.arguments[:100]})`" for tc in msg.tool_calls]
                        experience_log = "**[System - 工具纠错经验自动记录]**\n- 失败尝试录:\n  - " + "\n  - ".join(tool_errors_history) + "\n- 最终解决思路: 成功改用 " + " | ".join(success_calls)
                        self.journal.append(experience_log)
                        tool_errors_history.clear()
                    
                if consecutive_errors >= 3:
                    final_response = "⚠️ **执行安全中止**：连续多次调用工具报错已停止任务。"
                    yield _yield_event({"type": "message", "content": final_response})
                    break

                continue

            final_response = msg.content or ""
            yield _yield_event({"type": "message", "content": final_response})
            break

        if final_response is None:
            final_response = "（已完成工具操作，无额外回复。）"
            yield _yield_event({"type": "message", "content": final_response})

        session.add_message("user", user_input)
        session.add_message("assistant", final_response)
        self.sessions.save()
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._check_all_triggers)

    def _emit_system_event(self, content: str) -> None:
        """Central hub to record and broadcast background system events."""
        if self.event_queue:
            import time
            event = {
                "type": "system",
                "ts": time.strftime("%H:%M:%S"),
                "text": content
            }
            self.event_queue.put(event)
        print(f"[System] {content}")

    def _evolution_loop(self) -> None:
        """
        Background thread to periodically check for cross-day evolution triggers.
        This ensures evolution happens automatically at midnight even if no user interaction occurs.
        """
        import time
        while True:
            time.sleep(60)  # Check every 60 seconds
            try:
                self._check_all_triggers()
            except Exception as e:
                print(f"[EvolutionLoop] Error: {e}")

    def _has_conversations(self, date_str: str) -> bool:
        """Check if there are any real chat messages (not debug_logs) on a given date."""
        for path in self.sessions.sessions_dir.glob("*.json"):
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for m in data.get("messages", []):
                    if m.get("timestamp", "").startswith(date_str) and m.get("role") != "debug_log":
                        return True
            except Exception:
                continue
        return False

    def _startup_evolution(self) -> None:
        """
        On startup, check recent days for un-processed journals or chat sessions.
        """
        from datetime import datetime, timedelta

        today = datetime.now().strftime("%Y-%m-%d")
        # Look back up to 7 days
        for days_back in range(1, 8):
            check_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            
            # If a diary already exists, this day was fully completed.
            if self.diary.has_diary(check_date):
                # We assume earlier days were also processed.
                break

            journal_content = self.journal.read_day(check_date)
            has_journal = bool(journal_content and journal_content.strip())
            
            if not has_journal and not self._has_conversations(check_date):
                continue  # No activity on this day

            # Found an un-processed day!
            self._emit_system_event(f"🔍 发现 {check_date} 的日志尚未总结，已将其加入后台自我进化队列...")
            
            # 串行处理历史遗留任务，每个日期之间增加间隔，防止 429 报错
            _run_evolution(check_date)
            import time
            time.sleep(5) # 每个补做任务之间休息 5 秒

        # Set to today so _check_all_triggers works correctly for future cross-day
        self.last_interaction_date = today

    def _check_all_triggers(self) -> None:
        """Check and execute maintenance triggers."""
        # 1. Date change -> Daily Summary + Evolution
        current_date = time.strftime("%Y-%m-%d")
        if current_date != self.last_interaction_date:
            prev_date = self.last_interaction_date
            self._emit_system_event(f"检测到跨天 ({prev_date} -> {current_date})，后台自我进化已启动。")

            def _run_daily_evo(d=prev_date):
                try:
                    # Step 1: 汇总昨天所有聊天记录写入 journal
                    self._summarize_day_conversations(d)

                    # Step 2: 基于完整 journal (视觉日志 + 聊天总结) 生成 diary + 提取记忆
                    self._emit_system_event(f"🧠 开始后台自我进化：分析 {d} 日志...")
                    new_mems = self.evolution.evolve_from_journal(d)
                    if new_mems:
                        self._emit_system_event(f"✨ 后台进化完成！习得了 {len(new_mems)} 条新记忆。")
                    else:
                        self._emit_system_event(f"✅ 后台进化完成，未通过日志发现新知识。")

                    # Step 3: 尝试人设微调
                    self.evolution.evolve_persona()
                except Exception as e:
                    self._emit_system_event(f"⚠️ 跨天后台进化出错: {e}")

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

        # Format for summarization (ignore debug logs)
        filtered_pruned = [m for m in pruned if m["role"] != "debug_log"]
        if not filtered_pruned:
            print(f"[System] 滚动收尾清理：释放了 {len(pruned)} 条调试信息（无实质内容需总结）。")
            self.sessions.save()
            return
            
        text_block = "\n".join([f"{m['role']}: {m['content']}" for m in filtered_pruned])
        
        # 1. Summarize
        try:
            prompt = f"请总结以下对话片段，提取关键信息（意图、操作、结果），作为'前情提要'。保留关键事实，去除闲聊。\n\n{text_block}"
            
            # Simple retry for 429
            retry_count = 0
            while retry_count < 3:
                try:
                    resp = self.client.chat.completions.create(
                        model=self.evolution_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=500,
                    )
                    summary_text = resp.choices[0].message.content
                    break
                except Exception as e:
                    if "429" in str(e) or "limit" in str(e).lower():
                        retry_count += 1
                        import time
                        time.sleep(5 * retry_count)
                        continue
                    raise e
            else:
                summary_text = "(Summary failed after retries)"
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
        daily_sessions = []
        for path in sorted(self.sessions.sessions_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                messages = data.get("messages", [])
                # Filter messages for the specific date and ignore debug logs
                day_msgs = [
                    m for m in messages
                    if m.get("timestamp", "").startswith(date_str) and m.get("role") != "debug_log"
                ]
                if day_msgs:
                    all_conversations.extend(day_msgs)
            except Exception:
                continue

        if not all_conversations:
            print(f"[System] {date_str} 没有找到聊天记录，跳过对话总结。")
            return

        # Sort by timestamp to ensure chronological order across sessions
        all_conversations.sort(key=lambda m: m.get("timestamp", ""))

        # 2. Format conversation content (and sanitize multimodal payloads for text-only LLM)
        lines = []
        for m in all_conversations:
            role = m["role"]
            if role == "user":
                role_str = "用户"
            elif role == "assistant":
                role_str = "AI"
            elif role == "visual_log":
                role_str = "【系统旁白:视觉感知】"
            else:
                role_str = role
                
            content = m.get("content", "")
            # Multimodal Payload Sanitization: Evolve model (Qwen-max) takes text only
            if isinstance(content, list):
                safe_text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get('type') == 'text':
                            safe_text_parts.append(item.get('text', ''))
                        elif item.get('type') == 'image_url':
                            safe_text_parts.append('[图片附件]') # Replace image with a placeholder
                content = " ".join(safe_text_parts)
            
            if len(content) > 500:
                content = content[:500] + "...(截断)"
            ts = m.get("timestamp", "").split(" ")[-1] if " " in m.get("timestamp", "") else ""
            lines.append(f"[{ts}] {role_str}: {content}")

        conversation_text = "\n".join(lines)

        # 3. 用 LLM 总结
        print(f"[System] 📝 正在总结 {date_str} 的 {len(all_conversations)} 条聊天记录...")
        try:
            prompt = (
                f"请总结以下一天的人机聊天记录，按主题分类整理。\n"
                f"每个主题下需要包含：\n"
                f"1. 主题名称（如：代码调试、工具记录等）\n"
                f"2. 用户的问题或需求\n"
                f"3. AI 的回答与操作记录（特别是工具纠错记录，需要完整提炼出解决思路）\n"
                f"保留具体事实，去除无意义的寒暄。用 Markdown 格式输出。\n"
                f"总字数控制在 2500 字以内。\n\n"
                f"## {date_str} 聊天记录\n{conversation_text}"
            )
            resp = self.client.chat.completions.create(
                model=self.evolution_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8000,
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
