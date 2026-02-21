import os
import socket
import subprocess
import time

def ensure_browser_running(port: int = 9222):
    """
    检查指定端口上的 CDP 调试器是否已经启动。
    如果没有启动，则自动寻找系统中的浏览器（优先 Edge，后 Chrome）并以脱离模式拉起。
    """
    port_open = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            port_open = True
            
    if not port_open:
        # 优先级列表：Edge -> Chrome
        possible_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             # 补充常见的用户级安装路径
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        
        browser_path = None
        for path in possible_paths:
            if os.path.exists(path):
                browser_path = path
                break
        
        if not browser_path:
            return # 未找到可用浏览器，交给后续连接逻辑报错
            
        # 无论是 Edge 还是 Chrome，都统一使用隔离的调试环境，防止与用户的日常主浏览器进程冲突
        # 注意：如果不加 --user-data-dir，若系统后台已有 Edge 进程存活，Edge 会直接忽略调试端口重用旧进程，导致死锁崩溃。
        user_data_dir = r"D:\browser_debug"
        browser_cmd = rf'"{browser_path}" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
        
        try:
            # 使用完全脱离当前终端的方式运行
            creation_flags = 0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                browser_cmd, 
                shell=True, 
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags
            )
            time.sleep(2) 
        except Exception:
            pass 
