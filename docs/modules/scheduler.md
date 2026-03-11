# 任务调度系统 (Scheduler)

## 概述

任务调度系统负责定时执行系统任务和用户自定义任务，支持 Cron 表达式和一次性任务。

**文件位置**: `core/scheduler/scheduler.py`, `core/scheduler/task.py`

---

## 架构

```
┌──────────────────────────────────────────┐
│         TaskScheduler                    │
│  (任务调度引擎)                           │
└──────────────────────────────────────────┘
           ↓
    ┌──────────────────────────────────────┐
    │         ScheduledTask                │
    │  (任务定义)                           │
    └──────────────────────────────────────┘
           ↓
    ┌──────────────────────────────────────┐
    │         scheduled_task_runner        │
    │  (任务执行器)                         │
    └──────────────────────────────────────┘
```

---

## 任务类型

### TriggerType (触发类型)

```python
class TriggerType(str, Enum):
    CRON = "cron"          # Cron 表达式定时触发
    ONCE = "once"          # 一次性任务（指定时间）
    MANUAL = "manual"      # 手动触发
```

### TaskType (任务类型)

```python
class TaskType(str, Enum):
    SYSTEM = "system"      # 系统任务（如自检、记忆整合）
    REMINDER = "reminder"  # 提醒任务（只显示消息）
    PROMPT = "prompt"      # LLM 任务（调用 Agent.chat）
```

---

## ScheduledTask 结构

```python
@dataclass
class ScheduledTask:
    id: str                      # 任务 ID（唯一）
    name: str                    # 任务名称
    description: str             # 任务描述
    trigger_type: TriggerType    # 触发类型
    task_type: TaskType          # 任务类型
    
    # Cron 任务
    cron_expr: Optional[str] = None      # Cron 表达式 "0 4 * * *"
    
    # 一次性任务
    scheduled_time: Optional[str] = None  # ISO 时间 "2026-03-15T10:00:00"
    
    # 任务内容
    prompt: str = ""                     # LLM 任务的 prompt
    reminder_message: str = ""           # 提醒任务的消息
    action: Optional[str] = None         # 系统任务的 action（如 "system:daily_selfcheck"）
    
    # 状态
    enabled: bool = True                 # 是否启用
    last_run: Optional[datetime] = None  # 上次执行时间
    next_run: Optional[datetime] = None  # 下次执行时间
    fail_count: int = 0                  # 失败次数
    deletable: bool = True               # 是否可删除（内置任务不可删除）
```

---

## TaskScheduler

### 初始化

```python
from core.scheduler import TaskScheduler

scheduler = TaskScheduler(
    data_dir="data/scheduler",
    executor=scheduled_task_runner,  # 任务执行器
    timezone="Asia/Shanghai",
    max_concurrent=3,                # 最大并发任务数
    check_interval_seconds=30        # 检查间隔（秒）
)
```

### 添加任务

```python
from core.scheduler import ScheduledTask, TriggerType, TaskType

# Cron 任务
await scheduler.add_task(ScheduledTask(
    id="daily_selfcheck",
    name="系统自检",
    description="每日凌晨自动检查系统健康状态",
    trigger_type=TriggerType.CRON,
    task_type=TaskType.SYSTEM,
    cron_expr="0 4 * * *",  # 每日 04:00
    action="system:daily_selfcheck",
    deletable=False
))

# 一次性任务
await scheduler.add_task(ScheduledTask(
    id="meeting_reminder",
    name="会议提醒",
    description="下午 3 点会议提醒",
    trigger_type=TriggerType.ONCE,
    task_type=TaskType.REMINDER,
    scheduled_time="2026-03-15T15:00:00",
    reminder_message="⏰ 会议将在 15:00 开始"
))

# LLM 任务
await scheduler.add_task(ScheduledTask(
    id="daily_summary",
    name="每日总结",
    description="每晚生成当天工作总结",
    trigger_type=TriggerType.CRON,
    task_type=TaskType.PROMPT,
    cron_expr="0 22 * * *",  # 每晚 22:00
    prompt="总结今天的对话和完成的任务"
))
```

### 管理任务

```python
# 列出所有任务
tasks = scheduler.list_tasks()

# 获取单个任务
task = scheduler.get_task("daily_selfcheck")

# 更新任务
await scheduler.update_task("daily_selfcheck", enabled=False)

# 删除任务
await scheduler.delete_task("meeting_reminder")

# 手动执行
await scheduler.trigger_task("daily_selfcheck")
```

### 启动 / 停止

```python
await scheduler.start()   # 启动调度器
await scheduler.stop()    # 停止调度器
scheduler.pause()         # 暂停调度
scheduler.resume()        # 恢复调度
```

---

## Cron 表达式

### 格式

```
分 时 日 月 周
*  *  *  *  *
```

### 示例

| 表达式 | 说明 |
|--------|------|
| `0 4 * * *` | 每日 04:00 |
| `0 */2 * * *` | 每 2 小时 |
| `30 9 * * 1-5` | 工作日 09:30 |
| `0 0 1 * *` | 每月 1 号 00:00 |
| `0 12 * * 0` | 每周日 12:00 |

### 特殊字符

- `*`: 任意值
- `*/n`: 每 n 个单位
- `n-m`: 范围
- `n,m`: 列表

---

## 任务执行器

### scheduled_task_runner

```python
async def scheduled_task_runner(task: ScheduledTask) -> tuple[bool, str]:
    """
    通用任务执行器，根据任务类型分发：
    - SYSTEM: 调用 execute_system_task()
    - REMINDER: 发送提醒消息
    - PROMPT: 调用 Agent.chat()
    
    返回: (success, result_message)
    """
```

### 系统任务

在 `core/tasks.py` 中定义：

```python
async def execute_system_task(task, push_fn) -> tuple[bool, str]:
    action = task.action or ""
    if action == "system:daily_selfcheck":
        return await _system_daily_selfcheck(push_fn)
    if action == "system:memory_consolidate":
        return await _system_memory_consolidate(push_fn, task)
    if action == "system:memory_audit":
        return await _system_memory_audit(push_fn)
    return False, f"Unknown system action: {action}"
```

---

## 内置任务

### 系统自检

```python
ScheduledTask(
    id="system_daily_selfcheck",
    name="系统自检",
    cron_expr="0 4 * * *",
    task_type=TaskType.SYSTEM,
    action="system:daily_selfcheck",
    deletable=False
)
```

### 记忆整合

```python
ScheduledTask(
    id="system_memory_consolidate",
    name="记忆整合",
    cron_expr="0 3 * * *",
    task_type=TaskType.SYSTEM,
    action="system:memory_consolidate",
    deletable=False
)
```

### 记忆审计

```python
ScheduledTask(
    id="system_memory_audit",
    name="记忆审计",
    cron_expr="0 2 * * 0",  # 每周日 02:00
    task_type=TaskType.SYSTEM,
    action="system:memory_audit",
    deletable=False
)
```

---

## 数据持久化

### 存储格式

`data/scheduler/tasks.json`:

```json
{
  "daily_selfcheck": {
    "id": "daily_selfcheck",
    "name": "系统自检",
    "description": "每日凌晨自动检查系统健康状态",
    "trigger_type": "cron",
    "task_type": "system",
    "cron_expr": "0 4 * * *",
    "action": "system:daily_selfcheck",
    "enabled": true,
    "last_run": "2026-03-11T04:00:00",
    "next_run": "2026-03-12T04:00:00",
    "fail_count": 0,
    "deletable": false
  }
}
```

### 自动保存

任务状态变更时自动保存到文件。

---

## API 接口

### REST API

```
GET    /api/scheduler/tasks           # 列出所有任务
POST   /api/scheduler/tasks           # 添加任务
GET    /api/scheduler/tasks/{id}      # 获取任务详情
PUT    /api/scheduler/tasks/{id}      # 更新任务
DELETE /api/scheduler/tasks/{id}      # 删除任务
POST   /api/scheduler/tasks/{id}/run  # 手动执行任务
POST   /api/scheduler/pause           # 暂停调度器
POST   /api/scheduler/resume          # 恢复调度器
```

### 示例

```bash
# 添加任务
curl -X POST http://localhost:8080/api/scheduler/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "id": "daily_summary",
    "name": "每日总结",
    "trigger_type": "cron",
    "task_type": "prompt",
    "cron_expr": "0 22 * * *",
    "prompt": "总结今天的对话"
  }'

# 手动执行
curl -X POST http://localhost:8080/api/scheduler/tasks/daily_summary/run
```

---

## 最佳实践

1. **合理设置间隔**：避免任务执行时间过于密集
2. **错误处理**：任务失败时记录日志，避免静默失败
3. **并发控制**：限制最大并发任务数，避免资源耗尽
4. **时区设置**：确保时区配置正确（默认 Asia/Shanghai）
5. **任务命名**：使用清晰的任务名称和描述

---

## 故障排查

### 任务未执行

1. 检查任务是否启用：`enabled=true`
2. 查看 `next_run` 时间是否正确
3. 检查调度器是否运行：`GET /api/scheduler/tasks`
4. 查看日志：`Task triggered: {task_name}`

### Cron 表达式错误

1. 使用在线工具验证：https://crontab.guru/
2. 检查时区设置
3. 查看日志：`Invalid cron expression`

### 任务执行失败

1. 查看 `fail_count` 字段
2. 查看日志：`Scheduled task error`
3. 手动执行任务，查看详细错误

---

## 未来优化方向

1. **任务依赖**：支持任务之间的依赖关系
2. **任务优先级**：高优先级任务优先执行
3. **任务历史**：记录任务执行历史和结果
4. **任务通知**：任务失败时发送通知
