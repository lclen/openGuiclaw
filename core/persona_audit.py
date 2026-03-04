"""
Persona Audit: Snapshot and rollback system for identity files.

Snapshots are saved to data/identity/snapshots/.
Auto-migrates from legacy data/persona_snapshots/ on first use.
"""

import shutil
import time
from pathlib import Path
from typing import List, Optional


class PersonaSnapshot:
    """Metadata for a single persona snapshot."""
    def __init__(self, path: Path):
        self.path = path
        self.filename = path.name
        self.timestamp = path.stem.replace("_", " ").replace("-", ":", 2)
        self.lines = len(path.read_text(encoding="utf-8").splitlines())

    def __repr__(self):
        return f"<Snapshot {self.filename} ({self.lines} lines)>"


class PersonaAudit:
    """
    Manages identity file snapshots for audit and rollback.

    Usage:
        audit = PersonaAudit(persona_path="data/identity/HABITS.md", data_dir="data")
        audit.snapshot()          # Save current state before modification
        snaps = audit.list()      # List all snapshots
        audit.diff(0)             # Diff latest vs snapshot #0
        audit.rollback(0)         # Restore snapshot #0
    """

    def __init__(self, persona_path: str = "PERSONA.md", data_dir: str = "data"):
        self.persona_path = Path(persona_path)
        self.snapshot_dir = Path(data_dir) / "identity" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Auto-migrate from legacy persona_snapshots/ if new dir is empty
        legacy_dir = Path(data_dir) / "persona_snapshots"
        if legacy_dir.exists() and not any(self.snapshot_dir.glob("*.md")):
            for f in legacy_dir.glob("*.md"):
                shutil.copy2(f, self.snapshot_dir / f.name)
            print(f"[PersonaAudit] 已迁移快照: {legacy_dir} → {self.snapshot_dir}")

    # ── Public API ──────────────────────────────────────────────────

    def snapshot(self, reason: str = "", target_file: str = "HABITS.md") -> Optional[Path]:
        """
        Save a snapshot of the current persona/identity file.
        Returns the path of the snapshot file, or None if source not found.
        """
        if not self.persona_path.exists():
            return None

        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        dest = self.snapshot_dir / f"{ts}.md"

        content = self.persona_path.read_text(encoding="utf-8")
        header = f"<!-- Snapshot: {ts} | Target: {target_file} | Reason: {reason} -->\n"
        dest.write_text(header + content, encoding="utf-8")
        return dest

    def list(self) -> List[PersonaSnapshot]:
        """Return all snapshots sorted from oldest to newest."""
        paths = sorted(self.snapshot_dir.glob("*.md"))
        return [PersonaSnapshot(p) for p in paths]

    def diff(self, idx: int) -> str:
        """
        Show line-level diff between the current file and snapshot[idx].
        Returns a formatted string showing added (+) and removed (-) lines.
        """
        snaps = self.list()
        if not snaps:
            return "（没有快照）"
        if idx < 0 or idx >= len(snaps):
            return f"（索引超出范围，共 {len(snaps)} 个快照）"

        snap = snaps[idx]
        old_lines = set(_strip_header(snap.path.read_text(encoding="utf-8")).splitlines())
        new_lines = set(self.persona_path.read_text(encoding="utf-8").splitlines()) \
            if self.persona_path.exists() else set()

        added   = new_lines - old_lines
        removed = old_lines - new_lines

        lines = [f"📸 对比快照 #{idx}: {snap.filename}"]
        if not added and not removed:
            lines.append("  （两者完全一致，无差异）")
        for line in sorted(removed):
            if line.strip():
                lines.append(f"  - {line}")
        for line in sorted(added):
            if line.strip():
                lines.append(f"  + {line}")
        return "\n".join(lines)

    def rollback(self, idx: int) -> bool:
        """
        Restore the persona file to snapshot[idx].
        Returns True on success.
        """
        snaps = self.list()
        if idx < 0 or idx >= len(snaps):
            print(f"[PersonaAudit] 索引超出范围（共 {len(snaps)} 个快照）")
            return False

        snap = snaps[idx]
        content = _strip_header(snap.path.read_text(encoding="utf-8"))

        self.snapshot(reason=f"before rollback to {snap.filename}")
        self.persona_path.write_text(content, encoding="utf-8")
        print(f"[PersonaAudit] ✅ 已回滚到快照 #{idx}: {snap.filename}")
        return True


# ── Helpers ────────────────────────────────────────────────────────

def _strip_header(text: str) -> str:
    """Remove the <!-- Snapshot: ... --> header line from snapshot files."""
    if text.startswith("<!--"):
        _, _, rest = text.partition("\n")
        return rest
    return text
