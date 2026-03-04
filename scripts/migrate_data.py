"""
Data Migration Script

Migrates legacy data layout to the new structured layout:
  data/user_profile.json          → data/identity/USER.md + HABITS.md (via IdentityManager)
  data/interaction_habits.md      → data/identity/HABITS.md
  data/diary_vectors.jsonl        → data/diary/diary_vectors.jsonl
  data/journal_vectors.jsonl      → data/journals/journal_vectors.jsonl
  data/scene_memory.jsonl         → data/memory/scene_memory.jsonl
  data/scene_memory_vectors.jsonl → data/memory/scene_memory_vectors.jsonl
  data/persona_snapshots/         → data/identity/snapshots/

Usage:
    python scripts/migrate_data.py [--dry-run] [--data-dir DATA_DIR]
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.identity_manager import IdentityManager


class MigrationRunner:
    def __init__(self, data_dir: str = "data", dry_run: bool = False):
        self.data_dir = Path(data_dir)
        self.dry_run = dry_run
        self.backup_dir = self.data_dir / "migration_backup" / time.strftime("%Y%m%d_%H%M%S")
        self.manifest: list = []
        self._rolled_back: list = []

    # ── Helpers ──────────────────────────────────────────────────────

    def _backup_file(self, path: Path) -> Path:
        """Copy file to backup dir before touching it."""
        dest = self.backup_dir / path.name
        if not self.dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        print(f"  [backup] {path.name} → {dest}")
        return dest

    def _move_file(self, src: Path, dst: Path) -> bool:
        """Move src → dst. In dry-run mode only prints."""
        if not src.exists():
            return False
        if self.dry_run:
            print(f"  [dry-run] move {src} → {dst}")
            return True
        dst.parent.mkdir(parents=True, exist_ok=True)
        self._backup_file(src)
        shutil.move(str(src), str(dst))
        self.manifest.append({"src": str(src), "dst": str(dst)})
        print(f"  [moved] {src} → {dst}")
        return True

    # ── Migration Steps ───────────────────────────────────────────────

    def _migrate_user_profile(self) -> None:
        """Migrate user_profile.json + interaction_habits.md → identity/ via IdentityManager."""
        profile = self.data_dir / "user_profile.json"
        habits = self.data_dir / "interaction_habits.md"

        if not profile.exists() and not habits.exists():
            print("  [skip] user_profile.json / interaction_habits.md not found")
            return

        if self.dry_run:
            print(f"  [dry-run] IdentityManager.migrate_from_legacy({profile}, {habits})")
            return

        mgr = IdentityManager(data_dir=str(self.data_dir))
        mgr.migrate_from_legacy(str(profile), str(habits))
        self.manifest.append({"action": "identity_migration", "profile": str(profile), "habits": str(habits)})

    def _migrate_vector_indices(self) -> None:
        """Move diary/journal vector index files to subdirectories."""
        moves = [
            (self.data_dir / "diary_vectors.jsonl",   self.data_dir / "diary" / "diary_vectors.jsonl"),
            (self.data_dir / "journal_vectors.jsonl", self.data_dir / "journals" / "journal_vectors.jsonl"),
        ]
        for src, dst in moves:
            self._move_file(src, dst)

    def _migrate_memory_files(self) -> None:
        """Move scene_memory and vector files to data/memory/."""
        moves = [
            (self.data_dir / "scene_memory.jsonl",         self.data_dir / "memory" / "scene_memory.jsonl"),
            (self.data_dir / "scene_memory_vectors.jsonl", self.data_dir / "memory" / "scene_memory_vectors.jsonl"),
        ]
        for src, dst in moves:
            self._move_file(src, dst)

    def _migrate_snapshots(self) -> None:
        """Move persona_snapshots/ → identity/snapshots/."""
        src_dir = self.data_dir / "persona_snapshots"
        dst_dir = self.data_dir / "identity" / "snapshots"

        if not src_dir.exists():
            print("  [skip] persona_snapshots/ not found")
            return

        if self.dry_run:
            count = sum(1 for _ in src_dir.glob("*.md"))
            print(f"  [dry-run] move {src_dir}/ ({count} files) → {dst_dir}/")
            return

        dst_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in src_dir.glob("*.md"):
            dst = dst_dir / f.name
            if not dst.exists():
                self._backup_file(f)
                shutil.move(str(f), str(dst))
                self.manifest.append({"src": str(f), "dst": str(dst)})
                moved += 1
        print(f"  [moved] {moved} snapshots → {dst_dir}")

    def _save_manifest(self) -> None:
        path = self.data_dir / "migration_manifest.json"
        if self.dry_run:
            print(f"  [dry-run] would write manifest to {path}")
            return
        path.write_text(
            json.dumps({"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "entries": self.manifest},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  [manifest] saved to {path}")

    def _rollback(self) -> None:
        """Restore moved files from backup on error."""
        print("[MigrationRunner] 回滚中...")
        for entry in reversed(self.manifest):
            src = entry.get("src")
            dst = entry.get("dst")
            if src and dst and Path(dst).exists():
                try:
                    shutil.move(dst, src)
                    print(f"  [rollback] {dst} → {src}")
                except Exception as e:
                    print(f"  [rollback error] {e}")

    # ── Main Entry ────────────────────────────────────────────────────

    def run(self) -> bool:
        """Execute the full migration. Returns True on success."""
        print("\n=== 数据迁移计划 ===")
        print(f"数据目录: {self.data_dir.resolve()}")
        print(f"模式: {'dry-run（仅预览）' if self.dry_run else '实际执行'}")
        print()

        if not self.dry_run:
            confirm = input("确认执行迁移？(y/N): ").strip().lower()
            if confirm != "y":
                print("已取消。")
                return False

        steps = [
            ("用户档案迁移 (user_profile → identity/)", self._migrate_user_profile),
            ("向量索引迁移 (diary/journal vectors)",     self._migrate_vector_indices),
            ("记忆文件迁移 (scene_memory → memory/)",   self._migrate_memory_files),
            ("快照迁移 (persona_snapshots → identity/snapshots/)", self._migrate_snapshots),
        ]

        try:
            for label, fn in steps:
                print(f"\n--- {label} ---")
                fn()

            self._save_manifest()
            print("\n✅ 迁移完成。")
            return True

        except Exception as e:
            print(f"\n❌ 迁移失败: {e}")
            error_log = self.data_dir / "migration_error.log"
            error_log.write_text(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {e}\n",
                encoding="utf-8",
            )
            if not self.dry_run:
                self._rollback()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate openGuiclaw data to new layout")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--data-dir", default="data", help="Path to data directory")
    args = parser.parse_args()

    runner = MigrationRunner(data_dir=args.data_dir, dry_run=args.dry_run)
    success = runner.run()
    sys.exit(0 if success else 1)
