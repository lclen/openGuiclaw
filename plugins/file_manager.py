"""
Enhanced File Manager: Professional file system operations.
"""

import os
import shutil
from pathlib import Path
from core.skills import SkillManager


def register(manager: SkillManager) -> None:
    """Register enhanced file management skills."""

    @manager.skill(
        name="read_file",
        description="读取本地文件的内容。支持文本编码处理。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "文件绝对或相对路径"},
            },
            "required": ["path"],
        },
        category="filesystem",
    )
    def read_file(path: str) -> str:
        p = Path(path)
        if not p.exists(): return f"错误: 文件不存在 {path}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"读取失败: {e}"

    @manager.skill(
        name="write_file",
        description="将指定内容写入文件（直接覆盖）。如果父目录不存在会自动创建。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "content": {"type": "string", "description": "要写入的文本内容"},
            },
            "required": ["path", "content"],
        },
        category="filesystem",
    )
    def write_file(path: str, content: str) -> str:
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"[OK] 成功写入: {path}"
        except Exception as e:
            return f"写入异常: {e}"

    @manager.skill(
        name="list_dir",
        description="列出指定目录下的文件和子目录，并返回类型标识。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "目录路径，默认为当前目录"},
            },
            "required": [],
        },
        category="filesystem",
    )
    def list_dir(path: str = ".") -> str:
        p = Path(path)
        if not p.exists() or not p.is_dir(): return f"错误: 路径无效 {path}"
        try:
            items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = []
            for item in items:
                icon = "📁" if item.is_dir() else "📄"
                lines.append(f"{icon} {item.name}")
            return "\n".join(lines) if lines else "(空目录)"
        except Exception as e:
            return f"列目录失败: {e}"

    @manager.skill(
        name="move_path",
        description="移动或重命名文件或目录。",
        parameters={
            "properties": {
                "src": {"type": "string", "description": "源路径"},
                "dst": {"type": "string", "description": "目标路径"},
            },
            "required": ["src", "dst"],
        },
        category="filesystem",
    )
    def move_path(src: str, dst: str) -> str:
        try:
            shutil.move(src, dst)
            return f"[OK] 已将 {src} 移动到 {dst}"
        except Exception as e:
            return f"移动失败: {e}"

    @manager.skill(
        name="delete_path",
        description="【慎用】删除文件或整个目录（递归删除）。",
        parameters={
            "properties": {
                "path": {"type": "string", "description": "要删除的路径"},
            },
            "required": ["path"],
        },
        category="filesystem",
    )
    def delete_path(path: str) -> str:
        p = Path(path)
        if not p.exists(): return f"跳过: 路径不存在 {path}"
        try:
            if p.is_file(): p.unlink()
            else: shutil.rmtree(path)
            return f"[OK] 已成功删除: {path}"
        except Exception as e:
            return f"删除失败: {e}"

    @manager.skill(
        name="search_files",
        description="在指定目录中搜索包含特定关键字的文件名，可选过滤后缀。",
        parameters={
            "properties": {
                "root": {"type": "string", "description": "起始目录"},
                "pattern": {"type": "string", "description": "文件名匹配模式（支持 * 通配符，如 *.py）"},
            },
            "required": ["pattern"],
        },
        category="filesystem",
    )
    def search_files(pattern: str, root: str = ".") -> str:
        try:
            results = list(Path(root).rglob(pattern))
            if not results: return "未找到匹配项。"
            return "\n".join([str(r) for r in results[:50]]) # Limit to 50
        except Exception as e:
            return f"搜索异常: {e}"
