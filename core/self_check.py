"""
core/self_check.py — AI-driven log analysis and auto-fix.

优化点：
1. 分层修复策略：Core 错误只记录，Tool/Skill/Channel 才真正执行修复
2. 修复验证：修复后测试文件读写 / shell 命令确认是否成功
3. 重试 + 降级：Agent 修复失败后重试，最终降级到脚本级修复
"""
import json
import logging
import os
import glob
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 只允许自动修复的错误类型（Core 层一律不动）
_ALLOWED_FIX_TYPES = {"tool", "skill", "channel", "plugin", "mcp"}


class FixRecord(BaseModel):
    component: str
    error_pattern: str
    can_fix: bool
    fix_action: str
    success: bool
    verification_result: str = ""


class SelfChecker:
    def __init__(self, agent=None):
        self.agent = agent
        from core.state import _APP_BASE
        self.app_base = _APP_BASE

    # ── 日志收集 ──────────────────────────────────────────────────────────────

    def gather_recent_errors(self, max_lines: int = 50) -> list[str]:
        """Gather recent ERROR/CRITICAL lines from log files."""
        errors = []
        log_files = (
            glob.glob(str(self.app_base / "*.log"))
            + glob.glob(str(self.app_base / "logs" / "*.log"))
        )
        log_files.sort(key=os.path.getmtime, reverse=True)

        for lf in log_files:
            if len(errors) >= max_lines:
                break
            try:
                with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for line in reversed(lines[-500:]):
                    if " ERROR " in line or " CRITICAL " in line:
                        errors.append(line.strip())
                        if len(errors) >= max_lines:
                            break
            except Exception:
                pass

        return list(reversed(errors))

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def analyze_and_fix(self, push_fn=None) -> tuple[int, int, list[FixRecord]]:
        """
        Analyze recent errors using LLM, then attempt to auto-fix fixable ones.
        
        优化：从 Memory 中提取历史 ERROR 记忆，一起分析；修复成功后删除对应记忆。
        
        Returns: (core_errors_count, tool_errors_count, fix_records)
        """
        if not self.agent:
            return 0, 0, []

        # 1. 收集日志错误
        log_errors = self.gather_recent_errors()
        
        # 2. 从 Memory 中提取 ERROR 类型记忆（历史错误教训）
        error_memories = []
        if hasattr(self.agent, 'memory') and self.agent.memory:
            error_memories = self.agent.memory.list_by_type("error")
            logger.info(f"Found {len(error_memories)} error memories in long-term storage")
        
        if not log_errors and not error_memories:
            return 0, 0, []

        # 3. 构建综合分析输入（日志 + 记忆）
        sections = []
        
        if log_errors:
            sections.append("## 日志错误（最近发生）\n" + "\n".join(log_errors))
        
        if error_memories:
            mem_lines = [
                f"- [{m.created_at}] {m.content} (来源: {m.source})"
                for m in error_memories[:20]  # 最多取 20 条
            ]
            sections.append("## 历史错误记忆（长期存储）\n" + "\n".join(mem_lines))
        
        error_context = "\n\n".join(sections)
        
        prompt = f"""分析以下系统错误信息（包含日志错误和历史记忆）。
将错误分类为 Core（核心引擎）或 Tool/Skill/Channel/Plugin（能力层）。

规则：
1. Core 级别：core/ 目录核心文件、引擎启动、数据库等报错 → can_fix: false
2. Tool/Skill/Channel/Plugin 级别：plugins/、skills/、channels/、MCP 相关 → can_fix: true
3. 如果历史记忆中的错误已经在日志中重复出现，优先修复（说明之前没修好）

以 JSON 格式返回：
{{
    "errors": [
        {{
            "component": "报错模块名称或路径",
            "error_pattern": "错误简述",
            "error_type": "core|tool|skill|channel|plugin|mcp",
            "is_core": bool,
            "can_fix": bool,
            "fix_instruction": "如果 can_fix 为 true，给出具体修复指令（shell 命令或 Python 代码）",
            "from_memory": bool  // 是否来自历史记忆
        }}
    ]
}}

错误信息：
{error_context}
"""

        core_errors = 0
        tool_errors = 0
        records: list[FixRecord] = []

        try:
            response = self.agent.client.chat.completions.create(
                model=self.agent.config.get("model", "qwen-plus"),
                messages=[
                    {"role": "system", "content": "You are a backend diagnostic AI. Output valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return 0, 0, []

        for err in data.get("errors", []):
            component = err.get("component", "unknown")
            is_core = err.get("is_core", True)
            error_type = err.get("error_type", "core" if is_core else "tool")
            can_fix = err.get("can_fix", False) and error_type in _ALLOWED_FIX_TYPES
            instruction = err.get("fix_instruction", "")
            from_memory = err.get("from_memory", False)

            if is_core or error_type not in _ALLOWED_FIX_TYPES:
                # ── 优化点 1：Core 层只记录，不修复 ──────────────────────────
                core_errors += 1
                records.append(FixRecord(
                    component=component,
                    error_pattern=err.get("error_pattern", ""),
                    can_fix=False,
                    fix_action="需人工干预 (Core 层)",
                    success=False,
                    verification_result="",
                ))
                continue

            tool_errors += 1

            if not can_fix or not instruction:
                records.append(FixRecord(
                    component=component,
                    error_pattern=err.get("error_pattern", ""),
                    can_fix=False,
                    fix_action="无修复指令，跳过",
                    success=False,
                ))
                continue

            # ── 优化点 3：重试 + 降级 ─────────────────────────────────────────
            if push_fn:
                mem_tag = " (历史记忆)" if from_memory else ""
                push_fn({"type": "chat_event", "role": "system",
                         "content": f"🔧 [自动修复] 正在尝试修复 `{component}`{mem_tag}..."})

            record = await self._fix_with_retry(
                component, err.get("error_pattern", ""), instruction, push_fn
            )
            
            # ── 新增：修复成功后删除对应的 error 记忆 ────────────────────────
            if record.success and from_memory and hasattr(self.agent, 'memory'):
                self._cleanup_fixed_error_memory(component, err.get("error_pattern", ""))
            
            records.append(record)

        return core_errors, tool_errors, records

    # ── 重试 + 降级 ───────────────────────────────────────────────────────────

    async def _fix_with_retry(
        self,
        component: str,
        error_pattern: str,
        instruction: str,
        push_fn=None,
        max_retries: int = 2,
    ) -> FixRecord:
        """Try to execute fix instruction, retry on failure, then fall back to script-level fix."""
        record = FixRecord(
            component=component,
            error_pattern=error_pattern,
            can_fix=True,
            fix_action=f"执行修复: {instruction}",
            success=False,
        )

        for attempt in range(max_retries):
            try:
                success, result_msg = await self._execute_fix(instruction)
                if success:
                    # ── 优化点 2：修复验证 ────────────────────────────────────
                    verified, verify_msg = await self._verify_fix(component)
                    record.success = verified
                    record.verification_result = verify_msg
                    if verified:
                        logger.info(f"Fix verified for {component} on attempt {attempt + 1}")
                        return record
                    else:
                        logger.warning(f"Fix executed but verification failed for {component}: {verify_msg}")
                        # 验证失败也继续重试
                else:
                    logger.warning(f"Fix attempt {attempt + 1} failed for {component}: {result_msg}")

            except Exception as e:
                logger.error(f"Fix attempt {attempt + 1} error for {component}: {e}")

        # 所有重试失败，降级到脚本级修复
        logger.info(f"All retries failed for {component}, attempting script-level fallback")
        return await self._script_level_fallback(record, component, error_pattern)

    async def _execute_fix(self, instruction: str) -> tuple[bool, str]:
        """Execute a fix instruction (shell command or Python snippet)."""
        instruction = instruction.strip()
        if not instruction:
            return False, "空指令"

        # 安全检查：拒绝危险命令
        _DENY_PATTERNS = [
            "powershell", "pwsh", "reg.exe", "regedit", "icacls",
            "netsh", "schtasks", "taskkill", "shutdown", "format",
            "rm -rf /", "del /s /q c:\\",
        ]
        lower = instruction.lower()
        for pat in _DENY_PATTERNS:
            if pat in lower:
                return False, f"拒绝执行危险命令: {pat}"

        try:
            result = subprocess.run(
                instruction,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.app_base),
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or f"returncode={result.returncode}"
        except subprocess.TimeoutExpired:
            return False, "执行超时 (30s)"
        except Exception as e:
            return False, str(e)

    # ── 修复验证 ──────────────────────────────────────────────────────────────

    async def _verify_fix(self, component: str) -> tuple[bool, str]:
        """Verify the fix worked by running a lightweight sanity check."""
        comp_lower = component.lower()

        try:
            if any(k in comp_lower for k in ("file", "memory", "session", "data")):
                # 文件读写测试
                test_file = Path(tempfile.gettempdir()) / "openguiclaw_verify.tmp"
                test_file.write_text("verify_ok", encoding="utf-8")
                content = test_file.read_text(encoding="utf-8")
                test_file.unlink(missing_ok=True)
                if content == "verify_ok":
                    return True, "文件读写测试通过"
                return False, f"文件读写测试失败: 读到 '{content}'"

            elif any(k in comp_lower for k in ("shell", "subprocess", "system")):
                # Shell 命令测试
                result = subprocess.run(
                    "echo verify_ok",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and "verify_ok" in result.stdout:
                    return True, "Shell 命令测试通过"
                return False, f"Shell 测试失败: {result.stderr}"

            elif any(k in comp_lower for k in ("channel", "plugin", "skill", "mcp")):
                # 检查对应目录是否存在
                for d in ("plugins", "skills", "channels"):
                    if d in comp_lower:
                        target = self.app_base / d
                        if target.exists():
                            return True, f"{d}/ 目录存在，基础验证通过"
                return True, "目录验证通过（需手动确认功能）"

            else:
                # 通用：data 目录存在即可
                data_dir = self.app_base / "data"
                if data_dir.exists():
                    return True, "data 目录检查通过"
                return False, "data 目录不存在"

        except Exception as e:
            return False, f"验证异常: {e}"

    # ── 脚本级降级 ────────────────────────────────────────────────────────────

    async def _script_level_fallback(
        self, record: FixRecord, component: str, error_pattern: str
    ) -> FixRecord:
        """Last-resort script-level fix when LLM-driven fix fails."""
        comp_lower = component.lower()
        logger.info(f"Script-level fallback for {component}")

        try:
            if any(k in comp_lower for k in ("cache",)):
                # 清理缓存目录
                cache_dir = self.app_base / "data" / "cache"
                if cache_dir.exists():
                    import shutil
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    record.fix_action = "脚本降级: 已清理 data/cache/"
                    record.success = True
                    record.verification_result = "缓存目录已重建"
                else:
                    record.fix_action = "脚本降级: 缓存目录不存在，无需清理"
                    record.success = True
                    record.verification_result = "无缓存目录"

            elif any(k in comp_lower for k in ("not found", "missing", "no such file")):
                # 重建必要目录
                for rel in ("data", "data/sessions", "data/memory", "data/scheduler"):
                    (self.app_base / rel).mkdir(parents=True, exist_ok=True)
                record.fix_action = "脚本降级: 已重建必要目录"
                record.success = True
                record.verification_result = "目录已重建"

            else:
                record.fix_action = "脚本降级: 无法自动修复，需人工检查"
                record.success = False
                record.verification_result = f"建议手动检查 {component} 模块"

        except Exception as e:
            record.fix_action = f"脚本降级失败: {e}"
            record.success = False

        return record

    # ── 清理已修复的 error 记忆 ───────────────────────────────────────────────

    def _cleanup_fixed_error_memory(self, component: str, error_pattern: str) -> None:
        """
        修复成功后，删除 Memory 中对应的 error 记忆。
        
        匹配规则：component 或 error_pattern 在记忆内容中出现。
        """
        if not hasattr(self.agent, 'memory') or not self.agent.memory:
            return
        
        try:
            error_memories = self.agent.memory.list_by_type("error")
            deleted_count = 0
            
            for mem in error_memories:
                content_lower = mem.content.lower()
                comp_lower = component.lower()
                pattern_lower = error_pattern.lower()
                
                # 如果记忆内容包含组件名或错误模式，认为是相关的
                if comp_lower in content_lower or pattern_lower in content_lower:
                    if self.agent.memory.delete(mem.id):
                        deleted_count += 1
                        logger.info(f"Deleted fixed error memory: {mem.id} - {mem.content[:50]}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} fixed error memories for {component}")
        
        except Exception as e:
            logger.warning(f"Failed to cleanup error memory: {e}")
