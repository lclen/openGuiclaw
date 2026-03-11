"""
core/tasks.py — Built-in scheduled system tasks.

Extracted from server.py lifespan to keep server.py focused on
HTTP wiring only.  All functions are async and receive a push_fn
callable so they can broadcast events to SSE subscribers.
"""
import asyncio
import glob
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from core.state import app_state, _APP_BASE, logger


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def execute_system_task(task, push_fn: Callable) -> tuple[bool, str]:
    """Route a system task to its handler by action name."""
    action = task.action or ""
    if action == "system:daily_selfcheck":
        return await _system_daily_selfcheck(push_fn)
    if action == "system:memory_consolidate":
        return await _system_memory_consolidate(push_fn, task)
    if action == "system:memory_audit":
        return await _system_memory_audit(push_fn)
    if action == "system:daily_evolution":
        return await _system_daily_evolution(push_fn, task)
    return False, f"Unknown system action: {action}"


# ── Daily self-check ──────────────────────────────────────────────────────────

async def _system_daily_selfcheck(push_fn: Callable) -> tuple[bool, str]:
    """
    Check data-directory integrity, scan log files for errors, and
    summarise scheduler task health.  Pushes a Markdown report to chat.
    """
    lines = [f"## 🔍 系统自检报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    issues: list[str] = []

    # 1. Required directories
    required_dirs = [
        str(_APP_BASE / d) for d in [
            "data", "data/sessions", "data/memory", "data/scheduler",
            "data/diary", "data/journals", "data/identities", "data/identity",
            "data/plans", "data/consolidation",
        ]
    ]
    for d in required_dirs:
        if not os.path.exists(d):
            try:
                os.makedirs(d, exist_ok=True)
                issues.append(f"⚠️ 目录 `{d}` 不存在，已自动创建")
            except Exception as e:
                issues.append(f"❌ 目录 `{d}` 创建失败: {e}")

    # 2. Log error scan
    log_errors: dict[str, int] = {}
    for lf in glob.glob("*.log") + glob.glob("logs/*.log"):
        try:
            with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if " ERROR " in line or " CRITICAL " in line:
                        parts = line.split(" - ")
                        module = parts[1].strip() if len(parts) > 2 else "unknown"
                        log_errors[module] = log_errors.get(module, 0) + 1
        except Exception:
            pass

    # 3. Scheduler summary
    scheduler = app_state.get("task_scheduler")
    task_summary = {"total": 0, "enabled": 0, "failed": 0}
    if scheduler:
        tasks = scheduler.list_tasks()
        task_summary["total"] = len(tasks)
        task_summary["enabled"] = sum(1 for t in tasks if t.enabled)
        task_summary["failed"] = sum(1 for t in tasks if t.fail_count > 0)

    # 4. Agent + session + memory counts
    ag = app_state.get("agent")
    agent_ok = ag is not None
    session_count = len(glob.glob(str(_APP_BASE / "data" / "sessions" / "*.json")))
    memory_count = 0
    memory_file = str(_APP_BASE / "data" / "memory.jsonl")
    if os.path.exists(memory_file):
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                memory_count = sum(1 for line in f if line.strip())
        except Exception:
            pass

    # 5. AI log analysis & auto-fix (分层修复 + 验证 + 重试降级)
    core_errs, tool_errs, records = 0, 0, []
    if log_errors and ag:
        try:
            from core.self_check import SelfChecker
            checker = SelfChecker(agent=ag)
            core_errs, tool_errs, records = await checker.analyze_and_fix(push_fn)
        except Exception as e:
            logger.error(f"AI self-check failed: {e}")

    # Build report
    lines.append(f"\n**Agent 状态**: {'✅ 在线' if agent_ok else '❌ 离线'}")
    lines.append(f"**会话文件**: {session_count} 个")
    lines.append(f"**记忆条目**: {memory_count} 条")
    lines.append(
        f"\n**计划任务**: 共 {task_summary['total']} 个，"
        f"启用 {task_summary['enabled']} 个，"
        f"有失败记录 {task_summary['failed']} 个"
    )
    if log_errors:
        lines.append(f"\n**日志错误** ({sum(log_errors.values())} 条):")
        for mod, cnt in sorted(log_errors.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  - `{mod}`: {cnt} 次")
        if records:
            fixed_count = sum(1 for r in records if r.success)
            lines.append(
                f"\n  *AI 诊断*: 核心错误 **{core_errs}** 个 (需人工处理)，"
                f"能力层错误 **{tool_errs}** 个，"
                f"自动修复成功 **{fixed_count}** 个"
            )
    else:
        lines.append("\n**日志错误**: 无")

    if issues or records:
        lines.append("\n**自动修复 / 诊断建议**:")
        for issue in issues:
            lines.append(f"  - {issue}")
        for rec in records:
            if not rec.can_fix:
                prefix = "🔴 [需人工处理]"
            elif rec.success:
                prefix = "✅ [已自动修复]"
            else:
                prefix = "⚠️ [修复失败]"
            lines.append(f"  - {prefix} `{rec.component}`: {rec.error_pattern}")
            lines.append(f"    👉 {rec.fix_action}")
            if rec.verification_result:
                lines.append(f"    🔍 验证: {rec.verification_result}")

    status = (
        "✅ 系统运行正常"
        if not issues and not log_errors
        else f"⚠️ 发现 {len(issues)} 个问题，{len(log_errors)} 个错误模块"
    )
    lines.append(f"\n**总结**: {status}")
    report = "\n".join(lines)

    if ag:
        ag.sessions.current.add_message("assistant", report)
        ag.sessions.save()
    push_fn({"type": "chat_event", "role": "assistant", "content": report})
    logger.info(f"System selfcheck completed: {status}")
    return True, status


# ── Memory consolidation ──────────────────────────────────────────────────────

async def _system_memory_consolidate(push_fn: Callable, task: Optional[Any] = None) -> tuple[bool, str]:
    """
    Scan recent sessions and extract new long-term memories via MemoryExtractor.
    Pushes a Markdown summary report to chat.
    """
    ag = app_state.get("agent")
    if not ag or not hasattr(ag, "memory_extractor") or not hasattr(ag, "memory"):
        return False, "Agent or memory subsystem not ready"

    push_fn({"type": "chat_event", "role": "system", "content": "🧠 [记忆整理] 开始扫描会话历史信息…"})

    # Optimization: Use task.last_run if available to scan only new/modified sessions
    now = datetime.now()
    if task and task.last_run:
        # Buffer of 10 minutes to ensure no overlap loss
        cutoff = task.last_run - timedelta(minutes=10)
    else:
        # Initial run: scan last 7 days
        cutoff = now - timedelta(days=7)

    logger.info(f"Memory consolidate scan starting (cutoff: {cutoff})")
    session_files = sorted(
        (_APP_BASE / "data" / "sessions").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    current_sid = ag.sessions.current.session_id if ag.sessions.current else None
    scanned = written = skipped = 0

    for sf in session_files:
        try:
            if datetime.fromtimestamp(sf.stat().st_mtime) < cutoff:
                break
            with open(sf, "r", encoding="utf-8") as f:
                data = json.load(f)
            sid = data.get("session_id", sf.stem)
            messages = data.get("messages", [])
            if sid == current_sid or not messages:
                skipped += 1
                continue
            chat_msgs = [m for m in messages if m.get("role") in ("user", "assistant")]
            if len(chat_msgs) < 2:
                skipped += 1
                continue
            scanned += 1
            loop = asyncio.get_running_loop()
            new_items = await loop.run_in_executor(
                None, ag.memory_extractor.extract_from_conversation, chat_msgs
            )
            written += len(new_items) if new_items else 0
        except Exception as e:
            logger.warning(f"Memory consolidate: skipped {sf.name}: {e}")
            skipped += 1

    total_memories = len(ag.memory.list_all())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    type_meta = [
        ("fact", "客观事实"), ("preference", "用户偏好"), ("rule", "规则约束"),
        ("skill", "技能模式"), ("error", "待规避错误"), ("experience", "可复用经验"),
    ]
    type_rows = "\n".join(
        f"| `{t}` | {desc} | {len(ag.memory.list_by_type(t))} |"
        for t, desc in type_meta
    )
    report = (
        f"## 🧠 记忆整理报告 — {ts}\n\n"
        f"- **扫描会话**: {scanned} 个　**跳过**: {skipped} 个　**写入新记忆**: {written} 条\n\n"
        f"| 类型 | 说明 | 当前总量 |\n|------|------|---------|\n{type_rows}\n\n"
        f"{'✅ 整理完成，记忆库已更新。' if written > 0 else '✅ 整理完成，无新增内容（已是最新）。'}"
        f"  记忆库共 **{total_memories}** 条。"
    )
    if ag:
        ag.sessions.current.add_message("assistant", report)
        ag.sessions.save()
    push_fn({"type": "chat_event", "role": "assistant", "content": report})
    status = f"扫描 {scanned} 个会话，写入 {written} 条新记忆"
    logger.info(f"Memory consolidate completed: {status}")
    return True, status


# ── Scheduler task runner (called by TaskScheduler) ───────────────────────────

async def scheduled_task_runner(task) -> tuple[bool, str]:
    """
    Universal task runner passed to TaskScheduler as its executor.
    Handles reminder / prompt / system task types.
    """
    import concurrent.futures
    from core.state import _ctx_event_queue

    ag = app_state.get("agent")
    if not ag:
        return False, "Agent not ready"

    def _push(event: dict) -> None:
        _ctx_event_queue.put(event)

    try:
        _push({"type": "chat_event", "role": "system", "content": f"⏰ [计划任务触发] {task.name}"})

        if task.task_type.value == "system":
            return await execute_system_task(task, _push)

        if task.task_type.value == "reminder":
            msg = task.reminder_message or "无提醒内容"
            ag.sessions.current.add_message("assistant", f"⏰ **{task.name}**\n\n{msg}")
            ag.sessions.save()
            _push({"type": "chat_event", "role": "assistant", "content": msg})
            return True, "Reminder sent"

        # Default: LLM prompt task
        full_prompt = f"[计划任务: {task.name}] {task.prompt}"
        _push({"type": "chat_event", "role": "user", "content": full_prompt})

        def _run_chat():
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                return ag.chat(full_prompt)
            finally:
                loop.close()
                _asyncio.set_event_loop(None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="sched") as pool:
            response = await asyncio.get_running_loop().run_in_executor(pool, _run_chat)

        _push({"type": "chat_event", "role": "assistant", "content": response})
        return True, response

    except Exception as e:
        logger.error(f"Scheduled task error: {e}", exc_info=True)
        return False, str(e)

async def _system_memory_audit(push_fn: Callable) -> tuple[bool, str]:
    """
    Perform AI-driven memory deduplication and cleanup.
    Wipes old memories and replaces them with audited/optimized entries.
    """
    ag = app_state.get("agent")
    if not ag or not hasattr(ag, "memory_extractor") or not hasattr(ag, "memory"):
        return False, "Agent or memory subsystem not ready"

    push_fn({"type": "chat_event", "role": "system", "content": "🧹 [记忆审计] 正在启动 AI 自主审查与去重…"})

    try:
        loop = asyncio.get_running_loop()
        # Audit: Get optimized list from AI
        # Audit: AI natively handles actions (delete/update/merge/keep)
        old_count = len(ag.memory.list_all())
        report = await loop.run_in_executor(
            None, ag.memory_extractor.audit_memories
        )
        
        if not report:
            logger.warning("[Task] Memory audit returned empty/failed.")
            return False, "AI 审计未能完成，已中止。"

        new_count = len(ag.memory.list_all())
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        summary = (
            f"### 🧹 记忆库审计报告 — {ts}\n\n"
            f"- **审查前总数**: {old_count} 条\n"
            f"- **审查后总数**: {new_count} 条\n"
            f"- **操作统计**: 删除 {report.get('deleted', 0)} 条, 合并 {report.get('merged', 0)} 条, 更新 {report.get('updated', 0)} 条, 保留 {report.get('kept', 0)} 条\n\n"
            "✅ 记忆库已通过例行自检完成优化。"
        )
        
        if ag:
            ag.sessions.current.add_message("assistant", summary)
            ag.sessions.save()
            
        push_fn({"type": "chat_event", "role": "assistant", "content": summary})
        return True, f"审计完成: {old_count} -> {new_count}"
        
    except Exception as e:
        logger.error(f"Memory audit error: {e}", exc_info=True)
        return False, str(e)


# ── Daily evolution ───────────────────────────────────────────────────────────

async def _system_daily_evolution(push_fn: Callable, task=None) -> tuple[bool, str]:
    """
    Run daily self-evolution: summarize yesterday's journal, extract memories,
    update persona. If task.prompt contains a date string (YYYY-MM-DD), use it
    as the target date (for catchup runs triggered by _startup_evolution).
    """
    ag = app_state.get("agent")
    if not ag:
        return False, "Agent not ready"

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Check if a specific date was passed via task.prompt (catchup scenario)
    import re as _re
    task_prompt = getattr(task, "prompt", "") or ""
    if _re.match(r"^\d{4}-\d{2}-\d{2}$", task_prompt.strip()):
        target_date = task_prompt.strip()
        # Clear the prompt so next scheduled run uses normal logic
        if task:
            task.prompt = ""
    elif ag.evolution.is_evolution_done(yesterday):
        target_date = today
    else:
        target_date = yesterday

    push_fn({"type": "chat_event", "role": "system",
             "content": f"🌱 [自我进化] 开始处理 {target_date} 的日志…"})

    try:
        loop = asyncio.get_running_loop()

        # Step 1: summarize conversations for the day
        await loop.run_in_executor(None, ag._summarize_day_conversations, target_date)

        # Step 2: evolve from journal
        new_mems = await loop.run_in_executor(
            None, ag.evolution.evolve_from_journal, target_date
        )

        # Step 3: evolve persona
        await loop.run_in_executor(None, ag.evolution.evolve_persona)

        research_count = sum(1 for m in new_mems if m.startswith("[探索研究]"))
        base_count = len(new_mems) - research_count
        parts = []
        if base_count:
            parts.append(f"{base_count} 条日志记忆")
        if research_count:
            parts.append(f"{research_count} 条主动探索知识")

        summary = f"🌱 [自我进化] {target_date} 进化完成，习得 {' + '.join(parts)}。" if parts else \
                  f"🌱 [自我进化] {target_date} 进化完成，无新记忆。"

        push_fn({"type": "chat_event", "role": "system", "content": summary})
        logger.info(f"Daily evolution completed for {target_date}: {len(new_mems)} memories")
        return True, summary

    except Exception as e:
        logger.error(f"Daily evolution error: {e}", exc_info=True)
        push_fn({"type": "chat_event", "role": "system", "content": f"⚠️ [自我进化] 出错: {e}"})
        return False, str(e)
