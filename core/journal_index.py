"""
Journal Index: Semantic search over daily journal logs.

Journals live in data/journals/YYYY-MM-DD.md.
This module splits them into chunks, embeds them via Qwen,
and stores the results in data/journal_vectors.jsonl.

Each line in journal_vectors.jsonl:
    {"date": "2026-02-19", "chunk": 0, "text": "...", "v": [...]}

On search, all chunks are scored and the top-k unique (date, chunk) pairs
are returned with their text snippets.
"""

import json
import time
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from core.vector_memory import split_text, _cosine_similarity


class JournalChunk:
    """A single indexed piece of a journal."""
    def __init__(self, date: str, chunk_idx: int, text: str, vector: List[float]):
        self.date = date
        self.chunk_idx = chunk_idx
        self.text = text
        self.vector = vector


class JournalIndex:
    """
    Manages semantic indexing of daily journal files.

    Usage:
        ji = JournalIndex(embedding_client, data_dir="data")
        ji.index_day("2026-02-19", journal_text)
        results = ji.search("上周做了什么", top_k=3)
    """

    def __init__(self, embedding_client, data_dir: str = "data"):
        self.embedding_client = embedding_client
        self.data_dir = Path(data_dir)
        self.index_file = self.data_dir / "journals" / "journal_vectors.jsonl"
        self.index_file.parent.mkdir(parents=True, exist_ok=True)

        # Auto-migrate from legacy flat path
        legacy = self.data_dir / "journal_vectors.jsonl"
        if legacy.exists() and not self.index_file.exists():
            legacy.rename(self.index_file)
            print(f"[JournalIndex] 已迁移索引: {legacy} → {self.index_file}")

        self._chunks: List[JournalChunk] = []
        self._indexed_dates: Dict[str, int] = {}
        self._load()

    # ── Public API ──────────────────────────────────────────────────

    def has_indexed(self, date_str: str) -> bool:
        return date_str in self._indexed_dates

    def index_day(self, date_str: str, text: str) -> int:
        """
        Split and vectorize a day's journal text.
        Skips if already indexed.
        Returns the number of chunks added.
        """
        if self.has_indexed(date_str):
            return 0
        if not text or not text.strip():
            return 0

        chunks_text = split_text(text, chunk_size=600, overlap=60)
        vectors = self.embedding_client.embed_batch(chunks_text)

        count = 0
        for i, (chunk_text, vec) in enumerate(zip(chunks_text, vectors)):
            if not vec:
                continue
            jc = JournalChunk(date_str, i, chunk_text, vec)
            self._chunks.append(jc)
            self._save_one(jc)
            count += 1

        if count:
            self._indexed_dates[date_str] = count
        return count

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Semantic search over all journal chunks.
        Returns [{date, text, score}] sorted by score DESC.
        """
        if not self._chunks:
            return []

        query_vec = self.embedding_client.embed(query)
        if not query_vec:
            return []

        # Score all chunks, pick highest per date (max-pooling per date)
        best: Dict[str, Tuple[float, str]] = {}  # date -> (score, text)
        for jc in self._chunks:
            score = _cosine_similarity(query_vec, jc.vector)
            if jc.date not in best or score > best[jc.date][0]:
                best[jc.date] = (score, jc.text)

        results = [
            {"date": date, "score": score, "text": text}
            for date, (score, text) in best.items()
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def list_indexed_dates(self) -> List[str]:
        return sorted(self._indexed_dates.keys())

    # ── Internal ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.index_file.exists():
            return
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    jc = JournalChunk(
                        date=data["date"],
                        chunk_idx=data.get("chunk", 0),
                        text=data.get("text", ""),
                        vector=data.get("v", []),
                    )
                    self._chunks.append(jc)
                    self._indexed_dates[jc.date] = self._indexed_dates.get(jc.date, 0) + 1
        except Exception as e:
            print(f"[JournalIndex] Load error: {e}")

    def _save_one(self, jc: JournalChunk) -> None:
        with open(self.index_file, "a", encoding="utf-8") as f:
            record = {
                "date": jc.date,
                "chunk": jc.chunk_idx,
                "text": jc.text,
                "v": jc.vector,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _rewrite(self) -> None:
        """Rewrite the index file from the in-memory chunk list (used after removal)."""
        with open(self.index_file, "w", encoding="utf-8") as f:
            for jc in self._chunks:
                record = {
                    "date": jc.date,
                    "chunk": jc.chunk_idx,
                    "text": jc.text,
                    "v": jc.vector,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
