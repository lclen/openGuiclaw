# Identity Manager 人设管理系统

## 概述

IdentityManager 管理 AI 的身份层（Identity Layer），包括用户档案（USER.md）、交互习惯（HABITS.md）和 Agent 行为规范（AGENT.md）。它是新一代的人设管理架构，替代了旧的 `user_profile.json` 和 `interaction_habits.md`。

## 架构

```
IdentityManager
├── data/identity/
│   ├── USER.md      # 用户档案（客观信息）
│   ├── HABITS.md    # 交互习惯与约束规则
│   └── AGENT.md     # Agent 行为规范（可选）
├── 自动时间戳更新
├── Prompt 注入
└── 旧文件迁移
```

## 核心功能

### 1. 文件结构

**USER.md**（用户档案 v2.0）：

采用 OpenAkita 风格的结构化 Markdown 格式，比简单列表更易读：

```markdown
# User Profile
<!--
参考来源:
- GitHub Copilot Memory
- ai-agent-memory-system

此文件由 OpenGuiclaw 自动学习和更新，记录用户的偏好和习惯。
-->

## Basic Information

- **称呼**: [待学习]
- **工作领域**: [待学习]
- **主要语言**: 中文
- **时区**: [待学习]

## Technical Stack

### Preferred Languages

[待学习]

### Frameworks & Tools

[待学习]

### Development Environment

- **OS**: [待学习]
- **IDE**: [待学习]
- **Shell**: [待学习]

## Preferences

### Communication Style

- **详细程度**: [待学习]
- **代码注释**: [待学习]
- **解释方式**: [待学习]

### Code Style

- **命名约定**: [待学习]
- **格式化工具**: [待学习]
- **测试框架**: [待学习]

### Work Habits

- **工作时间**: [待学习]
- **响应速度偏好**: [待学习]
- **确认需求**: [待学习]

---

*此文件由 OpenGuiclaw 自动维护。用户也可以手动编辑以提供更准确的信息。*
*最后更新: 2026-03-11 15:30*
```

**HABITS.md**（交互习惯）：
```markdown
# 交互习惯与约束规则 (HABITS)
<!-- updated: 2026-03-11 -->

## 代码风格
- 使用下划线命名（snake_case）
- 所有文件必须 UTF-8 编码

## 回复风格
- 简洁直接，不要废话
- 代码示例必须完整可运行

<!-- 自动进化 2026-03-11 -->
- 用户不喜欢看到长篇大论的解释
```

**AGENT.md**（Agent 行为规范，可选）：
```markdown
# Agent 行为规范

你是 OpenGuiclaw AI 助手，基于 Qwen 模型。

## 核心原则
- 主动思考，不要被动等待指令
- 优先使用工具，而不是猜测
- 遇到错误时自动重试
```

### 2. 用户档案管理（v2.0）

**智能更新机制**：

```python
# 更新用户信息（自动处理结构化 Markdown）
identity.update_user("称呼", "张三")
identity.update_user("工作领域", "AI 开发")
identity.update_user("OS", "Windows 11")

# 读取用户信息
user_data = identity.get_user()
# {"称呼": "张三", "工作领域": "AI 开发", "OS": "Windows 11", ...}
```

**更新逻辑**：

1. 如果 key 已存在（如 `称呼`），直接替换该行
2. 如果 key 不存在，插入到 `## Basic Information` 章节的最后一个 `- **` 行之后
3. 自动更新底部时间戳：`*最后更新: 2026-03-11 15:30*`

**预定义 Key 列表**（与 `self_evolution.py` 的 `EXTRACTION_PROMPT` 保持一致）：

```python
ALLOWED_KEYS = [
    "称呼", "工作领域", "主要语言", "时区",
    "OS", "IDE", "Shell",
    "详细程度", "代码注释", "解释方式",
    "命名约定", "格式化工具", "测试框架",
    "工作时间", "响应速度偏好", "确认需求"
]
```

**实现细节**：

```python
def update_user(self, key: str, value: str) -> None:
    """Update or insert a key-value pair in USER.md.
    
    Supports structured Markdown format with sections.
    """
    text = self._read(self.user_path)
    pattern = rf"^- \*\*{re.escape(key)}\*\*: .*$"
    new_line = f"- **{key}**: {value}"
    
    if re.search(pattern, text, flags=re.MULTILINE):
        # Key exists, replace it
        text = re.sub(pattern, new_line, text, flags=re.MULTILINE)
    else:
        # Key doesn't exist, insert in Basic Information section
        lines = text.split('\n')
        in_basic = False
        last_item_idx = -1
        
        for i, line in enumerate(lines):
            if '## Basic Information' in line:
                in_basic = True
            elif line.startswith('##') and in_basic:
                break
            elif in_basic and line.startswith('- **'):
                last_item_idx = i
        
        if last_item_idx >= 0:
            lines.insert(last_item_idx + 1, new_line)
            text = '\n'.join(lines)
        else:
            # Fallback: append to end
            text = text.rstrip("\n") + f"\n{new_line}\n"
    
    self._write(self.user_path, text)
    self._update_timestamp(self.user_path)
```

### 3. 习惯管理

```python
# 追加新习惯
identity.append_habit("- 用户喜欢用 Vim")

# 修改现有习惯
identity.modify_habit(
    target="用户喜欢用 Vim",
    replacement="用户喜欢用 Neovim"
)

# 读取所有习惯
habits = identity.get_habits()
```

### 4. Prompt 注入

```python
# 构建系统 Prompt
prompt = identity.build_prompt()

# 返回格式：
# AGENT.md 内容
# 
# USER.md 内容（完整的结构化 Markdown）
# 
# HABITS.md 内容
# 
# # 核心记忆（来自 scene_memory.jsonl）
# ## 偏好
# - 用户喜欢简洁的回复
# ## 规则
# - 所有文件必须 UTF-8 编码
```

**注意**：USER.md 会完整注入，包括所有章节和占位符。LLM 会自动忽略 `[待学习]` 占位符。

### 5. 自动时间戳（双格式支持）

```python
# 每次更新时自动更新时间戳
identity.update_user("称呼", "张三")

# USER.md 底部的时间戳会自动更新：
# *最后更新: 2026-03-11 15:30*

# HABITS.md 和 AGENT.md 使用 comment 格式：
# <!-- updated: 2026-03-11 -->
```

**实现细节**：

```python
def _update_timestamp(self, path: Path) -> None:
    """Replace or insert the timestamp in a file.
    
    Supports two formats:
    1. <!-- updated: YYYY-MM-DD --> (for HABITS.md, AGENT.md)
    2. *最后更新: YYYY-MM-DD HH:MM* (for USER.md)
    """
    text = self._read(path)
    today = self._today()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Try USER.md format first
    user_pattern = r"\*最后更新: [^\*]+\*"
    if re.search(user_pattern, text):
        text = re.sub(user_pattern, f"*最后更新: {now}*", text)
    else:
        # Try comment format
        comment_pattern = r"<!-- updated: \d{4}-\d{2}-\d{2}[^>]* -->"
        ts = f"<!-- updated: {today} -->"
        if re.search(comment_pattern, text):
            text = re.sub(comment_pattern, ts, text, count=1)
        else:
            # Insert after first line
            lines = text.splitlines(keepends=True)
            if lines:
                lines.insert(1, ts + "\n")
                text = "".join(lines)
    
    self._write(path, text)
```

### 6. 旧文件迁移

```python
# 一次性迁移旧文件
identity.migrate_from_legacy(
    profile_path="data/user_profile.json",
    habits_path="data/interaction_habits.md",
    identities_default_path="data/identities/default.md"
)

# 迁移后原文件会重命名为 .bak
```

## API 接口

### 初始化

```python
from core.identity_manager import IdentityManager

identity = IdentityManager(data_dir="data")
```

### 用户档案操作

```python
# 更新用户信息
identity.update_user("姓名", "张三")
identity.update_user("年龄", "25")
identity.update_user("职业", "软件工程师")

# 读取用户信息
user_data = identity.get_user()
print(user_data)
# {"姓名": "张三", "年龄": "25", "职业": "软件工程师"}
```

### 习惯操作

```python
# 追加习惯
identity.append_habit("""
## 新增规则
- 代码必须有注释
- 函数必须有文档字符串
""")

# 修改习惯
success = identity.modify_habit(
    target="代码必须有注释",
    replacement="代码必须有详细注释"
)

# 读取习惯
habits = identity.get_habits()
print(habits)
```

### Prompt 构建

```python
# 构建完整的系统 Prompt
system_prompt = identity.build_prompt()

# 传递给 LLM
response = client.chat.completions.create(
    model="qwen-max",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "你好"}
    ]
)
```

### 迁移

```python
# 从旧文件迁移
identity.migrate_from_legacy(
    profile_path="data/user_profile.json",
    habits_path="data/interaction_habits.md",
    identities_default_path="data/identities/default.md"
)
```

## 配置

### 文件位置

```
data/identity/
├── USER.md      # 用户档案
├── HABITS.md    # 交互习惯
└── AGENT.md     # Agent 行为规范（可选）
```

### 时间戳格式

```markdown
<!-- updated: 2026-03-11 -->
```

## 最佳实践

### 1. 用户档案分层

```python
# 客观信息（objective）
identity.update_user("姓名", "张三")
identity.update_user("年龄", "25")
identity.update_user("职业", "软件工程师")

# 主观偏好（subjective）→ 放到 HABITS.md
identity.append_habit("- 用户喜欢简洁的回复")
```

### 2. 习惯分类

```markdown
# 交互习惯与约束规则 (HABITS)

## 代码风格
- 使用下划线命名
- 所有文件 UTF-8 编码

## 回复风格
- 简洁直接
- 避免废话

## 工作流程
- 修改代码前先备份
- 运行测试后再提交
```

### 3. 自动进化标记

```python
# 自动进化时添加时间戳
ts = time.strftime("%Y-%m-%d")
identity.append_habit(f"<!-- 自动进化 {ts} -->\n{content}")
```

### 4. 集成到 Agent

```python
# Agent 初始化时注入 Identity
class Agent:
    def __init__(self, ...):
        self.identity = IdentityManager(data_dir)
        
        # 构建系统 Prompt
        system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self) -> str:
        parts = []
        
        # 1. 基础人设（PERSONA.md）
        parts.append(self.persona)
        
        # 2. Identity 层（USER + HABITS + AGENT）
        parts.append(self.identity.build_prompt())
        
        # 3. 内置技能说明
        parts.append(BUILTIN_SYSTEM_SUFFIX)
        
        return "\n\n".join(parts)
```

### 5. 版本控制

```python
# 使用 Git 追踪 Identity 文件
# .gitignore 中不要忽略 data/identity/
git add data/identity/
git commit -m "更新用户档案"
```

## 故障排查

### 问题 1: 文件不存在

**症状**：初始化时报错

**解决方案**：
```python
# IdentityManager 会自动创建默认文件
identity = IdentityManager(data_dir="data")

# 检查文件是否存在
print(identity.user_path.exists())
print(identity.habits_path.exists())
```

### 问题 2: 时间戳未更新

**症状**：修改后时间戳仍是旧的

**解决方案**：
```python
# 检查 _update_timestamp 是否被调用
def update_user(self, key: str, value: str) -> None:
    # ... 更新逻辑 ...
    self._update_timestamp(self.user_path)  # 确保调用
```

### 问题 3: 迁移失败

**症状**：`migrate_from_legacy()` 报错

**解决方案**：
```python
# 检查旧文件是否存在
profile_path = Path("data/user_profile.json")
if not profile_path.exists():
    print("旧文件不存在，无需迁移")

# 手动迁移
import json
with open(profile_path, "r") as f:
    data = json.load(f)
    for key, value in data.get("objective_memory", {}).items():
        identity.update_user(key, str(value))
```

### 问题 4: Prompt 过长

**症状**：系统 Prompt 超过 Token 限制

**解决方案**：
```python
# 精简 HABITS.md
# 移除冗余规则
# 合并相似规则

# 或者在构建 Prompt 时截断
def build_prompt(self, max_length: int = 4000) -> str:
    prompt = self._build_full_prompt()
    if len(prompt) > max_length:
        prompt = prompt[:max_length] + "\n\n（内容已截断）"
    return prompt
```

## 性能优化

### 1. 缓存 Prompt

```python
_prompt_cache = None
_prompt_mtime = 0

def build_prompt_cached(self) -> str:
    global _prompt_cache, _prompt_mtime
    
    # 检查文件是否修改
    current_mtime = max(
        self.user_path.stat().st_mtime,
        self.habits_path.stat().st_mtime
    )
    
    if _prompt_cache and current_mtime == _prompt_mtime:
        return _prompt_cache
    
    _prompt_cache = self.build_prompt()
    _prompt_mtime = current_mtime
    return _prompt_cache
```

### 2. 延迟加载

```python
# 只在需要时读取文件
def get_habits(self) -> str:
    if not hasattr(self, "_habits_cache"):
        self._habits_cache = self._read(self.habits_path)
    return self._habits_cache
```

### 3. 批量更新

```python
# 累积多个更新后一次性写入
updates = [
    ("姓名", "张三"),
    ("年龄", "25"),
    ("职业", "软件工程师")
]

for key, value in updates:
    identity.update_user(key, value)
# 每次 update_user 都会写文件，效率低

# 优化：批量更新
def update_user_batch(self, updates: List[Tuple[str, str]]) -> None:
    text = self._read(self.user_path)
    for key, value in updates:
        pattern = rf"^- \*\*{re.escape(key)}\*\*: .*$"
        new_line = f"- **{key}**: {value}"
        if re.search(pattern, text, flags=re.MULTILINE):
            text = re.sub(pattern, new_line, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{new_line}\n"
    self._write(self.user_path, text)
    self._update_timestamp(self.user_path)
```

## 未来优化方向

1. **多人设支持**：支持多个 Identity 配置（工作/生活/娱乐）
2. **版本历史**：记录 Identity 文件的修改历史
3. **冲突检测**：检测 USER 和 HABITS 中的矛盾信息
4. **自动补全**：根据对话自动补全用户档案
5. **隐私保护**：敏感信息加密存储
6. **导出/导入**：支持 Identity 配置的导出和分享
