# 系统自检模块 (Self-Check)

## 概述

系统自检模块负责定期扫描日志错误、分析问题根因、自动修复能力层错误，并生成健康报告。

**文件位置**: `core/self_check.py`, `core/tasks.py::_system_daily_selfcheck`

**调度方式**: 每日凌晨 04:00 自动执行（通过 TaskScheduler）

---

## 核心功能

### 1. 日志错误收集

从日志文件中提取 ERROR 和 CRITICAL 级别的错误：

```python
def gather_recent_errors(self, max_lines: int = 50) -> list[str]:
    """从 *.log 和 logs/*.log 中提取最近 50 条错误"""
```

- 扫描范围：项目根目录 `*.log` 和 `logs/*.log`
- 每个文件读取最后 500 行
- 按修改时间倒序扫描

### 2. Memory 集成

从长期记忆中提取历史错误教训：

```python
error_memories = self.agent.memory.list_by_type("error")
```

- 提取 `type="error"` 的记忆条目
- 最多取 20 条最近的错误记忆
- 与日志错误一起提交给 LLM 分析

### 3. LLM 驱动分析

使用 Qwen 模型分析错误并决定修复策略：

**输入**：
- 日志错误（最近发生）
- 历史错误记忆（长期存储）

**输出** (JSON 格式)：
```json
{
  "errors": [
    {
      "component": "channels/dingtalk",
      "error_pattern": "连接超时",
      "error_type": "channel",
      "is_core": false,
      "can_fix": true,
      "fix_instruction": "重启 DingTalk 适配器",
      "from_memory": false
    }
  ]
}
```

### 4. 分层修复策略

**只允许修复的类型**：
```python
_ALLOWED_FIX_TYPES = {"tool", "skill", "channel", "plugin", "mcp"}
```

**Core 层错误**（不修复）：
- `core/` 目录核心文件
- 引擎启动错误
- 数据库错误
- 标记为 `can_fix=false`，只记录到报告

**能力层错误**（自动修复）：
- `plugins/` 插件
- `skills/` 技能
- `channels/` IM 通道
- MCP 相关错误

### 5. 重试 + 降级机制

```python
async def _fix_with_retry(self, component, error_pattern, instruction, push_fn, max_retries=2):
    """最多重试 2 次，失败后降级到脚本级修复"""
```

**执行流程**：
1. 尝试执行修复指令（shell 命令或 Python 代码）
2. 验证修复是否成功
3. 失败则重试（最多 2 次）
4. 全部失败后进入脚本级降级

**脚本级降级策略**：
- 缓存错误 → 清理 `data/cache/`
- 文件缺失 → 重建必要目录
- 其他 → 提示人工检查

### 6. 修复验证

根据组件类型执行针对性测试：

| 组件类型 | 验证方法 |
|---------|---------|
| file/memory/session/data | 临时文件读写测试 |
| shell/subprocess/system | `echo verify_ok` 命令测试 |
| channel/plugin/skill/mcp | 目录存在性检查 |
| 其他 | data 目录检查 |

### 7. Memory 清理

修复成功后，删除对应的 error 记忆：

```python
def _cleanup_fixed_error_memory(self, component, error_pattern):
    """匹配组件名或错误模式，删除相关 error 记忆"""
```

**匹配规则**：
- 记忆内容包含组件名（不区分大小写）
- 记忆内容包含错误模式（不区分大小写）

---

## 安全机制

### 危险命令拦截

拒绝执行以下命令：
```python
_DENY_PATTERNS = [
    "powershell", "pwsh", "reg.exe", "regedit", "icacls",
    "netsh", "schtasks", "taskkill", "shutdown", "format",
    "rm -rf /", "del /s /q c:\\"
]
```

### 执行超时

所有修复指令限制 30 秒超时，避免阻塞。

---

## 报告格式

### Markdown 报告示例

```markdown
## 🔍 系统自检报告 — 2026-03-11 04:00

**Agent 状态**: ✅ 在线
**会话文件**: 15 个
**记忆条目**: 234 条

**计划任务**: 共 5 个，启用 4 个，有失败记录 1 个

**日志错误** (12 条):
  - `channels.dingtalk`: 3 次
  - `plugins.browser`: 2 次

  *AI 诊断*: 核心错误 **1** 个 (需人工处理)，能力层错误 **2** 个，自动修复成功 **1** 个

**自动修复 / 诊断建议**:
  - 🔴 [需人工处理] `core.agent`: 内存溢出
    👉 需人工干预 (Core 层)
  - ✅ [已自动修复] `channels.dingtalk`: 连接超时 (历史记忆)
    👉 执行修复: 重启 DingTalk 适配器
    🔍 验证: 目录验证通过（需手动确认功能）
  - ⚠️ [修复失败] `plugins.browser`: 浏览器进程僵死
    👉 脚本降级: 无法自动修复，需人工检查

**总结**: ⚠️ 发现 0 个问题，2 个错误模块
```

---

## 配置

### 定时任务配置

在 `core/server.py::lifespan()` 中注册：

```python
await scheduler.add_task(ScheduledTask(
    id="system_daily_selfcheck",
    name="系统自检",
    cron_expr="0 4 * * *",  # 每日凌晨 04:00
    description="每日凌晨自动检查数据目录、日志错误、任务状态，生成健康报告",
    trigger_type=TriggerType.CRON,
    task_type=TaskType.SYSTEM,
    action="system:daily_selfcheck",
    deletable=False,
))
```

### 手动触发

通过 Web UI 的"计划任务"面板，点击"立即执行"按钮。

---

## 依赖

- **LLM**: Qwen 模型（用于错误分析）
- **Memory**: `core/memory.py::MemoryManager`
- **Scheduler**: `core/scheduler/scheduler.py::TaskScheduler`

---

## 最佳实践

1. **定期查看报告**：每天早上检查自检报告，关注 Core 层错误
2. **手动确认修复**：自动修复后，手动测试相关功能是否正常
3. **记录错误教训**：遇到新错误时，用 `add_memory(type="error")` 记录到长期记忆
4. **清理过期记忆**：定期清理已修复的 error 记忆（自动清理机制已内置）

---

## 故障排查

### 自检任务未执行

1. 检查 TaskScheduler 是否启动：`GET /api/scheduler/tasks`
2. 查看任务状态：`fail_count` 是否 > 0
3. 查看日志：`openguiclaw.log` 中搜索 `System selfcheck`

### 修复失败

1. 查看报告中的 `fix_action` 和 `verification_result`
2. 手动执行修复指令，查看详细错误
3. 如果是 Core 层错误，需要人工修复

### Memory 清理失败

1. 检查 `agent.memory` 是否初始化
2. 查看日志：`Failed to cleanup error memory`
3. 手动删除：通过 Web UI 的"记忆管理"面板

---

## 未来优化方向

1. **修复历史记录**：保存每次修复的详细日志，供审计
2. **修复成功率统计**：按组件类型统计修复成功率
3. **自动学习修复策略**：从成功的修复中学习，优化 LLM prompt
4. **多模型支持**：支持切换不同的 LLM 模型进行分析
