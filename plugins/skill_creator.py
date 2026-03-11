"""
动态技能创造引擎 (Dynamic Skill Creator)

允许 AI 编写全新的 Python 插件代码并保存到 plugins/ 目录下，
配合主框架的热加载机制，实现 AI 技能的自我扩充（代码自举）。
"""

import os
import re
from pathlib import Path


def _get_plugins_dir() -> Path:
    """返回 plugins/ 目录的绝对路径，优先使用 APP_BASE_DIR 环境变量。"""
    base = os.environ.get("APP_BASE_DIR")
    if base:
        return Path(base) / "plugins"
    # fallback：此文件所在目录即 plugins/，其父目录即项目根
    return Path(__file__).resolve().parent


def register(skills_manager):
    @skills_manager.skill(
        name="create_plugin",
        description="【终极能力：自我进化】当你发现自己缺少某个能力（例如：需要查股票、需要解析特定内容、需要新的计算工具），你可以自己编写一个 Python 插件代码。框架会自动将其保存到 plugins 目录并立即热加载为你提供新的能力！",
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

        plugins_dir = _get_plugins_dir()
        plugins_dir.mkdir(parents=True, exist_ok=True)
        file_path = plugins_dir / f"{plugin_name}.py"

        # 覆写确认
        is_update = file_path.exists()

        # 简单清洗可能的 Markdown 格式干扰
        if code_content.startswith("```python"):
            code_content = code_content[9:]
        if code_content.startswith("```"):
            code_content = code_content[3:]
        if code_content.endswith("```"):
            code_content = code_content[:-3]

        # 写入文件
        try:
            file_path.write_text(code_content.strip() + "\n", encoding="utf-8")
        except Exception as e:
            return f"❌ 文件写入失败: {e}"

        action_word = "更新" if is_update else "创建"

        # 立即热加载：从 server.app_state 获取 plugin_manager
        reload_result = ""
        try:
            from core.server import app_state
            pm = app_state.get("plugin_manager")
            if pm:
                if is_update:
                    ok = pm.reload(plugin_name)
                else:
                    ok = pm.load(f"{plugin_name}.py") is not None
                reload_result = "✅ 热加载成功，新技能已立即可用！" if ok else "⚠️ 热加载失败，请重启程序后使用。"
            else:
                reload_result = "⚠️ 无法获取 PluginManager，请重启程序后使用。"
        except Exception as e:
            reload_result = f"⚠️ 热加载异常: {e}，请重启程序后使用。"

        return (
            f"🚀 成功！插件 `{plugin_name}.py` 已{action_word}并写入 {plugins_dir} 目录。\n"
            f"{reload_result}"
        )

    @skills_manager.skill(
        name="create_skill",
        description="【技能引擎】创建符合 Agent Skills 规范的声明式技能（SKILL.md）。相比 create_plugin 创建 Python 代码，此工具用来创建轻量级的工作流指令集、提示词集、特定外挂指南或业务规范。",
        parameters={
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能名称（如 'frontend-design', 'github-automation'），仅限小写字母、数字和连字符"
                },
                "description": {
                    "type": "string",
                    "description": "简短的一两句话描述，解释该技能的作用和应当何时触发调用"
                },
                "content": {
                    "type": "string",
                    "description": "SKILL.md 的完整正文内容（包含 Markdown 格式的完整操作步骤、示例等，无需包含 YAML 头部）"
                }
            },
            "required": ["skill_name", "description", "content"]
        },
        category="system"
    )
    def create_skill(skill_name: str, description: str, content: str) -> str:
        if not re.match(r"^[a-z0-9\-]+$", skill_name):
            return "❌ 技能名称不合法，只能包含小写字母、数字和连字符(-)。"
            
        # 遵循现有路径逻辑查找基目录
        try:
            base_dir = Path(os.environ.get("APP_BASE_DIR", Path(__file__).resolve().parent.parent))
        except Exception:
            base_dir = Path.cwd()
            
        # 根据 OpenAkita 惯例存放于 .agents/skills 或 skills 目录
        skills_dir = base_dir / ".agents" / "skills" / skill_name
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        md_path = skills_dir / "SKILL.md"
        is_update = md_path.exists()
        
        # 组装完整的 SKILL.md 内容
        yaml_frontmatter = f"---\nname: {skill_name}\ndescription: {description}\n---\n\n"
        full_content = yaml_frontmatter + content
        
        try:
            md_path.write_text(full_content, encoding="utf-8")
        except Exception as e:
            return f"❌ 文件写入失败: {e}"
        
        action = "更新" if is_update else "创建"
        return f"✅ 声明式技能 `{skill_name}` {action}成功！文件已存至: {md_path}\n💡 你现在可以通过 `get_skill_info` 自主读取它，下次加载外挂系统时该技能将在全局内有效。"


