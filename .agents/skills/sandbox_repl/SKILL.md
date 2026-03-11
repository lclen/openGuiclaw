---
name: sandbox_repl
description: 状态隔离的 Python 沙箱运行环境。与普通的 execute_command(python -c ...) 不同，沙箱中的变量、定义的函数、甚至导入的依赖库都会跨回合保留。当你需要分步运行复杂的 Python 数据处理、读取 API 聚合信息，或进行算法调试时优先使用此工具。
allowed-tools: None
---

# Python 执行环境指南 (Sandbox & Bridge)

为了平衡安全与功能，系统提供了两种 Python 执行环境：**Sandbox REPL (沙箱模式)** 和 **Python Bridge (桥接模式)**。

---

## 1. Sandbox REPL (沙箱模式)

`sandbox_repl` 提供了一个**持续存活 (Stateful)** 且受限的 Python 环境。

### 核心特性：状态持久化 (State Persistence)
当你连续两次调用该工具运行代码时，第二次依然可以访问第一次定义的变量！

#### 使用场景
1. **分步调试 (Step-by-step)**：将复杂逻辑拆分为多步执行，中间结果可保留。
2. **重型库加载**：只需在第一步 `import pandas as pd`，后续步骤即可直接使用 `pd`。

#### 暴露的 Tool: `run_in_sandbox`
必须参数: `python_code` (字符串)。可选参数: `sandbox_id` (用于分组状态)。

```json
{
  "action": "run_in_sandbox",
  "parameters": {
    "python_code": "x = 10\nprint(x * 2)",
    "sandbox_id": "math_task"
  }
}
```

---

## 2. Python Bridge (桥接模式)

`python_bridge` 提供了一个**完全不受限 (Unconstrained)** 的原生 Python 环境。

### 为什么需要桥接模式？
由于沙箱模式基于 `RestrictedPython`，它严禁文件读写、系统调用。当你需要处理本地文件、调用复杂 C 扩展库（如 OpenCV）或进行大规模 IO 时，必须使用桥接模式。

### 核心特性：全权限与子进程隔离
1. **无限制导入**：支持所有已安装的第三方库。
2. **文件系统访问**：可以直接读取、修改、删除本地文件。
3. **独立进程**：每次执行都是一个全新的 `subprocess`，不保留变量状态。

#### 暴露的 Tool: `execute_python_script`
必须参数: `script` (完整的 Python 脚本字符串)。

#### 正确范例
```python
import os
import pandas as pd

# 读取本地 CSV 并进行复杂处理
if os.path.exists("data.csv"):
    df = pd.read_csv("data.csv")
    result = df.describe()
    print(result)
else:
    print("找不到文件")
```

---

## 3. 沙箱 (Sandbox) vs 桥接 (Bridge) 抉择指南

| 特性 | Sandbox REPL (`run_in_sandbox`) | Python Bridge (`execute_python_script`) |
| :--- | :--- | :--- |
| **执行机制** | RestrictedPython (AST层劫持) | Subprocess (拉起原生子进程) |
| **状态持久化**| **支持** (变量跨步保留) | **不支持** (单次运行，环境清理) |
| **安全性** | **极高** (禁止 I/O 和危险调用) | **普通** (拥有当前用户的全权限) |
| **常用库支持** | numpy, pandas, json, requests | **所有库** (OpenCV, OS, Subprocess 等) |
| **最佳用例** | 数据探究、逻辑验证、逐步交互 | **文件处理、系统自动化、重型库调用** |

> [!IMPORTANT]
> **默认建议**：优先使用 `run_in_sandbox` 进行逻辑运算。当遇到 `ImportError`（模块被禁用）或 `PermissionError`（无法访问文件）时，请主动切换到 `execute_python_script`。
