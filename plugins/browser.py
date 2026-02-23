"""
Browser Automation Plugin

Integration with the `agent-browser` CLI for precise DOM-based web automation.
"""

import subprocess

# 全局记录当前浏览器的运行模式
# 可选值: "background" (默认无头后台), "headed" (可见的Playwright), "system" (连接到系统的 Edge/Chrome)
_CURRENT_MODE = "system"

def register(skills_manager):
    def run_agent_browser(args: list[str]) -> str:
        """Helper to run agent-browser via npx, applying the correct mode flags."""
        global _CURRENT_MODE
        final_args = []
        
        if _CURRENT_MODE == "system":
            final_args.append("--auto-connect")
            from core.browser_utils import ensure_browser_running
            ensure_browser_running(9222)
        elif _CURRENT_MODE == "headed":
            final_args.append("--headed")

        final_args.extend(args)

        # Use subprocess.list2cmdline to safely format the command for shell=True on Windows
        cmd_str = f"npx agent-browser {subprocess.list2cmdline(final_args)}"
        try:
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                return f"❌ Browser Error (code {result.returncode}):\n{err}"
            
            out = result.stdout.strip()
            return out if out else "✅ 执行成功 (无输出)"
            
        except subprocess.TimeoutExpired:
            return "❌ Browser Error: 执行超时 (超过 60 秒)"
        except Exception as e:
            return f"❌ Browser System Error: {e}"

    @skills_manager.skill(
        name="browser_open",
        description="【网页专用】自动打开浏览器并进入指定的 URL。默认是 background 无头后台模式（静默运行不打扰用户）。如果你需要展示给用户看，请将 mode 设为 'headed'（可见的独立浏览器）或 'system'（强行拉起并接管系统的 Edge 或 Chrome，默认优先使用 Edge）。",
        parameters={
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要打开的网页地址"
                },
                "mode": {
                    "type": "string",
                    "description": "运行模式。\n- 'background': (默认) 完全后台无界面静皮运行，适合绝大部分不用给用户看的数据扒取和操作。\n- 'headed': 弹出一个可见的独立浏览器窗口。\n- 'system': 强行打开/连接用户电脑上的真实浏览器（优先寻找 Microsoft Edge，若无则使用 Google Chrome）。",
                    "enum": ["background", "headed", "system"],
                    "default": "background"
                }
            },
            "required": ["url"]
        },
        category="browser"
    )
    def browser_open(url: str, mode: str = "background") -> str:
        global _CURRENT_MODE
        if mode in ["background", "headed", "system"]:
            _CURRENT_MODE = mode
        return run_agent_browser(["open", url])


    @skills_manager.skill(
        name="browser_get_snapshot",
        description="【网页专用】获取当前网页的精简可访问性 DOM 树 (Accessibility Tree)。你会得到类似 `[1] @e2 button \"Submit\"` 的引用节点 (Ref)。只有拿到 Ref 以后你才能精确点击。",
        parameters={"properties": {}},
        category="browser"
    )
    def browser_get_snapshot() -> str:
        # -i flag limits output to interactive elements (buttons, inputs, links) to save tokens
        return run_agent_browser(["snapshot", "-i"])

    @skills_manager.skill(
        name="browser_interact",
        description="【网页专用】与网页上的元素进行精确交互。必须传入之前通过 browser_get_snapshot 获得的 Ref 标记（如 @e2）。",
        parameters={
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": ["click", "fill", "type", "hover", "focus", "check", "uncheck"]
                },
                "target": {
                    "type": "string",
                    "description": "目标元素，强烈推荐直接使用 Ref 解析号 (例如之前快照里看到的 @e5)。也可以兼容标准 CSS 选择器 (如 #submit-btn)。"
                },
                "value": {
                    "type": "string",
                    "description": "如果 action 是 fill 或 type，则必须提供需要填入的文本字符串，其他操作留空即可"
                }
            },
            "required": ["action", "target"]
        },
        category="browser"
    )
    def browser_interact(action: str, target: str, value: str = "") -> str:
        args = [action, target]
        if value and action in ["fill", "type"]:
            args.append(value)
        return run_agent_browser(args)

    @skills_manager.skill(
        name="browser_extract_text",
        description="【网页专用】从网页特定元素中提取文本内容。",
        parameters={
            "properties": {
                "target": {
                    "type": "string",
                    "description": "目标元素代码 (推荐 Ref 格式如 @e3)。"
                },
                "extract_type": {
                    "type": "string",
                    "description": "提取类型，支持 text (纯文本), html (内部HTML), value (输入框的值)。默认是 text。",
                    "enum": ["text", "html", "value"]
                }
            },
            "required": ["target"]
        },
        category="browser"
    )
    def browser_extract_text(target: str, extract_type: str = "text") -> str:
        return run_agent_browser(["get", extract_type, target])

    @skills_manager.skill(
        name="browser_scroll",
        description="【网页专用】在网页上滚动。支持按方向(up/down)滚动，或者直接滚动到特定元素(scrollintoview)使其可见。",
        parameters={
            "properties": {
                "direction_or_target": {
                    "type": "string",
                    "description": "如果向下滚动整页，填 down；向上滚填 up。如果要滚动到特定元素可见，这里填元素 Ref (如 @e5)。"
                }
            },
            "required": ["direction_or_target"]
        },
        category="browser"
    )
    def browser_scroll(direction_or_target: str) -> str:
        if direction_or_target.lower() in ["up", "down", "left", "right"]:
            return run_agent_browser(["scroll", direction_or_target])
        else:
            return run_agent_browser(["scrollintoview", direction_or_target])

    @skills_manager.skill(
        name="browser_wait",
        description="【网页专用】在继续动作之前等待。可以等待特定的网络状态，或者特定的时间(毫秒)。非常适合处理加载慢的重型网页。",
        parameters={
            "properties": {
                "wait_type": {
                    "type": "string",
                    "description": "等待策略。固定策略: 'networkidle' (等网络消停), 'load' (等页面加载)。或者填数字表示等待的毫秒数 (比如 '5000')。",
                }
            },
            "required": ["wait_type"]
        },
        category="browser"
    )
    def browser_wait(wait_type: str) -> str:
        if wait_type.isdigit():
            return run_agent_browser(["wait", wait_type])
        else:
            return run_agent_browser(["wait", "--load", wait_type])

    @skills_manager.skill(
        name="browser_navigate",
        description="【网页专用】控制网页历史记录：后退(back)、前进(forward)或刷新(reload)。",
        parameters={
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["back", "forward", "reload"]
                }
            },
            "required": ["action"]
        },
        category="browser"
    )
    def browser_navigate(action: str) -> str:
        return run_agent_browser([action])

    @skills_manager.skill(
        name="browser_check_state",
        description="【网页专用】检查某个网页元素的当前状态（是否可见、是否被勾选等）。",
        parameters={
            "properties": {
                "target": {
                    "type": "string",
                    "description": "要检查的元素 Ref (如 @e2)。"
                },
                "state": {
                    "type": "string",
                    "enum": ["visible", "enabled", "checked"]
                }
            },
            "required": ["target", "state"]
        },
        category="browser"
    )
    def browser_check_state(target: str, state: str) -> str:
        return run_agent_browser(["is", state, target])

    @skills_manager.skill(
        name="browser_close",
        description="【网页专用】在完全结束浏览器操作计划后，关闭后台的浏览器实例。释放所有系统资源。",
        parameters={"properties": {}},
        category="browser"
    )
    def browser_close() -> str:
        return run_agent_browser(["close"])
