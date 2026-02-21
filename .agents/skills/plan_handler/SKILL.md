---
name: plan_handler
description: 复杂多步任务的状态机规划器。遇到涉及多步骤的长链条任务时，必须先使用此工具创建一个带有 ID 的确切计划，并逐步执行。可有效防止在漫长执行中陷入死循环或偏离最终目标。
allowed-tools: None
---

# 复杂任务规划器 (Plan Handler) 技能手册

`plan_handler` 是系统内置的高级任务统筹防呆机制。由于 AI 面临复杂长链条任务（如"去Github搜索一个项目、克隆下来、分析特定代码、跑测试"）时容易中途遗忘初衷，你**必须**使用这套状态机流转系统。

## 铁律流转范式 (The State Machine Paradigm)

任何耗时预计超过 3 次工具调用的任务，都必须遵循以下生老病死周期：

### 1. 立项设锁：`create_plan`
在动手使用任何实际干活的工具（如 Browser 或 Bash）前，**第一步总是先调用 `create_plan`**。
你不要只是脑子里规划，必须把步骤具象化写入系统：
```json
{
  "action": "create_plan",
  "parameters": {
    "summary": "重构前端登录模块",
    "steps": [
      {"id": "s1", "description": "查看目前 LoginPage.tsx 的代码"},
      {"id": "s2", "description": "编写新的 auth_hook.ts"},
      {"id": "s3", "description": "运行测试确保未破坏现有逻辑"}
    ]
  }
}
```
*注：系统随时只能存在一个活跃计划，不能并发创建。*

### 2. 推进打卡：`update_plan_step`
每当你完成了一个实质性动作（例如你刚刚阅读完了文件，完成了 step1），必须像员工汇报一样，立即调用 `update_plan_step` 标记完成。
这样即使因为上下文截断导致了重启，系统也能知道你进展到了哪里。
```json
{
  "action": "update_plan_step",
  "parameters": {
    "step_id": "s1",
    "status": "completed", 
    "result": "发现代码里将 token 硬编码在了 localStorage，下一步我将提取它"
  }
}
```
`status` 的合法值：`in_progress`, `completed`, `failed`, `skipped`。

### 3. 解锁结案：`complete_plan`
**（最重要的一步！）** 
当你发现所有 steps 都已标记为 `completed` 或 `skipped` 后，你必须立刻调用 `complete_plan` 来销毁当前计划实例，释放全局锁！！否则后续如果用户分配了新目标，你将因为"存在未完结计划"报错而卡死。
```json
{
  "action": "complete_plan",
  "parameters": {
    "summary": "登录模块重构完毕，已成功引入了新的 auth_hook，测试全部通过。"
  }
}
```

---

## 最佳实践：如何应对突发情况

- **死胡同 (Dead End)**：如果在 `s2` 阶段发现原定方案根本不可行（例如缺少某个无法安装的依赖库），请将 `s2` 设置为 `failed`。如果你决定放弃整个大任务，请直接调用 `complete_plan` 结案并告知用户。
- **临时加活 (Scope Creep)**：如果在执行中发现必须插入一个原本没想到的步骤，正常执行它即可，不要求必须修改计划列表，但最终必须要把原本登记在案的 steps 全部打卡完。
- **被系统痛骂有活跃计划却不干活**：通常是因为你忘记了调用 `complete_plan`。立即调用它清理状态。
