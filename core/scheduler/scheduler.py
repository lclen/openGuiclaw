"""
任务调度器

核心调度器:
- 管理任务生命周期
- 触发任务执行
- 任务持久化
"""

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from .task import ScheduledTask, TaskStatus, TriggerType
from .triggers import Trigger

logger = logging.getLogger(__name__)

# 执行器类型定义
TaskExecutorFunc = Callable[[ScheduledTask], Awaitable[tuple[bool, str]]]


class TaskScheduler:
    """任务调度器"""

    def __init__(
        self,
        storage_path: Path | None = None,
        executor: TaskExecutorFunc | None = None,
        timezone: str = "Asia/Shanghai",
        max_concurrent: int = 5,
        check_interval_seconds: int = 2,
        advance_seconds: int = 5,  # 提前执行秒数
    ):
        self.storage_path = Path(storage_path) if storage_path else Path("data/scheduler")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.executor = executor
        self.timezone = timezone
        self.max_concurrent = max_concurrent
        self.check_interval = check_interval_seconds
        self.advance_seconds = 0  # no advance trigger; cron times are exact

        self._tasks: dict[str, ScheduledTask] = {}
        self._triggers: dict[str, Trigger] = {}

        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._running_tasks: set[str] = set()
        self._semaphore: asyncio.Semaphore | None = None

        self._load_tasks()

    async def start(self) -> None:
        """启动调度器"""
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        now = datetime.now()
        for task in self._tasks.values():
            if task.is_active:
                if task.next_run is None:
                    # ONCE task with last_run set means it already fired — mark completed
                    if task.trigger_type == TriggerType.ONCE and task.last_run is not None:
                        logger.info(f"One-time task {task.id} has last_run but no next_run, marking completed")
                        task.status = TaskStatus.COMPLETED
                        task.enabled = False
                    else:
                        self._update_next_run(task)
                elif task.next_run < now:
                    self._recalculate_missed_run(task, now)

        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"TaskScheduler started with {len(self._tasks)} tasks")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task

        if self._running_tasks:
            logger.info(f"Waiting for {len(self._running_tasks)} running tasks...")
            await asyncio.sleep(2)

        self._save_tasks()
        logger.info("TaskScheduler stopped")

    async def add_task(self, task: ScheduledTask) -> str:
        """添加任务"""
        trigger = Trigger.from_config(task.trigger_type.value, task.trigger_config)
        task.next_run = trigger.get_next_run_time()
        task.status = TaskStatus.SCHEDULED

        self._tasks[task.id] = task
        self._triggers[task.id] = trigger

        self._save_tasks()
        logger.info(f"Added task: {task.id} ({task.name}), next run: {task.next_run}")
        return task.id

    async def remove_task(self, task_id: str, force: bool = False) -> bool:
        """删除任务"""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            if not task.deletable and not force:
                logger.warning(f"Task {task_id} is a system task and cannot be deleted.")
                return False

            task.cancel()
            del self._tasks[task_id]
            if task_id in self._triggers:
                del self._triggers[task_id]

            self._save_tasks()
            logger.info(f"Removed task: {task_id}")
            return True
        return False

    async def update_task(self, task_id: str, updates: dict) -> bool:
        """更新任务"""
        if task_id not in self._tasks:
            return False

        # Ensure enum types are correctly cast from strings to prevent state corruption
        if "trigger_type" in updates and isinstance(updates["trigger_type"], str):
            updates["trigger_type"] = TriggerType(updates["trigger_type"])
        if "task_type" in updates and isinstance(updates["task_type"], str):
            from .task import TaskType
            updates["task_type"] = TaskType(updates["task_type"])
        if "status" in updates and isinstance(updates["status"], str):
            updates["status"] = TaskStatus(updates["status"])

        task = self._tasks[task_id]
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.now()

        if "trigger_config" in updates or "trigger_type" in updates:
            trigger = Trigger.from_config(task.trigger_type.value, task.trigger_config)
            self._triggers[task_id] = trigger
            task.next_run = trigger.get_next_run_time(task.last_run)

        self._save_tasks()
        logger.info(f"Updated task: {task_id}")
        return True

    async def enable_task(self, task_id: str) -> bool:
        """启用任务"""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.enable()
            self._update_next_run(task)
            self._save_tasks()
            return True
        return False

    async def disable_task(self, task_id: str) -> bool:
        """禁用任务"""
        if task_id in self._tasks:
            task = self._tasks[task_id]
            task.disable()
            self._save_tasks()
            return True
        return False

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self, enabled_only: bool = False) -> list[ScheduledTask]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if enabled_only:
            tasks = [t for t in tasks if t.enabled]
        return sorted(tasks, key=lambda t: t.next_run or datetime.max)

    async def trigger_now(self, task_id: str) -> bool:
        """立即触发任务（后台异步执行，立即返回）"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        # 在后台运行，不阻塞 HTTP 响应
        asyncio.create_task(self._run_task_safe(task))
        return True

    async def _scheduler_loop(self) -> None:
        """调度循环"""
        while self._running:
            try:
                now = datetime.now()
                for task_id, task in list(self._tasks.items()):
                    if not task.is_active:
                        continue

                    if task_id in self._running_tasks:
                        continue

                    if task.next_run:
                        trigger_time = task.next_run - timedelta(seconds=self.advance_seconds)
                        if now >= trigger_time:
                            self._running_tasks.add(task_id)
                            asyncio.create_task(self._run_task_safe(task))

                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(1)

    async def _run_task_safe(self, task: ScheduledTask) -> None:
        """安全地执行任务"""
        try:
            async with self._semaphore:
                await self._execute_task(task)
        finally:
            self._running_tasks.discard(task.id)

    async def _execute_task(self, task: ScheduledTask) -> None:
        """执行任务"""
        logger.info(f"Executing task: {task.id} ({task.name})")
        task.mark_running()

        try:
            success = True
            error_msg = ""
            if self.executor:
                success, error_msg = await self.executor(task)
            else:
                logger.warning(f"No executor configured for task {task.id}")

            if success:
                trigger = self._triggers.get(task.id)
                next_run = trigger.get_next_run_time(datetime.now()) if trigger else None
                task.mark_completed(next_run)
                logger.info(f"Task {task.id} completed successfully")
            else:
                task.mark_failed(error_msg)
                trigger = self._triggers.get(task.id)
                next_run = trigger.get_next_run_time(datetime.now()) if trigger else None
                if next_run:
                    task.next_run = next_run
                logger.warning(f"Task {task.id} reported failure: {error_msg}")

        except Exception as e:
            error_msg = str(e)
            task.mark_failed(error_msg)
            logger.error(f"Task {task.id} failed: {error_msg}", exc_info=True)

        self._save_tasks()

    def _update_next_run(self, task: ScheduledTask) -> None:
        """更新任务的下一次运行时间"""
        trigger = self._triggers.get(task.id)
        if not trigger:
            trigger = Trigger.from_config(task.trigger_type.value, task.trigger_config)
            self._triggers[task.id] = trigger

        task.next_run = trigger.get_next_run_time(task.last_run)

    def _recalculate_missed_run(self, task: ScheduledTask, now: datetime) -> None:
        """重新计算错过执行时间的任务的下一次运行时间"""
        trigger = self._triggers.get(task.id)
        if not trigger:
            trigger = Trigger.from_config(task.trigger_type.value, task.trigger_config)
            self._triggers[task.id] = trigger

        if task.trigger_type == TriggerType.ONCE:
            logger.info(f"One-time task {task.id} missed, marking as completed")
            task.last_run = task.last_run or now  # ensure last_run is set so restart won't re-trigger
            task.status = TaskStatus.COMPLETED
            task.enabled = False
            self._save_tasks()
            return

        next_run = trigger.get_next_run_time(now)
        min_next_run = now + timedelta(seconds=60)
        if next_run and next_run < min_next_run:
            next_run = trigger.get_next_run_time(min_next_run)

        task.next_run = next_run
        logger.info(f"Recalculated next_run for task {task.id}: {next_run}")

    def _atomic_write_json(self, target: Path, data: object) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        bak = target.with_suffix(target.suffix + ".bak")

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        if target.exists():
            with contextlib.suppress(Exception):
                if bak.exists():
                    bak.unlink()
                os.replace(str(target), str(bak))

        os.replace(str(tmp), str(target))

    def _try_recover_json(self, target: Path) -> bool:
        bak = target.with_suffix(target.suffix + ".bak")
        tmp = target.with_suffix(target.suffix + ".tmp")

        if target.exists():
            return False

        if bak.exists():
            with contextlib.suppress(Exception):
                os.replace(str(bak), str(target))
                logger.warning(f"Recovered {target.name} from backup")
                return True

        if tmp.exists():
            with contextlib.suppress(Exception):
                os.replace(str(tmp), str(target))
                logger.warning(f"Recovered {target.name} from temp file")
                return True

        return False

    def _load_tasks(self) -> None:
        tasks_file = self.storage_path / "scheduler_tasks.json"

        if not tasks_file.exists():
            self._try_recover_json(tasks_file)
        if not tasks_file.exists():
            return

        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)

            for item in data:
                try:
                    task = ScheduledTask.from_dict(item)
                    self._tasks[task.id] = task
                    trigger = Trigger.from_config(task.trigger_type.value, task.trigger_config)
                    self._triggers[task.id] = trigger
                except Exception as e:
                    logger.warning(f"Failed to load task: {e}")

            logger.info(f"Loaded {len(self._tasks)} tasks from storage")
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")

    def _save_tasks(self) -> None:
        tasks_file = self.storage_path / "scheduler_tasks.json"
        try:
            data = [task.to_dict() for task in self._tasks.values()]
            self._atomic_write_json(tasks_file, data)
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")
