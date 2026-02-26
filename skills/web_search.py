"""
Web skills: web_fetch
Fetches and extracts readable text from a URL.

The LLM's built-in search (enable_search) handles free-text queries.
This skill handles explicit URL fetching so the model can "open" a page.
"""

from core.skills import SkillManager


def register(manager: SkillManager) -> None:

    @manager.skill(
        name="web_fetch",
        description=(
            "抓取指定 URL 网页的正文文本内容，返回纯文字。"
            "当你已经知道具体网址、需要阅读某个页面详细内容时使用。"
        ),
        parameters={
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页 URL，必须以 http:// 或 https:// 开头",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "返回的最大字符数，默认 3000，最大 8000",
                },
            },
            "required": ["url"],
        },
        ui_config=[
            {
                "key": "default_max_chars",
                "label": "默认最大提取字符数",
                "type": "text",
                "default": "3000",
                "help": "如果没有传入 max_chars，则使用该配置值"
            },
            {
                "key": "proxy_url",
                "label": "代理地址 (可选)",
                "type": "text",
                "default": "",
                "help": "例如: http://127.0.0.1:7890"
            }
        ],
        category="web",
    )
    def web_fetch(url: str, max_chars: int = None) -> str:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return "❌ 缺少依赖：请执行 `pip install requests beautifulsoup4`"

        # retrieve config
        agent = getattr(manager, "_agent", None) # manager generally not holding agent explicitly, but we registered it, so let's fish it out from _registry
        skill_def = manager.get("web_fetch")
        if skill_def:
            config = skill_def.config_values
            default_max = int(config.get("default_max_chars") or 3000)
            proxy_url = config.get("proxy_url") or ""
        else:
            default_max = 3000
            proxy_url = ""

        max_chars = min(int(max_chars or default_max), 8000)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        try:
            resp = requests.get(url, headers=headers, proxies=proxies, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding  # handle charset correctly
        except requests.exceptions.Timeout:
            return f"❌ 请求超时（15s）: {url}"
        except requests.exceptions.HTTPError as e:
            return f"❌ HTTP 错误 {e.response.status_code}: {url}"
        except Exception as e:
            return f"❌ 请求失败: {e}"

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "noscript", "svg", "img"]):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Collapse blank lines
        lines = [ln for ln in text.splitlines() if ln.strip()]
        cleaned = "\n".join(lines)

        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + f"\n\n...[内容过长, 已截断至 {max_chars} 字符]"

        if not cleaned:
            return "⚠️ 页面内容为空或无法解析。"

        return f"[页面内容: {url}]\n\n{cleaned}"
