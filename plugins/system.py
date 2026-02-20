"""
终端命令执行引擎 (Terminal Command Execution Engine)

允许 AI 助理在本地宿主机器上执行安全的 Shell 命令。
具有超时保护（默认 30 秒）和输出截断（防止返回过大冲破 Context）。
"""

import subprocess
import os

def register(skills_manager):
    @skills_manager.skill(
        name="execute_command",
        description="【非常强大】在本地机器的终端中执行给定的 Shell 环境命令（如 python, pip, git, ls, dir 等）。拥有超时保护。当用户遇到环境问题或要求你运行代码时首先使用此工具！",
        parameters={
            "properties": {
                "command": {"type": "string", "description": "要执行的完整的 Shell 命令内容，例如 'pip install requests'，'python --version'"},
                "timeout": {"type": "integer", "description": "超时时间（秒）。默认30，最大不得超过60秒，防止死循环阻塞主线程。", "default": 30}
            },
            "required": ["command"]
        },
        category="system"
    )
    def execute_command(command: str, timeout: int = 30) -> str:
        # 安全限制：防止过长超时导致整个 AI 休克
        if timeout > 60:
            timeout = 60
        
        try:
            # shell=True 允许使用管道、重定向、内部命令等
            # capture_output 捕获原始字节流，以便我们手动处理乱码
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout
            )
            
            def _decode_bytes(b: bytes) -> str:
                if not b:
                    return ""
                try:
                    return b.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        return b.decode('gbk')  # Windows 默认常见编码
                    except UnicodeDecodeError:
                        return b.decode('utf-8', errors='replace')
            
            stdout_str = _decode_bytes(result.stdout).strip()
            stderr_str = _decode_bytes(result.stderr).strip()

            # 组合 stdout 和 stderr
            output_parts = []
            if stdout_str:
                output_parts.append(f"✅ [标准输出 STDOUT]:\n{stdout_str}")
            if stderr_str:
                output_parts.append(f"⚠️ [标准错误 STDERR]:\n{stderr_str}")
            
            if not output_parts:
                return f"命令 '{command}' 已执行完毕 (返回码: {result.returncode})，无输出。"
                
            full_output = f"返回码: {result.returncode}\n\n" + "\n\n".join(output_parts)
            
            # 为防止输出太大冲爆 Token，强制截断
            max_len = 2000
            if len(full_output) > max_len:
                full_output = full_output[:max_len] + f"\n... (输出已在 {max_len} 字符处被截断，防止超出限制)"
                
            return full_output
            
        except subprocess.TimeoutExpired:
            return f"❌ 错误: 命令 '{command}' 运行超过了给定的 {timeout} 秒超时时间，已被系统强制中止。这可能是因为它是一个交互式或无穷无尽的进程（如 'top'）。"
        except Exception as e:
            return f"❌ 严重错误: 无法执行命令 '{command}'，系统错误: {e}"
