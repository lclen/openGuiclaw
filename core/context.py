"""
ContextManager: Visual Proactive Awareness

Background thread that:
1. Periodically captures the screen.
2. Analyzes it using a Vision-capable model.
3. Logs the summary into the daily journal.
4. Optionally pushes a proactive message to the user.
"""

import base64
import io
import json
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI


# ── Prompt ─────────────────────────────────────────────────────────

VISION_PROMPT = """\
请分析这张屏幕截图，用简体中文描述用户当前正在做什么。
要求：
- summary: 1~2句话，简洁描述用户正在做的事，例如"用户在 VSCode 中编写 Python 代码"。
- status: 以下之一 —— working（正在工作）/ idle（屏幕静止/发呆）/ error（看到报错）/ entertainment（游戏/视频/娱乐）
- needs_interaction: 布尔值，是否值得主动与用户互动。
  - true 的情况：检测到报错、用户看起来卡住了、状态从 working 切换到 entertainment（休息了）、已经 idle 超过阈值。
  - false 的情况：用户正常工作、只是浏览网页。
- suggested_message: 如果 needs_interaction=true，给出1~2句自然、活泼的互动话语（中文）。否则为 null。

返回纯 JSON，不要 Markdown 代码块。格式：
{"summary": "...", "status": "working", "needs_interaction": false, "suggested_message": null}
"""


# 活泼度模式
MODE_SILENT  = "silent"   # 静默：只记录日志，永不主动打扰
MODE_NORMAL  = "normal"   # 正常：仅在出错或明显空闲时才打扰
MODE_LIVELY  = "lively"   # 活泼：积极寒暄，状态变化时就出声


# ── ContextManager ──────────────────────────────────────────────────

class ContextManager:
    """
    Runs a background thread that watches the screen using a Vision model.

    Args:
        client: OpenAI-compatible client (Qwen API).
        vision_model: Model name with Vision capability, e.g. "qwen-vl-plus".
        journal: JournalManager instance to log visual summaries.
        interval_seconds: How often to capture. Default 300 (5 min).
        notification_queue: A queue.Queue() that main loop reads proactive msgs from.
        cooldown_minutes: After sending a proactive msg, silence for N minutes if no reply.
    """

    def __init__(
        self,
        client: OpenAI,
        vision_model: str,
        journal,
        interval_seconds: int = 300,
        notification_queue: Optional[queue.Queue] = None,
        cooldown_minutes: int = 30,
    ):
        self.client = client
        self.vision_model = vision_model
        self.journal = journal
        self.interval = interval_seconds
        self.notification_queue = notification_queue or queue.Queue()
        self.cooldown_minutes = cooldown_minutes
        self.mode: str = MODE_NORMAL       # 默认普通模式
        self.verbose: bool = True          # 是否在终端显示截屏日志（后期可在设置中关闭）

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status: str = "unknown"
        self._last_summary: str = ""
        self._last_proactive_at: float = 0.0
        self._enabled: bool = True

    # ── Public Control ──────────────────────────────────────────────

    def start(self) -> None:
        """Start the background loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ContextLoop")
        self._thread.start()
        print("[Context] 视觉感知线程已启动。")

    def stop(self) -> None:
        """Stop the background loop gracefully."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[Context] 视觉感知线程已停止。")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_mode(self, mode: str) -> None:
        """Switch proactive mode: silent / normal / lively."""
        if mode not in (MODE_SILENT, MODE_NORMAL, MODE_LIVELY):
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode

    def notify_user_replied(self) -> None:
        """Call this when user sends ANY message, to reset cooldown."""
        self._last_proactive_at = 0.0  # reset — they replied, cooldown lifted

    # ── Background Loop ─────────────────────────────────────────────

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._enabled:
                try:
                    self._tick()
                except Exception as e:
                    print(f"[Context] [WARN] 感知循环出错: {e}")
            self._stop_event.wait(self.interval)

    def _tick(self) -> None:
        """One cycle: capture → analyze → log → maybe interact."""
        screenshot_b64 = self._capture_screen()
        if not screenshot_b64:
            return

        if self.verbose:
            ts = time.strftime("%H:%M:%S")
            print(f"\n[Context {ts}] 正在分析屏幕...", flush=True)

        result = self._analyze_screen(screenshot_b64)
        if not result:
            return

        summary   = result.get("summary", "")
        status    = result.get("status", "unknown")
        needs_interaction = result.get("needs_interaction", False)
        suggested_message = result.get("suggested_message", None)

        if self.verbose:
            status_icon = {
                "working": "💻", "idle": "😴",
                "error": "🔴", "entertainment": "🎮",
            }.get(status, "❓")
            print(f"[Context] {status_icon} {status} — {summary[:60]}")
            print("You > ", end="", flush=True)  # 重新打印输入提示符

        # ── 活泼度模式决策 ──────────────────────────────────────────
        if self.mode == MODE_SILENT:
            needs_interaction = False  # 永远不打扰

        elif self.mode == MODE_LIVELY:
            # IDE/代码编辑器/工作状态：不打扰专注工作的用户
            if status == "working":
                needs_interaction = False
            # 娱乐、游戏、空闲：主动搭话
            elif status in ("entertainment", "idle", "error"):
                needs_interaction = True
            # 其它未知状态：沿用模型判断

        # MODE_NORMAL: 完全沿用模型自身判断（needs_interaction 不修改）

        # ── 日志去重逻辑 (Deduplication) ─────────────────────────
        is_duplicate = False
        if self._last_summary and self._last_status == status:
            import re
            def _tokens(text: str):
                return set(re.split(r'[\s，。：、（）【】「」\.\-]+', text.lower()))
            t1, t2 = _tokens(self._last_summary), _tokens(summary)
            union = t1 | t2
            if union:
                sim = len(t1 & t2) / len(union)
                if sim >= 0.55:  # >= 55% 词级别重合度才算同一行为延续
                    is_duplicate = True

        # Log to journal
        if summary and not is_duplicate:
            log_entry = f"**[视觉日志]** 状态: `{status}` — {summary}"
            self.journal.append(log_entry)
            self._last_summary = summary
        elif summary and is_duplicate:
            self.journal.update_last_time()
            if self.verbose:
                print(f"[Context] 💤 状态未发生显著变化（延续 {status}），已自动更新记录的时长。")

        # Proactive interaction decision
        if needs_interaction and suggested_message:
            self._maybe_push_notification(status, suggested_message)

        # Update last known status
        self._last_status = status

    # ── Screen Capture ───────────────────────────────────────────────

    def _capture_screen(self) -> Optional[str]:
        """Capture screen and return as Base64-encoded PNG."""
        try:
            import pyautogui
            from PIL import Image

            screenshot = pyautogui.screenshot()

            # Downscale to 960×540 to save tokens
            screenshot.thumbnail((960, 540), Image.LANCZOS)

            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        except ImportError:
            print("[Context] [WARN] 缺少依赖: pip install pyautogui pillow")
            return None
        except Exception as e:
            print(f"[Context] 截屏失败: {e}")
            return None

    # ── Vision Analysis ──────────────────────────────────────────────

    def _analyze_screen(self, screenshot_b64: str) -> Optional[dict]:
        """Send screenshot to vision model and parse result."""
        try:
            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"
                                },
                            },
                            {
                                "type": "text",
                                "text": VISION_PROMPT,
                            },
                        ],
                    }
                ],
                max_tokens=300,
                temperature=0.2,
            )
            text = response.choices[0].message.content or "{}"
            # Strip code fences if present
            if "```" in text:
                text = text.split("```")[-2] if "```" in text else text
                text = text.lstrip("json").strip()

            result = json.loads(text)
            return result
        except json.JSONDecodeError:
            print(f"[Context] Vision 模型返回非 JSON: {text[:100]}")
            return None
        except Exception as e:
            print(f"[Context] Vision 分析失败: {e}")
            return None

    # ── Notification Logic ───────────────────────────────────────────

    def _maybe_push_notification(self, status: str, message: str) -> None:
        """
        Put a proactive message into the queue, respecting cooldown.

        Cooldown logic:
        - If a proactive message was sent and the user has NOT replied for
          `cooldown_minutes`, we skip sending another one.
        """
        now = time.time()
        elapsed_since_last = (now - self._last_proactive_at) / 60  # minutes

        if self._last_proactive_at > 0 and elapsed_since_last < self.cooldown_minutes:
            # Still in cooldown — user hasn't replied; stay quiet
            return

        # Push message to queue
        self.notification_queue.put({
            "type": "proactive",
            "status": status,
            "message": message,
        })
        self._last_proactive_at = now
