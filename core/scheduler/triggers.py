"""
触发器定义

支持三种触发类型:
- OnceTrigger: 一次性（指定时间执行）
- IntervalTrigger: 间隔（每 N 分钟/小时）
- CronTrigger: Cron 表达式
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

def parse_local_datetime(dt_str: str) -> datetime:
    """Parse an ISO format string into a naive local datetime."""
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is not None:
        # Convert to local timezone and remove tzinfo
        dt = dt.astimezone().replace(tzinfo=None)
    return dt

class TriggerType(Enum):
    """触发器类型"""
    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"


class Trigger(ABC):
    """触发器基类"""

    @abstractmethod
    def get_next_run_time(self, last_run: datetime | None = None) -> datetime | None:
        pass

    @abstractmethod
    def should_run(self, last_run: datetime | None = None) -> bool:
        pass

    @classmethod
    def from_config(cls, trigger_type: str, config: dict) -> "Trigger":
        if trigger_type == "once":
            return OnceTrigger.from_config(config)
        elif trigger_type == "interval":
            return IntervalTrigger.from_config(config)
        elif trigger_type == "cron":
            return CronTrigger.from_config(config)
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type}")


class OnceTrigger(Trigger):
    """一次性触发器"""

    def __init__(self, run_at: datetime):
        self.run_at = run_at
        self._fired = False

    def get_next_run_time(self, last_run: datetime | None = None) -> datetime | None:
        if last_run is not None or self._fired:
            return None
        return self.run_at

    def should_run(self, last_run: datetime | None = None) -> bool:
        if last_run is not None or self._fired:
            return False
        return datetime.now() >= self.run_at

    def mark_fired(self) -> None:
        self._fired = True

    @classmethod
    def from_config(cls, config: dict) -> "OnceTrigger":
        run_at = config.get("run_at")
        if isinstance(run_at, str):
            run_at = parse_local_datetime(run_at)
        elif isinstance(run_at, (int, float)):
            run_at = datetime.fromtimestamp(run_at)

        if not run_at:
            raise ValueError("OnceTrigger requires 'run_at' in config")

        return cls(run_at=run_at)


class IntervalTrigger(Trigger):
    """间隔触发器"""

    def __init__(
        self,
        interval_seconds: int = 0,
        interval_minutes: int = 0,
        interval_hours: int = 0,
        interval_days: int = 0,
        start_time: datetime | None = None,
    ):
        self.interval = timedelta(
            seconds=interval_seconds,
            minutes=interval_minutes,
            hours=interval_hours,
            days=interval_days,
        )

        if self.interval.total_seconds() <= 0:
            raise ValueError("Interval must be positive")

        self.start_time = start_time or datetime.now()

    def get_next_run_time(self, last_run: datetime | None = None) -> datetime:
        now = datetime.now()

        if last_run is None:
            if now < self.start_time:
                return self.start_time
            elapsed = now - self.start_time
            intervals_passed = int(elapsed.total_seconds() / self.interval.total_seconds())
            return self.start_time + self.interval * (intervals_passed + 1)

        next_run = last_run + self.interval
        while next_run < now:
            next_run += self.interval
        return next_run

    def should_run(self, last_run: datetime | None = None) -> bool:
        next_run = self.get_next_run_time(last_run)
        return datetime.now() >= next_run

    @classmethod
    def from_config(cls, config: dict) -> "IntervalTrigger":
        interval_seconds = config.get("interval_seconds", 0)
        interval_minutes = config.get("interval_minutes", 0)
        interval_hours = config.get("interval_hours", 0)
        interval_days = config.get("interval_days", 0)

        if "interval" in config:
            interval_minutes = config["interval"]

        start_time = config.get("start_time")
        if isinstance(start_time, str):
            start_time = parse_local_datetime(start_time)

        return cls(
            interval_seconds=interval_seconds,
            interval_minutes=interval_minutes,
            interval_hours=interval_hours,
            interval_days=interval_days,
            start_time=start_time,
        )


class CronTrigger(Trigger):
    """Cron 表达式触发器"""

    def __init__(self, cron_expression: str):
        self.expression = cron_expression
        self._parse_expression()

    def _parse_expression(self) -> None:
        parts = self.expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {self.expression}. Expected 5 fields.")

        self.minute_spec = self._parse_field(parts[0], 0, 59)
        self.hour_spec = self._parse_field(parts[1], 0, 23)
        self.day_spec = self._parse_field(parts[2], 1, 31)
        self.month_spec = self._parse_field(parts[3], 1, 12)
        self.weekday_spec = self._parse_field(parts[4], 0, 6)

    def _parse_field(self, field: str, min_val: int, max_val: int) -> set[int]:
        result = set()
        for part in field.split(","):
            if part == "*":
                result.update(range(min_val, max_val + 1))
            elif "/" in part:
                base, step = part.split("/")
                step = int(step)
                if base == "*":
                    result.update(range(min_val, max_val + 1, step))
                elif "-" in base:
                    start, end = map(int, base.split("-"))
                    result.update(range(start, end + 1, step))
                else:
                    start = int(base)
                    result.update(range(start, max_val + 1, step))
            elif "-" in part:
                start, end = map(int, part.split("-"))
                result.update(range(start, end + 1))
            else:
                result.add(int(part))
        return result

    def get_next_run_time(self, last_run: datetime | None = None) -> datetime:
        if last_run:
            start = last_run + timedelta(minutes=1)
        else:
            start = datetime.now() + timedelta(minutes=1)

        start = start.replace(second=0, microsecond=0)
        max_iterations = 365 * 2 * 24 * 60

        current = start
        for _ in range(max_iterations):
            if self._matches(current):
                return current
            current += timedelta(minutes=1)

        logger.warning(f"Could not find next run time for cron: {self.expression}")
        return start + timedelta(days=365)

    def _matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minute_spec
            and dt.hour in self.hour_spec
            and dt.day in self.day_spec
            and dt.month in self.month_spec
            and dt.weekday() in self._convert_weekday(self.weekday_spec)
        )

    def _convert_weekday(self, weekday_spec: set[int]) -> set[int]:
        result = set()
        for w in weekday_spec:
            if w == 0 or w == 7:
                result.add(6)
            else:
                result.add(w - 1)
        return result

    def should_run(self, last_run: datetime | None = None) -> bool:
        next_run = self.get_next_run_time(last_run)
        return datetime.now() >= next_run

    @classmethod
    def from_config(cls, config: dict) -> "CronTrigger":
        cron = config.get("cron")
        if not cron:
            raise ValueError("CronTrigger requires 'cron' in config")
        return cls(cron_expression=cron)

    def describe(self) -> str:
        descriptions = {
            "* * * * *": "每分钟",
            "0 * * * *": "每小时",
            "0 0 * * *": "每天午夜",
            "0 9 * * *": "每天上午9点",
            "0 9 * * 1": "每周一上午9点",
            "0 0 1 * *": "每月1日午夜",
        }
        return descriptions.get(self.expression, f"Cron: {self.expression}")
