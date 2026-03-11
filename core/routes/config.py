"""Config, identity, endpoints, model config, and system control routes."""
import json
import os
import time
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from core.state import app_state, _APP_BASE, logger

router = APIRouter(tags=["config"])


# ── Built-in provider presets ─────────────────────────────────────────────────
_BUILTIN_PROVIDERS = [
    {"slug": "dashscope-coding", "name": "阿里云 DashScope (Coding)", "category": "coding",
     "api_type": "openai", "base_url": "https://coding.dashscope.aliyuncs.com/v1",
     "key_hint": "DASHSCOPE_API_KEY", "is_local": False,
     "desc": "阿里编程专版，适配 AutoGUI 与代码生成",
     "models": ["qwen3.5-plus", "qwen3-max"]},
    {"slug": "kimi-coding", "name": "Kimi (Coding)", "category": "coding",
     "api_type": "anthropic", "base_url": "https://api.kimi.com/coding/",
     "key_hint": "KIMI_API_KEY", "is_local": False,
     "desc": "Kimi 编程专版 (Anthropic 协议适配)",
     "models": ["kimi-k2.5", "kimi-k2"]},
    {"slug": "minimax-coding", "name": "MiniMax (Coding)", "category": "coding",
     "api_type": "anthropic", "base_url": "https://api.minimaxi.com/anthropic",
     "key_hint": "MINIMAX_API_KEY", "is_local": False,
     "desc": "MiniMax 编程专版 (Anthropic 协议适配)",
     "models": ["minimax-m2.5", "minimax-m2"]},
    {"slug": "zhipu-coding", "name": "智谱 ZhipuAI (Coding)", "category": "coding",
     "api_type": "anthropic", "base_url": "https://open.bigmodel.cn/api/anthropic",
     "key_hint": "ZHIPU_API_KEY", "is_local": False,
     "desc": "智谱编程专版 (Anthropic 协议适配)",
     "models": ["glm-4-plus", "glm-5"]},
    {"slug": "volcengine-coding", "name": "火山方舟 (Coding)", "category": "coding",
     "api_type": "anthropic", "base_url": "https://ark.cn-beijing.volces.com/api/coding",
     "key_hint": "ARK_API_KEY", "is_local": False,
     "desc": "火山引擎编程专版 (Anthropic 协议适配)",
     "models": ["doubao-1.5-pro-256k", "doubao-seed-1-6"]},
    {"slug": "dashscope", "name": "阿里云 DashScope", "category": "cn_official",
     "api_type": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "key_hint": "DASHSCOPE_API_KEY", "is_local": False,
     "desc": "通义千问官方端点，支持全系列模型",
     "models": ["qwen3.5-plus", "qwen3-max", "qwen-plus", "qwen-turbo", "qwen-vl-max", "text-embedding-v4"]},
    {"slug": "zhipu", "name": "智谱 ZhipuAI", "category": "cn_official",
     "api_type": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "key_hint": "ZHIPU_API_KEY", "is_local": False,
     "desc": "GLM 系列官方端点",
     "models": ["glm-4-plus", "glm-4v-plus", "glm-5", "glm-4-air", "glm-4-flash"]},
    {"slug": "moonshot", "name": "Kimi (月之暗面)", "category": "cn_official",
     "api_type": "openai", "base_url": "https://api.moonshot.cn/v1",
     "key_hint": "MOONSHOT_API_KEY", "is_local": False,
     "desc": "Kimi 官方标准端点",
     "models": ["kimi-k2.5", "kimi-k2", "moonshot-v1-128k"]},
    {"slug": "minimax", "name": "MiniMax", "category": "cn_official",
     "api_type": "openai", "base_url": "https://api.minimax.chat/v1",
     "key_hint": "MINIMAX_API_KEY", "is_local": False,
     "desc": "MiniMax 官方标准端点",
     "models": ["minimax-m2.5", "minimax-m2", "abab6.5s-chat"]},
    {"slug": "openai", "name": "OpenAI", "category": "intl_official",
     "api_type": "openai", "base_url": "https://api.openai.com/v1",
     "key_hint": "OPENAI_API_KEY", "is_local": False,
     "desc": "GPT-4o / o1 官方端点",
     "models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]},
    {"slug": "anthropic", "name": "Anthropic", "category": "intl_official",
     "api_type": "anthropic", "base_url": "https://api.anthropic.com",
     "key_hint": "ANTHROPIC_API_KEY", "is_local": False,
     "desc": "Claude 3.5 系列官方端点",
     "models": ["claude-opus-4.5", "claude-sonnet-4.5", "claude-haiku-4.5", "claude-3-5-sonnet"]},
    {"slug": "google", "name": "Google Gemini", "category": "intl_official",
     "api_type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "key_hint": "GOOGLE_API_KEY", "is_local": False,
     "desc": "Gemini 系列官方端点",
     "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]},
    {"slug": "deepseek", "name": "DeepSeek", "category": "intl_official",
     "api_type": "openai", "base_url": "https://api.deepseek.com/v1",
     "key_hint": "DEEPSEEK_API_KEY", "is_local": False,
     "desc": "DeepSeek 官方低价端点",
     "models": ["deepseek-chat", "deepseek-reasoner"]},
    {"slug": "siliconflow", "name": "SiliconFlow", "category": "relay",
     "api_type": "openai", "base_url": "https://api.siliconflow.cn/v1",
     "key_hint": "SILICONFLOW_API_KEY", "is_local": False,
     "desc": "硅基流动，低价开源模型中转",
     "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen3-235B-A22B"]},
    {"slug": "openrouter", "name": "OpenRouter", "category": "relay",
     "api_type": "openai", "base_url": "https://openrouter.ai/api/v1",
     "key_hint": "OPENROUTER_API_KEY", "is_local": False,
     "desc": "国际顶级模型聚合平台",
     "models": ["openai/gpt-4o", "anthropic/claude-3-5-sonnet", "meta-llama/llama-3.3-70b-instruct"]},
    {"slug": "ollama", "name": "Ollama (本地)", "category": "local",
     "api_type": "openai", "base_url": "http://localhost:11434/v1",
     "key_hint": "", "is_local": True,
     "desc": "本地开源模型推理",
     "models": ["llama3.1:8b", "qwen2.5:7b", "deepseek-r1:8b"]},
]

_ENDPOINT_ROLES = [
    {"key": "api",            "label": "主模型",   "desc": "主要对话与工具调用",    "icon": "🧠"},
    {"key": "vision",         "label": "视觉模型", "desc": "屏幕截图分析与主动感知", "icon": "👁"},
    {"key": "image_analyzer", "label": "图像解析", "desc": "用户上传图片智能解读",   "icon": "🖼"},
    {"key": "embedding",      "label": "嵌入模型", "desc": "向量语义检索与记忆",    "icon": "🔢"},
    {"key": "autogui",        "label": "GUI 操作", "desc": "屏幕自动化与界面交互",  "icon": "🤖"},
]


# ── Pydantic models ───────────────────────────────────────────────────────────

class IdentityFileUpdate(BaseModel):
    filename: str
    content: str


class ModelEndpointWrite(BaseModel):
    role: str
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    context_window: Optional[int] = None


class ChatEndpointItem(BaseModel):
    id: Optional[str] = None
    name: str
    provider: Optional[str] = "custom"
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = 8000
    temperature: Optional[float] = 0.7
    capabilities: Optional[list] = None
    note: Optional[str] = ""


class ChatEndpointActiveSwitch(BaseModel):
    id: str


class RoleEndpointsWrite(BaseModel):
    role: str
    endpoints: list


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render_memory_md() -> str:
    """Render scene_memory.jsonl as a human-readable Markdown string."""
    memory_file = _APP_BASE / "data" / "memory" / "scene_memory.jsonl"
    if not memory_file.exists():
        return "# 长期记忆\n\n暂无记忆条目。\n"
    type_labels = {
        "fact": "📌 事实", "preference": "❤️ 偏好", "experience": "🔧 经验",
        "skill": "⚡ 技能", "goal": "🎯 目标", "relationship": "🤝 关系",
    }
    groups: dict = {}
    for line in memory_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            mem = json.loads(line)
        except Exception:
            continue
        groups.setdefault(mem.get("type", "other"), []).append(mem)
    lines = [
        "# 长期记忆 (Memory Readable View)", "",
        f"> 共 {sum(len(v) for v in groups.values())} 条记忆，只读视图，原始数据存储于 `scene_memory.jsonl`", "",
    ]
    for t, mems in sorted(groups.items()):
        label = type_labels.get(t, f"🗂 {t}")
        lines.append(f"## {label}（{len(mems)} 条）\n")
        for m in sorted(mems, key=lambda x: x.get("timestamp", 0), reverse=True):
            created = m.get("created_at", "")[:10]
            content = m.get("content", "").replace("\n", " ")
            tags = m.get("tags", [])
            tag_str = "  `" + "` `".join(tags) + "`" if tags else ""
            lines.append(f"- **[{created}]** {content}{tag_str}")
        lines.append("")
    return "\n".join(lines)


def _load_config_json():
    cfg_path = _APP_BASE / "config.json"
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f), cfg_path


def _save_config_json(data: dict, cfg_path):
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── General config ────────────────────────────────────────────────────────────

@router.get("/api/config")
async def get_config():
    full, _ = _load_config_json()
    return full


@router.post("/api/config")
async def update_config(request: Request):
    """Update config.json and hot-reload applicable agent subsystems."""
    try:
        new_config = await request.json()
        _ALLOWED_KEYS = {
            "proactive", "browser_choice", "model", "api_key", "base_url",
            "persona", "memory", "skills", "plugins", "journal", "knowledge_graph",
            "api", "vision", "image_analyzer", "embedding", "autogui", "screen", "agent",
            "channels", "chat_endpoints", "active_chat_endpoint_id", "vrm",
        }
        if not isinstance(new_config, dict):
            raise HTTPException(status_code=400, detail="Config must be a JSON object")
        unknown = set(new_config.keys()) - _ALLOWED_KEYS
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown config keys: {unknown}")
        if "proactive" in new_config:
            p = new_config["proactive"]
            if not isinstance(p, dict):
                raise HTTPException(status_code=400, detail="proactive must be an object")
            for field in ("interval_minutes", "cooldown_minutes"):
                if field in p and p[field] is not None and not isinstance(p[field], (int, float)):
                    raise HTTPException(status_code=400, detail=f"proactive.{field} must be a number or null")
        if "journal" in new_config:
            j = new_config["journal"]
            if not isinstance(j, dict):
                raise HTTPException(status_code=400, detail="journal must be an object")
            if "enable_diary" in j and not isinstance(j["enable_diary"], bool):
                raise HTTPException(status_code=400, detail="journal.enable_diary must be a boolean")

        with open(_APP_BASE / "config.json", "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=4, ensure_ascii=False)

        if "agent" in app_state:
            app_state["agent"].config = new_config
            if hasattr(app_state["agent"], "evolution") and app_state["agent"].evolution:
                app_state["agent"].evolution._diary_enabled = new_config.get("journal", {}).get("enable_diary", True)
        if "context_manager" in app_state:
            app_state["context_manager"].reload_config(new_config.get("proactive", {}))
        return {"status": "success", "message": "Config updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update config: {str(e)}")


# ── Identity files ────────────────────────────────────────────────────────────

@router.get("/api/identity/files")
async def get_identity_files():
    identity_dir = _APP_BASE / "data" / "identity"
    memory_file = _APP_BASE / "data" / "memory" / "scene_memory.jsonl"
    files = []
    if identity_dir.exists():
        for f in sorted(identity_dir.glob("*.md")):
            files.append({"name": f.name, "type": "md", "readonly": False})
    if memory_file.exists():
        files.append({"name": "memory_readable.md", "type": "md", "readonly": True})
    return {"files": files}


@router.get("/api/identity/file")
async def get_identity_file(filename: str):
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if filename == "memory_readable.md":
        return {"content": _render_memory_md(), "readonly": True}
    target_path = _APP_BASE / "data" / "identity" / filename
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": target_path.read_text(encoding="utf-8"), "readonly": False}


@router.post("/api/identity/file")
async def update_identity_file(req: IdentityFileUpdate):
    if ".." in req.filename or req.filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if req.filename == "memory_readable.md":
        raise HTTPException(status_code=403, detail="memory_readable.md is read-only")
    target_path = _APP_BASE / "data" / "identity" / req.filename
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(req.content, encoding="utf-8")
    return {"status": "ok"}


# ── Status / context / sandbox ────────────────────────────────────────────────

@router.post("/api/context/poke")
async def poke_context():
    if "context_manager" not in app_state:
        raise HTTPException(status_code=400, detail="ContextManager not initialized")
    app_state["context_manager"].poke()
    return {"status": "success", "message": "Poked"}


@router.post("/api/sandbox/clear")
async def clear_sandbox():
    try:
        from plugins.sandbox_repl import _sandboxes
        count = len(_sandboxes)
        for sb in list(_sandboxes.values()):
            sb.close()
        _sandboxes.clear()
        return {"status": "ok", "message": f"成功清理了 {count} 个存活的沙箱实例。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/status")
async def get_status():
    agent = app_state.get("agent")
    ctx = app_state.get("context_manager")
    if not agent:
        return {"status": "offline"}
    return {
        "status": "online",
        "vision_enabled": getattr(ctx, "_enabled", False) if ctx else False,
        "vision_mode": getattr(ctx, "mode", "unknown") if ctx else "unknown",
        "last_context_summary": getattr(ctx, "_last_summary", "") if ctx else "",
    }


# ── VRM preferences (also in vrm.py but config panel uses /api/config/preferences) ──

@router.get("/api/config/preferences")
async def get_preferences():
    prefs_file = str(_APP_BASE / "data" / "vrm_preferences.json")
    if os.path.exists(prefs_file):
        with open(prefs_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@router.post("/api/config/preferences")
async def save_preferences(request: Request):
    prefs_file = str(_APP_BASE / "data" / "vrm_preferences.json")
    try:
        data = await request.json()
        os.makedirs(str(_APP_BASE / "data"), exist_ok=True)
        with open(prefs_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Model endpoint config ─────────────────────────────────────────────────────

@router.get("/api/config/model/providers")
async def get_model_providers():
    return {"providers": _BUILTIN_PROVIDERS, "roles": _ENDPOINT_ROLES}


@router.get("/api/config/model")
async def get_model_config():
    cfg_path = _APP_BASE / "config.json"
    if not cfg_path.exists():
        return {"config": {}, "error": "config.json not found"}
    try:
        with open(cfg_path, encoding="utf-8") as f:
            full = json.load(f)
        result = {}
        for role_def in _ENDPOINT_ROLES:
            key = role_def["key"]
            section = full.get(key, {})
            if section:
                api_key = section.get("api_key", "")
                masked = (api_key[:4] + "***" + api_key[-2:]) if len(api_key) > 6 else ("***" if api_key else "")
                result[key] = {
                    "base_url": section.get("base_url", ""),
                    "api_key": api_key,
                    "api_key_masked": masked,
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


@router.post("/api/config/model")
async def set_model_config(body: ModelEndpointWrite):
    valid_roles = {r["key"] for r in _ENDPOINT_ROLES}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")
    full, cfg_path = _load_config_json()
    section = full.setdefault(body.role, {})
    section["base_url"] = body.base_url
    section["api_key"] = body.api_key
    section["model"] = body.model
    if body.max_tokens is not None:
        section["max_tokens"] = body.max_tokens
    if body.temperature is not None:
        section["temperature"] = body.temperature
    if body.context_window is not None:
        section["context_window"] = body.context_window
    _save_config_json(full, cfg_path)
    return {"status": "ok", "role": body.role, "model": body.model, "requires_restart": True}


@router.post("/api/config/model/test")
async def test_model_endpoint(body: ModelEndpointWrite):
    import asyncio
    def _do_test():
        from openai import OpenAI
        client = OpenAI(base_url=body.base_url, api_key=body.api_key or "test")
        resp = client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "Hi, reply with a single word: OK"}],
            max_tokens=8, timeout=15,
        )
        return resp.choices[0].message.content if resp.choices else ""
    try:
        reply = await asyncio.to_thread(_do_test)
        return {"status": "ok", "reply": reply, "model": body.model}
    except Exception as e:
        raw = str(e).lower()
        if "401" in raw or "unauthorized" in raw or "invalid_api_key" in raw or "authentication" in raw:
            friendly = "API Key 无效或已过期"
        elif "403" in raw or "permission" in raw or "forbidden" in raw:
            friendly = "API Key 权限不足"
        elif "404" in raw or "not found" in raw:
            friendly = "模型不存在，请检查模型名称"
        elif "connect" in raw or "timeout" in raw:
            friendly = "无法连接到服务商，请检查 base_url 和网络"
        else:
            friendly = str(e)[:120]
        return {"status": "error", "error": friendly}


# ── Chat endpoints management ─────────────────────────────────────────────────

@router.get("/api/endpoints")
async def list_chat_endpoints():
    try:
        full, _ = _load_config_json()
    except HTTPException:
        return {"endpoints": [], "active_id": None}
    endpoints = full.get("chat_endpoints", [])
    active_id = full.get("active_chat_endpoint_id")
    if not endpoints and "api" in full:
        api_cfg = full["api"]
        endpoints = [{"id": "default", "name": "主模型 (默认)", "provider": "custom",
                      "base_url": api_cfg.get("base_url", ""), "api_key": api_cfg.get("api_key", ""),
                      "model": api_cfg.get("model", ""), "max_tokens": api_cfg.get("max_tokens", 8000),
                      "temperature": api_cfg.get("temperature", 0.7), "capability": ["text"]}]
        active_id = active_id or "default"
    masked = []
    for ep in endpoints:
        ep2 = dict(ep)
        k = ep2.get("api_key", "")
        ep2["api_key_masked"] = (k[:4] + "***" + k[-2:]) if len(k) > 6 else ("***" if k else "")
        masked.append(ep2)
    return {"endpoints": masked, "active_id": active_id}


@router.post("/api/endpoints")
async def save_chat_endpoints(body: list[ChatEndpointItem]):
    full, cfg_path = _load_config_json()
    result = []
    for ep in body:
        d = ep.model_dump()
        if not d.get("id"):
            d["id"] = str(_uuid.uuid4())[:8]
        result.append(d)
    full["chat_endpoints"] = result
    ids = [e["id"] for e in result]
    active_id = full.get("active_chat_endpoint_id")
    if not active_id or active_id not in ids:
        full["active_chat_endpoint_id"] = ids[0] if ids else None
    _save_config_json(full, cfg_path)
    return {"status": "ok", "count": len(result), "active_id": full.get("active_chat_endpoint_id"), "requires_restart": True}


@router.post("/api/endpoints/active")
async def switch_active_endpoint(body: ChatEndpointActiveSwitch):
    full, cfg_path = _load_config_json()
    endpoints = full.get("chat_endpoints", [])
    target = next((e for e in endpoints if e.get("id") == body.id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Endpoint id={body.id!r} not found")
    full["active_chat_endpoint_id"] = body.id
    _save_config_json(full, cfg_path)
    return {"status": "ok", "active_id": body.id, "name": target["name"], "model": target["model"], "requires_restart": True}


# ── Role extra endpoints ──────────────────────────────────────────────────────

@router.get("/api/config/role-endpoints")
async def get_role_endpoints():
    try:
        full, _ = _load_config_json()
        return {"role_extra_endpoints": full.get("role_extra_endpoints", {})}
    except HTTPException:
        return {"role_extra_endpoints": {}}


@router.post("/api/config/role-endpoints")
async def save_role_endpoints(body: RoleEndpointsWrite):
    full, cfg_path = _load_config_json()
    full.setdefault("role_extra_endpoints", {})
    clean = [{k: v for k, v in (ep.items() if isinstance(ep, dict) else ep)} for ep in body.endpoints]
    for ep in clean:
        ep.pop("_new", None)
    full["role_extra_endpoints"][body.role] = clean
    _save_config_json(full, cfg_path)
    return {"status": "ok", "role": body.role, "count": len(clean), "requires_restart": True}


# ── IM Channels Health Check ──────────────────────────────────────────────────

class ChannelHealthCheckRequest(BaseModel):
    channel: str  # telegram, feishu, dingtalk, etc. If empty, check all.
    config: Optional[dict] = None # Optional override config for testing before saving

@router.post("/api/config/channels/health")
async def health_check_channels(req: ChannelHealthCheckRequest):
    import httpx
    import time
    
    # Get effective config
    full, _ = _load_config_json()
    channels_cfg = full.get("channels", {})
    if req.config:
        channels_cfg.update(req.config)
        
    targets = ["telegram", "feishu", "dingtalk"]
    if req.channel:
        if req.channel not in targets:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {req.channel}")
        targets = [req.channel]

    results = []
    
    for ch in targets:
        ch_cfg = channels_cfg.get(ch, {})
        
        # Check required keys based on openakita logic
        if ch == "telegram":
            required = ["bot_token"]
        elif ch == "feishu":
            required = ["app_id", "app_secret"]
        elif ch == "dingtalk":
            required = ["client_id", "client_secret"]
        else:
            required = []
            
        missing = [k for k in required if not ch_cfg.get(k, "").strip()]
        if missing:
            results.append({
                "channel": ch,
                "status": "unhealthy",
                "error": f"缺少必填配置: {', '.join(missing)}",
                "last_checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")
            })
            continue
            
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if ch == "telegram":
                    token = ch_cfg["bot_token"].strip()
                    proxy = ch_cfg.get("proxy", "").strip()
                    transport = None
                    # Basic proxing handling if provided
                    if proxy:
                        proxies = {"http://": proxy, "https://": proxy}
                        # httpx AsyncClient proxy configuration
                        # This is a simplified proxy setup just for the healthcheck
                        resp = await httpx.AsyncClient(proxies=proxies, timeout=15).get(f"https://api.telegram.org/bot{token}/getMe")
                    else:
                        resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                    
                    resp.raise_for_status()
                    data = resp.json()
                    if not data.get("ok"):
                        raise Exception(data.get("description", "Telegram API 返回错误"))
                        
                elif ch == "feishu":
                    app_id = ch_cfg["app_id"].strip()
                    app_secret = ch_cfg["app_secret"].strip()
                    resp = await client.post(
                        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                        json={"app_id": app_id, "app_secret": app_secret},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("code", -1) != 0:
                        raise Exception(data.get("msg", "飞书验证失败"))
                        
                elif ch == "dingtalk":
                    client_id = ch_cfg["client_id"].strip()
                    client_secret = ch_cfg["client_secret"].strip()
                    resp = await client.post(
                        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
                        json={"appKey": client_id, "appSecret": client_secret},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if not data.get("accessToken"):
                        raise Exception(data.get("message", "钉钉验证失败"))

            results.append({
                "channel": ch,
                "status": "healthy",
                "error": None,
                "last_checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")
            })
        except Exception as e:
            results.append({
                "channel": ch,
                "status": "unhealthy",
                "error": str(e)[:500],
                "last_checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")
            })

    return {"results": results}


# ── System control ────────────────────────────────────────────────────────────

@router.post("/api/system/restart")
async def restart_backend(background_tasks: BackgroundTasks):
    """Exit the process so the launcher watchdog can restart it."""
    def _do_restart():
        import time as _time
        _time.sleep(0.15)
        logger.info("[System] Exiting backend process for watchdog restart...")
        os._exit(0)
    background_tasks.add_task(_do_restart)
    return {"status": "ok", "message": "Backend is restarting"}
