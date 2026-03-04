"""
System Tools: Shell command execution and process info.
"""

import subprocess
import os
from core.skills import SkillManager


def register(manager: SkillManager) -> None:
    """Register system and shell skills."""

    @manager.skill(
        name="execute_command",
        description="【慎用】在系统终端中执行 Shell 命令。可以用于安装依赖、检查系统状态、运行脚本等。注意禁止执行具有破坏性的删除或格式化命令。",
        parameters={
            "properties": {
                "command": {"type": "string", "description": "要执行的 Shell 命令（如: pip install x, whoami, ls）"},
                "cwd": {"type": "string", "description": "工作目录，默认为当前目录"}
            },
            "required": ["command"]
        },
        category="system"
    )
    def execute_command(command: str, cwd: str = ".") -> str:
        try:
            # Basic security check
            blacklist = ["rm -rf /", "format ", "mkfs", "dd if="]
            if any(b in command for b in blacklist):
                return "错误: 该命令包含高风险操作，已拦截。"
                
            res = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=30
            )
            
            output = res.stdout if res.stdout else ""
            if res.stderr:
                output += f"\n[Error/Stderr]:\n{res.stderr}"
                
            return output if output else f"命令执行完成 (退出码: {res.returncode})"
        except subprocess.TimeoutExpired:
            return "错误: 命令执行超时（超过 30 秒）。"
        except Exception as e:
            return f"执行失败: {e}"
