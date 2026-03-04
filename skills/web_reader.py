"""
Web Reader: Fetch URL content and convert to Markdown.
"""

from pathlib import Path
from core.skills import SkillManager


def _ensure_dependencies():
    """Install dependencies if missing."""
    try:
        import httpx
        import markdownify
    except ImportError:
        import subprocess
        import sys
        print("  [WEB_READER] Installing dependencies: httpx, markdownify...")
        subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "markdownify", "-q"], check=False)


def register(manager: SkillManager) -> None:
    """Register web reading skills."""
    _ensure_dependencies()

    @manager.skill(
        name="web_read",
        description="抓取网页 URL 内容并转换为 Markdown。支持最大长度配置和代理。",
        parameters={
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页 URL"},
                "max_chars": {"type": "integer", "description": "返回的最大字符数，默认 4000"}
            },
            "required": ["url"]
        },
        ui_config=[
            {
                "key": "proxy_url",
                "label": "代理地址 (可选)",
                "type": "text",
                "default": "",
                "help": "例如: http://127.0.0.1:7890"
            }
        ],
        category="web"
    )
    def web_read(url: str, max_chars: int = None) -> str:
        try:
            import httpx
            from markdownify import markdownify as md
            
            # get config
            skill_def = manager.get("web_read")
            proxy_url = skill_def.config_values.get("proxy_url") if skill_def else ""
            proxies = {"http://": proxy_url, "https://": proxy_url} if proxy_url else None
            
            limit = int(max_chars or 4000)
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            with httpx.Client(follow_redirects=True, timeout=15.0, proxies=proxies) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
            
            markdown = md(html, heading_style="atx", strip=['script', 'style', 'nav', 'footer', 'header'])
            import re
            markdown = re.sub(r'\n{3,}', '\n\n', markdown).strip()
            
            if len(markdown) > limit:
                markdown = markdown[:limit] + f"\n\n...(内容已截断至 {limit} 字符)"
                
            return markdown if markdown else "未能提取到实质性内容。"
        except Exception as e:
            return f"抓取失败: {e}"
