"""Chat, Sessions, and Diary API routes."""
import json
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core.state import app_state, _APP_BASE, logger, get_profile_store

router = APIRouter(tags=["chat"])


# ── Pydantic models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None      # per-request model override
    agent_id: Optional[str] = None   # per-request agent override


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_agent_overrides(request: ChatRequest):
    """Return (system_prompt_override, allowed_skills, skills_mode, orig_model_to_restore)."""
    agent = app_state.get("agent")
    orig_model = None
    system_prompt_override = None
    allowed_skills = None
    skills_mode = "inclusive"

    if request.model:
        orig_model = agent.model
        agent.model = request.model

    if request.agent_id:
        store = get_profile_store()
        profile = store.get(request.agent_id)
        if profile:
            if profile.preferred_model and not request.model:
                orig_model = agent.model
                agent.model = profile.preferred_model
            if profile.custom_prompt:
                system_prompt_override = profile.custom_prompt
            allowed_skills = profile.skills
            skills_mode = profile.skills_mode.value

    return system_prompt_override, allowed_skills, skills_mode, orig_model


# ── Chat endpoints ────────────────────────────────────────────────────────────

@router.post("/api/chat/sync")
async def chat_sync(request: ChatRequest):
    """Synchronous chat endpoint. Blocks until the agent finishes."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    system_prompt_override, allowed_skills, skills_mode, orig_model = _resolve_agent_overrides(request)
    try:
        response = agent.chat(
            request.message,
            system_prompt_override=system_prompt_override,
            allowed_skills=allowed_skills,
            skills_mode=skills_mode,
        )
        return {"response": response}
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
    finally:
        if orig_model is not None:
            agent.model = orig_model


@router.post("/api/chat/upload")
async def chat_upload(files: list[UploadFile] = File(...), prompt: str = Form(default="")):
    """Accept multiple image or text files and stream the agent response via SSE."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    user_content_list = []
    
    for file in files:
        if not file.filename:
            continue
            
        content_type = (file.content_type or "").lower()
        raw = await file.read()

        if content_type.startswith("image/"):
            import base64
            b64 = base64.b64encode(raw).decode("utf-8")
            data_url = f"data:{content_type};base64,{b64}"
            user_content_list.append({"type": "image_url", "image_url": {"url": data_url}})
        elif content_type.startswith("text/") or file.filename.lower().endswith(
            (".txt", ".md", ".csv", ".log", ".py", ".js", ".html", ".css", ".json")
        ):
            try:
                text_body = raw.decode("utf-8", errors="replace")
            except Exception:
                text_body = raw.decode("latin-1", errors="replace")
            
            # 限制单个文件长度防止过载
            text_body_trunc = text_body[:8000]
            if len(text_body) > 8000:
                text_body_trunc += f"\n... (截断，剩余 {len(text_body)-8000} 字符)"
                
            user_content_list.append(
                {"type": "text", "text": f"【文件内容：{file.filename}】\n```\n{text_body_trunc}\n```\n\n"}
            )
        else:
            # 对于不支持的文件，我们可以记录一条提示或者抛出异常。
            # 这里选择将其内容尝试解析，或者直接给出文件名提示
            user_content_list.append(
                {"type": "text", "text": f"【附件：{file.filename} (内容不支持直接查阅，类型: {content_type})】\n\n"}
            )
            
    # Combine texts and images
    final_content = []
    text_parts = []
    
    for item in user_content_list:
        if item["type"] == "text":
            text_parts.append(item["text"])
        else:
            final_content.append(item)
            
    # Append the user prompt
    if prompt.strip():
        text_parts.append(prompt)
    elif not text_parts and final_content:
        text_parts.append("请分析以上内容。")
        
    if text_parts:
        final_content.append({"type": "text", "text": "".join(text_parts)})
        
    # 如果只有纯文本部分，降级为字符串格式，不使用 multimodal list 以适配更多模型
    if len(final_content) == 1 and final_content[0]["type"] == "text":
        user_content = final_content[0]["text"]
    else:
        user_content = final_content

    async def event_generator():
        try:
            async for chunk in agent.chat_stream(user_content):
                yield dict(data=chunk)
            yield dict(data="[DONE]")
        except Exception as e:
            logger.error(f"Upload stream error: {e}")
            yield dict(data=json.dumps({"type": "error", "content": str(e)}))

    return EventSourceResponse(event_generator())


@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint via Server-Sent Events."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    system_prompt_override, allowed_skills, skills_mode, orig_model = _resolve_agent_overrides(request)

    async def event_generator():
        try:
            async for chunk in agent.chat_stream(
                request.message,
                system_prompt_override=system_prompt_override,
                allowed_skills=allowed_skills,
                skills_mode=skills_mode,
            ):
                yield dict(data=chunk)
            yield dict(data="[DONE]")
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield dict(data=json.dumps({"type": "error", "content": str(e)}))
        finally:
            if orig_model is not None:
                agent.model = orig_model

    return EventSourceResponse(event_generator())


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/api/sessions")
async def list_sessions():
    """Return a summary list of all past sessions (most recent first, max 30)."""
    sessions_dir = str(_APP_BASE / "data" / "sessions")
    if not os.path.exists(sessions_dir):
        return []
    result = []
    IM_PREFIXES = ("dingtalk_", "feishu_", "telegram_")
    for fname in sorted(os.listdir(sessions_dir), reverse=True):
        if not fname.endswith(".json") or fname.startswith(IM_PREFIXES):
            continue
        fpath = os.path.join(sessions_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = data.get("messages", [])
            title = next(
                (
                    (
                        m["content"]
                        if isinstance(m["content"], str)
                        else " ".join(
                            p.get("text", "")
                            for p in m["content"]
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    )[:40]
                    for m in messages
                    if m.get("role") == "user" and m.get("content")
                ),
                "(空对话)",
            )
            result.append({
                "id": fname.replace(".json", ""),
                "title": title,
                "message_count": len([m for m in messages if m.get("role") in ("user", "assistant")]),
                "created_at": data.get("created_at", ""),
            })
        except Exception:
            continue
    return result[:30]


@router.post("/api/sessions/new")
async def new_session():
    """Start a fresh session."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    agent.sessions.new_session()
    agent.sessions.save()
    session_id = getattr(agent.sessions.current, "session_id", "unknown")
    return {"status": "ok", "session_id": session_id}


@router.get("/api/sessions/current/info")
async def get_current_session():
    """Return the current active session ID."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not ready")
    session_id = getattr(agent.sessions.current, "session_id", None)
    if not session_id:
        raise HTTPException(status_code=404, detail="No active session")
    return {"session_id": session_id}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Return the chat messages of a specific session."""
    agent = app_state.get("agent")
    if not agent:
        raise HTTPException(status_code=500, detail="Backend agent is not initialized.")
        
    # 同步切换后端的当前会话指针
    data = agent.sessions.load(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    data = data.to_dict() if hasattr(data, "to_dict") else data
    EXCLUDED_ROLES = {"system"}
    messages = [m for m in data.get("messages", []) if m.get("role") not in EXCLUDED_ROLES]

    # Estimate token count using the same logic as Session.estimate_tokens()
    import re
    _cjk_re = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]')
    def _count(text: str) -> int:
        cjk = len(_cjk_re.findall(text))
        return cjk + (len(text) - cjk) // 4

    estimated_tokens = _count(data.get("summary", ""))
    for m in data.get("messages", []):
        if m.get("role") == "debug_log":
            continue
        content = m.get("content", "")
        if isinstance(content, str):
            estimated_tokens += _count(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        estimated_tokens += _count(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        estimated_tokens += 1000
        if m.get("tool_calls"):
            try:
                estimated_tokens += _count(json.dumps(m["tool_calls"], ensure_ascii=False))
            except Exception:
                pass

    return {"session_id": session_id, "messages": messages, "estimated_tokens": estimated_tokens}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a specific session file."""
    fpath = str(_APP_BASE / "data" / "sessions" / f"{session_id}.json")
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        os.remove(fpath)
        return {"status": "ok", "message": f"Session {session_id} deleted."}
    except Exception as e:
        logger.error(f"Failed to delete session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Diary ─────────────────────────────────────────────────────────────────────

@router.get("/api/diary")
async def list_diary():
    """Return a list of available diary dates."""
    diary_dir = str(_APP_BASE / "data" / "diary")
    if not os.path.exists(diary_dir):
        return []
    return sorted(
        [f.replace(".md", "") for f in os.listdir(diary_dir) if f.endswith(".md")],
        reverse=True,
    )


@router.get("/api/diary/{date}")
async def get_diary(date: str):
    """Return the content of a diary entry."""
    fpath = str(_APP_BASE / "data" / "diary" / f"{date}.md")
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Diary not found")
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    return {"date": date, "content": content}
