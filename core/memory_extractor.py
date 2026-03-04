"""
MemoryExtractor: LLM-driven automatic memory extraction.

Analyzes conversation turns and sessions to extract long-term valuable
user information, writing results into MemoryManager.
"""

import json
import logging
import re
from typing import List, Optional

from core.memory import MemoryItem, MemoryManager

logger = logging.getLogger(__name__)

EXPERIENCE_TYPES = {"skill", "error", "experience"}

_PROMPT_EXTRACT_TURN = """\
你是一个记忆提取助手。分析以下对话轮次，判断是否包含值得长期记住的用户信息。

【判断标准】
- 只提取在未来新对话中仍有价值的信息
- 区分「用户长期特征」（偏好、身份、规则）和「一次性任务内容」
- 绝大多数对话轮次应输出 NONE
- 不要提取临时性、上下文相关的信息

【记忆类型】
- fact: 客观事实（用户的职业、所在地等）
- preference: 用户偏好（喜欢的工具、风格等）
- rule: 用户设定的规则约束
- skill: 用户擅长的技能或成功模式
- error: 需要避免的错误
- experience: 可复用的任务经验

用户: {user_message}
助手: {assistant_message}

如果有值得记录的信息，输出 JSON（单个对象），content 字段不超过 100 字：
{{"type": "...", "subject": "...", "predicate": "...", "content": "...", "importance": 1-5}}
否则输出：NONE\
"""

_PROMPT_EXTRACT_CONVERSATION = """\
回顾整段对话，提取值得长期记住的用户信息。

对话内容：
{conversation}

【已有记忆（避免重复提取语义相近的内容）】
{existing_memories}

【只提取以下类型的信息】
- 用户身份、职业、所在地（fact）
- 用户长期偏好、习惯（preference）
- 用户对 AI 行为的持久要求（rule）
- 可复用的技能或成功模式（skill）
- 需要长期避免的错误（error）
- 可复用的任务经验（experience）

【绝对不要提取】
- 一次性任务请求
- 临时性需求
- 打招呼、寒暄
- 与已有记忆语义重复的内容

如果有值得记录的信息，输出 JSON 数组（最多 3 条），每条 content 不超过 100 字：
[{{"type": "...", "content": "...", "importance": 1-5}}]
否则输出：NONE\
"""

_PROMPT_EXTRACT_EXPERIENCE = """\
分析以下已完成任务的对话，提取可复用的经验教训。

对话内容：
{conversation}

任务结果：
{task_result}

【已有记忆（避免重复提取语义相近的内容）】
{existing_memories}

【只提取以下类型】
- skill: 用户擅长的技能或成功模式
- error: 需要避免的错误
- experience: 可复用的任务经验

【不要提取其他类型（fact、preference、rule 等）】
【不要提取与已有记忆语义重复的内容】

如果有值得记录的信息，输出 JSON 数组（最多 3 条），每条 content 不超过 100 字：
[{{"type": "skill|error|experience", "content": "...", "importance": 1-5}}]
否则输出：NONE\
"""


class MemoryExtractor:
    """LLM-driven memory extractor that writes results into MemoryManager."""

    def __init__(self, llm_client, memory_manager: MemoryManager, model: str):
        self.client = llm_client
        self.memory = memory_manager
        self.model = model

    # ── Private helpers ──────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM and return the raw text response.

        Returns an empty string on any network or API error.
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("[MemoryExtractor] LLM 调用失败: %s", e)
            return ""

    def _parse_response(self, raw: str) -> Optional[dict]:
        """Parse a JSON object or array from the LLM response.

        - Tries to find a JSON object ``{...}`` first.
        - Falls back to a JSON array ``[...]``; if found, returns the first element.
        - Returns ``None`` on any parse failure (logs a warning, never raises).
        """
        if not raw:
            return None
        try:
            # For single-object responses (extract_from_turn), try object first.
            # Use non-greedy inner match to avoid over-consuming when multiple JSON blocks exist.
            obj_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", raw, re.DOTALL)
            if obj_match:
                return json.loads(obj_match.group())

            # Fall back to array — return first element
            arr_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if arr_match:
                arr = json.loads(arr_match.group())
                if isinstance(arr, list) and arr:
                    return arr[0] if isinstance(arr[0], dict) else None
        except Exception:
            pass

        logger.warning("[MemoryExtractor] 解析失败: %r", raw[:200])
        return None

    def _parse_array_response(self, raw: str) -> List[dict]:
        """Parse a JSON array from the LLM response.

        Returns an empty list on any parse failure.
        """
        if not raw:
            return []
        try:
            arr_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if arr_match:
                arr = json.loads(arr_match.group())
                if isinstance(arr, list):
                    return [item for item in arr if isinstance(item, dict)]
        except Exception:
            pass

        # Maybe it's a single object — wrap it
        parsed = self._parse_response(raw)
        if parsed:
            return [parsed]

        logger.warning("[MemoryExtractor] 解析失败: %r", raw[:200])
        return []

    @staticmethod
    def _build_conversation_text(messages: List[dict], max_turns: int = 20) -> str:
        """Format the last ``max_turns`` user/assistant messages into a readable string."""
        # Only include user and assistant roles — skip visual_log, debug_log, tool, system, etc.
        _DISPLAY_ROLES = {"user", "assistant"}
        filtered = [m for m in messages if m.get("role") in _DISPLAY_ROLES]
        recent = filtered[-max_turns:]
        lines = []
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # content may be a list (multimodal) — extract text parts only
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}: {content}")
        return "\n".join(lines)

    # ── Public extraction methods ─────────────────────────────────────────────

    def extract_from_turn(
        self, user_message: str, assistant_message: str
    ) -> List[MemoryItem]:
        """Extract memory from a single conversation turn.

        Returns a list of written MemoryItems (usually empty).
        """
        try:
            prompt = _PROMPT_EXTRACT_TURN.format(
                user_message=user_message,
                assistant_message=assistant_message,
            )
            raw = self._call_llm(prompt)
            if not raw or raw.strip().upper() == "NONE":
                return []

            parsed = self._parse_response(raw)
            if not parsed or "content" not in parsed:
                return []

            item = self.memory.add(
                content=parsed["content"],
                type=parsed.get("type", "fact"),
                source="auto_extracted",
            )
            return [item]
        except Exception as e:
            logger.warning("[MemoryExtractor] extract_from_turn 异常: %s", e)
            return []

    def extract_from_conversation(self, messages: List[dict]) -> List[MemoryItem]:
        """Batch-extract user profile information from a full conversation.

        Takes the last 20 messages and writes up to 3 memory items.
        Returns the list of written MemoryItems.
        """
        try:
            conversation = self._build_conversation_text(messages, max_turns=20)
            existing = self._build_existing_summary()
            prompt = _PROMPT_EXTRACT_CONVERSATION.format(
                conversation=conversation,
                existing_memories=existing,
            )
            raw = self._call_llm(prompt)
            if not raw or raw.strip().upper() == "NONE":
                return []

            items_data = self._parse_array_response(raw)
            written: List[MemoryItem] = []
            for data in items_data:
                if "content" not in data:
                    continue
                item = self.memory.add(
                    content=data["content"],
                    type=data.get("type", "fact"),
                    source="auto_extracted",
                )
                written.append(item)
            return written
        except Exception as e:
            logger.warning("[MemoryExtractor] extract_from_conversation 异常: %s", e)
            return []

    def extract_experience(
        self, messages: List[dict], task_result: str
    ) -> List[MemoryItem]:
        """Extract reusable experience from a completed task conversation.

        Only writes memories of type ``skill``, ``error``, or ``experience``.
        Other types returned by the LLM are silently filtered out.
        """
        try:
            conversation = self._build_conversation_text(messages, max_turns=20)
            existing = self._build_existing_summary(types=list(EXPERIENCE_TYPES))
            prompt = _PROMPT_EXTRACT_EXPERIENCE.format(
                conversation=conversation,
                task_result=task_result,
                existing_memories=existing,
            )
            raw = self._call_llm(prompt)
            if not raw or raw.strip().upper() == "NONE":
                return []

            items_data = self._parse_array_response(raw)
            written: List[MemoryItem] = []
            for data in items_data:
                if "content" not in data:
                    continue
                mem_type = data.get("type", "")
                if mem_type not in EXPERIENCE_TYPES:
                    continue  # filter out non-experience types
                item = self.memory.add(
                    content=data["content"],
                    type=mem_type,
                    source="auto_extracted",
                )
                written.append(item)
            return written
        except Exception as e:
            logger.warning("[MemoryExtractor] extract_experience 异常: %s", e)
            return []

    def _build_existing_summary(self, types: List[str] = None, max_items: int = 20) -> str:
        """Build a short summary of existing memories to inject into prompts."""
        all_mems = self.memory.list_all()
        if types:
            all_mems = [m for m in all_mems if m.type in types]
        recent = sorted(all_mems, key=lambda m: m.timestamp, reverse=True)[:max_items]
        if not recent:
            return "（暂无已有记忆）"
        return "\n".join(f"- [{m.type}] {m.content}" for m in recent)
