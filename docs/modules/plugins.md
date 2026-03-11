# Plugin 插件系统

## 概述

PluginManager 提供热加载插件机制，允许在运行时动态加载、卸载和重载插件。每个插件是一个独立的 Python 文件，通过 `register(skills_manager)` 函数注册技能。

## 架构

```
PluginManager
├── 插件扫描（plugins/ 目录）
├── 动态加载（importlib）
├── 热重载（文件监视）
├── 技能注册（SkillManager 集成）
└── 元数据管理（PLUGIN_INFO）
```

## 核心功能

### 1. 插件结构

```python
# plugins/my_plugin.py

PLUGIN_INFO = {
    "name": "My Plugin",
    "description": "Does something useful.",
    "version": "1.0.0",
    "author": "You",
}

def register(manager):
    @manager.skill(
        name="my_tool",
        description="Does something.",
        parameters={
            "properties": {
                "text": {"type": "string"}
            },
            "required": ["text"]
        },
        category="my_plugin",
    )
    def my_tool(text: str) -> str:
        return f"Result: {text}"
```

### 2. 热加载机制

```python
# 启动时加载所有插件
plugin_mgr.load_all()

# 启动文件监视器（自动热重载）
plugin_mgr.start_watcher(interval=1.0)

# 手动重载单个插件
plugin_mgr.reload("my_plugin")
```

### 3. 插件生命周期

```
[新建] → [加载] → [注册技能] → [运行]
                ↓
            [修改文件]
                ↓
            [自动卸载] → [重新加载] → [重新注册]
                ↓
            [删除文件]
                ↓
            [自动卸载]
```

### 4. 技能隔离

```python
# 每个插件注册的技能会被记录
info = PluginInfo(
    name="my_plugin",
    path=path,
    module=module,
    registered_skills=["my_tool", "another_tool"]
)

# 卸载时自动清除所有技能
for skill_name in info.skills:
    skills_manager._registry.pop(skill_name, None)
```

## API 接口

### 初始化

```python
from core.plugin_manager import PluginManager
from core.skills import SkillManager

skills = SkillManager()
plugins = PluginManager(skills, plugins_dir="plugins")
```

### 加载插件

```python
# 加载所有插件
loaded = plugins.load_all()
print(f"已加载: {loaded}")

# 加载单个插件
name = plugins.load("my_plugin.py")
if name:
    print(f"插件 {name} 加载成功")
```

### 重载插件

```python
# 热重载（不重启程序）
success = plugins.reload("my_plugin")

# 重载所有插件
reloaded = plugins.reload_all()
```

### 卸载插件

```python
# 卸载插件（移除所有技能）
plugins.unload("my_plugin")
```

### 查询插件

```python
# 列出所有插件
for info in plugins.list_plugins():
    print(f"{info.name} v{info.version} - {info.description}")

# 获取摘要
print(plugins.summary())
```

### 文件监视

```python
# 启动自动监视（推荐）
plugins.start_watcher(interval=1.0)

# 停止监视
plugins.stop_watcher()
```

## 配置

### 插件元数据（可选）

```python
PLUGIN_INFO = {
    "name": "Weather Plugin",        # 显示名称
    "description": "查询天气信息",    # 描述
    "version": "1.0.0",              # 版本号
    "author": "OpenGuiclaw Team",    # 作者
}
```

### 技能配置

```python
@manager.skill(
    name="weather",
    description="查询指定城市的天气",
    parameters={
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称"
            }
        },
        "required": ["city"]
    },
    category="weather",  # 分类（用于 UI 分组）
    enabled=True,        # 默认启用
    ui_config=[          # UI 配置项（可选）
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password"
        }
    ]
)
def weather(city: str) -> str:
    # 从技能配置读取 API Key
    api_key = manager.get("weather").config_values.get("api_key")
    # 实现逻辑...
    return f"{city} 的天气是晴天"
```

## 最佳实践

### 1. 插件命名规范

```
plugins/
├── basic.py           # 基础工具（文件、时间）
├── autogui.py         # GUI 自动化
├── web_search.py      # 网页搜索
├── plan_handler.py    # 计划执行
└── mcp_gateway.py     # MCP 协议网关
```

- 使用小写 + 下划线
- 避免与 Python 内置模块冲突
- 不要以 `_` 开头（会被跳过）

### 2. 错误处理

```python
def register(manager):
    @manager.skill(
        name="risky_tool",
        description="可能失败的工具",
        parameters={"properties": {}, "required": []}
    )
    def risky_tool() -> str:
        try:
            # 危险操作
            result = do_something_risky()
            return f"成功: {result}"
        except Exception as e:
            # 返回错误信息（不要抛出异常）
            return f"错误: {str(e)}"
```

### 3. 异步支持

```python
@manager.skill(
    name="async_tool",
    description="异步工具",
    parameters={"properties": {}, "required": []}
)
async def async_tool() -> str:
    import asyncio
    await asyncio.sleep(1)
    return "异步执行完成"
```

### 4. 依赖管理

```python
def register(manager):
    # 检查依赖
    try:
        import requests
    except ImportError:
        print("[Plugin] weather 插件需要 requests 库")
        return
    
    # 注册技能
    @manager.skill(...)
    def weather(...):
        ...
```

### 5. 配置持久化

```python
# 技能配置会自动保存到 data/skills.json
# 重载后配置会自动恢复

@manager.skill(
    name="configured_tool",
    description="带配置的工具",
    parameters={"properties": {}, "required": []},
    ui_config=[
        {"key": "api_key", "label": "API Key", "type": "password"},
        {"key": "timeout", "label": "超时时间", "type": "number"}
    ]
)
def configured_tool() -> str:
    skill = manager.get("configured_tool")
    api_key = skill.config_values.get("api_key", "")
    timeout = skill.config_values.get("timeout", 30)
    # 使用配置...
```

## 故障排查

### 问题 1: 插件加载失败

**症状**：`load_all()` 返回空列表

**解决方案**：
```python
# 检查插件目录
import os
print(os.listdir("plugins"))

# 检查插件文件
# 必须有 register(manager) 函数
# 不能以 _ 开头
```

### 问题 2: 热重载不工作

**症状**：修改插件文件后没有自动重载

**解决方案**：
```python
# 检查监视器状态
if plugins._watcher_thread and plugins._watcher_thread.is_alive():
    print("监视器正在运行")
else:
    print("监视器未启动")
    plugins.start_watcher()

# 检查文件修改时间
import time
mtime = os.path.getmtime("plugins/my_plugin.py")
print(f"文件修改时间: {time.ctime(mtime)}")
```

### 问题 3: 技能冲突

**症状**：两个插件注册了同名技能

**解决方案**：
```python
# 使用唯一的技能名称
@manager.skill(
    name="plugin_name.tool_name",  # 加前缀
    ...
)

# 或者在插件中检查
if manager.get("tool_name"):
    print("技能名称已被占用")
    return
```

### 问题 4: 卸载后技能仍可用

**症状**：`unload()` 后技能仍在注册表中

**解决方案**：
```python
# 检查技能注册表
print(list(skills_manager._registry.keys()))

# 手动清除
skills_manager._registry.pop("tool_name", None)

# 重新加载配置
skills_manager._load_config()
```

## 性能优化

### 1. 延迟加载

```python
# 只在需要时导入重型依赖
def register(manager):
    @manager.skill(...)
    def heavy_tool():
        import tensorflow  # 延迟导入
        # 使用 tensorflow...
```

### 2. 缓存结果

```python
_cache = {}

@manager.skill(...)
def cached_tool(key: str) -> str:
    if key in _cache:
        return _cache[key]
    result = expensive_operation(key)
    _cache[key] = result
    return result
```

### 3. 并发控制

```python
import threading

_lock = threading.Lock()

@manager.skill(...)
def thread_safe_tool() -> str:
    with _lock:
        # 线程安全操作
        return "完成"
```

## 内置插件示例

### 1. plan_handler.py

多步骤计划执行，支持自驾/确认/普通三种模式。

### 2. mcp_gateway.py

MCP 协议网关，动态加载 MCP 服务器的工具。

### 3. skill_creator.py

AI 自主创建新插件（元编程）。

### 4. browser.py

浏览器操作（基于 Playwright MCP）。

### 5. system.py

Shell 命令执行（带安全检查）。

## 未来优化方向

1. **插件依赖管理**：自动安装插件所需的 Python 包
2. **插件市场**：从远程仓库安装插件
3. **插件沙箱**：隔离插件运行环境（RestrictedPython）
4. **插件版本控制**：支持插件升级和回滚
5. **插件权限系统**：限制插件可访问的资源
6. **插件性能监控**：统计插件执行时间和资源消耗
