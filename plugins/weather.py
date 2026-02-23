"""
示例插件：天气查询（演示插件系统用）

将此文件放在 plugins/ 目录下即可自动加载。
"""

PLUGIN_INFO = {
    "name": "天气查询",
    "description": "通过 wttr.in 查询城市天气（无需 API Key）",
    "version": "1.0.0",
    "author": "plugin-example",
}


def register(manager):
    """必须实现此函数，manager 是 SkillManager 实例。"""

    @manager.skill(
        name="get_weather",
        description="查询指定城市的当前天气。直接返回文本天气报告。",
        parameters={
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名，例如 'Beijing'、'Shanghai'、'Tokyo'",
                }
            },
            "required": ["city"],
        },
        category="weather",
    )
    def get_weather(city: str) -> str:
        try:
            import urllib.request
            import urllib.parse
            city_encoded = urllib.parse.quote(city)
            url = f"https://wttr.in/{city_encoded}?format=3&lang=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read().decode("utf-8").strip()
        except Exception as e:
            return f"天气查询失败: {e}"
