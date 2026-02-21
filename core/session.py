"""
Session Manager: Conversation history management with persistence.

Inspired by Nanobot's SessionManager.
- Sessions stored as JSONL under data/sessions/
- Supports /new command to start fresh
- Auto-saved after every message
"""

import json
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

    def get_history(self, max_messages: int = 30) -> List[Dict[str, str]]:
        """Return recent messages in LLM format (role + content only)."""
        result = []
        # Prepend rolling summary token if exists
        if self.summary:
            result.append({
                "role": "system",
                "content": f"[前情提要]\n{self.summary}"
            })
        result += [
            {"role": m["role"], "content": m["content"]}
            for m in self.messages[-max_messages:] if m["role"] != "visual_log"
        ]
        return result

    def estimate_tokens(self) -> int:
        """
        Rough token estimate: ~1 token per 3 characters (works for both CJK and Latin).
        Includes the rolling summary and visual_log messages in the estimate.
        """
        total_chars = sum(len(m.get("content", "")) for m in self.messages)  # includes visual_log
        total_chars += len(self.summary)
        return total_chars // 3

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
        self._current: Session = Session()

    @property
    def current(self) -> Session:
        return self._current

    def new_session(self) -> Session:
        """Save current session and start a new one."""
        self.save(self._current)
        self._current = Session()
        return self._current

    def save(self, session: Optional[Session] = None) -> None:
        """Save a session to disk as JSON."""
        s = session or self._current
        path = self.sessions_dir / f"{s.session_id}.json"
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
