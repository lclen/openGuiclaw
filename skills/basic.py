"""
Basic Skills: lightweight utility tools.
"""

import time
import platform
import os
from pathlib import Path
from core.skills import SkillManager


def register(manager: SkillManager) -> None:
    """Register basic utility skills."""

    @manager.skill(
        name="ask_user",
        description="向用户提供结构化的单选/多选选项，或者询问用户具体问题以获得交互式选择而非常规文本回复。如果你需要让用户从几个预设选项中做决定，必须调用此工具。",
        parameters={
            "properties": {
                "question": {"type": "string", "description": "在此输入你要问用户的文字描述"},
                "options": {
                    "type": "array",
                    "description": "选项列表。只有在此列出，前端才会显示交互按钮。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "机器可读的该选项唯一ID标识，必须"},
                            "label": {"type": "string", "description": "展示给用户看的纯中文字母文案，必须"}
                        },
                        "required": ["id", "label"]
                    }
                },
                "allow_multiple": {"type": "boolean", "description": "是否支持多选，默认为 false", "default": False}
            },
            "required": ["question", "options"],
        },
        category="interaction"
    )
    def ask_user(question: str, options: list, allow_multiple: bool = False) -> str:
        # Backend intercepts __ASK_USER_INTERRUPT__ so we return this magic string
        return "__ASK_USER_INTERRUPT__"

    @manager.skill(
        name="get_time",
        description="返回当前日期和时间。",
        parameters={"properties": {}, "required": []},
        category="utility",
    )
    def get_time() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S (%A)")

    @manager.skill(
        name="get_system_info",
        description="返回系统基本信息（OS、Python版本等）。",
        parameters={"properties": {}, "required": []},
        category="utility",
    )
    def get_system_info() -> str:
        return (
            f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"Node: {platform.node()}\n"
            f"Python: {platform.python_version()}"
        )

    @manager.skill(
        name="read_file",
        description="读取本地文件内容。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
            },
            "required": ["path"],
        },
        category="filesystem",
    )
    def read_file(path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"文件不存在: {path}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"读取失败: {e}"

    @manager.skill(
        name="write_file",
        description="将内容写入本地文件（覆盖写入）。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
            },
            "required": ["path", "content"],
        },
        category="filesystem",
    )
    def write_file(path: str, content: str) -> str:
        try:
            Path(path).write_text(content, encoding="utf-8")
            return f"[OK] 写入成功: {path}"
        except Exception as e:
            return f"写入失败: {e}"

    @manager.skill(
        name="list_dir",
        description="列出目录下的文件和子目录。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认当前目录"},
            },
            "required": [],
        },
        category="filesystem",
    )
    def list_dir(path: str = ".") -> str:
        p = Path(path)
        if not p.is_dir():
            return f"不是有效目录: {path}"
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for item in items:
            prefix = "📁" if item.is_dir() else "📄"
            lines.append(f"{prefix} {item.name}")
        return "\n".join(lines) if lines else "（空目录）"

    @manager.skill(
        name="update_user_profile",
        description="即时更新用户的长期档案与核心设定（客观实事与主观偏好）。当你得知了重要事实、偏好、习惯或约束限制时，不要等当天结束，而是立刻使用此工具让其生效。",
        parameters={
            "properties": {
                "layer": {"type": "string", "enum": ["objective", "subjective"], "description": "记忆分层。客观事实如名字/地点选objective；主观偏好/约束规则选subjective。"},
                "key": {"type": "string", "description": "属性键名（如：喜爱颜色，文件写入规范，语言偏好）"},
                "value": {"type": "string", "description": "偏好或属性的具体内容"}
            },
            "required": ["layer", "key", "value"],
        },
        category="system",
    )
    def update_user_profile(layer: str, key: str, value: str) -> str:
        try:
            from core.user_profile import UserProfileManager
            upm = UserProfileManager(data_dir="data")
            if layer == "subjective":
                upm.update_subjective(key, value)
            else:
                upm.update_objective(key, value)
            return f"[OK] 核心档案更新成功！[{layer}] {key}: {value}"
        except Exception as e:
            return f"档案更新失败: {e}"
