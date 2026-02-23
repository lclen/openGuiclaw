import asyncio
import json
import logging
import os
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
app.mount("/static", StaticFiles(directory="static"), name="static")
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
                         "persona", "memory", "skills", "plugins", "journal", "knowledge_graph"}
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
        "active_persona": getattr(agent, "active_persona_name", "unknown"),
        "last_context_status": getattr(ctx, "_last_status", "unknown") if ctx else "unknown",
        "last_context_summary": getattr(ctx, "_last_summary", "") if ctx else ""
    }

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
                (m["content"][:40] for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)),
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
    # 返回空列表，让前端使用默认值
    return []

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

# To run: uvicorn core.server:app --host 127.0.0.1 --port 8000
