"""
Session Manager: Conversation history management with persistence.

Inspired by Nanobot's SessionManager.
- Sessions stored as JSONL under data/sessions/
- Supports /new command to start fresh
- Auto-saved after every message
"""

import json
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional


class Session:
    """A single conversation session."""

    def __init__(self, session_id: str = None):
        self.session_id = session_id or f"session_{int(time.time())}"
        self.messages: List[Dict[str, Any]] = []
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.updated_at = self.created_at
        # Rolling summary: injected as a context prefix when old messages are pruned
        self.summary: str = ""

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = msg["timestamp"]

    def get_history(self, max_messages: int = 200) -> List[Dict[str, Any]]:
        """Return recent messages in LLM format (role + content + tool spec)."""
        result = []
        # Prepend rolling summary as a user/assistant exchange so it's compatible
        # with APIs that only allow a single system message at index 0.
        if self.summary:
            result.append({"role": "user",     "content": "[前情提要请求] 请确认你已了解之前的对话摘要。"})
            result.append({"role": "assistant", "content": f"[前情提要]\n{self.summary}\n\n已了解，我会基于以上摘要继续对话。"})

        raw_subset = self.messages[-max_messages:]

        # ── Pass 1: build clean message list, skipping internal log roles ──────
        cleaned: List[Dict] = []
        for m in raw_subset:
            if m["role"] in ("visual_log", "debug_log"):
                continue
            msg: Dict = {"role": m["role"], "content": m.get("content", "")}
            if "tool_calls" in m and m["tool_calls"]:
                tcs = m["tool_calls"]
                if isinstance(tcs, str):
                    try:
                        tcs = json.loads(tcs)
                    except Exception:
                        tcs = []
                msg["tool_calls"] = tcs
            if "tool_call_id" in m:
                msg["tool_call_id"] = m["tool_call_id"]
            if "name" in m:
                msg["name"] = m["name"]
            cleaned.append(msg)

        # ── Pass 2: validate tool call pairing ────────────────────────────────
        # Collect all tool_call_ids that are actually declared by an assistant turn.
        declared_ids: set = set()
        for msg in cleaned:
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id") if isinstance(tc, dict) else None
                    if tc_id:
                        declared_ids.add(tc_id)

        # Remove tool result messages whose preceding tool_call was not declared
        # (happens when prune_oldest cuts the assistant turn but keeps the result).
        validated: List[Dict] = []
        for msg in cleaned:
            if msg["role"] == "tool":
                if msg.get("tool_call_id") not in declared_ids:
                    continue  # orphaned tool result — drop it
            validated.append(msg)

        # ── Pass 3: trim leading/trailing edge cases ──────────────────────────
        # Drop leading tool messages (still possible after filtering)
        while validated and validated[0]["role"] == "tool":
            validated.pop(0)

        # Drop trailing assistant messages that have tool_calls but no results follow
        while validated and validated[-1]["role"] == "assistant" and validated[-1].get("tool_calls"):
            validated.pop()

        result.extend(validated)
        return result

    def estimate_tokens(self) -> int:
        """
        Estimate token count for the current session.
        - ASCII/Latin: ~4 chars per token
        - CJK characters: ~1 char per token
        - Images: ~1000 tokens each (conservative estimate)
        """
        import re
        _cjk_re = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]')

        def _count(text: str) -> int:
            cjk = len(_cjk_re.findall(text))
            other = len(text) - cjk
            return cjk + (other // 4)

        total = _count(self.summary)
        total_image_tokens = 0

        for m in self.messages:
            if m.get("role") == "debug_log":
                continue

            content = m.get("content", "")
            if isinstance(content, str):
                total += _count(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            total += _count(item.get("text", ""))
                        elif item.get("type") == "image_url":
                            total_image_tokens += 1000

            if "tool_calls" in m and m["tool_calls"]:
                try:
                    total += _count(json.dumps(m["tool_calls"], ensure_ascii=False))
                except Exception:
                    pass

        return total + total_image_tokens

    def prune_oldest(self, keep_last: int) -> List[Dict[str, Any]]:
        """
        Remove oldest messages, retain only the most recent `keep_last` messages.
        Returns the removed messages (for summarization).
        """
        if len(self.messages) <= keep_last:
            return []
        pruned = self.messages[:-keep_last]
        self.messages = self.messages[-keep_last:]
        return pruned

    def clear(self) -> None:
        """Reset the session."""
        self.messages = []
        self.summary = ""
        self.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    def update_last_visual_log(self, time_str: str) -> None:
        """Append a duration note to the last visual_log entry."""
        for msg in reversed(self.messages):
            if msg["role"] == "visual_log":
                # Remove any existing duration note before re-appending
                content = msg["content"]
                if "（持续至" in content:
                    content = content[:content.rfind("（持续至")].rstrip()
                msg["content"] = content + f"（持续至 {time_str}）"
                self.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
                return

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        s = cls(data["session_id"])
        s.created_at = data.get("created_at", s.created_at)
        s.updated_at = data.get("updated_at", s.updated_at)
        s.summary = data.get("summary", "")
        s.messages = data.get("messages", [])
        return s


class SessionManager:
    """
    Manages conversation sessions.
    - Current session kept in memory.
    - Sessions persisted as JSON under data/sessions/
    """

    def __init__(self, data_dir: str = "data"):
        self.sessions_dir = Path(data_dir) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        # Auto-resume: Find the most recently modified session file
        latest_session_id = None
        latest_mtime = 0
        
        for path in self.sessions_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_session_id = path.stem
            except Exception:
                continue
                
        if latest_session_id:
            # Attempt to load the last session
            self._current = Session() # Placeholder
            if not self.load(latest_session_id):
                self._current = Session()
        else:
            self._current = Session()

    @property
    def current(self) -> Session:
        return self._current

    def new_session(self) -> Session:
        """Save current session and start a new one."""
        self.save(self._current)
        self._current = Session()
        return self._current

    def save(self, session: Optional[Session] = None) -> None:
        """Save a session to disk as JSON. Thread-safe."""
        s = session or self._current
        path = self.sessions_dir / f"{s.session_id}.json"
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(s.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, session_id: str) -> Optional[Session]:
        """Load a specific session by ID."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = Session.from_dict(data)
            self._current = session
            return session
        except Exception as e:
            print(f"[Session] Failed to load {session_id}: {e}")
            return None

    def list_sessions(self) -> List[Dict[str, str]]:
        """List all saved sessions."""
        sessions = []
        for path in sorted(self.sessions_dir.glob("*.json"), reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data["session_id"],
                    "created_at": data.get("created_at", "?"),
                    "updated_at": data.get("updated_at", "?"),
                    "message_count": len(data.get("messages", [])),
                })
            except Exception:
                continue
        return sessions
