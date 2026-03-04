"""
定时任务定义

定义任务的数据结构和状态
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .triggers import TriggerType

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """任务类型"""
    REMINDER = "reminder"  # 简单提醒
    TASK = "task"          # Agent 执行
    SYSTEM = "system"      # 系统内置任务（不通过 LLM）


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DISABLED = "disabled"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """定时任务"""

    id: str
    name: str
    description: str

    trigger_type: TriggerType
    trigger_config: dict

    task_type: TaskType = TaskType.TASK
    reminder_message: str | None = None
    prompt: str = ""
    action: str | None = None

    enabled: bool = True
    status: TaskStatus = TaskStatus.PENDING
    deletable: bool = True

    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    fail_count: int = 0

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        trigger_type: TriggerType,
        trigger_config: dict,
        prompt: str = "",
        task_type: TaskType = TaskType.TASK,
        reminder_message: str | None = None,
        **kwargs,
    ) -> "ScheduledTask":
        return cls(
            id=f"task_{uuid.uuid4().hex[:12]}",
            name=name,
            description=description,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            task_type=task_type,
            reminder_message=reminder_message,
            prompt=prompt,
            **kwargs,
        )

    def enable(self) -> None:
        self.enabled = True
        self.status = TaskStatus.SCHEDULED
        self.updated_at = datetime.now()

    def disable(self) -> None:
        self.enabled = False
        self.status = TaskStatus.DISABLED
        self.updated_at = datetime.now()

    def cancel(self) -> None:
        self.enabled = False
        self.status = TaskStatus.CANCELLED
        self.updated_at = datetime.now()

    def mark_running(self) -> None:
        self.status = TaskStatus.RUNNING
        self.next_run = None  # clear to prevent re-trigger while running
        self.updated_at = datetime.now()

    def mark_completed(self, next_run: datetime | None = None) -> None:
        self.last_run = datetime.now()
        self.run_count += 1
        self.updated_at = datetime.now()

        if self.trigger_type == TriggerType.ONCE:
            self.status = TaskStatus.COMPLETED
            self.enabled = False
            self.next_run = None  # explicitly clear so restart won't re-trigger
        else:
            self.status = TaskStatus.SCHEDULED
            self.next_run = next_run

    def mark_failed(self, error: str = None) -> None:
        self.last_run = datetime.now()
        self.fail_count += 1
        self.updated_at = datetime.now()

        if self.fail_count >= 5:
            self.status = TaskStatus.FAILED
            self.enabled = False
            logger.warning(f"Task {self.id} disabled after {self.fail_count} failures")
        else:
            self.status = TaskStatus.SCHEDULED

    @property
    def is_active(self) -> bool:
        return self.enabled and self.status in (TaskStatus.PENDING, TaskStatus.SCHEDULED)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_type": self.trigger_type.value,
            "trigger_config": self.trigger_config,
            "task_type": self.task_type.value,
            "reminder_message": self.reminder_message,
            "prompt": self.prompt,
            "action": self.action,
            "enabled": self.enabled,
            "status": self.status.value,
            "deletable": self.deletable,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "fail_count": self.fail_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledTask":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            trigger_type=TriggerType(data["trigger_type"]),
            trigger_config=data["trigger_config"],
            task_type=TaskType(data.get("task_type", "task")),
            reminder_message=data.get("reminder_message"),
            prompt=data.get("prompt", ""),
            action=data.get("action"),
            enabled=data.get("enabled", True),
            status=TaskStatus(data.get("status", "pending")),
            deletable=data.get("deletable", True),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            run_count=data.get("run_count", 0),
            fail_count=data.get("fail_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
