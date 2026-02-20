"""
Memory Manager: JSONL-based persistent memory.

Inspired by Nanobot's two-layer memory, with MemU's structured records.
- memory.jsonl: Structured long-term facts (searchable by keyword)
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional


class MemoryItem:
    """A single memory record."""

    def __init__(self, content: str, tags: List[str] = None):
        self.id = f"mem_{int(time.time() * 1000)}"
        self.content = content
        self.tags = tags or []
        self.timestamp = time.time()
        self.created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryItem":
        item = cls(data["content"], data.get("tags", []))
        item.id = data.get("id", item.id)
        item.timestamp = data.get("timestamp", item.timestamp)
        item.created_at = data.get("created_at", item.created_at)
        return item


class MemoryManager:
    """
    Manages long-term memory using a JSONL file.

    If `embedding_client` and `vector_store` are provided, enables
    semantic (vector) search via Qwen text-embedding-v4.
    Falls back to keyword search otherwise.
    """

    def __init__(
        self,
        data_dir: str = "data",
        embedding_client=None,   # EmbeddingClient | None
        vector_store=None,       # VectorStore | None
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.memory_file = self.data_dir / "scene_memory.jsonl"
        self._memories: List[MemoryItem] = []
        self._embedding_client = embedding_client
        self._vector_store = vector_store
        self._load()

    def _load(self) -> None:
        """Load all memories from JSONL file."""
        if not self.memory_file.exists():
            return
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        self._memories.append(MemoryItem.from_dict(data))
        except Exception as e:
            print(f"[Memory] Failed to load: {e}")

    def _save_one(self, item: MemoryItem) -> None:
        """Append a single memory to the JSONL file."""
        with open(self.memory_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    def add(self, content: str, tags: List[str] = None) -> MemoryItem:
        """
        Add a new memory. Skips if exact same content already exists.
        If vector search is available, generates and stores embedding.
        """
        # Simple deduplication: normalize and compare content
        normalized = " ".join(content.lower().split())
        for mem in self._memories:
            if " ".join(mem.content.lower().split()) == normalized:
                return mem

        item = MemoryItem(content, tags)
        self._memories.append(item)
        self._save_one(item)

        # Generate and store vectors asynchronously
        if self._embedding_client and self._vector_store:
            try:
                # Use embed_text to get multiple chunks
                vectors = self._embedding_client.embed_text(content)
                if vectors:
                    self._vector_store.add_vectors(item.id, vectors)
            except Exception as e:
                print(f"[Memory] Vector generation failed: {e}")

        return item

    def search(self, query: str, top_k: int = 5, tag_filter: str = None) -> List[MemoryItem]:
        """
        Retrieve relevant memories.
        - Uses semantic vector search if available (Qwen embedding).
        - Falls back to keyword overlap search.
        """
        candidates = [
            m for m in self._memories
            if not tag_filter or tag_filter in m.tags
        ]
        if not candidates:
            return []

        # ── Semantic Search (preferred) ──────────────────────────────
        if self._embedding_client and self._vector_store:
            query_vec = self._embedding_client.embed(query)
            if query_vec:
                candidate_ids = [m.id for m in candidates]
                scored_ids = self._vector_store.search(query_vec, top_k=top_k, candidate_ids=candidate_ids)
                id_to_mem = {m.id: m for m in candidates}
                results = [id_to_mem[mid] for mid, _ in scored_ids if mid in id_to_mem]
                if results:
                    return results
                # Fall through to keyword if no vector results

        # ── Keyword Search (fallback) ─────────────────────────────────
        return self._keyword_search(query, candidates, top_k)

    def _keyword_search(
        self, query: str, candidates: List[MemoryItem], top_k: int
    ) -> List[MemoryItem]:
        query_lower = query.lower()
        query_words = set(query_lower.split())
        scored = []

        for mem in candidates:
            content_lower = mem.content.lower()
            tag_text_lower = " ".join(mem.tags).lower()

            content_words = set(content_lower.split())
            tag_words = set(tag_text_lower.split())
            word_score = len(query_words & content_words) + 0.5 * len(query_words & tag_words)

            matched_chars = sum(1 for ch in query_lower if ch in content_lower or ch in tag_text_lower)
            sub_score = matched_chars / max(len(query_lower), 1)

            score = max(word_score, sub_score)
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda x: (x[0], x[1].timestamp), reverse=True)
        return [mem for _, mem in scored[:top_k]]


    def get_recent(self, n: int = 5) -> List[MemoryItem]:
        """Return the n most recently added memories."""
        return sorted(self._memories, key=lambda m: m.timestamp, reverse=True)[:n]

    def build_context(self, query: str, top_k: int = 5) -> str:
        """
        Build a formatted memory context string to inject into the system prompt.
        Returns empty string if no relevant memories.
        """
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        lines = [f"  - [{m.created_at}] {m.content}" for m in results]
        return "【相关记忆】\n" + "\n".join(lines)

    def list_all(self) -> List[MemoryItem]:
        return list(self._memories)

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by id and rewrite the file."""
        before = len(self._memories)
        self._memories = [m for m in self._memories if m.id != memory_id]
        if len(self._memories) < before:
            self._rewrite_file()
            # Also remove from vector store if present
            if self._vector_store:
                self._vector_store.remove(memory_id)
            return True
        return False

    def update(self, memory_id: str, new_content: str, new_tags: List[str] = None) -> bool:
        """
        Update an existing memory by ID.
        Rewrites the file and regenerates the vector.
        """
        for mem in self._memories:
            if mem.id == memory_id:
                mem.content = new_content
                if new_tags is not None:
                    mem.tags = new_tags
                # Rewrite the whole file to reflect the edit
                self._rewrite_file()
                # Regenerate vector
                if self._embedding_client and self._vector_store:
                    try:
                        self._vector_store.remove(memory_id)
                        vectors = self._embedding_client.embed_text(new_content)
                        if vectors:
                            self._vector_store.add_vectors(memory_id, vectors)
                    except Exception as e:
                        print(f"[Memory] Vector update failed: {e}")
                return True
        return False

    def _rewrite_file(self) -> None:
        """Rewrite the entire JSONL file (used after deletion or update)."""
        with open(self.memory_file, "w", encoding="utf-8") as f:
            for mem in self._memories:
                f.write(json.dumps(mem.to_dict(), ensure_ascii=False) + "\n")
