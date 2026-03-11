"""
Identity Manager

Manages the data/identity/ directory with three Markdown files:
- USER.md    : Objective user profile (name, age, device, etc.)
- HABITS.md  : Interaction habits and constraint rules
- MEMORY.md  : Progress memory summary (≤800 chars)
"""

import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Optional

MEMORY_LIMIT = 800


class IdentityManager:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.identity_dir = self.data_dir / "identity"
        self.identity_dir.mkdir(parents=True, exist_ok=True) # Hardcoded filenames based on your design
        self.user_path = self.identity_dir / "USER.md"
        self.habits_path = self.identity_dir / "HABITS.md"
        self.agent_path = self.identity_dir / "AGENT.md"

        self._ensure_files()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today(self) -> str:
        return date.today().isoformat()

    def _read(self, path: Path) -> str:
        """Read a file with LF normalization."""
        return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

    def _write(self, path: Path, text: str) -> None:
        """Write a file always using LF line endings."""
        path.write_text(text, encoding="utf-8", newline="\n")

    def _ensure_files(self) -> None:
        """Create default files if they don't exist."""
        if not self.user_path.exists():
            self._write(
                self.user_path,
                f"# 用户档案 (USER)\n<!-- updated: {self._today()} -->\n\n",
            )
        if not self.habits_path.exists():
            self._write(
                self.habits_path,
                f"# 交互习惯与约束规则 (HABITS)\n<!-- updated: {self._today()} -->\n\n",
            )

    def _update_timestamp(self, path: Path) -> None:
        """Replace or insert the timestamp in a file.
        
        Supports two formats:
        1. <!-- updated: YYYY-MM-DD --> (for HABITS.md, AGENT.md)
        2. *最后更新: YYYY-MM-DD HH:MM* (for USER.md)
        """
        text = self._read(path)
        today = self._today()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Try USER.md format first
        user_pattern = r"\*最后更新: [^\*]+\*"
        if re.search(user_pattern, text):
            text = re.sub(user_pattern, f"*最后更新: {now}*", text)
        else:
            # Try comment format
            comment_pattern = r"<!-- updated: \d{4}-\d{2}-\d{2}[^>]* -->"
            ts = f"<!-- updated: {today} -->"
            if re.search(comment_pattern, text):
                text = re.sub(comment_pattern, ts, text, count=1)
            else:
                # Insert after first line (usually the title)
                lines = text.splitlines(keepends=True)
                if lines:
                    lines.insert(1, ts + "\n")
                    text = "".join(lines)
                else:
                    text = ts + "\n" + text
        
        self._write(path, text)

    # ------------------------------------------------------------------
    # USER.md
    # ------------------------------------------------------------------

    def update_user(self, key: str, value: str) -> None:
        """Update or insert a key-value pair in USER.md.
        
        Supports both simple list format and structured sections.
        If key exists, replaces it. If not, appends to Basic Information section.
        """
        text = self._read(self.user_path)
        pattern = rf"^- \*\*{re.escape(key)}\*\*: .*$"
        new_line = f"- **{key}**: {value}"
        
        if re.search(pattern, text, flags=re.MULTILINE):
            # Key exists, replace it
            text = re.sub(pattern, new_line, text, flags=re.MULTILINE)
        else:
            # Key doesn't exist, insert in Basic Information section
            lines = text.split('\n')
            in_basic = False
            last_item_idx = -1
            
            for i, line in enumerate(lines):
                if '## Basic Information' in line:
                    in_basic = True
                elif line.startswith('##') and in_basic:
                    # Found next section, stop
                    break
                elif in_basic and line.startswith('- **'):
                    last_item_idx = i
            
            if last_item_idx >= 0:
                # Insert after the last item in Basic Information
                lines.insert(last_item_idx + 1, new_line)
                text = '\n'.join(lines)
            else:
                # Fallback: append to end
                text = text.rstrip("\n") + f"\n{new_line}\n"
        
        self._write(self.user_path, text)
        self._update_timestamp(self.user_path)

    def get_user(self) -> dict:
        """Parse USER.md and return a dict of key-value pairs."""
        text = self._read(self.user_path)
        result = {}
        for m in re.finditer(r"^- \*\*(.+?)\*\*: (.*)$", text, flags=re.MULTILINE):
            result[m.group(1)] = m.group(2)
        return result

    # ------------------------------------------------------------------
    # HABITS.md
    # ------------------------------------------------------------------

    def append_habit(self, content: str) -> None:
        """Append new content to HABITS.md."""
        text = self._read(self.habits_path)
        text = text.rstrip("\n") + f"\n\n{content}\n"
        self._write(self.habits_path, text)
        self._update_timestamp(self.habits_path)

    def modify_habit(self, target: str, replacement: str) -> bool:
        """Replace the first occurrence of target text in HABITS.md."""
        text = self._read(self.habits_path)
        if target not in text:
            return False
        text = text.replace(target, replacement, 1)
        self._write(self.habits_path, text)
        self._update_timestamp(self.habits_path)
        return True

    def get_habits(self) -> str:
        """Return the full content of HABITS.md."""
        return self._read(self.habits_path)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_prompt(self) -> str:
        """Build the text block to inject into the system prompt."""
        parts = []

        agent_text = self._read(self.agent_path).strip()
        if agent_text:
            parts.append(agent_text)

        user_text = self._read(self.user_path).strip()
        if user_text:
            parts.append(user_text)

        habits_text = self._read(self.habits_path).strip()
        if habits_text:
            parts.append(habits_text)

        scene_memory_path = self.data_dir / "memory" / "scene_memory.jsonl"
        if scene_memory_path.exists():
            try:
                import json
                from collections import defaultdict
                memories_by_type = defaultdict(list)
                with open(scene_memory_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            item = json.loads(line)
                            mtype = item.get("type", "fact")
                            memories_by_type[mtype].append(item.get("content", ""))
                        except json.JSONDecodeError:
                            continue
                
                if memories_by_type:
                    type_zh = {
                        "preference": "偏好",
                        "rule": "规则",
                        "fact": "事实",
                        "experience": "经验",
                        "skill": "技能",
                        "error": "教训"
                    }
                    memory_sections = ["# 核心记忆"]
                    # Optionally force an order if preferred, but iterating over dict directly is fine
                    for mtype, contents in memories_by_type.items():
                        if not contents: continue
                        zh_name = type_zh.get(mtype, mtype)
                        memory_sections.append(f"\\n## {zh_name}")
                        for content in contents:
                            memory_sections.append(f"- {content}")
                    parts.append("\\n".join(memory_sections))
            except Exception as e:
                print(f"[IdentityManager] Failed to read scene_memory.jsonl: {e}")

        return "\\n\\n".join(parts)

    # ------------------------------------------------------------------
    # Migration from legacy files
    # ------------------------------------------------------------------

    def migrate_from_legacy(
        self,
        profile_path: str,
        habits_path: str,
        identities_default_path: Optional[str] = None,
    ) -> None:
        """
        One-time migration from old data files to identity/ Markdown files.

        - profile_path: path to user_profile.json
        - habits_path: path to interaction_habits.md
        - identities_default_path: optional path to identities/default.md
        """
        profile_path = Path(profile_path)
        habits_path = Path(habits_path)

        # --- Migrate USER.md from objective_memory ---
        objective: dict = {}
        subjective: dict = {}
        if profile_path.exists():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                objective = data.get("objective_memory", {})
                subjective = data.get("subjective_memory", {})
            except Exception as e:
                print(f"[IdentityManager] 读取 {profile_path} 失败: {e}")

        for key, value in objective.items():
            self.update_user(key, str(value))

        # --- Migrate HABITS.md ---
        habits_sections = []

        # From interaction_habits.md
        if habits_path.exists():
            raw = habits_path.read_text(encoding="utf-8")
            # Normalize line endings so content round-trips correctly
            habits_content = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
            if habits_content:
                habits_sections.append(
                    f"## 来自 interaction_habits.md\n{habits_content}"
                )

        # From subjective_memory
        if subjective:
            sub_lines = "\n".join(
                f"- **{k}**: {v}" for k, v in subjective.items()
            )
            habits_sections.append(
                f"## 来自 user_profile.json subjective_memory\n{sub_lines}"
            )

        # From identities/default.md (optional)
        if identities_default_path:
            default_path = Path(identities_default_path)
            if default_path.exists():
                default_content = default_path.read_text(encoding="utf-8").strip()
                if default_content:
                    habits_sections.append(
                        f"## 来自 identities/default.md\n{default_content}"
                    )

        if habits_sections:
            self.append_habit("\n\n".join(habits_sections))

        # --- Rename originals to .bak ---
        if profile_path.exists():
            bak = profile_path.with_suffix(profile_path.suffix + ".bak")
            bak.unlink(missing_ok=True)  # Windows: remove existing .bak before rename
            profile_path.rename(bak)
            print(f"[IdentityManager] 已备份: {profile_path} → {bak}")

        if habits_path.exists():
            bak = habits_path.with_suffix(habits_path.suffix + ".bak")
            bak.unlink(missing_ok=True)  # Windows: remove existing .bak before rename
            habits_path.rename(bak)
            print(f"[IdentityManager] 已备份: {habits_path} → {bak}")

        print("[IdentityManager] 迁移完成。")
