"""
动态技能创造引擎 (Dynamic Skill Creator)

允许 AI 编写全新的 Python 插件代码并保存到 plugins/ 目录下，
配合主框架的热加载机制，实现 AI 技能的自我扩充（代码自举）。
"""

import os
import re

def register(skills_manager):
    @skills_manager.skill(
        name="create_plugin",
        description="【终极能力：自我进化】当你发现自己缺少某个能力（例如：需要查股票、需要解析特定内容、需要新的计算工具），你可以自己编写一个 Python 插件代码。框架会自动将其保存到 plugins 目录并热加载为你提供新的能力！",
        parameters={
            "properties": {
                "plugin_name": {
                    "type": "string",
                    "description": "新插件的文件名（必须是合法的英文，如 'stock_price'，不需要加 .py）"
                },
                "code_content": {
                    "type": "string",
                    "description": "完整的 Python 代码内容。必须包含 `def register(skills_manager):` 入口，且内部必须使用 `@skills_manager.skill(name='...', description='...', parameters={'properties':{...}, 'required':[...]})` 的完整格式装饰器。千万不要省略参数！"
                }
            },
            "required": ["plugin_name", "code_content"]
        },
        category="system"
    )
    def create_plugin(plugin_name: str, code_content: str) -> str:
        # 安全验证文件名
        if not re.match(r"^[a-zA-Z0-9_]+$", plugin_name):
            return "❌ 文件名不合法，只能包含字母、数字和下划线。"
            
        file_path = os.path.join("plugins", f"{plugin_name}.py")
        
        # 覆写确认
        is_update = os.path.exists(file_path)
        
        # 写入文件
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                # 简单清洗可能的 Markdown 格式干扰
                if code_content.startswith("```python"):
                    code_content = code_content[9:]
                if code_content.endswith("```"):
                    code_content = code_content[:-3]
                    
                f.write(code_content.strip() + "\n")
        except Exception as e:
            return f"❌ 文件写入失败: {e}"
            
        action_word = "更新" if is_update else "创建"
        
        return (
            f"🚀 成功！插件 `{plugin_name}.py` 已{action_word}并写入 plugins/ 目录。\n"
            "系统即将（或已经）通过热加载监控将其实时挂载。\n"
            "请在后续对话中直接尝试使用你的新能力！"
        )
