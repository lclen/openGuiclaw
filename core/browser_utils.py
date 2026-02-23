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
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", # 增加 64 位原生路径
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
        # We explicitly open a blank valid data URL so that Playwright can find a page with a URL.
        # Otherwise, Playwright filters out pages with empty URLs, leading to "No page found" errors.
        # Using a minimal data URL as a blank page.
        #blank_url = "data:text/html,<html></html>"
        
        try:
            # 使用 cmd.exe /c start 来启动，这样可以确保浏览器以正常的 UI 进程形式启动，
            # 从而正确初始化带有有效 URL 的页面，否则 Playwright 的 CDP 客户端可能会因为找不到页面 (No page found) 而报错。
            # 同时 start 命令本身是非阻塞的，所以会立即返回并在后台独立运行。
            start_cmd = f'cmd.exe /c start "" "{browser_path}" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
            subprocess.Popen(
                start_cmd, 
                shell=True, 
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(2) 
        except Exception:
            pass 
