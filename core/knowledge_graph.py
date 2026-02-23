"""
Knowledge Graph: Lightweight entity-relation triples.

Stores "张三 → 是...导师 → 李四" style relationships extracted from journal.
Each triple is saved as one line in data/knowledge_graph.jsonl.

Format:
    {"subject": "...", "relation": "...", "object": "...",
     "source": "journal:2026-02-19", "ts": "..."}
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional


class Triple:
    """A single knowledge triple: subject → relation → object."""
    def __init__(self, subject: str, relation: str, obj: str,
                 source: str = "", ts: str = ""):
        self.subject = subject
        self.relation = relation
        self.object = obj
        self.source = source
        self.ts = ts or time.strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict:
        return {
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "source": self.source,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Triple":
        return cls(
            subject=d.get("subject", ""),
            relation=d.get("relation", ""),
            obj=d.get("object", ""),
            source=d.get("source", ""),
            ts=d.get("ts", ""),
        )

    def __repr__(self):
        return f"<Triple: {self.subject} → {self.relation} → {self.object}>"


class KnowledgeGraph:
    """
    Lightweight knowledge graph using JSONL storage.

    Usage:
        kg = KnowledgeGraph(data_dir="data")
        kg.add("张三", "是...的导师", "李四", source="journal:2026-02-19")
        triples = kg.query("张三")
        summary = kg.context_for_entity("张三")
    """

    def __init__(self, data_dir: str = "data"):
        self.graph_file = Path(data_dir) / "knowledge_graph.jsonl"
        self._triples: List[Triple] = []
        self._load()

    # ── Public API ──────────────────────────────────────────────────

    def add(self, subject: str, relation: str, obj: str, source: str = "") -> Triple:
        """Add a triple. Skips if an identical (subject, relation, object) exists."""
        for t in self._triples:
            if t.subject == subject and t.relation == relation and t.object == obj:
                return t  # Deduplicate

        triple = Triple(subject, relation, obj, source)
        self._triples.append(triple)
        self._save_one(triple)
        return triple

    def add_batch(self, triples: List[Dict], source: str = "") -> int:
        """
        Add multiple triples from a list of dicts (from LLM output).
        Expected format: [{"subject": ..., "relation": ..., "object": ...}]
        Returns the number of new triples added.
        """
        count = 0
        for item in triples:
            s = item.get("subject", "").strip()
            r = item.get("relation", "").strip()
            o = item.get("object", "").strip()
            if s and r and o:
                before = len(self._triples)
                self.add(s, r, o, source)
                if len(self._triples) > before:
                    count += 1
        return count

    def query(self, entity: str) -> List[Triple]:
        """Find all triples where entity is the subject OR the object.
        Uses space-normalized matching so 'Qwen3.5' can match 'Qwen 3.5'.
        """
        entity_lower = entity.lower()
        entity_nospace = entity_lower.replace(" ", "")

        def _matches(field: str) -> bool:
            fl = field.lower()
            return entity_lower in fl or entity_nospace in fl.replace(" ", "")

        return [t for t in self._triples if _matches(t.subject) or _matches(t.object)]

    def query_between(self, entity_a: str, entity_b: str) -> List[Triple]:
        """Find triples connecting entity_a and entity_b."""
        a, b = entity_a.lower(), entity_b.lower()
        return [
            t for t in self._triples
            if (a in t.subject.lower() and b in t.object.lower()) or
               (b in t.subject.lower() and a in t.object.lower())
        ]

    def context_for_entity(self, entity: str) -> str:
        """Return a formatted summary of all triples involving this entity."""
        triples = self.query(entity)
        if not triples:
            return ""
        lines = [f"【知识关联: {entity}】"]
        for t in triples:
            lines.append(f"  · {t.subject}  {t.relation}  {t.object}")
        return "\n".join(lines)

    def list_all(self) -> List[Triple]:
        return list(self._triples)

    def stats(self) -> str:
        entities = set()
        for t in self._triples:
            entities.add(t.subject)
            entities.add(t.object)
        return f"{len(self._triples)} 条关系，{len(entities)} 个实体"

    # ── Internal ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.graph_file.exists():
            return
        try:
            with open(self.graph_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._triples.append(Triple.from_dict(json.loads(line)))
        except Exception as e:
            print(f"[KnowledgeGraph] Load error: {e}")

    def _save_one(self, triple: Triple) -> None:
        with open(self.graph_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(triple.to_dict(), ensure_ascii=False) + "\n")
