---
name: sandbox_repl
description: 状态隔离的 Python 沙箱运行环境。与普通的 execute_command(python -c ...) 不同，沙箱中的变量、定义的函数、甚至导入的依赖库都会跨回合保留。当你需要分步运行复杂的 Python 数据处理、读取 API 聚合信息，或进行算法调试时优先使用此工具。
allowed-tools: None
---

# Sandbox REPL 状态沙箱技能手册

`sandbox_repl` 模块提供了一个**持续存活 (Stateful)**的 Python 子进程。这极大地颠覆了传统 AI 只能单次无状态执行代码的局限。

## 核心特性：状态持久化 (State Persistence)

当你连续两次调用该工具运行代码时，第二次依然可以访问第一次定义的变量！

### 正确范例
**第一步：**
```python
import xarray as xr
dataset = xr.open_dataset("weather.nc")
print(f"Loaded variables: {list(dataset.variables)}")
```
*(获取了打印输出后，你可以接着下一步，无需重新加载文件或重新导入包)*

**第二步：**
```python
# 'dataset' 和 'xr' 依旧存在于内存中，可直接计算并打印
mean_temp = dataset["temperature"].mean().item()
print(f"Mean temperature is {mean_temp}")
```

### 何时必须要用 Sandbox REPL？

1. **大文件/大模型加载**：如果你的代码需要加载几百MB的数据集或极其耗时的依赖（如 `torch`, `pandas`），请绝对避免使用 `execute_command` 每次重新加载！
2. **多步调试 (Step-by-step Debugging)**：当你写了一大段复杂逻辑不确定是否成功时，将代码拆成多块，每块执行后返回结果，利用 Sandbox 在上下文不丢失的情况下稳步推进。

## 暴露的 Tool: `run_sandbox_code`

暴露给你的函数名为 `run_sandbox_code`，只接受一个必须参数 `code` (类型:字符串)。

```json
{
  "action": "run_sandbox_code",
  "parameters": {
    "code": "import math\nprint(math.pi)"
  }
}
```

> [!TIP]
> **自动包裹机制**：你传入的代码会被自动包裹在 `try...except` 中执行，任何异常（如语法错误、运行时错误）都会被捕获并作为错误堆栈信息返回给你，不会导致沙箱崩溃。

## 重置与恢复机制

如果因为死循环（Timeout）或系统原因导致子进程异常阻塞，`run_sandbox_code` 在检测到底层进程不再响应或出错时，**会自动重启 `python -i` 进程**。

> [!WARNING]
> 一旦发生进程重启，之前所有的内存变量和状态都会被清空。系统会在返回的信息中提示您重新导入依赖或初始化变量。
