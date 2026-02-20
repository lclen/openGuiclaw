"""
沙箱 REPL (Stateful Python Sandbox)

为大模型提供一个持续存活的 Python 子进程。
模型可以在其中执行代码，定义的变量和导入的库在整个会话中保持持久化。
极大地增强了复杂数据处理和调试的能力。
"""

import subprocess
import threading
import queue
import sys
import os
import atexit

class PythonSandbox:
    def __init__(self):
        self.process = None
        self.output_queue = queue.Queue()
        self.error_queue = queue.Queue()
        self.is_running = False
        
        # 定义一个特殊的结束符，用于识别一次执行的输出完毕
        self.EXEC_EOF = "---SANDBOX_EXEC_EOF---"
        
        # 启动沙箱
        self.restart()
        atexit.register(self.close)

    def restart(self):
        self.close()
        self.is_running = True
        
        # 启动一个交互式的 Python 进程 (-i)
        # 禁用输出缓冲 (-u) 保证能及时读取
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        self.process = subprocess.Popen(
            [sys.executable, "-i", "-u"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0  # 无缓冲字节流
        )

        # 启动用于读取 stdout 和 stderr 的后台守护线程
        threading.Thread(target=self._read_stream, args=(self.process.stdout, self.output_queue), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(self.process.stderr, self.error_queue), daemon=True).start()

        # 暖机冲洗：消耗掉 Python 交互模式启动时的 banner 内容（如 Python 3.xx ... Type "help"...）
        # 发一条 pass 指令并等待结果，之后的调用输出才会干净
        import time as _t; _t.sleep(0.3)  # 给进程一点启动时间
        self.run_code("pass", timeout=8)

    def _decode_bytes(self, b: bytes) -> str:
        if not b:
            return ""
        try:
            return b.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return b.decode('gbk')
            except UnicodeDecodeError:
                return b.decode('utf-8', errors='replace')

    def _read_stream(self, stream, q):
        try:
            for line in stream:
                decoded = self._decode_bytes(line)
                q.put(decoded)
                if not self.is_running:
                    break
        except Exception:
            pass

    def run_code(self, code: str, timeout: int = 30) -> str:
        if not self.process or self.process.poll() is not None:
            self.restart()
            
        # 清空之前残留的队列
        while not self.output_queue.empty(): self.output_queue.get()
        while not self.error_queue.empty(): self.error_queue.get()

        # 为了捕获错误并防止卡死，我们将用户的代码包裹在一个 try-except 块中
        # 并在最后打印我们的专有 EOF 标识符
        wrapped_code = f"""
import traceback
import sys
__exec_globals = globals().copy()
try:
{self._indent_code(code)}
except Exception as __e:
    print(traceback.format_exc(), file=sys.stderr)
finally:
    print('{self.EXEC_EOF}')
    print('{self.EXEC_EOF}', file=sys.stderr)
"""
        
        try:
            self.process.stdin.write((wrapped_code + "\n").encode('utf-8'))
            self.process.stdin.flush()
        except Exception as e:
            self.restart()
            return f"[ERROR] 沙箱进程写入失败，已强制重启。原因: {e}"

        # 阻塞等待输出直到发现 EOF 或超时
        output_acc = []
        error_acc = []
        
        # 因为 stdout 和 stderr 是两条队列，我们在一定时间内不断轮询
        # 直到两边都收到了 EOF
        stdout_done = False
        stderr_done = False
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if stdout_done and stderr_done:
                break
                
            try:
                # 给一个极小的 block 时间防止死循环空转 CPU
                if not stdout_done:
                    line = self.output_queue.get(timeout=0.1)
                    if self.EXEC_EOF in line:
                        stdout_done = True
                    # 过滤掉交互式的提示符 '>>> ' 和 '... '
                    elif not (line.startswith('>>> ') or line.startswith('... ')):
                        output_acc.append(line)
            except queue.Empty:
                pass
                
            try:
                if not stderr_done:
                    line = self.error_queue.get(timeout=0.1)
                    if self.EXEC_EOF in line:
                        stderr_done = True
                    else:
                        error_acc.append(line)
            except queue.Empty:
                pass
        
        if not (stdout_done and stderr_done):
            self.restart()
            return f"[ERROR] 严重错误: 沙箱执行超过 {timeout} 秒超时！子进程可能已被死循环或阻塞操作挂起。沙箱已被系统强制重启以恢复可用性，之前保存的所有变量均已清空。"

        # 整理输出
        output_str = "".join(output_acc).strip()
        error_str = "".join(error_acc).strip()
        
        res = []
        if output_str:
            res.append(f"[OK] STDOUT:\n{output_str}")
        if error_str:
            res.append(f"[WARN] STDERR:\n{error_str}")
            
        if not res:
            return "（代码已执行，无输出返回。变量状态已保留）"
            
        return "\n\n".join(res)

    def _indent_code(self, code: str) -> str:
        return "\n".join("    " + line for line in code.split("\n"))

    def close(self):
        self.is_running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.process = None

# 全局单例沙箱
_sandbox = PythonSandbox()

def register(skills_manager):
    @skills_manager.skill(
        name="run_in_sandbox",
        description="【高级多步利器】在一个**持久存活**的 Python 沙箱中执行代码。与 execute_command 不同：你在沙箱里定义的变量 (如 a=10)、导入的模块 (如 import json)，在下一次调用这个工具时**仍然存在**！适合长流程爬虫、复杂数据分析或需要拆步 Debug 的情况。",
        parameters={
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": "要执行的纯 Python 代码块（不要带 ```python 标记，直接写代码）。如果需要看结果一定要 print 出来！"
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒）。默认30秒最高60秒。",
                    "default": 30
                }
            },
            "required": ["python_code"]
        },
        category="system"
    )
    def run_in_sandbox(python_code: str, timeout: int = 30) -> str:
        if timeout > 60:
            timeout = 60
            
        return _sandbox.run_code(python_code, timeout)
