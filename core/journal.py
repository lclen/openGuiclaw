"""
Journal Manager: Daily episodic memory.

Stores summarized events in data/journals/YYYY-MM-DD.md.
"""

from pathlib import Path
import time
from typing import Optional

class JournalManager:
    def __init__(self, data_dir: str = "data"):
        self.journal_dir = Path(data_dir) / "journals"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, date_str: str) -> Path:
        return self.journal_dir / f"{date_str}.md"

    def append(self, content: str, date_str: str = None) -> None:
        """Append content to the journal of the given date (default: today).
        Includes deduplication for visual logs."""
        if date_str is None:
            date_str = time.strftime("%Y-%m-%d")
        
        path = self._get_file_path(date_str)
        timestamp = time.strftime("%H:%M:%S")
        
        # --- Deduplication Logic for Visual Logs ---
        if "[视觉日志]" in content and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                last_content = ""
                for i in range(len(lines)-1, -1, -1):
                    if lines[i].startswith("## ["):
                        # Accumulate content lines after the timestamp
                        content_lines = []
                        for j in range(i+1, len(lines)):
                            if lines[j].strip():
                                content_lines.append(lines[j].strip())
                        last_content = " ".join(content_lines)
                        break
                
                # Simple similarity check: calculate character overlap overlap or exact match
                if last_content and content.strip() in last_content or last_content in content.strip():
                     # Content is functionally identical, just update the time and skip appending
                     self.update_last_time(date_str)
                     return
                     
                # For slightly varying descriptions (e.g. changing window names but same state),
                # we can use sequence matcher if exact substring matching is too strict.
                from difflib import SequenceMatcher
                if last_content:
                    similarity = SequenceMatcher(None, content.strip(), last_content).ratio()
                    if similarity > 0.85: # If 85% similar, consider it a duplicate
                        self.update_last_time(date_str)
                        return
                        
            except Exception as e:
                print(f"[Journal] Deduplication check failed: {e}")
        # -------------------------------------------

        entry = f"\n## [{timestamp}]\n{content}\n"
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

    def read_day(self, date_str: str) -> Optional[str]:
        """Read the full content of a specific day's journal."""
        path = self._get_file_path(date_str)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_dates(self) -> list:
        """Return all journal dates sorted descending (newest first)."""
        return sorted((p.stem for p in self.journal_dir.glob("*.md")), reverse=True)

    def search(self, query: str, top_k: int = 3) -> list:
        """
        Keyword search across all journal files.
        Returns [{"date": ..., "snippet": ...}] sorted by date descending.
        Falls back to returning the most recent days if no keyword match is found.
        """
        q_lower = query.lower()
        keywords = [w for w in q_lower.split() if len(w) > 1]
        results = []

        for date_str in self.list_dates():
            content = self.read_day(date_str) or ""
            content_lower = content.lower()
            # Score by how many keywords appear
            score = sum(1 for k in keywords if k in content_lower)
            if score > 0:
                # Find the first keyword hit for context extraction
                first_hit_idx = min(
                    (content_lower.find(k) for k in keywords if k in content_lower),
                    default=0
                )
                start = max(0, first_hit_idx - 80)
                end = min(len(content), first_hit_idx + 400)
                snippet = ("..." if start > 0 else "") + content[start:end].strip() + "..."
                results.append({"date": date_str, "snippet": snippet, "score": score})
        results.sort(key=lambda x: (-x["score"], x["date"]))
        return results[:top_k]

    def recent_days(self, n: int = 3) -> list:
        """
        Return the content of the most recent N journal days.
        Returns [{"date": ..., "content": ...}].
        """
        out = []
        for date_str in self.list_dates()[:n]:
            content = self.read_day(date_str)
            if content:
                # Truncate to avoid huge context
                out.append({"date": date_str, "content": content[:2000]})
        return out

    def update_last_time(self, date_str: str = None) -> None:
        """
        Updates the timestamp of the last log entry to indicate a duration.
        e.g., `## [13:00:00]` becomes `## [13:00:00 ~ 13:05:00]`
        """
        import re
        if date_str is None:
            date_str = time.strftime("%Y-%m-%d")
        
        path = self._get_file_path(date_str)
        if not path.exists():
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            # Find the last `## [...]` line
            for i in range(len(lines)-1, -1, -1):
                line = lines[i]
                if line.startswith("## ["):
                    current_time = time.strftime("%H:%M:%S")
                    m = re.match(r"^## \[([^~\]]+)(?: ~ [^\]]+)?\]", line)
                    if m:
                        start_time = m.group(1).strip()
                        lines[i] = f"## [{start_time} ~ {current_time}]\n"
                        with open(path, "w", encoding="utf-8") as f:
                            f.writelines(lines)
                    break
        except Exception as e:
            print(f"[Journal] Failed to update last time: {e}")
