"""IM channel and session management API."""
import os
import json
from pathlib import Path
from typing import List, Dict, Any
from fastapi import APIRouter
from core.state import app_state, _APP_BASE

router = APIRouter(tags=["im"])

# IM 通道识别前缀（与 gateway.py 中的 session_id 格式 {channel}_{chat_id} 保持一致）
_IM_CHANNEL_PREFIXES = ["dingtalk_", "feishu_", "telegram_"]


@router.get("/api/im/channels")
async def list_im_channels():
    """返回所有支持的 IM 通道及其运行状态。"""
    gateway = app_state.get("gateway")
    adapters = gateway.adapters if gateway else {}
    
    channels = []
    supported_channels = {
        "dingtalk": "钉钉",
        "feishu": "飞书",
        "telegram": "Telegram",
    }
    
    for cn_id, cn_name in supported_channels.items():
        adapter = adapters.get(cn_id)
        is_online = bool(adapter and getattr(adapter, "_running", False))
        channels.append({
            "id": cn_id,
            "name": cn_name,
            "status": "online" if is_online else "offline",
        })
        
    return {"channels": channels}


@router.get("/api/im/sessions")
async def list_im_sessions():
    """返回所有属于 IM 通道的会话列表，按最后修改时间降序排列。"""
    sessions_dir = _APP_BASE / "data" / "sessions"
    if not sessions_dir.exists():
        return {"sessions": []}
        
    im_sessions = []
    for fname in os.listdir(sessions_dir):
        if not fname.endswith(".json"):
            continue
            
        sid = fname[:-5]
        # 判断是否属于任一 IM 渠道
        channel = next((p[:-1] for p in _IM_CHANNEL_PREFIXES if sid.startswith(p)), None)
        if not channel:
            continue
            
        fpath = sessions_dir / fname
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            messages = data.get("messages", [])
            last_msg = ""
            for m in reversed(messages):
                if m.get("role") in ("user", "assistant"):
                    content = m.get("content", "")
                    if isinstance(content, list):
                        last_msg = next((i.get("text", "") for i in content if i.get("type") == "text"), "")
                    else:
                        last_msg = str(content)
                    break
            
            im_sessions.append({
                "id": sid,
                "channel": channel,
                "chat_id": sid[len(channel) + 1:],  # 去掉前缀 "dingtalk_"
                "last_message": last_msg[:120],
                "message_count": len([m for m in messages if m.get("role") in ("user", "assistant")]),
                "updated_at": data.get("updated_at", "") or data.get("created_at", ""),
                "_mtime": fpath.stat().st_mtime,
            })
        except Exception:
            continue
    
    # 按文件修改时间降序排序（最近活跃的在前）
    im_sessions.sort(key=lambda s: s.get("_mtime", 0), reverse=True)
    # 去掉内部排序字段
    for s in im_sessions:
        s.pop("_mtime", None)
            
    return {"sessions": im_sessions}

