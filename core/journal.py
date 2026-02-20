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
        """Append content to the journal of the given date (default: today)."""
        if date_str is None:
            date_str = time.strftime("%Y-%m-%d")
        
        path = self._get_file_path(date_str)
        timestamp = time.strftime("%H:%M:%S")
        
        entry = f"\n## [{timestamp}]\n{content}\n"
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

    def read_day(self, date_str: str) -> Optional[str]:
        """Read the full content of a specific day's journal."""
        path = self._get_file_path(date_str)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

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
