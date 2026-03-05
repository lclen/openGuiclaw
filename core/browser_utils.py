import os
import socket
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

def ensure_browser_running(port: int = 9222):
    """
    检查指定端口上的 CDP 调试器是否已经启动。
    如果没有启动，则自动寻找系统中的浏览器（优先 Edge，后 Chrome）并以脱离模式拉起。
    """
    port_open = False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        result = s.connect_ex(('127.0.0.1', port))
        logger.info(f"[BrowserUtils] CDP port {port} check: connect_ex={result}")
        if result == 0:
            port_open = True

    logger.info(f"[BrowserUtils] CDP port {port} open: {port_open}")

    if not port_open:
        # 优先级列表：Edge -> Chrome
        possible_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]

        browser_path = None
        for path in possible_paths:
            exists = os.path.exists(path)
            logger.info(f"[BrowserUtils] Checking browser path: {path} -> {exists}")
            if exists:
                browser_path = path
                break

        if not browser_path:
            logger.error("[BrowserUtils] No browser found in any of the expected paths")
            return

        logger.info(f"[BrowserUtils] Launching browser: {browser_path}")
        user_data_dir = os.path.join(os.path.expandvars("%TEMP%"), "browser_debug_cdp")
        start_cmd = f'cmd.exe /c start "" "{browser_path}" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
        logger.debug(f"[BrowserUtils] Launch command: {start_cmd}")

        try:
            proc = subprocess.Popen(
                start_cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"[BrowserUtils] Browser process spawned (pid={proc.pid}), waiting 2s...")
            time.sleep(2)

            # Verify port opened after launch
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.settimeout(1.0)
                post_result = s2.connect_ex(('127.0.0.1', port))
            logger.info(f"[BrowserUtils] CDP port {port} after launch: {'open' if post_result == 0 else f'still closed (code={post_result})'}")
        except Exception as e:
            logger.error(f"[BrowserUtils] Failed to launch browser: {e}", exc_info=True)
