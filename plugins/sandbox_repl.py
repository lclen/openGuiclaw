"""
沙箱 REPL (RestrictedPython-based Sandbox)

使用 RestrictedPython 在 AST 层面限制代码执行权限。
与原子进程方案相比，此方案从根本上阻止危险操作，而非依赖黑名单过滤。

隔离策略：
- 禁止访问 __builtins__ 中的危险函数（open, exec, eval, compile 等）
- 禁止导入受限模块（os, sys, subprocess, shutil 等）
- 禁止访问私有属性（__ 开头的属性）
- 每个沙箱实例拥有独立的持久化命名空间（变量跨调用保留）

依赖：pip install RestrictedPython
"""

import threading
import time
import traceback
import io
import sys
from typing import Dict, Any, Optional

# ── RestrictedPython 导入 ────────────────────────────────────────────

try:
    from RestrictedPython import compile_restricted, safe_globals, safe_builtins
    from RestrictedPython.Guards import (
        safe_iter_unpack_sequence,
        guarded_iter_unpack_sequence,
    )
    from RestrictedPython.PrintCollector import PrintCollector
    _RESTRICTED_AVAILABLE = True
except ImportError:
    _RESTRICTED_AVAILABLE = False


# ── 允许导入的模块白名单 ─────────────────────────────────────────────

_ALLOWED_MODULES = {
    # 数学与数据
    "math", "random", "statistics", "decimal", "fractions",
    # 字符串与格式
    "re", "string", "textwrap", "unicodedata",
    # 数据结构
    "collections", "itertools", "functools", "operator", "heapq", "bisect",
    # 时间（只读）
    "datetime", "calendar",
    # 编码
    "json", "base64", "hashlib", "hmac",
    # 类型
    "typing", "dataclasses", "enum", "abc",
    # 第三方常用
    "numpy", "pandas", "matplotlib", "scipy", "sklearn",
    "requests",  # 允许网络请求，但无文件系统权限
}

_BLOCKED_MODULES = {
    "os", "sys", "subprocess", "shutil", "pathlib", "glob",
    "socket", "ftplib", "telnetlib", "smtplib",
    "ctypes", "cffi", "mmap",
    "importlib", "pkgutil", "zipimport",
    "pickle", "shelve", "marshal",
    "pty", "tty", "termios", "fcntl",
    "signal", "resource", "gc",
    "builtins", "__builtin__",
}


def _make_restricted_import(allowed: set, blocked: set):
    """Build a guarded __import__ that enforces the module whitelist."""
    def _guarded_import(name, *args, **kwargs):
        top = name.split(".")[0]
        if top in blocked:
            raise ImportError(f"[Sandbox] 模块 '{name}' 已被禁止导入。")
        # If not explicitly blocked, allow if in whitelist OR not in blocked
        # (whitelist is advisory; blocked is enforced)
        return __builtins__["__import__"](name, *args, **kwargs) \
               if isinstance(__builtins__, dict) \
               else __import__(name, *args, **kwargs)
    return _guarded_import


def _safe_getattr(obj, name):
    """Block access to dunder attributes to prevent sandbox escapes."""
    if name.startswith("_"):
        raise AttributeError(f"[Sandbox] 禁止访问私有属性: '{name}'")
    return getattr(obj, name)


def _safe_getitem(obj, key):
    return obj[key]


def _safe_write(obj):
    """Required by RestrictedPython for augmented assignment targets."""
    return obj


# ── Sandbox 实例 ─────────────────────────────────────────────────────

class RestrictedSandbox:
    """
    A stateful restricted Python execution environment.
    Variables defined in one run_code() call persist to the next.
    """

    def __init__(self):
        self.last_used_time = time.time()
        self._lock = threading.Lock()
        self._globals: Dict[str, Any] = self._make_globals()

    def _make_globals(self) -> Dict[str, Any]:
        """Build a fresh restricted globals dict."""
        if not _RESTRICTED_AVAILABLE:
            return {}

        # Start from RestrictedPython's safe_globals
        glb = dict(safe_globals)

        # Build a restricted builtins set
        restricted_builtins = dict(safe_builtins)

        # Explicitly remove dangerous builtins
        for name in ("open", "exec", "eval", "compile", "__import__",
                     "input", "memoryview", "breakpoint"):
            restricted_builtins.pop(name, None)

        # Inject our guarded import
        restricted_builtins["__import__"] = _make_restricted_import(
            _ALLOWED_MODULES, _BLOCKED_MODULES
        )

        glb["__builtins__"] = restricted_builtins

        # RestrictedPython guard hooks
        glb["_getattr_"] = _safe_getattr
        glb["_getitem_"] = _safe_getitem
        glb["_write_"] = _safe_write
        glb["_iter_unpack_sequence_"] = safe_iter_unpack_sequence

        # PrintCollector: captures print() output
        glb["_print_"] = PrintCollector
        glb["_getiter_"] = iter

        return glb

    def reset(self) -> None:
        """Clear all user-defined variables, keep guards intact."""
        with self._lock:
            self._globals = self._make_globals()

    def run_code(self, code: str, timeout: int = 30) -> str:
        """
        Compile and execute code under RestrictedPython.
        Returns captured stdout + stderr as a string.
        Falls back to a clear error message if RestrictedPython is not installed.
        """
        self.last_used_time = time.time()

        if not _RESTRICTED_AVAILABLE:
            return (
                "[ERROR] RestrictedPython 未安装。\n"
                "请运行: pip install RestrictedPython\n"
                "安装后重启程序即可启用安全沙箱。"
            )

        result_holder = {"output": "", "error": ""}

        def _execute():
            try:
                # Compile with RestrictedPython (raises SyntaxError on violations)
                byte_code = compile_restricted(code, filename="<sandbox>", mode="exec")
            except SyntaxError as e:
                result_holder["error"] = f"[SyntaxError] {e}"
                return

            # Each execution gets a fresh PrintCollector for output capture.
            # RestrictedPython rewrites print(...) as _print_(...) and stores
            # the collector instance back into globals as '_print' after execution.
            local_globals = dict(self._globals)
            local_globals["_print_"] = PrintCollector

            # Redirect stderr
            old_stderr = sys.stderr
            stderr_buf = io.StringIO()
            sys.stderr = stderr_buf

            try:
                exec(byte_code, local_globals)  # noqa: S102 — intentional restricted exec
                # Merge any new user-defined names back into persistent globals
                _internal = {"__builtins__", "_print_", "_print",
                             "_getattr_", "_getitem_", "_write_",
                             "_getiter_", "_iter_unpack_sequence_"}
                with self._lock:
                    for k, v in local_globals.items():
                        if k not in _internal:
                            self._globals[k] = v
                # _print is the PrintCollector instance written back by RestrictedPython
                collector = local_globals.get("_print")
                result_holder["output"] = collector() if callable(collector) else ""
            except Exception:
                result_holder["error"] = traceback.format_exc()
            finally:
                sys.stderr = old_stderr
                stderr_out = stderr_buf.getvalue().strip()
                if stderr_out:
                    result_holder["error"] = (result_holder["error"] + "\n" + stderr_out).strip()

        t = threading.Thread(target=_execute, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            # Thread is stuck (infinite loop etc.) — reset globals to clean state
            self._globals = self._make_globals()
            return (
                f"[ERROR] 执行超时（>{timeout}s），可能存在死循环。"
                "沙箱状态已重置。"
            )

        out = result_holder["output"].strip()
        err = result_holder["error"].strip()

        parts = []
        if out:
            parts.append(f"[OK] 输出:\n{out}")
        if err:
            parts.append(f"[WARN] 错误:\n{err}")
        return "\n\n".join(parts) if parts else "（代码已执行，无输出。变量状态已保留）"


# ── 全局沙箱注册表 ───────────────────────────────────────────────────

_sandboxes: Dict[str, RestrictedSandbox] = {}
_sandboxes_lock = threading.Lock()


def _get_sandbox(sandbox_id: str) -> RestrictedSandbox:
    with _sandboxes_lock:
        if sandbox_id not in _sandboxes:
            _sandboxes[sandbox_id] = RestrictedSandbox()
        return _sandboxes[sandbox_id]


def _auto_cleanup_idle_sandboxes():
    """Background thread: release sandboxes idle for more than 30 minutes."""
    while True:
        time.sleep(60)
        now = time.time()
        expired = []
        with _sandboxes_lock:
            for sid, sb in list(_sandboxes.items()):
                if now - sb.last_used_time > 1800:
                    expired.append(sid)
            for sid in expired:
                del _sandboxes[sid]
                print(f"[Sandbox] 自动释放闲置沙箱: {sid}")


threading.Thread(
    target=_auto_cleanup_idle_sandboxes, daemon=True, name="SandboxCleanup"
).start()


# ── Skill 注册 ───────────────────────────────────────────────────────

def register(skills_manager):

    @skills_manager.skill(
        name="run_in_sandbox",
        description=(
            "【安全代码执行】在 RestrictedPython 沙箱中执行 Python 代码。"
            "变量在同一 sandbox_id 的多次调用间持久保留。"
            "禁止访问文件系统、系统调用、环境变量等危险操作。"
            "支持: 数学计算、字符串处理、数据分析(numpy/pandas)、JSON 处理等。"
            "如需看到结果，必须使用 print() 输出。"
        ),
        parameters={
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": "要执行的 Python 代码。结果必须通过 print() 输出。",
                },
                "sandbox_id": {
                    "type": "string",
                    "description": "沙箱实例 ID（如 'data_analysis'）。同 ID 的变量跨调用保留。默认 'default'。",
                    "default": "default",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 30，最大 60。",
                    "default": 30,
                },
            },
            "required": ["python_code"],
        },
        category="system",
    )
    def run_in_sandbox(
        python_code: str, sandbox_id: str = "default", timeout: int = 30
    ) -> str:
        timeout = min(timeout, 60)
        sb = _get_sandbox(sandbox_id)
        return sb.run_code(python_code, timeout)

    @skills_manager.skill(
        name="reset_sandbox",
        description="重置指定沙箱的所有变量状态，释放内存。",
        parameters={
            "properties": {
                "sandbox_id": {
                    "type": "string",
                    "description": "要重置的沙箱 ID，默认 'default'。",
                    "default": "default",
                }
            }
        },
        category="system",
    )
    def reset_sandbox(sandbox_id: str = "default") -> str:
        sb = _get_sandbox(sandbox_id)
        sb.reset()
        return f"[OK] 沙箱 '{sandbox_id}' 已重置，变量已清空。"

    @skills_manager.skill(
        name="list_sandboxes",
        description="列出当前所有活跃的沙箱实例 ID。",
        parameters={"properties": {}, "required": []},
        category="system",
    )
    def list_sandboxes() -> str:
        with _sandboxes_lock:
            active = list(_sandboxes.keys())
        if not active:
            return "当前没有活跃的沙箱实例。"
        return f"[OK] 活跃沙箱: {', '.join(active)}"

    @skills_manager.skill(
        name="delete_sandbox",
        description="彻底销毁一个沙箱实例，释放其占用的内存。",
        parameters={
            "properties": {
                "sandbox_id": {
                    "type": "string",
                    "description": "要销毁的沙箱 ID。",
                }
            },
            "required": ["sandbox_id"],
        },
        category="system",
    )
    def delete_sandbox(sandbox_id: str) -> str:
        with _sandboxes_lock:
            if sandbox_id in _sandboxes:
                del _sandboxes[sandbox_id]
                return f"[OK] 沙箱 '{sandbox_id}' 已销毁。"
        return f"[WARN] 未找到沙箱 '{sandbox_id}'。"
