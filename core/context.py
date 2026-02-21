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
from typing import Optional, Callable, List

from openai import OpenAI


# ── Prompt ─────────────────────────────────────────────────────────

VISION_PROMPT = """\
请分析这张屏幕截图，并结合提供的[历史上下文]，用简体中文描述用户当前正在做什么。
[历史上下文]包含了最近几分钟的视觉感知记录和聊天记录，请利用这些信息来保持感知的连续性，避免给出与前文矛盾的推断。

状态判定准则：
- status: 以下之一 ——
  - working: 正在工作。标志：编辑器（VSCode）、终端（充满日志/代码）、文档、协同工具（Slack/飞书）、学术网站。
  - entertainment: 娱乐休闲。标志：视频网站（Bilibili、YouTube、爱奇艺）、社交媒体（微博、Twitter）、各种游戏、音乐播放器。**注意**：即使角落里开了终端，只要主窗口或视觉焦点在视频/游戏上，就判定为 entertainment。
  - idle: 发呆/空闲。标志：显示桌面、屏保、长时间停留在无关紧要的静态网页。
  - error: 看到报错。标志：明显的红色报错日志、对话框警告。

要求：
- summary: 1~2句话，简洁描述，例如"用户在 B 站观看视频，侧边挂着终端"。
- status: 见上文。
- needs_interaction: 布尔值。如果进入 entertainment、idle 或 error 状态，通常应为 true。
- suggested_message: 如果 status 不为 working，请务必给出1~3句人性化、自然、有趣、“活人感”，带点主观色彩的互动内容（如关心、催促工作、吐槽视频内容等）。

返回纯 JSON，不要 Markdown 代码块。格式：
{"summary": "...", "status": "entertainment", "needs_interaction": true, "suggested_message": "..."}
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
        add_visual_log_func: Callback to write a visual log string into the current session.
        get_visual_history_func: Callback to retrieve recent visual logs from the current session.
        interval_seconds: How often to capture. Default 300 (5 min).
        notification_queue: A queue.Queue() that main loop reads proactive msgs from.
        cooldown_minutes: After sending a proactive msg, silence for N minutes if no reply.
    """

    def __init__(
        self,
        client: OpenAI,
        vision_model: str,
        add_visual_log_func: Optional[Callable] = None,
        get_visual_history_func: Optional[Callable] = None,
        update_visual_log_func: Optional[Callable] = None,
        interval_seconds: int = 300,
        notification_queue: Optional[queue.Queue] = None,
        cooldown_minutes: int = 30,
        get_history_func: Optional[Callable] = None,
    ):
        self.client = client
        self.vision_model = vision_model
        self.add_visual_log_func = add_visual_log_func
        self.get_visual_history_func = get_visual_history_func
        self.update_visual_log_func = update_visual_log_func
        self.interval = interval_seconds
        self.notification_queue = notification_queue or queue.Queue()
        self.cooldown_minutes = cooldown_minutes
        self.get_history_func = get_history_func
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

        # ── 获取上下文历史 ──
        history_text = ""
        # 1. 聊天历史
        if self.get_history_func:
            msgs = self.get_history_func()
            if msgs:
                chat_lines = [f"- {m['role']}: {m['content'][:100]}" for m in msgs]
                history_text += "【最近聊天】\n" + "\n".join(chat_lines) + "\n"
        
        # 2. 视觉感知历史 (从 Session 读取最近)
        if self.get_visual_history_func:
            v_msgs = self.get_visual_history_func()
            if v_msgs:
                history_text += "【最近感知日志】\n" + "\n".join(v_msgs[-4:]) + "\n"

        result = self._analyze_screen(screenshot_b64, history_text)
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

        # Log to Session
        if summary and not is_duplicate:
            log_entry = f"**[视觉日志]** 状态: `{status}` — {summary}"
            if self.add_visual_log_func:
                self.add_visual_log_func(log_entry)
            self._last_summary = summary
        elif summary and is_duplicate:
            # 去重：更新上一条日志的「持续至」时间，而不是跳过
            current_time = time.strftime("%H:%M:%S")
            if self.update_visual_log_func:
                self.update_visual_log_func(current_time)
            if self.verbose:
                print(f"[Context] 💤 状态延续（{status}），已更新持续时间至 {current_time}。")

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

    def _analyze_screen(self, screenshot_b64: str, history: str = "") -> Optional[dict]:
        """Send screenshot and optional history to vision model and parse result."""
        prompt = VISION_PROMPT
        if history:
            prompt = f"### [历史上下文] ###\n{history}\n\n" + prompt

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
                                "text": prompt,
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

        # 活泼模式下缩短冷却时间（例如 10 分钟），默认模式 30 分钟
        target_cooldown = 10 if self.mode == MODE_LIVELY else self.cooldown_minutes

        if self._last_proactive_at > 0 and elapsed_since_last < target_cooldown:
            # Still in cooldown — user hasn't replied; stay quiet
            return

        # Push message to queue
        self.notification_queue.put({
            "type": "proactive",
            "status": status,
            "message": message,
        })
        self._last_proactive_at = now
