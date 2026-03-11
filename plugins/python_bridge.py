"""
Python Bridge Plugin

Provides a complete, unconstrained Python execution environment by spawning
a child process. This complements `sandbox_repl` by allowing:
1. File system I/O
2. Complex library imports (e.g., OpenCV, Pandas, ML frameworks)
3. Heavy compute without blocking the main Agent thread

Note: This runs with the same privileges as the user running openGuiclaw.
"""

import os
import sys
import tempfile
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_python_executable() -> str:
    """
    Attempt to find the most appropriate Python executable.
    In openGuiclaw, sys.executable is usually the venv python if launched via launcher.py.
    """
    return sys.executable

def register(skills_manager):
    @skills_manager.skill(
        name="execute_python_script",
        description="【慎用】在完全无限制的 Python 环境中直接运行代码。如果你由于 RestrictedPython 的限制（如无法导入某个包、无法读取文件、无法进行系统级调用）而导致任务报错，请立刻改用此工具。它会在独立的子进程中完整地执行你的代码片段，适合处理数据分析、文件持久化、图像处理或网络请求。注意：这是高权限执行，请勿构造删除核心文件的代码。",
        parameters={
            "properties": {
                "script": {
                    "type": "string",
                    "description": "完整的 Python 代码字符串，你需要在一张空白的画布上书写脚本，并在代码末尾使用 print() 输出你需要的结果，因为只有 stdout 能够被收集回来。"
                },
                "timeout": {
                    "type": "integer",
                    "description": "脚本运行最大超时时间，单位为秒。可以防止死循环。默认为 60 秒。",
                    "default": 60
                }
            },
            "required": ["script"]
        },
        category="system"
    )
    def execute_python_script(script: str, timeout: int = 60) -> str:
        if not script.strip():
            return "❌ 没有提供任何 Python 代码。"
        
        # Write to temporary file
        fd, temp_path = tempfile.mkstemp(suffix=".py", prefix="openguiclaw_bridge_")
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(script)
            
            python_exe = _get_python_executable()
            logger.info(f"[PythonBridge] Executing temp script: {temp_path} using {python_exe} (Timeout: {timeout}s)")
            
            # Prepare subprocess kwargs
            kwargs = {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace"
            }
            if os.name == 'nt':
                # Avoid popping up terminal windows on Windows
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            
            try:
                # Spawn subprocess
                res = subprocess.run([python_exe, temp_path], timeout=timeout, **kwargs)
                
                output = []
                if res.stdout:
                    output.append(res.stdout)
                if res.stderr:
                    output.append(f"\n[Stderr / Warnings]:\n{res.stderr}")
                
                if res.returncode == 0:
                    result_text = "".join(output).strip()
                    if not result_text:
                        return "✅ 脚本执行成功完毕，但没有任何打印输出（stdout 为空）。如果你需要查看结果，请在脚本中使用 print()。"
                    return f"✅ 脚本执行成功:\n\n{result_text}"
                else:
                    return f"❌ 脚本执行失败 (退出码 {res.returncode}):\n\n{''.join(output)}"
                    
            except subprocess.TimeoutExpired:
                return f"❌ 脚本执行超时 (已超过设定上限 {timeout} 秒)，由于死循环或复杂计算导致进程被强制终止。"
            except Exception as e:
                logger.error(f"[PythonBridge] Unexpected Error: {e}", exc_info=True)
                return f"❌ 启动进程时发生内部异常: {str(e)}"
                
        finally:
            # Clean up temp file
            try:
                os.remove(temp_path)
            except Exception as e:
                logger.warning(f"[PythonBridge] Failed to clean up temp file {temp_path}: {e}")
