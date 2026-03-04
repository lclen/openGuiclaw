"""
Daily Consolidator: End-of-day summarization and memory promotion.

Runs once per day to:
1. Summarize the day's journal into MEMORY.md (≤800 chars)
2. Promote high-confidence PERSONA_TRAIT memories to HABITS.md / USER.md
3. Deduplicate scene_memory entries with similarity > 0.9
4. Save a consolidation report JSON
"""

import json
import time
from pathlib import Path
from typing import Optional


class DailyConsolidator:
    def __init__(
        self,
        client,
        model: str,
        identity,           # IdentityManager
        memory,             # MemoryManager
        journal,            # JournalManager
        data_dir: str = "data",
        promotion_threshold: float = 0.7,
        similarity_threshold: float = 0.75,
    ):
        self.client = client
        self.model = model
        self.identity = identity
        self.memory = memory
        self.journal = journal
        self.data_dir = Path(data_dir)
        self.report_dir = self.data_dir / "consolidation"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.promotion_threshold = promotion_threshold
        self.similarity_threshold = similarity_threshold

    def should_run(self, date_str: str = None) -> bool:
        """Return True if today's consolidation hasn't been done yet."""
        if date_str is None:
            date_str = time.strftime("%Y-%m-%d")
        return not (self.report_dir / f"consolidation_{date_str}.json").exists()

    def _summarize_journal(self, date_str: str) -> str:
        """Call LLM to summarize the day's journal into ≤800 chars."""
        content = self.journal.read_day(date_str)
        if not content or not content.strip():
            return ""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个助手，请将以下日志内容总结为不超过800字的摘要，保留关键事件和结论。",
                    },
                    {"role": "user", "content": content[:4000]},
                ],
                max_tokens=600,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[DailyConsolidator] LLM 摘要失败: {e}")
            return ""

    def _promote_memories(self) -> int:
        """
        Promote PERSONA_TRAIT memories with confidence > threshold to identity files.
        Removes promoted entries from scene_memory.
        Returns count of promoted items.
        """
        promoted = 0
        to_delete = []

        for mem in self.memory.list_all():
            if "PERSONA_TRAIT" not in mem.tags:
                continue
            # Look for confidence tag like "confidence:0.85"
            confidence = 0.0
            for tag in mem.tags:
                if tag.startswith("confidence:"):
                    try:
                        confidence = float(tag.split(":", 1)[1])
                    except ValueError:
                        pass

            if confidence < self.promotion_threshold:
                continue

            # Route by layer tag
            layer = "subjective"
            for tag in mem.tags:
                if tag in ("objective", "subjective"):
                    layer = tag
                    break

            if layer == "objective":
                # Try to parse "key: value" from content
                if ": " in mem.content:
                    key, _, value = mem.content.partition(": ")
                    self.identity.update_user(key.strip(), value.strip())
                else:
                    self.identity.update_user("trait", mem.content)
            else:
                self.identity.append_habit(mem.content)

            to_delete.append(mem.id)
            promoted += 1

        for mid in to_delete:
            self.memory.delete(mid)

        return promoted

    def _deduplicate_memories(self) -> int:
        """
        Remove duplicate memories. Uses vector cosine similarity when available,
        falls back to text-overlap ratio otherwise.
        Keeps the most recent entry. Returns count of removed items.
        """
        all_mems = self.memory.list_all()
        if len(all_mems) < 2:
            return 0

        # Sort by timestamp descending (keep newest)
        sorted_mems = sorted(all_mems, key=lambda m: m.timestamp, reverse=True)
        to_delete: set = set()

        # ── Vector-based dedup (preferred) ───────────────────────────
        if self.memory._vector_store and self.memory._embedding_client:
            from core.vector_memory import _cosine_similarity

            id_to_vec = {}
            for mid, vec in self.memory._vector_store._store:
                if mid not in id_to_vec:
                    id_to_vec[mid] = vec

            kept_ids: list = []
            for mem in sorted_mems:
                if mem.id in to_delete:
                    continue
                vec_a = id_to_vec.get(mem.id)
                if vec_a is None:
                    kept_ids.append(mem.id)
                    continue
                duplicate = False
                for kept_id in kept_ids:
                    vec_b = id_to_vec.get(kept_id)
                    if vec_b and _cosine_similarity(vec_a, vec_b) > self.similarity_threshold:
                        duplicate = True
                        break
                if duplicate:
                    to_delete.add(mem.id)
                else:
                    kept_ids.append(mem.id)

        else:
            # ── Text-overlap fallback ─────────────────────────────────
            kept: list = []
            for mem in sorted_mems:
                if mem.id in to_delete:
                    continue
                norm_a = " ".join(mem.content.lower().split())
                words_a = set(norm_a.split())
                duplicate = False
                for kept_mem in kept:
                    norm_b = " ".join(kept_mem.content.lower().split())
                    words_b = set(norm_b.split())
                    # Jaccard similarity
                    if not words_a or not words_b:
                        continue
                    jaccard = len(words_a & words_b) / len(words_a | words_b)
                    # Also check substring containment
                    shorter, longer = sorted([norm_a, norm_b], key=len)
                    contained = len(longer) > 0 and shorter in longer
                    if jaccard > 0.7 or contained:
                        duplicate = True
                        break
                if duplicate:
                    to_delete.add(mem.id)
                else:
                    kept.append(mem)

        for mid in to_delete:
            self.memory.delete(mid)

        return len(to_delete)

    def _save_report(self, date_str: str, stats: dict) -> None:
        path = self.report_dir / f"consolidation_{date_str}.json"
        path.write_text(
            json.dumps({"date": date_str, **stats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def run(self, date_str: str = None) -> dict:
        """
        Run the full consolidation pipeline for the given date.
        Returns a stats dict.
        """
        if date_str is None:
            date_str = time.strftime("%Y-%m-%d")

        stats = {
            "summary_chars": 0,
            "promoted": 0,
            "deduplicated": 0,
        }

        # Step 1: Summarize journal → MEMORY.md
        summary = self._summarize_journal(date_str)
        if summary:
            self.identity.write_memory(summary)
            stats["summary_chars"] = len(summary)

        # Step 2: Promote high-confidence memories
        stats["promoted"] = self._promote_memories()

        # Step 3: Deduplicate
        stats["deduplicated"] = self._deduplicate_memories()

        # Step 4: Save report
        self._save_report(date_str, stats)

        print(
            f"[DailyConsolidator] {date_str} 完成 — "
            f"摘要 {stats['summary_chars']} 字, "
            f"晋升 {stats['promoted']} 条, "
            f"去重 {stats['deduplicated']} 条"
        )
        return stats
