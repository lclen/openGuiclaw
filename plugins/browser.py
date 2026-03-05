"""
Browser Automation Plugin

Integration with the `agent-browser` CLI for precise DOM-based web automation.

架构说明：
- background 模式：agent-browser 内置 daemon，命令间浏览器持久化，适合自动化抓取
- headed 模式：通过环境变量 AGENT_BROWSER_HEADED=true 启动可见窗口，daemon 同样持久化
- system 模式：--auto-connect 连接用户已打开的 Edge/Chrome（需先手动开启 CDP 调试端口）
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# 当前会话模式，影响后续所有命令的 flag
# 注意：这是进程级全局状态，单用户场景下安全；多用户并发时需改为 per-session
_CURRENT_MODE = "background"
_mode_lock = __import__("threading").Lock()


def register(skills_manager):

    async def run_agent_browser(args: list[str], timeout: int = 45) -> str:
        """统一执行 agent-browser 命令，根据当前模式注入对应 flag/环境变量。"""
        import asyncio

        with _mode_lock:
            current_mode = _CURRENT_MODE

        final_args = []
        extra_env = {}

        if current_mode == "system":
            final_args.append("--auto-connect")
            from core.browser_utils import ensure_browser_running
            ensure_browser_running(9222)
        elif current_mode == "headed":
            extra_env["AGENT_BROWSER_HEADED"] = "true"

        final_args.extend(args)
        cmd_str = f"npx --no-install agent-browser {subprocess.list2cmdline(final_args)}"
        logger.info(f"[Browser] Running: {cmd_str}")

        env = {**os.environ, **extra_env}

        proc_holder = [None]  # 用列表持有进程引用，方便 timeout 时 kill

        def _run_sync():
            proc = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            proc_holder[0] = proc
            try:
                out, err = proc.communicate(timeout=timeout)
                return proc.returncode, out, err
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()  # 清理管道
                return -1, b"", b"timeout"

        try:
            loop = asyncio.get_running_loop()
            returncode, out_bytes, err_bytes = await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync),
                timeout=timeout + 5,
            )

            def decode_output(b_str):
                try:
                    return b_str.decode("utf-8").strip()
                except UnicodeDecodeError:
                    return b_str.decode("gbk", errors="replace").strip()

            out = decode_output(out_bytes)
            err = decode_output(err_bytes)

            if returncode == -1:
                logger.error(f"[Browser] Timed out after {timeout}s: {cmd_str}")
                return f"❌ Browser Error: 执行超时 (超过 {timeout} 秒)\nCMD: {cmd_str}"

            if returncode != 0:
                detail = err or out or "(no output)"
                logger.error(f"[Browser] Failed (code {returncode}): {detail}")
                return f"❌ Browser Error (code {returncode}):\nCMD: {cmd_str}\nSTDERR: {err}\nSTDOUT: {out}"

            return out if out else "✅ 执行成功 (无输出)"

        except asyncio.TimeoutError:
            # asyncio 层超时：强制 kill 进程
            proc = proc_holder[0]
            if proc and proc.poll() is None:
                proc.kill()
            logger.error(f"[Browser] asyncio timeout after {timeout + 5}s: {cmd_str}")
            return f"❌ Browser Error: 执行超时 (超过 {timeout} 秒)\nCMD: {cmd_str}"
        except Exception as e:
            logger.error(f"[Browser] System error: {e}", exc_info=True)
            return f"❌ Browser System Error: {type(e).__name__}: {e}"

    # ── Skills ────────────────────────────────────────────────────────────────

    @skills_manager.skill(
        name="browser_open",
        description="【网页专用】自动打开浏览器并进入指定的 URL。默认是 background 无头后台模式（静默运行不打扰用户）。如果你需要展示给用户看，请将 mode 设为 'headed'（可见的独立浏览器）或 'system'（强行拉起并接管系统的 Edge 或 Chrome，默认优先使用 Edge）。",
        parameters={
            "properties": {
                "url": {"type": "string", "description": "要打开的网页地址"},
                "mode": {
                    "type": "string",
                    "description": (
                        "运行模式。\n"
                        "- 'background': (默认) 完全后台无界面静默运行，适合数据抓取和自动化操作。\n"
                        "- 'headed': 弹出可见的浏览器窗口，后续 snapshot/click 等操作仍可正常使用。\n"
                        "- 'system': 连接用户已打开的 Edge 或 Chrome（需开启 CDP 调试端口 9222）。"
                    ),
                    "enum": ["background", "headed", "system"],
                    "default": "background",
                },
            },
            "required": ["url"],
        },
        category="browser",
    )
    async def browser_open(url: str, mode: str = "background") -> str:
        import asyncio
        global _CURRENT_MODE
        if mode in ["background", "headed", "system"]:
            with _mode_lock:
                _CURRENT_MODE = mode
        
        result = await run_agent_browser(["open", url])
        
        # 验证浏览器是否真的启动成功：尝试获取页面标题
        if not result.startswith("❌"):
            await asyncio.sleep(2)  # 给浏览器 2 秒启动时间
            verify_result = await run_agent_browser(["eval", "document.title"], timeout=10)
            if verify_result.startswith("❌"):
                logger.warning(f"[Browser] 浏览器可能未成功启动，验证失败: {verify_result}")
                return f"⚠️ 浏览器命令已执行，但无法验证是否成功打开页面。\n原始结果: {result}\n验证失败: {verify_result}"
            else:
                logger.info(f"[Browser] 浏览器启动验证成功，页面标题: {verify_result[:50]}")
                return f"✅ 浏览器已成功打开 {url}\n页面标题: {verify_result}"
        
        return result

    @skills_manager.skill(
        name="browser_get_snapshot",
        description="【网页专用】获取当前网页的精简可访问性 DOM 树 (Accessibility Tree)。你会得到类似 `[1] @e2 button \"Submit\"` 的引用节点 (Ref)。只有拿到 Ref 以后你才能精确点击。",
        parameters={"properties": {}},
        category="browser",
    )
    async def browser_get_snapshot() -> str:
        return await run_agent_browser(["snapshot", "-i"])

    @skills_manager.skill(
        name="browser_interact",
        description="【网页专用】与网页上的元素进行精确交互。必须传入之前通过 browser_get_snapshot 获得的 Ref 标记（如 @e2）。",
        parameters={
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型",
                    "enum": ["click", "fill", "type", "hover", "focus", "check", "uncheck"],
                },
                "target": {
                    "type": "string",
                    "description": "目标元素，推荐使用 Ref（如 @e5），也支持 CSS 选择器（如 #submit-btn）。",
                },
                "value": {
                    "type": "string",
                    "description": "fill 或 type 操作时必填，其他操作留空。",
                },
            },
            "required": ["action", "target"],
        },
        category="browser",
    )
    async def browser_interact(action: str, target: str, value: str = "") -> str:
        args = [action, target]
        if value and action in ["fill", "type"]:
            args.append(value)
        return await run_agent_browser(args)

    @skills_manager.skill(
        name="browser_extract_text",
        description="【网页专用】从网页特定元素中提取文本内容。",
        parameters={
            "properties": {
                "target": {"type": "string", "description": "目标元素 Ref（如 @e3）或 CSS 选择器。"},
                "extract_type": {
                    "type": "string",
                    "description": "提取类型：text（纯文本）、html（内部HTML）、value（输入框的值）。默认 text。",
                    "enum": ["text", "html", "value"],
                },
            },
            "required": ["target"],
        },
        category="browser",
    )
    async def browser_extract_text(target: str, extract_type: str = "text") -> str:
        return await run_agent_browser(["get", extract_type, target])

    @skills_manager.skill(
        name="browser_scroll",
        description="【网页专用】在网页上滚动。支持按方向（up/down/left/right）滚动，或滚动到特定元素使其可见。",
        parameters={
            "properties": {
                "direction_or_target": {
                    "type": "string",
                    "description": "方向（up/down/left/right）或元素 Ref（如 @e5，滚动到该元素可见）。",
                }
            },
            "required": ["direction_or_target"],
        },
        category="browser",
    )
    async def browser_scroll(direction_or_target: str) -> str:
        if direction_or_target.lower() in ["up", "down", "left", "right"]:
            return await run_agent_browser(["scroll", direction_or_target])
        return await run_agent_browser(["scrollintoview", direction_or_target])

    @skills_manager.skill(
        name="browser_wait",
        description="【网页专用】等待页面加载完成或指定时间。适合处理加载慢的页面。",
        parameters={
            "properties": {
                "wait_type": {
                    "type": "string",
                    "description": (
                        "等待策略：\n"
                        "- 'networkidle'：等待网络请求停止（页面完全加载）\n"
                        "- 'load'：等待 load 事件触发\n"
                        "- 数字字符串（如 '3000'）：等待指定毫秒数"
                    ),
                }
            },
            "required": ["wait_type"],
        },
        category="browser",
    )
    async def browser_wait(wait_type: str) -> str:
        # 纯数字：等待毫秒；其他字符串：作为 load 状态传给 --load flag
        if wait_type.strip().isdigit():
            return await run_agent_browser(["wait", wait_type], timeout=int(wait_type) // 1000 + 15)
        return await run_agent_browser(["wait", "--load", wait_type], timeout=60)

    @skills_manager.skill(
        name="browser_navigate",
        description="【网页专用】控制网页历史记录：后退（back）、前进（forward）或刷新（reload）。",
        parameters={
            "properties": {
                "action": {"type": "string", "enum": ["back", "forward", "reload"]}
            },
            "required": ["action"],
        },
        category="browser",
    )
    async def browser_navigate(action: str) -> str:
        return await run_agent_browser([action])

    @skills_manager.skill(
        name="browser_check_state",
        description="【网页专用】检查某个网页元素的当前状态（是否可见、是否启用、是否被勾选）。",
        parameters={
            "properties": {
                "target": {"type": "string", "description": "要检查的元素 Ref（如 @e2）。"},
                "state": {"type": "string", "enum": ["visible", "enabled", "checked"]},
            },
            "required": ["target", "state"],
        },
        category="browser",
    )
    async def browser_check_state(target: str, state: str) -> str:
        return await run_agent_browser(["is", state, target])

    @skills_manager.skill(
        name="browser_screenshot",
        description="【网页专用】截取当前网页的截图，返回保存路径。可选全页截图。",
        parameters={
            "properties": {
                "full_page": {
                    "type": "boolean",
                    "description": "是否截取完整页面（包含滚动区域），默认 false 只截可视区域。",
                }
            },
            "required": [],
        },
        category="browser",
    )
    async def browser_screenshot(full_page: bool = False) -> str:
        args = ["screenshot"]
        if full_page:
            args.append("--full")
        return await run_agent_browser(args)

    @skills_manager.skill(
        name="browser_eval",
        description="【网页专用】在当前页面执行任意 JavaScript 代码，返回执行结果。",
        parameters={
            "properties": {
                "js": {"type": "string", "description": "要执行的 JavaScript 代码字符串。"}
            },
            "required": ["js"],
        },
        category="browser",
    )
    async def browser_eval(js: str) -> str:
        return await run_agent_browser(["eval", js])

    @skills_manager.skill(
        name="browser_close",
        description="【网页专用】关闭浏览器 daemon 并释放所有资源。完成所有浏览器操作后调用。",
        parameters={"properties": {}},
        category="browser",
    )
    async def browser_close() -> str:
        global _CURRENT_MODE
        result = await run_agent_browser(["close"])
        with _mode_lock:
            _CURRENT_MODE = "background"
        return result
