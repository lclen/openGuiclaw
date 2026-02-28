# OpenGuiclaw

> 一个基于 Qwen（通义千问）的智能桌面 AI 伙伴框架，具备视觉感知、GUI 自动化、长期记忆与自我进化能力。

提供 **Web UI** 和 **CLI** 两种交互方式，支持 3D 虚拟形象、插件热加载、MCP 协议扩展，以及完整的 Token 用量统计。

---

## 核心能力

### 🧠 智能对话
- 基于 OpenAI 兼容接口，支持 Qwen、DeepSeek 等任意兼容模型
- 原生支持 Function Calling 工具调用，多轮工具链自动执行
- 集成 Qwen 联网搜索（`enable_search`），实时获取最新信息
- 支持图片上传与多模态分析，可配置独立的视觉解析模型

### 👀 视觉感知（主动上下文）
后台独立线程定时截取屏幕，通过 Vision 模型分析当前状态，并根据配置主动发起对话：

| 模式 | 行为 |
|------|------|
| 🤐 静默 | 只记录日志，不打扰 |
| 😐 正常 | 检测到报错或长时间空闲时发言 |
| 🤩 活泼 | 状态变化即主动寒暄，话多 |

### 💾 记忆系统
- **短期记忆**：完整的会话历史，支持滚动摘要压缩
- **长期记忆**：自动从对话中提取关键事实，持久化存储
- **向量检索（RAG）**：基于 `text-embedding-v4` 的语义搜索，让 AI 能"想起"模糊的往事
- **知识图谱**：实体关系存储，支持 `query_knowledge` 工具查询

### 🔄 自我进化
- 每天（或跨天首次启动时）自动回顾昨日对话日志
- 提炼新的长期记忆，更新用户画像
- 根据交互历史自动提议微调 `PERSONA.md` 人设，性格越来越贴合你的偏好

### 🎮 GUI 自动化
- 封装 `pyautogui` + `mss`，支持点击、双击、拖拽、滚轮、键盘输入
- 支持基于归一化坐标（0-1000）的视觉定位操作
- `screenshot_and_act` 工具：截屏 → 视觉模型分析 → 自动执行，一步完成复杂 UI 任务

### 📋 计划执行
- `create_plan` 工具将复杂目标分解为多步骤计划
- 三种执行模式：**自驾**（全自动）、**确认**（每步等待确认）、**普通**
- 计划状态实时追踪，支持中途查看进度

### 🔌 插件与 MCP
- `plugins/` 目录热加载，运行时无需重启
- 内置 Python 沙箱执行（`run_in_sandbox`），安全运行动态代码
- MCP 协议网关，通过 `config/mcp_servers.json` 接入任意 MCP 服务
- AI 可通过 `create_plugin` 工具**自主编写并加载新插件**（自我进化的终极形态）

### 🎭 3D 虚拟形象
- Web UI 内置 Three.js + VRM 渲染，支持多模型切换
- 内置动画系统（等待、互动等），支持上传自定义 `.vrm` 模型
- 模型商店，可在线下载更多 VRM 模型和动画

### 📊 Token 统计
- 实时追踪每次 API 调用的 prompt / completion token 用量
- 按模型分组展示，支持一键重置

---

## 快速开始

### 1. 安装依赖

```bash
# 推荐使用 uv
uv pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.json.example config.json
```

编辑 `config.json`，最小配置只需填入主模型的 API Key：

```json
{
  "api": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "YOUR_API_KEY",
    "model": "qwen-max"
  }
}
```

完整配置项见 [config.json.example](./config.json.example)。

### 3. 启动

**Web UI（推荐）**

```bash
uv run uvicorn core.server:app --host 127.0.0.1 --port 8080
```

访问 `http://127.0.0.1:8080`

**命令行模式**

```bash
uv run python main.py
```

---

## 配置说明

| 配置块 | 用途 |
|--------|------|
| `api` | 主对话模型（必填） |
| `vision` | 视觉感知后台截屏分析模型 |
| `image_analyzer` | 用户上传图片的解析模型 |
| `embedding` | 向量嵌入模型，用于语义记忆检索 |
| `autogui` | GUI 自动化专用视觉模型 |
| `proactive` | 主动感知行为（间隔分钟数、冷却时间、模式） |

> 各模型可以配置为同一个 API Key 下的不同模型，也可以指向完全不同的服务商。

---

## 项目结构

```
openGuiclaw/
├── main.py              # CLI 入口
├── config.json          # 配置文件（本地，不提交）
├── PERSONA.md           # AI 人设定义（支持自动进化）
├── core/
│   ├── agent.py         # Agent 主逻辑，LLM 调用与工具分发
│   ├── server.py        # FastAPI Web 服务 + REST API
│   ├── context.py       # 视觉感知后台线程
│   ├── memory.py        # 长期记忆管理
│   ├── vector_memory.py # 向量存储与语义检索
│   ├── self_evolution.py# 自我进化引擎
│   ├── session.py       # 会话管理与持久化
│   ├── skills.py        # 技能注册装饰器系统
│   ├── knowledge_graph.py # 知识图谱
│   ├── user_profile.py  # 用户画像管理
│   └── scheduler/       # 定时任务调度器
├── skills/              # 内置技能模块
│   ├── basic.py         # 文件读写、时间、系统信息
│   ├── autogui.py       # 屏幕控制与视觉操作
│   └── web_search.py    # 网页抓取
├── plugins/             # 热加载插件
│   ├── plan_handler.py  # 多步骤计划执行
│   ├── sandbox_repl.py  # Python 沙箱
│   ├── mcp_gateway.py   # MCP 协议网关
│   ├── skill_creator.py # AI 自主创建插件
│   ├── scheduled.py     # 定时提醒
│   ├── weather.py       # 天气查询
│   └── system.py        # Shell 命令执行
├── templates/           # Jinja2 HTML 模板
│   └── panels/          # 各功能面板（对话、日记、技能、调度器等）
├── static/
│   ├── js/              # 前端逻辑（Alpine.js）
│   ├── models/          # VRM 3D 模型文件
│   └── libs/            # Three.js、VRM 等前端库
└── data/                # 运行时数据（自动生成）
    ├── sessions/        # 会话历史
    ├── diary/           # AI 每日日记
    ├── identities/      # 人设文件
    └── plans/           # 计划任务记录
```

---

## 扩展开发

### 添加插件

在 `plugins/` 目录下新建 `.py` 文件，实现 `register` 函数：

```python
def register(skills_manager):
    @skills_manager.skill(
        name="my_tool",
        description="工具描述，AI 会根据此描述决定何时调用",
        parameters={
            "properties": {
                "arg": {"type": "string", "description": "参数说明"}
            },
            "required": ["arg"]
        },
        category="utility"  # 用于 Web UI 技能面板分组
    )
    def my_tool(arg: str) -> str:
        return f"执行结果: {arg}"
```

重启服务或在 Web UI 技能面板点击「刷新」即可加载。也可以直接让 AI 调用 `create_plugin` 工具自动生成。

### 自定义人设

在 `data/identities/` 目录下新建 `<name>.md` 文件，在 Web UI 人设面板或通过 `/persona <name>` 指令切换。AI 的自我进化功能会在每日回顾后自动提议更新人设内容。

### 接入 MCP 服务

编辑 `config/mcp_servers.json`，添加 MCP 服务器配置，AI 即可通过 `call_mcp_tool` 工具调用其提供的能力。

---

## CLI 常用指令

| 指令 | 说明 |
|------|------|
| `/new` | 开启新会话（保存当前对话） |
| `/mode` | 切换视觉感知模式（静默 / 正常 / 活泼） |
| `/plan` | 切换计划执行模式（自驾 / 确认 / 普通） |
| `/memory` | 查看所有长期记忆 |
| `/skills` | 列出已加载技能 |
| `/plugins [reload]` | 查看或热重载插件 |
| `/persona [name]` | 列出或切换人设 |
| `/sessions` | 列出历史会话 |
| `/switch <id>` | 切换到指定历史会话 |
| `/upload <路径> [提示词]` | 上传文件给 AI 分析 |
| `/poke` | 强制触发一次视觉感知 |
| `/context` | 查看视觉感知状态 |
| `/help` | 显示帮助 |

---

## 注意事项

- 视觉感知功能会定时截屏，图片仅临时发送给 LLM API 分析，不保存到本地
- 开启视觉感知会产生额外的 Vision 模型 API 费用，可通过 `/mode` 切换到静默模式降低消耗
- `config.json` 包含 API Key，已加入 `.gitignore`，请勿提交到版本控制
- 自我进化功能会修改 `PERSONA.md` 和记忆文件，建议定期备份 `data/` 目录
