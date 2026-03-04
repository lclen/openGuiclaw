# Project Structure

```
openGuiclaw/
├── main.py                  # CLI 入口
├── mcp_server.py            # MCP Server 入口
├── config.json              # 本地配置（不提交 git）
├── config.json.example      # 配置模板
├── PERSONA.md               # 默认 AI 人设（支持自动进化）
├── requirements.txt         # Python 依赖
│
├── core/                    # 核心业务逻辑
│   ├── agent.py             # Agent 主逻辑：LLM 调用、工具分发、对话循环
│   ├── server.py            # FastAPI Web 服务 + REST/SSE API
│   ├── context.py           # 视觉感知后台线程
│   ├── memory.py            # 长期记忆管理（读写/检索）
│   ├── memory_extractor.py  # 从对话中提取记忆条目
│   ├── vector_memory.py     # 向量存储与语义检索（RAG）
│   ├── knowledge_graph.py   # 实体关系知识图谱
│   ├── self_evolution.py    # 自我进化引擎（每日回顾）
│   ├── session.py           # 会话管理与持久化
│   ├── skills.py            # 技能注册装饰器系统
│   ├── identity_manager.py  # 人设文件管理
│   ├── user_profile.py      # 用户画像管理
│   ├── diary.py             # AI 日记
│   ├── journal.py           # 对话日志
│   ├── plugin_manager.py    # 插件热加载管理
│   ├── mcp_client.py        # MCP 协议客户端
│   ├── daily_consolidator.py# 每日记忆整合
│   └── scheduler/           # 定时任务调度器
│
├── skills/                  # 内置技能模块（通过 @skills_manager.skill 注册）
│   ├── basic.py             # 文件读写、时间、系统信息
│   ├── autogui.py           # 屏幕控制与视觉操作
│   └── web_search.py        # 网页抓取
│
├── plugins/                 # 热加载插件（每个文件实现 register(skills_manager) 函数）
│   ├── plan_handler.py      # 多步骤计划执行
│   ├── sandbox_repl.py      # Python 沙箱
│   ├── mcp_gateway.py       # MCP 协议网关
│   ├── skill_creator.py     # AI 自主创建插件
│   ├── scheduled.py         # 定时提醒
│   ├── browser.py           # 浏览器操作
│   ├── weather.py           # 天气查询
│   └── system.py            # Shell 命令执行
│
├── templates/               # Jinja2 HTML 模板
│   ├── index.html           # 主页面
│   └── panels/              # 各功能面板（chat、memory、skills、diary 等）
│
├── static/
│   ├── js/                  # 前端逻辑（Alpine.js，无构建步骤）
│   ├── models/              # VRM 3D 模型文件
│   └── libs/                # Three.js、VRM 等前端库
│
├── config/
│   └── mcp_servers.json     # MCP 服务器配置
│
└── data/                    # 运行时数据（自动生成，不提交 git）
    ├── sessions/            # 会话历史 JSON
    ├── memory/              # 长期记忆 JSON
    ├── diary/               # AI 每日日记
    ├── journals/            # 对话日志
    ├── identities/          # 自定义人设文件
    ├── plans/               # 计划任务记录
    ├── scheduler/           # 定时任务数据
    ├── screenshots/         # 临时截图
    └── token_usage.db       # Token 用量 SQLite
```

## 关键约定

- **插件开发**：在 `plugins/` 新建 `.py` 文件，实现 `register(skills_manager)` 函数，使用 `@skills_manager.skill(name, description, parameters, category)` 装饰器注册工具
- **技能分类**：`category` 字段用于 Web UI 技能面板分组展示
- **人设文件**：放在 `data/identities/<name>.md`，通过 `/persona <name>` 或 Web UI 切换
- **数据目录**：`data/` 全部运行时生成，已加入 `.gitignore`
- **配置安全**：`config.json` 含 API Key，已加入 `.gitignore`，永远不提交
- **前端无构建**：前端使用 Alpine.js，直接编辑 `templates/` 和 `static/js/`，无需任何构建步骤
