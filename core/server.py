import asyncio
import json
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from sse_starlette.sse import EventSourceResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("qwen_autogui.server")

import queue
import threading

# Global dependencies
app_state: Dict[str, Any] = {}

# ── Global Event Broadcast System ────────────────────────────────────────────
# threading.Queue receives events from the background thread (ContextManager)
# asyncio queues carry them to SSE subscribers
_ctx_event_queue: queue.Queue = queue.Queue()   # thread-safe input
_sse_subscribers: set = set()                   # set of asyncio.Queue
_sse_lock = threading.Lock()

def _broadcast_thread():
    """Bridge: moves items from _ctx_event_queue to all asyncio SSE subscribers."""
    loop = None
    while True:
        try:
            event = _ctx_event_queue.get(timeout=1)
        except queue.Empty:
            continue
        if loop is None:
            loop = app_state.get("event_loop")
        if loop is None:
            continue
        with _sse_lock:
            dead = set()
            for q in _sse_subscribers:
                try:
                    loop.call_soon_threadsafe(q.put_nowait, event)
                except Exception:
                    dead.add(q)
            _sse_subscribers.difference_update(dead)

_bridge = threading.Thread(target=_broadcast_thread, daemon=True, name="SSEBridge")
_bridge.start()

class ChatRequest(BaseModel):
    message: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to initialize and cleanup the Agent."""
    logger.info("Starting OpenAkita Server...")
    
    try:
        from core.agent import Agent
        from core.context import ContextManager
        from core.plugin_manager import PluginManager
        
        # 1. Load config
        config_path = "config.json"
        
        # 2. Init Agent
        agent = Agent(config_path=config_path, data_dir="data", auto_evolve=True)
        agent.event_queue = _ctx_event_queue  # Thread-safe queue for broadcasting system events
        
        # 3. Load core skills (previously only in main.py)
        try:
            from skills import basic
            agent.register_skill_module(basic)
            logger.info("  [OK] 技能加载: basic")
        except Exception as e:
            logger.warning(f"  [WARN] Basic 技能加载失败: {e}")

        try:
            from skills import autogui
            agent.register_skill_module(autogui)
            logger.info("  [OK] 技能加载: autogui")
        except Exception as e:
            logger.warning(f"  [WARN] AutoGUI 加载失败: {e}")

        try:
            from skills import web_search
            agent.register_skill_module(web_search)
            logger.info("  [OK] 技能加载: web_search")
        except Exception as e:
            logger.warning(f"  [WARN] Web 技能加载失败: {e}")

        # 4. Init Plugins
        plugin_manager = PluginManager(skill_manager=agent.skills, plugins_dir="plugins")
        plugin_manager.load_all()
        
        # Start background threads AFTER all plugins and their modules are fully loaded
        agent.start_background_tasks()
        
        # 4. Init Vision Context Manager
        def add_visual_log(content: str):
            agent.add_visual_log(content)
            
        def get_visual_history() -> list[str]:
            return [m["content"] for m in agent.sessions.current.messages if m["role"] == "visual_log"]
            
        def update_visual_log(time_str: str):
            agent.update_visual_log(time_str)
            
        def get_chat_history():
            return [m for m in agent.sessions.current.messages if m["role"] in ("user", "assistant")]
            
        context_manager = ContextManager(
            client=agent.vision_client,
            vision_model=agent.vision_model,
            add_visual_log_func=add_visual_log,
            get_visual_history_func=get_visual_history,
            update_visual_log_func=update_visual_log,
            get_history_func=get_chat_history,
            interval_minutes=agent.config.get("proactive", {}).get("interval_minutes", 5),
            proactive_config=agent.config.get("proactive", {}),
        )
        agent.context = context_manager
        
        # Wire log_queue so context events can be broadcast to the frontend
        context_manager.log_queue = _ctx_event_queue

        # Start the visual context analysis loop
        context_manager.start()
        
        app_state["agent"] = agent
        app_state["context_manager"] = context_manager
        app_state["plugin_manager"] = plugin_manager
        app_state["event_loop"] = asyncio.get_event_loop()

        # 5. Init Task Scheduler
        from core.scheduler import TaskScheduler, ScheduledTask

        async def _scheduled_task_runner(task: ScheduledTask) -> tuple[bool, str]:
            ag = app_state.get("agent")
            if not ag:
                return False, "Agent not ready"
            
            def _push(event: dict):
                _ctx_event_queue.put(event)

            try:
                _push({"type": "chat_event", "role": "system", "content": f"⏰ [计划任务触发] {task.name}"})
                
                # ── 系统内置任务（不走 LLM）──────────────────────────────
                if task.task_type.value == "system":
                    return await _execute_system_task(task, _push)

                if task.task_type.value == "reminder":
                    msg = task.reminder_message or "无提醒内容"
                    # Persist reminder as assistant message so it shows in chat history
                    ag.sessions.current.add_message("assistant", f"⏰ **{task.name}**\n\n{msg}")
                    ag.sessions.save()
                    _push({"type": "chat_event", "role": "assistant", "content": msg})
                    return True, "Reminder sent"
                else:
                    # Build the prompt with task context prefix
                    full_prompt = f"[计划任务: {task.name}] {task.prompt}"
                    _push({"type": "chat_event", "role": "user", "content": full_prompt})

                    # Run ag.chat in a dedicated thread with its own event loop
                    # to avoid nested-asyncio issues (ag.chat is sync but calls asyncio internally)
                    # ag.chat() internally persists both the user message and assistant response.
                    import concurrent.futures

                    def _run_chat():
                        import asyncio as _asyncio
                        loop = _asyncio.new_event_loop()
                        _asyncio.set_event_loop(loop)
                        try:
                            return ag.chat(full_prompt)
                        finally:
                            loop.close()
                            _asyncio.set_event_loop(None)

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="sched") as pool:
                        response = await asyncio.get_running_loop().run_in_executor(pool, _run_chat)

                    _push({"type": "chat_event", "role": "assistant", "content": response})
                    return True, response
            except Exception as e:
                logger.error(f"Scheduled task error: {e}", exc_info=True)
                return False, str(e)

        async def _execute_system_task(task: ScheduledTask, push_fn) -> tuple[bool, str]:
            """执行系统内置任务，不通过 LLM。"""
            action = task.action or ""
            if action == "system:daily_selfcheck":
                return await _system_daily_selfcheck(push_fn)
            return False, f"Unknown system action: {action}"

        async def _system_daily_selfcheck(push_fn) -> tuple[bool, str]:
            """
            系统自检：检查数据目录完整性、日志错误、调度器状态，
            生成摘要报告并以 assistant 消息推送到聊天。
            """
            import glob
            from datetime import datetime

            lines = [f"## 🔍 系统自检报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
            issues = []

            # 1. 数据目录检查
            required_dirs = ["data", "data/sessions", "data/memory", "data/scheduler", "data/diary"]
            for d in required_dirs:
                if not os.path.exists(d):
                    try:
                        os.makedirs(d, exist_ok=True)
                        issues.append(f"⚠️ 目录 `{d}` 不存在，已自动创建")
                    except Exception as e:
                        issues.append(f"❌ 目录 `{d}` 创建失败: {e}")

            # 2. 日志错误扫描（扫描 Python logging 输出的 ERROR 行）
            log_errors: dict[str, int] = {}
            log_files = glob.glob("*.log") + glob.glob("logs/*.log")
            for lf in log_files:
                try:
                    with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if " ERROR " in line or " CRITICAL " in line:
                                # 提取模块名作为 key
                                parts = line.split(" - ")
                                module = parts[1].strip() if len(parts) > 2 else "unknown"
                                log_errors[module] = log_errors.get(module, 0) + 1
                except Exception:
                    pass

            # 3. 调度器任务状态
            scheduler = app_state.get("task_scheduler")
            task_summary = {"total": 0, "enabled": 0, "failed": 0}
            if scheduler:
                tasks = scheduler.list_tasks()
                task_summary["total"] = len(tasks)
                task_summary["enabled"] = sum(1 for t in tasks if t.enabled)
                task_summary["failed"] = sum(1 for t in tasks if t.fail_count > 0)

            # 4. Agent 状态
            ag = app_state.get("agent")
            agent_ok = ag is not None

            # 5. Session 文件数量
            session_count = len(glob.glob("data/sessions/*.json"))

            # 6. 记忆条目数
            memory_count = 0
            memory_file = "data/memory.jsonl"
            if os.path.exists(memory_file):
                try:
                    with open(memory_file, "r", encoding="utf-8") as f:
                        memory_count = sum(1 for line in f if line.strip())
                except Exception:
                    pass

            # ── 组装报告 ──────────────────────────────────────────────
            lines.append(f"\n**Agent 状态**: {'✅ 在线' if agent_ok else '❌ 离线'}")
            lines.append(f"**会话文件**: {session_count} 个")
            lines.append(f"**记忆条目**: {memory_count} 条")
            lines.append(f"\n**计划任务**: 共 {task_summary['total']} 个，启用 {task_summary['enabled']} 个，有失败记录 {task_summary['failed']} 个")

            if log_errors:
                lines.append(f"\n**日志错误** ({sum(log_errors.values())} 条):")
                for mod, cnt in sorted(log_errors.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"  - `{mod}`: {cnt} 次")
            else:
                lines.append("\n**日志错误**: 无")

            if issues:
                lines.append("\n**自动修复**:")
                for issue in issues:
                    lines.append(f"  - {issue}")

            status = "✅ 系统运行正常" if not issues and not log_errors else f"⚠️ 发现 {len(issues)} 个问题，{len(log_errors)} 个错误模块"
            lines.append(f"\n**总结**: {status}")

            report = "\n".join(lines)

            # 持久化到 session 并推送
            if ag:
                ag.sessions.current.add_message("assistant", report)
                ag.sessions.save()
            push_fn({"type": "chat_event", "role": "assistant", "content": report})

            logger.info(f"System selfcheck completed: {status}")
            return True, status

        task_scheduler = TaskScheduler(
            storage_path=Path("data/scheduler"),
            executor=_scheduled_task_runner
        )
        await task_scheduler.start()
        app_state["task_scheduler"] = task_scheduler

        # ── 注册内置系统任务 ──────────────────────────────────────────
        from core.scheduler import TriggerType, TaskType
        
        # 查找是否存在 selfcheck 任务
        existing_selfcheck = next((t for t in task_scheduler.list_tasks() if t.action == "system:daily_selfcheck"), None)

        if not existing_selfcheck:
            selfcheck_task = ScheduledTask(
                id="system_daily_selfcheck",
                name="系统自检",
                description="每日凌晨自动检查数据目录、日志错误、任务状态，生成健康报告",
                trigger_type=TriggerType.CRON,
                trigger_config={"cron": "0 4 * * *"},
                task_type=TaskType.SYSTEM,
                prompt="",
                action="system:daily_selfcheck",
                deletable=False,
            )
            await task_scheduler.add_task(selfcheck_task)
            logger.info("Registered built-in task: system_daily_selfcheck (04:00 daily)")
        else:
            # 确保已有任务的 deletable=False 和 action 正确
            existing = existing_selfcheck
            if existing:
                changed = False
                if existing.deletable:
                    existing.deletable = False
                    changed = True
                if not existing.action:
                    existing.action = "system:daily_selfcheck"
                    changed = True
                if changed:
                    task_scheduler._save_tasks()
        
        logger.info("OpenAkita Server initialized successfully.")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        import traceback
        traceback.print_exc()
        raise e
    finally:
        logger.info("Shutting down OpenAkita Server...")
        if "context_manager" in app_state:
            app_state["context_manager"].stop()
        if "task_scheduler" in app_state:
            await app_state["task_scheduler"].stop()

# Create FastAPI app
app = FastAPI(
    title="Qwen AutoGUI Server",
    description="Backend API Gateway for Qwen AutoGUI with 3D Desktop integration.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Mount static files and templates
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("data/screenshots", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/screenshots", StaticFiles(directory="data/screenshots"), name="screenshots")
templates = Jinja2Templates(directory="templates")

# ─── UI Routes ────────────────────────────────────────────────────────────────
@app.get("/", response_class=FileResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}



@app.get("/api/config")
async def get_config():
    """Get the current configuration from config.json."""
    if not os.path.exists("config.json"):
        raise HTTPException(status_code=404, detail="config.json not found")
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {str(e)}")

@app.post("/api/config")
async def update_config(request: Request):
    """Update config.json and reload applicable parts of the agent."""
    try:
        new_config = await request.json()

        # Schema validation: must be a dict and contain known top-level keys only
        _ALLOWED_KEYS = {"proactive", "browser_choice", "model", "api_key", "base_url",
                         "persona", "memory", "skills", "plugins", "journal", "knowledge_graph",
                         "api", "vision", "image_analyzer", "embedding", "autogui", "screen", "agent"}
        if not isinstance(new_config, dict):
            raise HTTPException(status_code=400, detail="Config must be a JSON object")
        unknown_keys = set(new_config.keys()) - _ALLOWED_KEYS
        if unknown_keys:
            raise HTTPException(status_code=400, detail=f"Unknown config keys: {unknown_keys}")

        # Validate proactive sub-object if present
        if "proactive" in new_config:
            p = new_config["proactive"]
            if not isinstance(p, dict):
                raise HTTPException(status_code=400, detail="proactive must be an object")
            for field in ("interval_minutes", "cooldown_minutes"):
                if field in p and p[field] is not None and not isinstance(p[field], (int, float)):
                    raise HTTPException(status_code=400, detail=f"proactive.{field} must be a number or null")

        # Save to file
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=4, ensure_ascii=False)

        # Dynamically reload proactive config
        if "agent" in app_state:
            app_state["agent"].config = new_config
        if "context_manager" in app_state:
            app_state["context_manager"].reload_config(new_config.get("proactive", {}))

        return {"status": "success", "message": "Config updated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")

@app.post("/api/context/poke")
async def poke_context():
    """Manually trigger a proactive vision analysis cycle."""
    if "context_manager" not in app_state:
        raise HTTPException(status_code=400, detail="ContextManager not initialized")
    app_state["context_manager"].poke()
    return {"status": "success", "message": "Poked"}

@app.post("/api/sandbox/clear")
async def clear_sandbox():
    """Clear all active python sandboxes."""
    try:
        from plugins.sandbox_repl import _sandboxes
        count = len(_sandboxes)
        for sb in list(_sandboxes.values()):
            sb.close()
        _sandboxes.clear()
        return {"status": "ok", "message": f"成功清理了 {count} 个存活的沙箱实例。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    """Get current status of the agent (e.g. idle, working, vision mode)."""
    agent = app_state.get("agent")
    ctx = app_state.get("context_manager")
    
    if not agent:
        return {"status": "offline"}
        
    return {
        "status": "online",
        "vision_enabled": getattr(ctx, "_enabled", False) if ctx else False,
        "vision_mode": getattr(ctx, "mode", "unknown") if ctx else "unknown",
            "last_context_summary": getattr(ctx, "_last_summary", "") if ctx else ""
    }

@app.post("/api/skills/config")
async def save_skill_config(request: Request):
    """Save configuration for a specific skill."""
    data = await request.json()
    skill_name = data.get("name")
    config_values = data.get("config_values", {})
    
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not ready")
        
    try:
        agent.skills.update_config(skill_name, config_values)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error saving skill config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─── Scheduler Routes ────────────────────────────────────────────────────────

from core.scheduler import ScheduledTask, TriggerType, TaskType

@app.get("/api/scheduler/tasks")
async def list_tasks():
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        return {"tasks": []}
    
    tasks = scheduler.list_tasks()
    return {"tasks": [t.to_dict() for t in tasks]}

@app.post("/api/scheduler/tasks")
async def create_task(req: Request):
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not ready")
    
    data = await req.json()
    try:
        task = ScheduledTask.create(
            name=data["name"],
            description=data.get("description", ""),
            trigger_type=TriggerType(data["trigger_type"]),
            trigger_config=data["trigger_config"],
            prompt=data.get("prompt", ""),
            task_type=TaskType(data.get("task_type", "task")),
            reminder_message=data.get("reminder_message"),
            action=data.get("action")
        )
        if not data.get("enabled", True):
            task.disable()
            
        await scheduler.add_task(task)
        return {"status": "success", "task_id": task.id}
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/scheduler/tasks/{task_id}")
async def update_task(task_id: str, req: Request):
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not ready")
        
    data = await req.json()
    success = await scheduler.update_task(task_id, data)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}

@app.delete("/api/scheduler/tasks/{task_id}")
async def delete_task(task_id: str):
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not ready")
        
    success = await scheduler.remove_task(task_id, force=True)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}

@app.post("/api/scheduler/tasks/{task_id}/toggle")
async def toggle_task(task_id: str, req: Request):
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not ready")
        
    data = await req.json()
    enabled = data.get("enabled", True)
    
    if enabled:
        success = await scheduler.enable_task(task_id)
    else:
        success = await scheduler.disable_task(task_id)
        
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}

@app.post("/api/scheduler/tasks/{task_id}/trigger")
async def trigger_task(task_id: str):
    scheduler = app_state.get("task_scheduler")
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not ready")
        
    success = await scheduler.trigger_now(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}

@app.post("/api/chat/sync")
async def chat_sync(request: ChatRequest):
    """Synchronous chat endpoint. Blocks until the agent finishes processing."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
        
    try:
        response = agent.chat(request.message)
        return {"response": response}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.post("/api/chat/upload")
async def chat_upload(file: UploadFile = File(...), prompt: str = Form(default="")):
    """
    Accept a file (image or plain text) from the frontend, convert it to a
    multimodal message, and stream the agent response via SSE.

    Supported types:
      - image/*  → base64-encoded image_url content block
      - text/*   → inline text content block
    """
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    content_type = (file.content_type or "").lower()
    raw = await file.read()

    if content_type.startswith("image/"):
        import base64
        b64 = base64.b64encode(raw).decode("utf-8")
        data_url = f"data:{content_type};base64,{b64}"
        user_content = [
            {"type": "image_url", "image_url": {"url": data_url}},
            # Always include a text block; use user's prompt if provided,
            # otherwise a neutral fallback so the vision model has a task.
            {"type": "text", "text": prompt if prompt.strip() else "请描述这张图片的内容。"},
        ]
    elif content_type.startswith("text/") or file.filename.lower().endswith((".txt", ".md", ".csv", ".log")):
        try:
            text_body = raw.decode("utf-8", errors="replace")
        except Exception:
            text_body = raw.decode("latin-1", errors="replace")
        user_content = (
            f"【文件内容：{file.filename}】\n```\n{text_body[:8000]}\n```\n\n"
            + (prompt or "请分析以上文件内容。")
        )
    else:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_type}")

    async def event_generator():
        try:
            async for chunk in agent.chat_stream(user_content):
                yield dict(data=chunk)
            yield dict(data="[DONE]")
        except Exception as e:
            logger.error(f"Upload stream error: {e}")
            yield dict(data=json.dumps({"type": "error", "content": str(e)}))

    return EventSourceResponse(event_generator())


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint using Server-Sent Events (SSE).
    This allows intermediate tool execution logs to be sent to the frontend.
    """
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    async def event_generator():
        try:
            async for chunk in agent.chat_stream(request.message):
                yield dict(data=chunk)
            yield dict(data="[DONE]")
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield dict(data=json.dumps({"type": "error", "content": str(e)}))
            
    return EventSourceResponse(event_generator())

# ─── Session & Memory Management API ─────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    """Return a summary list of all past sessions."""
    sessions_dir = "data/sessions"
    if not os.path.exists(sessions_dir):
        return []
    result = []
    for fname in sorted(os.listdir(sessions_dir), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(sessions_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = data.get("messages", [])
            title = next(
                (
                    (m["content"] if isinstance(m["content"], str) else
                     " ".join(p.get("text","") for p in m["content"] if isinstance(p,dict) and p.get("type")=="text"))[:40]
                    for m in messages
                    if m.get("role") == "user" and m.get("content")
                ),
                "(\u7a7a\u5bf9\u8bdd)"
            )
            result.append({
                "id": fname.replace(".json", ""),
                "title": title,
                "message_count": len([m for m in messages if m.get("role") in ("user", "assistant")]),
                "created_at": data.get("created_at", "")
            })
        except Exception:
            continue
    return result[:30]

@app.post("/api/sessions/new")
async def new_session():
    """Ask the agent to start a fresh session."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    agent.sessions.new_session()
    agent.sessions.save()
    session_id = getattr(agent.sessions.current, 'session_id', 'unknown')
    return {"status": "ok", "session_id": session_id}

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Return the chat messages of a specific session."""
    fpath = f"data/sessions/{session_id}.json"
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Session not found")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Passthrough all displayable roles to the frontend (it decides how to render each)
    EXCLUDED_ROLES = {"system", "tool"}  # internal scaffolding only; never shown
    messages = [m for m in data.get("messages", []) if m.get("role") not in EXCLUDED_ROLES]
    return {"session_id": session_id, "messages": messages}

@app.get("/api/sessions/current/info")
async def get_current_session():
    """Return the current active session ID so the frontend can load it on startup."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not ready")
    session_id = getattr(agent.sessions.current, "session_id", None)
    if not session_id:
        raise HTTPException(status_code=404, detail="No active session")
    return {"session_id": session_id}

@app.get("/api/diary")
async def list_diary():
    """Return a list of available diary dates."""
    diary_dir = "data/diary"
    if not os.path.exists(diary_dir):
        return []
    return sorted([f.replace(".md", "") for f in os.listdir(diary_dir) if f.endswith(".md")], reverse=True)

@app.get("/api/diary/{date}")
async def get_diary(date: str):
    """Return the content of a diary entry."""
    fpath = f"data/diary/{date}.md"
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Diary not found")
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"date": date, "content": content}

# ─── Memory API ───────────────────────────────────────────────────────────────

class MemoryCreateRequest(BaseModel):
    content: str
    type: Optional[str] = "fact"
    tags: Optional[list] = []

class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[list] = None

@app.get("/api/memory")
async def list_memory(type: Optional[str] = None, q: Optional[str] = None):
    """Return memory items, optionally filtered by type or keyword."""
    agent = app_state.get("agent")
    if not agent or not agent.memory:
        return {"memories": []}
    if type:
        items = agent.memory.list_by_type(type)
    else:
        items = agent.memory.list_all()
    if q:
        q_lower = q.lower()
        items = [m for m in items if q_lower in m.content.lower()]
    return {"memories": [m.to_dict() for m in items]}

@app.post("/api/memory")
async def create_memory(req: MemoryCreateRequest):
    """Create a new memory item."""
    agent = app_state.get("agent")
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory not available")
    item = agent.memory.add(req.content, tags=req.tags, type=req.type)
    return {"memory": item.to_dict()}

@app.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """Delete a memory item by ID."""
    agent = app_state.get("agent")
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory not available")
    ok = agent.memory.delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}

@app.put("/api/memory/{memory_id}")
async def update_memory(memory_id: str, req: MemoryUpdateRequest):
    """Update a memory item's content, type, or tags."""
    agent = app_state.get("agent")
    if not agent or not agent.memory:
        raise HTTPException(status_code=503, detail="Memory not available")
    ok = agent.memory.update(
        memory_id,
        new_content=req.content,
        new_tags=req.tags,
        new_type=req.type,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}

@app.get("/api/persona")
async def get_persona():
    """Return a readable summary of persona (PERSONA.md + identities)."""
    identities_dir = "data/identities"
    result = {}
    if os.path.exists(identities_dir):
        for fname in os.listdir(identities_dir):
            if fname.endswith(".md"):
                with open(os.path.join(identities_dir, fname), "r", encoding="utf-8") as f:
                    result[fname.replace(".md", "")] = f.read()
    return result

@app.get("/api/events")
async def stream_events(request: Request):
    """
    SSE endpoint that streams real-time system events (visual context analysis, etc.)
    to the frontend. Each client gets its own asyncio.Queue.
    """
    my_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    with _sse_lock:
        _sse_subscribers.add(my_queue)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(my_queue.get(), timeout=30)
                    yield {"data": json.dumps(event, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    # Send a heartbeat comment to keep the connection alive
                    yield {"comment": "heartbeat"}
        except asyncio.CancelledError:
            # Uvicorn is shutting down or client hard-disconnected the task
            pass
        finally:
            with _sse_lock:
                _sse_subscribers.discard(my_queue)

    return EventSourceResponse(generator())

# ─── VRM Preferences API ──────────────────────────────────────────────────────
_PREFS_FILE = "data/vrm_preferences.json"

@app.get("/api/config/preferences")
async def get_preferences():
    """Return saved VRM model preferences (position, scale, rotation, etc.)."""
    if os.path.exists(_PREFS_FILE):
        with open(_PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 返回空对象，让前端使用默认值
    return {}

@app.post("/api/config/preferences")
async def save_preferences(request: Request):
    """Save VRM model preferences sent from the frontend."""
    try:
        data = await request.json()
        os.makedirs("data", exist_ok=True)
        with open(_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/vrm/models")
async def list_vrm_models():
    """List all available VRM models in the static/models directory."""
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "models")
    os.makedirs(models_dir, exist_ok=True)
    models = []
    for f in os.listdir(models_dir):
        if f.lower().endswith('.vrm'):
            models.append({"name": f, "path": f"/static/models/{f}"})
    return {"models": models}

@app.get("/api/vrm/animations")
async def list_vrm_animations():
    """List all available VRMA animations in the static/vrm/animation directory."""
    anim_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "vrm", "animation")
    os.makedirs(anim_dir, exist_ok=True)
    animations = []
    for f in os.listdir(anim_dir):
        if f.lower().endswith('.vrma'):
            name = os.path.splitext(f)[0]
            animations.append({"name": name, "path": f"/static/vrm/animation/{f}"})
    return {"animations": animations}

@app.post("/api/vrm/upload")
async def upload_vrm_model(file: UploadFile = File(...)):
    """Upload a new VRM model to the static/models directory."""
    if not file.filename.lower().endswith('.vrm'):
        raise HTTPException(status_code=400, detail="Only .vrm files are allowed.")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "models")
    os.makedirs(models_dir, exist_ok=True)
    file_path = os.path.join(models_dir, file.filename)
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        return {"status": "ok", "filename": file.filename, "path": f"/static/models/{file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/vrm/models/{filename}")
async def delete_vrm_model(filename: str):
    """Delete a VRM model from the static/models directory."""
    models_dir = os.path.realpath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "models")
    )
    file_path = os.path.realpath(os.path.join(models_dir, filename))

    # Security: reject path traversal and non-.vrm files
    if not file_path.startswith(models_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not filename.lower().endswith('.vrm'):
        raise HTTPException(status_code=400, detail="Invalid file type")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model file not found")

    try:
        os.remove(file_path)
        logger.info(f"Deleted model file: {file_path}")
        return {"status": "ok", "message": f"Model {filename} deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting model {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")

# ─── VRM Store API ────────────────────────────────────────────────────────────

class StoreDownloadRequest(BaseModel):
    url: str
    type: str  # "model" or "animation"
    name: str

@app.get("/api/store/list")
async def get_store_index():
    """Fetch the store index JSON (currently served from a local mock file)."""
    # In a real scenario, this could fetch from a GitHub raw URL
    index_path = "data/store_index.json"
    if not os.path.exists(index_path):
        return {"models": [], "animations": []}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.post("/api/store/download")
async def download_store_item(req: StoreDownloadRequest, background_tasks: BackgroundTasks):
    """Asynchronously download a model or animation from the store URL."""
    if req.type == "model":
        target_dir = os.path.join("static", "models")
        filename = f"{req.name}.vrm"
    elif req.type == "animation":
        target_dir = os.path.join("static", "vrm", "animation")
        filename = f"{req.name}.vrma"
    else:
        raise HTTPException(status_code=400, detail="Invalid resource type")
        
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, filename)

    async def _download_task():
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                async with client.stream('GET', req.url) as response:
                    response.raise_for_status()
                    with open(file_path, 'wb') as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            logger.info(f"Successfully downloaded {req.type} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to download {req.url}: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)

    # Return immediately while download happens in background
    background_tasks.add_task(_download_task)
    return {"status": "started", "message": f"Downloading {req.name} in background..."}

# ─── Skills Management API ────────────────────────────────────────────────────
@app.get("/api/skills/list")
async def list_skills():
    """Get list of all registered skills with their status."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    skills_data = []
    for skill in agent.skills._registry.values():
        skills_data.append({
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "enabled": skill.enabled,
            "parameters": skill.parameters,
            "ui_config": skill.ui_config,
            "config_values": skill.config_values
        })
    
    return {"skills": skills_data}

class SkillToggleRequest(BaseModel):
    name: str
    enabled: bool

class SkillConfigRequest(BaseModel):
    name: str
    config: Dict[str, Any]

@app.post("/api/skills/config")
async def config_skill(request: SkillConfigRequest):
    """Update a skill's configuration values."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    skill = agent.skills.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")
        
    agent.skills.update_config(request.name, request.config)
    return {"status": "success", "name": request.name, "config_values": skill.config_values}

@app.post("/api/skills/toggle")
async def toggle_skill(request: SkillToggleRequest):
    """Enable or disable a skill."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    skill = agent.skills.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")
    
    if request.enabled:
        agent.skills.enable(request.name)
    else:
        agent.skills.disable(request.name)
    
    return {"status": "success", "name": request.name, "enabled": request.enabled}

@app.post("/api/skills/reload")
async def reload_skills():
    """Reload all skills."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        import importlib
        from skills import basic, autogui, office_tools, web_reader, system_tools, file_manager

        # Reload core skill modules
        importlib.reload(basic)
        importlib.reload(autogui)
        importlib.reload(office_tools)
        importlib.reload(web_reader)
        importlib.reload(system_tools)
        importlib.reload(file_manager)

        # Re-register core skills
        agent.skills._registry.clear()
        
        # Re-register built-in bounds
        if hasattr(agent, "_register_builtins"):
            agent._register_builtins()
        if hasattr(agent, "_build_builtin_skills"):
            agent._build_builtin_skills()
            
        # Re-register core skills modules
        agent.register_skill_module(basic)
        agent.register_skill_module(autogui)
        agent.register_skill_module(office_tools)
        agent.register_skill_module(web_reader)
        agent.register_skill_module(system_tools)
        agent.register_skill_module(file_manager)

        # Re-register plugin skills so the count matches startup
        plugin_manager = app_state.get("plugin_manager")
        if plugin_manager:
            plugin_manager.reload_all()

        return {"status": "success", "message": "Skills reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload skills: {str(e)}")

# ─── Skills Marketplace Proxy ────────────────────────────────────────────────────
_marketplace_cache: dict = {}   # key: query  →  (timestamp, data)
_MARKETPLACE_CACHE_TTL = 60     # seconds

@app.get("/api/skills/marketplace")
async def skills_marketplace(q: str = "agent"):
    """Proxy requests to skills.sh to avoid CORS issues in browser.
    Results are cached for 60 seconds per query to minimise external API calls.
    """
    import time

    # ── Try to import httpx; auto‑install if missing ──
    try:
        import httpx
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"], check=False)
        try:
            import httpx
        except ImportError:
            return {"skills": [], "error": "httpx not available; could not install automatically"}

    # ── Cache lookup ──
    cache_key = q.strip().lower()
    now = time.time()
    if cache_key in _marketplace_cache:
        ts, cached_data = _marketplace_cache[cache_key]
        if now - ts < _MARKETPLACE_CACHE_TTL:
            return cached_data

    agent = app_state.get("agent")

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            url = f"https://skills.sh/api/search?q={q}"
            resp = await client.get(url, headers={"User-Agent": "openGuiclaw/1.0"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        # Return empty list instead of erroring so UI degrades gracefully
        return {"skills": [], "error": str(e)}

    # ── Enrich with "installed" status ──
    installed_urls: set = set()
    if agent:
        for skill in agent.skills._registry.values():
            src = getattr(skill, "source_url", None) or getattr(skill, "sourceUrl", None)
            if src:
                installed_urls.add(src)

    raw_skills = data.get("skills", [])
    enriched = []
    for s in raw_skills:
        source = str(s.get("source", ""))
        skill_id = str(s.get("skillId", s.get("name", "")))
        install_url = f"{source}@{skill_id}" if source else skill_id
        
        # Fallback description since API often returns null for list items
        description = s.get("description")
        if not description:
            # Create a pretty title from the ID (e.g. vercel-react-native -> Vercel React Native)
            description = skill_id.replace("-", " ").replace("_", " ").title()
            
        # Refine tags
        tags: list = list(s.get("tags", []) or [])
        if not tags:
            # Extract author as a tag
            if "/" in source:
                author = source.split("/")[0]
                if author not in tags: tags.append(author)
            # Add category if exists
            cat = s.get("category")
            if cat and cat not in tags: tags.append(cat.lower())
        
        enriched.append({
            "id": str(s.get("id", "")),
            "name": skill_id,
            "description": str(description),
            "author": source.split("/")[0] if source else "community",
            "url": install_url,
            "installs": s.get("installs", 0),
            "stars": s.get("stars", 0),
            "tags": tags,
            "installed": install_url in installed_urls,
        })

    result = {"skills": enriched}
    _marketplace_cache[cache_key] = (now, result)
    return result

# ─── Skill Install ────────────────────────────────────────────────────────────────
class SkillInstallRequest(BaseModel):
    url: str
    name: str = ""

@app.post("/api/skills/install")
async def install_skill(request: SkillInstallRequest):
    """Install a skill from a URL via pip or skills.sh CLI."""
    import subprocess, sys, shlex
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Determine install source - support GitHub URLs, skills.sh IDs, and pip packages
    if url.startswith("http://") or url.startswith("https://"):
        pip_url = f"git+{url}"
    elif "/" in url and not url.startswith("git+"):
        # skills.sh format: "source@skillId" or "username/repo"
        pip_url = f"git+https://github.com/{url}"
    else:
        pip_url = url  # plain package name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pip_url, "--quiet"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise Exception(result.stderr or result.stdout or "pip install failed")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Installation timed out (>120s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Installation failed: {e}")

    # Hot-reload after install
    try:
        if hasattr(agent, "_register_builtins"):
            agent._register_builtins()
        if hasattr(agent, "_build_builtin_skills"):
            agent._build_builtin_skills()
        plugin_manager = app_state.get("plugin_manager")
        if plugin_manager:
            plugin_manager.reload_all()
    except Exception:
        pass  # Reload failure shouldn't block success response

    return {
        "status": "success",
        "message": f"Skill installed from {url}",
        "source_url": url
    }

# ─── Skill Uninstall ─────────────────────────────────────────────────────────────
class SkillUninstallRequest(BaseModel):
    name: str

@app.post("/api/skills/uninstall")
async def uninstall_skill(request: SkillUninstallRequest):
    """Uninstall an external skill by name."""
    import subprocess, sys
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    skill = agent.skills.get(request.name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{request.name}' not found")

    source_url = getattr(skill, "source_url", None)
    if not source_url:
        raise HTTPException(status_code=400, detail=f"Skill '{request.name}' is a built-in skill and cannot be uninstalled")

    # Determine package name to uninstall
    pkg_name = request.name.replace("_", "-")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", pkg_name, "-y", "--quiet"],
            capture_output=True, text=True, timeout=60
        )
        # Don't fail if pip can't find it by name - the skill files may need manual removal
    except Exception as e:
        logger.warning(f"pip uninstall warning for {pkg_name}: {e}")

    # Remove from registry
    try:
        if request.name in agent.skills._registry:
            del agent.skills._registry[request.name]
    except Exception as e:
        logger.warning(f"Failed to remove {request.name} from registry: {e}")

    return {"status": "success", "message": f"Skill '{request.name}' uninstalled"}

@app.get("/api/token-stats")
async def get_token_stats(period: str = "all"):
    """Return token usage statistics.

    period: all | 1天 | 3天 | 1周 | 1月 | 6月 | 1年
    Returns aggregated totals + per-model breakdown for the given period.
    """
    import sqlite3
    from datetime import datetime, timedelta

    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    # Build time filter
    delta_map = {
        "1d": timedelta(days=1),
        "3d": timedelta(days=3),
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "6m": timedelta(days=180),
        "1y": timedelta(days=365),
    }
    where_clause = ""
    params: list = []
    if period in delta_map:
        since = (datetime.now() - delta_map[period]).strftime("%Y-%m-%d %H:%M:%S")
        where_clause = "WHERE timestamp >= ?"
        params = [since]

    try:
        with sqlite3.connect(agent._token_db_path) as conn:
            # Totals
            row = conn.execute(
                f"SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens), COUNT(*) "
                f"FROM token_usage {where_clause}",
                params,
            ).fetchone()
            total_p, total_c, total_t, total_req = (row[0] or 0, row[1] or 0, row[2] or 0, row[3] or 0)

            # Per-model
            model_rows = conn.execute(
                f"SELECT model, SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens), COUNT(*) "
                f"FROM token_usage {where_clause} GROUP BY model",
                params,
            ).fetchall()
            by_model = {
                r[0]: {"prompt": r[1] or 0, "completion": r[2] or 0, "total": r[3] or 0, "count": r[4] or 0}
                for r in model_rows
            }

            # Timeline: hourly buckets for 1d/3d, daily for others
            if period in ("1d", "3d"):
                bucket_fmt = "%Y-%m-%d %H:00"
                sqlite_fmt = "strftime('%Y-%m-%d %H:00', timestamp)"
            else:
                bucket_fmt = "%Y-%m-%d"
                sqlite_fmt = "strftime('%Y-%m-%d', timestamp)"

            tl_rows = conn.execute(
                f"SELECT {sqlite_fmt} as bucket, SUM(prompt_tokens), SUM(completion_tokens), SUM(total_tokens) "
                f"FROM token_usage {where_clause} GROUP BY bucket ORDER BY bucket",
                params,
            ).fetchall()
            timeline = [
                {"time": r[0], "prompt": r[1] or 0, "completion": r[2] or 0, "total": r[3] or 0}
                for r in tl_rows
            ]
    except Exception as e:
        # Fallback to in-memory stats if DB unavailable
        return agent.token_stats

    return {
        "period": period,
        "total_prompt_tokens": total_p,
        "total_completion_tokens": total_c,
        "total_tokens": total_t,
        "request_count": total_req,
        "by_model": by_model,
        "timeline": timeline,
    }


@app.post("/api/token-stats/reset")
async def reset_token_stats():
    """Reset token usage counters to zero (truncates DB table)."""
    import sqlite3

    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    try:
        with sqlite3.connect(agent._token_db_path) as conn:
            conn.execute("DELETE FROM token_usage")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")
    agent.token_stats = {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
        "by_model": {},
    }
    return {"status": "ok"}


# ─── Model Endpoint Configuration API ────────────────────────────────────────

# Built-in provider presets (matching openakita's registry style)
_BUILTIN_PROVIDERS = [
    # ── 💻 编程专用端点 (Coding Plans) ─────────────────────────────────────────
    {
        "slug": "dashscope-coding", "name": "阿里云 DashScope (Coding)", "category": "coding",
        "api_type": "openai", "base_url": "https://coding.dashscope.aliyuncs.com/v1",
        "key_hint": "DASHSCOPE_API_KEY", "is_local": False,
        "desc": "阿里编程专版，适配 AutoGUI 与代码生成",
        "models": ["qwen3.5-plus", "qwen3-max"],
    },
    {
        "slug": "kimi-coding", "name": "Kimi (Coding)", "category": "coding",
        "api_type": "anthropic", "base_url": "https://api.kimi.com/coding/",
        "key_hint": "KIMI_API_KEY", "is_local": False,
        "desc": "Kimi 编程专版 (Anthropic 协议适配)",
        "models": ["kimi-k2.5", "kimi-k2"],
    },
    {
        "slug": "minimax-coding", "name": "MiniMax (Coding)", "category": "coding",
        "api_type": "anthropic", "base_url": "https://api.minimaxi.com/anthropic",
        "key_hint": "MINIMAX_API_KEY", "is_local": False,
        "desc": "MiniMax 编程专版 (Anthropic 协议适配)",
        "models": ["minimax-m2.5", "minimax-m2"],
    },
    {
        "slug": "zhipu-coding", "name": "智谱 ZhipuAI (Coding)", "category": "coding",
        "api_type": "anthropic", "base_url": "https://open.bigmodel.cn/api/anthropic",
        "key_hint": "ZHIPU_API_KEY", "is_local": False,
        "desc": "智谱编程专版 (Anthropic 协议适配)",
        "models": ["glm-4-plus", "glm-5"],
    },
    {
        "slug": "volcengine-coding", "name": "火山方舟 (Coding)", "category": "coding",
        "api_type": "anthropic", "base_url": "https://ark.cn-beijing.volces.com/api/coding",
        "key_hint": "ARK_API_KEY", "is_local": False,
        "desc": "火山引擎编程专版 (Anthropic 协议适配)",
        "models": ["doubao-1.5-pro-256k", "doubao-seed-1-6"],
    },
    # ── 🇨🇳 国内官方服务商 ───────────────────────────────────────────────────────
    {
        "slug": "dashscope",    "name": "阿里云 DashScope",  "category": "cn_official",
        "api_type": "openai",   "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_hint": "DASHSCOPE_API_KEY", "is_local": False,
        "desc": "通义千问官方端点，支持全系列模型",
        "models": ["qwen3.5-plus", "qwen3-max", "qwen-plus", "qwen-turbo", "qwen-vl-max", "text-embedding-v4"],
    },
    {
        "slug": "zhipu",  "name": "智谱 ZhipuAI",  "category": "cn_official",
        "api_type": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_hint": "ZHIPU_API_KEY", "is_local": False,
        "desc": "GLM 系列官方端点",
        "models": ["glm-4-plus", "glm-4v-plus", "glm-5", "glm-4-air", "glm-4-flash"],
    },
    {
        "slug": "moonshot", "name": "Kimi (月之暗面)",  "category": "cn_official",
        "api_type": "openai", "base_url": "https://api.moonshot.cn/v1",
        "key_hint": "MOONSHOT_API_KEY", "is_local": False,
        "desc": "Kimi 官方标准端点",
        "models": ["kimi-k2.5", "kimi-k2", "moonshot-v1-128k"],
    },
    {
        "slug": "minimax", "name": "MiniMax",  "category": "cn_official",
        "api_type": "openai", "base_url": "https://api.minimax.chat/v1",
        "key_hint": "MINIMAX_API_KEY", "is_local": False,
        "desc": "MiniMax 官方标准端点",
        "models": ["minimax-m2.5", "minimax-m2", "abab6.5s-chat"],
    },
    # ── 🌐 国际官方服务商 ───────────────────────────────────────────────────────
    {
        "slug": "openai", "name": "OpenAI",  "category": "intl_official",
        "api_type": "openai", "base_url": "https://api.openai.com/v1",
        "key_hint": "OPENAI_API_KEY", "is_local": False,
        "desc": "GPT-4o / o1 官方端点",
        "models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
    },
    {
        "slug": "anthropic", "name": "Anthropic",  "category": "intl_official",
        "api_type": "anthropic", "base_url": "https://api.anthropic.com",
        "key_hint": "ANTHROPIC_API_KEY", "is_local": False,
        "desc": "Claude 3.5 系列官方端点",
        "models": ["claude-opus-4.5", "claude-sonnet-4.5", "claude-haiku-4.5", "claude-3-5-sonnet"],
    },
    {
        "slug": "google", "name": "Google Gemini",  "category": "intl_official",
        "api_type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_hint": "GOOGLE_API_KEY", "is_local": False,
        "desc": "Gemini 系列官方端点",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
    {
        "slug": "deepseek", "name": "DeepSeek",  "category": "intl_official",
        "api_type": "openai", "base_url": "https://api.deepseek.com/v1",
        "key_hint": "DEEPSEEK_API_KEY", "is_local": False,
        "desc": "DeepSeek 官方低价端点",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    # ── 🔀 中转/聚合服务商 ────────────────────────────────────────────────────
    {
        "slug": "siliconflow", "name": "SiliconFlow",  "category": "relay",
        "api_type": "openai", "base_url": "https://api.siliconflow.cn/v1",
        "key_hint": "SILICONFLOW_API_KEY", "is_local": False,
        "desc": "硅基流动，低价开源模型中转",
        "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen3-235B-A22B"],
    },
    {
        "slug": "openrouter", "name": "OpenRouter",  "category": "relay",
        "api_type": "openai", "base_url": "https://openrouter.ai/api/v1",
        "key_hint": "OPENROUTER_API_KEY", "is_local": False,
        "desc": "国际顶级模型聚合平台",
        "models": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "meta-llama/llama-3.3-70b-instruct"],
    },
    # ── 💻 本地模型 ──────────────────────────────────────────────────────────
    {
        "slug": "ollama", "name": "Ollama (本地)",  "category": "local",
        "api_type": "openai", "base_url": "http://localhost:11434/v1",
        "key_hint": "", "is_local": True,
        "desc": "本地开源模型推理",
        "models": ["llama3.1:8b", "qwen2.5:7b", "deepseek-r1:8b"],
    },
]

# Endpoint role definitions
_ENDPOINT_ROLES = [
    {"key": "api",            "label": "主模型",    "desc": "主要对话与工具调用",             "icon": "🧠"},
    {"key": "vision",         "label": "视觉模型",  "desc": "屏幕截图分析与主动感知",          "icon": "👁"},
    {"key": "image_analyzer", "label": "图像解析",  "desc": "用户上传图片智能解读",            "icon": "🖼"},
    {"key": "embedding",      "label": "嵌入模型",  "desc": "向量语义检索与记忆",             "icon": "🔢"},
    {"key": "autogui",        "label": "GUI 操作",  "desc": "屏幕自动化与界面交互",           "icon": "🤖"},
]


class ModelEndpointWrite(BaseModel):
    role: str      # "api" | "vision" | "image_analyzer" | "embedding" | "autogui"
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    context_window: Optional[int] = None


@app.get("/api/config/model/providers")
async def get_model_providers():
    """Return built-in provider presets for the LLM configuration UI."""
    return {"providers": _BUILTIN_PROVIDERS, "roles": _ENDPOINT_ROLES}


@app.get("/api/config/model")
async def get_model_config():
    """Read current model endpoint configuration from config.json."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        return {"config": {}, "error": "config.json not found"}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)
        # Return only model-related sections, masking API keys
        result = {}
        for role_def in _ENDPOINT_ROLES:
            key = role_def["key"]
            section = full.get(key, {})
            if section:
                # Mask api_key for display
                api_key = section.get("api_key", "")
                masked_key = (api_key[:4] + "***" + api_key[-2:]) if len(api_key) > 6 else ("***" if api_key else "")
                result[key] = {
                    "base_url": section.get("base_url", ""),
                    "api_key": api_key,          # full key for editing
                    "api_key_masked": masked_key, # masked for display
                    "model": section.get("model", ""),
                    "max_tokens": section.get("max_tokens"),
                    "temperature": section.get("temperature"),
                    "context_window": section.get("context_window"),
                    "configured": bool(section.get("api_key") and section.get("model")),
                }
            else:
                result[key] = {"configured": False}
        return {"config": result}
    except Exception as e:
        return {"config": {}, "error": str(e)}


@app.post("/api/config/model")
async def set_model_config(body: ModelEndpointWrite):
    """Write an endpoint role's config to config.json and hot-reload the agent client."""
    valid_roles = {r["key"] for r in _ENDPOINT_ROLES}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    cfg_path = Path("config.json")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")

    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)

        if body.role not in full:
            full[body.role] = {}

        section = full[body.role]
        section["base_url"] = body.base_url
        section["api_key"] = body.api_key
        section["model"] = body.model
        if body.max_tokens is not None:
            section["max_tokens"] = body.max_tokens
        if body.temperature is not None:
            section["temperature"] = body.temperature
        if body.context_window is not None:
            section["context_window"] = body.context_window

        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)

        # Hot-reload: update the running agent's client/model
        agent = app_state.get("agent")
        if agent:
            from openai import OpenAI
            new_client = OpenAI(base_url=body.base_url, api_key=body.api_key)
            if body.role == "api":
                agent.client = new_client
                agent.model = body.model
                if body.max_tokens:
                    agent.max_tokens = body.max_tokens
                if body.temperature:
                    agent.temperature = body.temperature
                if body.context_window:
                    agent.context_window = body.context_window
                logger.info(f"[ModelConfig] Hot-reloaded main model → {body.model}")
            elif body.role == "vision":
                agent.vision_client = new_client
                agent.vision_model = body.model
                logger.info(f"[ModelConfig] Hot-reloaded vision model → {body.model}")
            elif body.role == "image_analyzer":
                agent.image_analyzer_client = new_client
                agent.image_analyzer_model = body.model
                logger.info(f"[ModelConfig] Hot-reloaded image_analyzer model → {body.model}")
            elif body.role == "autogui":
                # autogui client is accessed via app_state
                app_state["autogui_client"] = new_client
                app_state["autogui_model"] = body.model
                logger.info(f"[ModelConfig] Hot-reloaded autogui model → {body.model}")
            # embedding: requires restart due to VectorStore init chain

        return {"status": "ok", "role": body.role, "model": body.model, "hot_reloaded": agent is not None}
    except Exception as e:
        logger.error(f"[ModelConfig] Save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/model/test")
async def test_model_endpoint(body: ModelEndpointWrite):
    """Test a model endpoint by sending a minimal probe request."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=body.base_url, api_key=body.api_key or "test")
        # Send a minimal single-token request to validate connectivity
        resp = client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "Hi, reply with a single word: OK"}],
            max_tokens=8,
            timeout=12,
        )
        reply = resp.choices[0].message.content if resp.choices else ""
        return {"status": "ok", "reply": reply, "model": body.model}
    except Exception as e:
        raw = str(e).lower()
        if "401" in raw or "unauthorized" in raw or "invalid_api_key" in raw or "authentication" in raw:
            friendly = "API Key 无效或已过期"
        elif "403" in raw or "permission" in raw or "forbidden" in raw:
            friendly = "API Key 权限不足，请确认已开通该模型的访问权限"
        elif "404" in raw or "not found" in raw:
            friendly = "模型不存在，请检查模型名称是否正确"
        elif "connect" in raw or "connection" in raw or "network" in raw or "timeout" in raw:
            friendly = "无法连接到服务商，请检查 base_url 和网络状态"
        else:
            friendly = str(e)[:120]
        return {"status": "error", "error": friendly}


# To run: uvicorn core.server:app --host 127.0.0.1 --port 8000


# ── Chat Endpoints Management ──────────────────────────────────────────────────

import uuid as _uuid


class ChatEndpointItem(BaseModel):
    id: Optional[str] = None               # UUID; auto-generated if missing
    name: str                              # display name e.g. "DashScope Qwen"
    provider: Optional[str] = "custom"    # slug from _BUILTIN_PROVIDERS
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = 8000
    temperature: Optional[float] = 0.7
    capabilities: Optional[list] = None   # e.g. ["text","tools","vision"]
    note: Optional[str] = ""


class ChatEndpointActiveSwitch(BaseModel):
    id: str   # endpoint id to activate


@app.get("/api/endpoints")
async def list_chat_endpoints():
    """Return all saved chat endpoints + active endpoint id."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        return {"endpoints": [], "active_id": None}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)
        endpoints = full.get("chat_endpoints", [])
        active_id = full.get("active_chat_endpoint_id", None)
        
        # Legacy compatibility: migration from single 'api' key
        if not endpoints and "api" in full:
            api_cfg = full["api"]
            default_ep = {
                "id": "default",
                "name": "主模型 (默认)",
                "provider": "custom",
                "base_url": api_cfg.get("base_url", ""),
                "api_key": api_cfg.get("api_key", ""),
                "model": api_cfg.get("model", ""),
                "max_tokens": api_cfg.get("max_tokens", 8000),
                "temperature": api_cfg.get("temperature", 0.7),
                "capability": ["text"]
            }
            endpoints = [default_ep]
            if not active_id:
                active_id = "default"
        # Mask API keys in output
        masked = []
        for ep in endpoints:
            ep2 = dict(ep)
            k = ep2.get("api_key", "")
            ep2["api_key"] = k  # return full key for editing
            ep2["api_key_masked"] = (k[:4] + "***" + k[-2:]) if len(k) > 6 else ("***" if k else "")
            masked.append(ep2)
        return {"endpoints": masked, "active_id": active_id}
    except Exception as e:
        return {"endpoints": [], "active_id": None, "error": str(e)}


@app.post("/api/endpoints")
async def save_chat_endpoints(body: list[ChatEndpointItem]):
    """Save the full chat endpoints list to config.json."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)

        # Auto-assign UUIDs
        result = []
        for ep in body:
            d = ep.model_dump()
            if not d.get("id"):
                d["id"] = str(_uuid.uuid4())[:8]
            result.append(d)

        full["chat_endpoints"] = result

        # If no active_id set yet, or active ID no longer exists, pick first
        active_id = full.get("active_chat_endpoint_id")
        ids = [e["id"] for e in result]
        if not active_id or active_id not in ids:
            full["active_chat_endpoint_id"] = ids[0] if ids else None

        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "count": len(result), "active_id": full.get("active_chat_endpoint_id")}
    except Exception as e:
        logger.error(f"[ChatEndpoints] Save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/endpoints/active")
async def switch_active_endpoint(body: ChatEndpointActiveSwitch):
    """Switch the active chat endpoint and hot-reload the running agent."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)

        endpoints = full.get("chat_endpoints", [])
        target = next((e for e in endpoints if e.get("id") == body.id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Endpoint id={body.id!r} not found")

        full["active_chat_endpoint_id"] = body.id
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)

        # Hot-reload agent main client
        agent = app_state.get("agent")
        if agent:
            from openai import OpenAI
            new_client = OpenAI(base_url=target["base_url"], api_key=target["api_key"])
            agent.client = new_client
            agent.model = target["model"]
            if target.get("max_tokens"):
                agent.max_tokens = target["max_tokens"]
            if target.get("temperature"):
                agent.temperature = target["temperature"]
            logger.info(f"[ChatEndpoints] Switched active endpoint → {target['name']} ({target['model']})")

        return {
            "status": "ok",
            "active_id": body.id,
            "name": target["name"],
            "model": target["model"],
            "hot_reloaded": agent is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ChatEndpoints] Switch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Role Extra Endpoints ──────────────────────────────────────────────────────
class RoleEndpointsWrite(BaseModel):
    role: str                # e.g. "vision", "embedding", "autogui", "image_analyzer"
    endpoints: list          # list of endpoint dicts


@app.get("/api/config/role-endpoints")
async def get_role_endpoints():
    """Return all extra role-specific endpoints from config.json."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        return {"role_extra_endpoints": {}}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)
        return {"role_extra_endpoints": full.get("role_extra_endpoints", {})}
    except Exception as e:
        return {"role_extra_endpoints": {}, "error": str(e)}


@app.post("/api/config/role-endpoints")
async def save_role_endpoints(body: RoleEndpointsWrite):
    """Save extra endpoint list for a specific functional role to config.json."""
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)

        if "role_extra_endpoints" not in full:
            full["role_extra_endpoints"] = {}

        # Strip internal _new flag before saving
        clean = []
        for ep in body.endpoints:
            d = dict(ep) if isinstance(ep, dict) else ep
            d.pop("_new", None)
            clean.append(d)

        full["role_extra_endpoints"][body.role] = clean

        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(full, f, ensure_ascii=False, indent=2)

        return {"status": "ok", "role": body.role, "count": len(clean)}
    except Exception as e:
        logger.error(f"[RoleEndpoints] Save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
