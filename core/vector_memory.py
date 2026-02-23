"""
Vector Memory: Semantic search using Qwen text-embedding-v4.

Stores embedding vectors alongside memories to enable similarity-based retrieval.
Falls back to keyword search if vectors are unavailable.

Storage: data/memory_vectors.jsonl  (each line: {id, vector})
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from openai import OpenAI

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False


# ── Text Splitting Utility ──────────────────────────────────────────

def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Splits long text into overlapping chunks.
    Useful for indexing long logs or documents.
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)
        if start >= len(text):
            break
    return chunks


# ── EmbeddingClient ──────────────────────────────────────────────────

class EmbeddingClient:
    """Thin wrapper around Qwen embedding API with auto-chunking."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4",
    ):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_text(self, text: str) -> List[List[float]]:
        """
        Takes potentially long text, splits it, and returns a list of embeddings.
        Always returns a list (even for 1 chunk).
        """
        chunks = split_text(text)
        return self.embed_batch(chunks)

    def embed(self, text: str) -> Optional[List[float]]:
        """Used for single query embedding (top chunk only)."""
        vectors = self.embed_text(text)
        return vectors[0] if vectors else None

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts (handles API calls)."""
        if not texts: return []
        try:
            # DashScope supports batching
            resp = self.client.embeddings.create(
                model=self.model,
                input=texts,
                encoding_format="float",
            )
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            return [d.embedding for d in sorted_data]
        except Exception as e:
            print(f"[VectorMemory] API Error: {e}")
            return []


# ── VectorStore ───────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity. Uses numpy if available, otherwise pure Python."""
    if _NUMPY_AVAILABLE:
        a_arr = np.array(a, dtype=np.float32)
        b_arr = np.array(b, dtype=np.float32)
        denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        return float(np.dot(a_arr, b_arr) / denom) if denom else 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """
    Persists embedding vectors. Supports multiple vectors (chunks) per ID.
    Storage format: data/scene_memory_vectors.jsonl
    """

    def __init__(self, data_dir: str = "data"):
        self.vector_file = Path(data_dir) / "scene_memory_vectors.jsonl"
        self._store: List[Tuple[str, List[float]]] = []  # List of (id, vector)
        self._load()

    def _load(self) -> None:
        if not self.vector_file.exists():
            return
        try:
            with open(self.vector_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        # We use 'v' as key for backward compatibility or new 'vector'
                        vec = data.get("v") or data.get("vector")
                        if vec:
                            self._store.append((data["id"], vec))
        except Exception as e:
            print(f"[VectorStore] Load error: {e}")

    def add_vectors(self, mem_id: str, vectors: List[List[float]]) -> None:
        """Add multiple chunks for a single memory entry. Skips if already indexed."""
        if self.has(mem_id):
            return
        for v in vectors:
            self._store.append((mem_id, v))
            self._save_one(mem_id, v)

    def add(self, mem_id: str, vector: List[float]) -> None:
        """Legacy support for single vector."""
        self.add_vectors(mem_id, [vector])

    def has(self, mem_id: str) -> bool:
        for mid, _ in self._store:
            if mid == mem_id: return True
        return False

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        candidate_ids: Optional[List[str]] = None,
        threshold: float = 0.4,
    ) -> List[Tuple[str, float]]:
        """
        Similarity search with aggregation.
        If an entry has multiple chunks, we take the highest score (max-pooling).
        Uses numpy batch computation when available for better performance.
        """
        target_set = set(candidate_ids) if candidate_ids else None

        # Filter candidates first
        pairs = [(mid, vec) for mid, vec in self._store
                 if not target_set or mid in target_set]
        if not pairs:
            return []

        best_scores: Dict[str, float] = {}

        if _NUMPY_AVAILABLE and pairs:
            q = np.array(query_vector, dtype=np.float32)
            q_norm = np.linalg.norm(q)
            if q_norm == 0:
                return []
            q = q / q_norm
            # Batch matrix multiply: (n_vecs, dim) @ (dim,) -> (n_vecs,)
            mat = np.array([v for _, v in pairs], dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            mat = mat / norms
            scores = mat @ q  # cosine similarity for all at once
            for (mid, _), score in zip(pairs, scores.tolist()):
                s = float(score)
                if mid not in best_scores or s > best_scores[mid]:
                    best_scores[mid] = s
        else:
            for mid, vec in pairs:
                score = _cosine_similarity(query_vector, vec)
                if mid not in best_scores or score > best_scores[mid]:
                    best_scores[mid] = score

        filtered = [(mid, score) for mid, score in best_scores.items() if score >= threshold]
        sorted_results = sorted(filtered, key=lambda x: x[1], reverse=True)
        return sorted_results[:top_k]

    def remove(self, mem_id: str) -> None:
        self._store = [(mid, v) for mid, v in self._store if mid != mem_id]
        self._rewrite()

    def _save_one(self, mem_id: str, vector: List[float]) -> None:
        with open(self.vector_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": mem_id, "v": vector}, ensure_ascii=False) + "\n")

    def _rewrite(self) -> None:
        with open(self.vector_file, "w", encoding="utf-8") as f:
            for mid, vec in self._store:
                f.write(json.dumps({"id": mid, "v": vec}, ensure_ascii=False) + "\n")
