# Skills 技能系统

## 概述

SkillManager 是 OpenGuiclaw 的技能注册和执行引擎，提供装饰器风格的技能定义、动态启用/禁用、配置管理和 OpenAI Function Calling 格式转换。

## 架构

```
SkillManager
├── 技能注册表（_registry: Dict[str, SkillDefinition]）
├── 配置持久化（data/skills.json）
├── 装饰器注册（@skill）
├── 同步/异步执行
└── OpenAI 工具定义生成
```

## 核心功能

### 1. 技能定义

```python
@dataclass
class SkillDefinition:
    name: str                          # 技能名称（唯一）
    description: str                   # 描述（LLM 可见）
    parameters: Dict[str, Any]         # JSON Schema 参数定义
    handler: Callable                  # 执行函数
    enabled: bool = True               # 是否启用
    category: str = "general"          # 分类（UI 分组）
    ui_config: List[Dict] = []         # UI 配置项
    config_values: Dict[str, Any] = {} # 配置值
```

### 2. 装饰器注册

```python
skills = SkillManager()

@skills.skill(
    name="get_time",
    description="获取当前时间",
    parameters={
        "properties": {},
        "required": []
    },
    category="basic"
)
def get_time() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")
```

### 3. 参数验证

```python
@skills.skill(
    name="read_file",
    description="读取文件内容",
    parameters={
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径"
            },
            "encoding": {
                "type": "string",
                "description": "编码格式",
                "default": "utf-8"
            }
        },
        "required": ["path"]
    }
)
def read_file(path: str, encoding: str = "utf-8") -> str:
    with open(path, "r", encoding=encoding) as f:
        return f.read()
```

### 4. 动态启用/禁用

```python
# 禁用技能
skills.disable("dangerous_tool")

# 启用技能
skills.enable("dangerous_tool")

# 配置会自动保存到 data/skills.json
```

### 5. 配置管理

```python
# 更新技能配置
skills.update_config("weather", {
    "api_key": "sk-xxx",
    "timeout": 30
})

# 读取配置
skill = skills.get("weather")
api_key = skill.config_values.get("api_key")
```

### 6. 同步/异步执行

```python
# 同步技能
@skills.skill(...)
def sync_tool() -> str:
    return "同步执行"

# 异步技能
@skills.skill(...)
async def async_tool() -> str:
    await asyncio.sleep(1)
    return "异步执行"

# 统一执行接口（自动检测）
result = await skills.execute("tool_name", {"param": "value"})
```

## API 接口

### 初始化

```python
from core.skills import SkillManager

skills = SkillManager(config_path="data/skills.json")
```

### 注册技能

```python
# 方式 1: 装饰器
@skills.skill(
    name="my_tool",
    description="我的工具",
    parameters={"properties": {}, "required": []},
    category="custom"
)
def my_tool() -> str:
    return "完成"

# 方式 2: 手动注册
from core.skills import SkillDefinition

skills.register(SkillDefinition(
    name="manual_tool",
    description="手动注册的工具",
    parameters={"properties": {}, "required": []},
    handler=lambda: "完成",
    category="custom"
))
```

### 执行技能

```python
# 异步执行（推荐）
result = await skills.execute("tool_name", {"param": "value"})

# 错误处理
try:
    result = await skills.execute("tool_name", {})
except Exception as e:
    print(f"执行失败: {e}")
```

### 查询技能

```python
# 获取单个技能
skill = skills.get("tool_name")
if skill:
    print(f"{skill.name}: {skill.description}")

# 列出所有启用的技能
for skill in skills.list_enabled():
    print(f"- {skill.name} ({skill.category})")

# 生成摘要
print(skills.summary())
```

### 生成工具定义

```python
# 转换为 OpenAI Function Calling 格式
tools = skills.get_tool_definitions()

# 传递给 LLM
response = client.chat.completions.create(
    model="qwen-max",
    messages=[...],
    tools=tools
)
```

## 配置

### data/skills.json 结构

```json
{
  "weather": {
    "enabled": true,
    "config_values": {
      "api_key": "sk-xxx",
      "timeout": 30
    }
  },
  "dangerous_tool": {
    "enabled": false,
    "config_values": {}
  }
}
```

### UI 配置项

```python
@skills.skill(
    name="configured_tool",
    description="带配置的工具",
    parameters={"properties": {}, "required": []},
    ui_config=[
        {
            "key": "api_key",
            "label": "API Key",
            "type": "password",
            "required": True
        },
        {
            "key": "timeout",
            "label": "超时时间（秒）",
            "type": "number",
            "default": 30
        },
        {
            "key": "mode",
            "label": "模式",
            "type": "select",
            "options": ["fast", "accurate"]
        }
    ]
)
def configured_tool() -> str:
    skill = skills.get("configured_tool")
    api_key = skill.config_values.get("api_key")
    timeout = skill.config_values.get("timeout", 30)
    mode = skill.config_values.get("mode", "fast")
    # 使用配置...
```

## 最佳实践

### 1. 参数设计

```python
# 好的参数设计
@skills.skill(
    name="search",
    description="搜索文件内容",
    parameters={
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "path": {
                "type": "string",
                "description": "搜索路径（可选）",
                "default": "."
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "是否区分大小写",
                "default": False
            }
        },
        "required": ["query"]
    }
)
def search(query: str, path: str = ".", case_sensitive: bool = False) -> str:
    # 实现...
```

### 2. 错误处理

```python
@skills.skill(...)
def safe_tool(path: str) -> str:
    try:
        # 危险操作
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return f"错误: 文件 {path} 不存在"
    except PermissionError:
        return f"错误: 没有权限读取 {path}"
    except Exception as e:
        return f"错误: {str(e)}"
```

### 3. 长时间操作

```python
@skills.skill(...)
def long_running_tool() -> str:
    import time
    # 分段报告进度
    for i in range(10):
        time.sleep(1)
        # 可以通过日志或回调报告进度
    return "完成"
```

### 4. 资源清理

```python
@skills.skill(...)
def resource_tool() -> str:
    resource = acquire_resource()
    try:
        result = use_resource(resource)
        return result
    finally:
        release_resource(resource)
```

### 5. 分类管理

```python
# 按功能分类
categories = {
    "basic": ["read_file", "write_file", "get_time"],
    "web": ["web_search", "web_fetch"],
    "gui": ["click", "type", "screenshot"],
    "memory": ["remember", "search_memory"],
    "system": ["run_command", "list_processes"]
}

# 在 UI 中按分类展示
for category, skill_names in categories.items():
    print(f"## {category}")
    for name in skill_names:
        skill = skills.get(name)
        if skill:
            print(f"- {skill.description}")
```

## 故障排查

### 问题 1: 技能未注册

**症状**：`skills.get("tool_name")` 返回 None

**解决方案**：
```python
# 检查注册表
print(list(skills._registry.keys()))

# 确认装饰器已执行
# 确保插件已加载
```

### 问题 2: 参数类型错误

**症状**：LLM 传递的参数类型不匹配

**解决方案**：
```python
@skills.skill(...)
def typed_tool(count: int) -> str:
    # 添加类型转换
    count = int(count)
    return f"处理了 {count} 个项目"
```

### 问题 3: 异步执行失败

**症状**：`await skills.execute()` 报错

**解决方案**：
```python
# 确保在异步上下文中调用
async def main():
    result = await skills.execute("tool_name", {})

# 或者使用 asyncio.run()
import asyncio
result = asyncio.run(skills.execute("tool_name", {}))
```

### 问题 4: 配置丢失

**症状**：重启后配置恢复默认值

**解决方案**：
```python
# 检查配置文件
import json
with open("data/skills.json", "r") as f:
    config = json.load(f)
    print(config)

# 手动保存
skills._save_config()
```

## 性能优化

### 1. 缓存结果

```python
from functools import lru_cache

@skills.skill(...)
def cached_tool(key: str) -> str:
    return _cached_impl(key)

@lru_cache(maxsize=128)
def _cached_impl(key: str) -> str:
    # 昂贵的计算
    return result
```

### 2. 并发执行

```python
@skills.skill(...)
async def concurrent_tool(urls: list) -> str:
    import asyncio
    import aiohttp
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
    
    return "\n".join(results)
```

### 3. 延迟导入

```python
@skills.skill(...)
def heavy_tool() -> str:
    # 只在需要时导入
    import tensorflow as tf
    # 使用 tensorflow...
```

## 内置技能示例

### 1. remember（记忆写入）

```python
@skills.skill(
    name="remember",
    description="将重要信息写入长期记忆",
    parameters={
        "properties": {
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["content"]
    },
    category="memory"
)
def remember(content: str, tags: list = None):
    item = memory.add(content, tags or [])
    return f"✅ 已记住: {item.content}"
```

### 2. search_memory（记忆搜索）

```python
@skills.skill(
    name="search_memory",
    description="搜索长期记忆、日记、日志、知识图谱",
    parameters={
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    },
    category="memory"
)
def search_memory(query: str):
    # 并发搜索多个数据源
    results = []
    results.append(_search_journal(query))
    results.append(_search_diary(query))
    results.append(_search_vector(query))
    results.append(_search_kg(query))
    return "\n\n".join(results)
```

### 3. web_fetch（网页抓取）

```python
@skills.skill(
    name="web_fetch",
    description="抓取指定网页的正文内容",
    parameters={
        "properties": {
            "url": {"type": "string"}
        },
        "required": ["url"]
    },
    category="web"
)
def web_fetch(url: str) -> str:
    import requests
    from bs4 import BeautifulSoup
    
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, "html.parser")
    return soup.get_text()
```

## 未来优化方向

1. **技能依赖管理**：声明技能间的依赖关系
2. **技能组合**：将多个技能组合成工作流
3. **技能权限**：基于角色的技能访问控制
4. **技能版本**：支持技能升级和回滚
5. **技能市场**：从远程仓库安装技能
6. **技能监控**：统计技能调用频率和成功率
