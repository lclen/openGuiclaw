# Tech Stack

## Runtime & Package Manager

- Python 3.10+
- `uv` 推荐作为包管理器（也可用 pip）

## Backend

- **FastAPI** + **Uvicorn** — Web 服务框架
- **Jinja2** — HTML 模板渲染
- **SSE (sse-starlette)** — 流式响应
- **OpenAI SDK** (`openai>=1.0.0`) — LLM 调用，兼容 Qwen/DeepSeek 等 OpenAI 兼容接口
- **httpx** — 异步 HTTP 客户端
- **pydantic v2** — 数据校验

## AI / 模型

- 主对话模型：Qwen（通过 DashScope OpenAI 兼容接口）
- 视觉模型：`qwen3-vl-flash`（屏幕感知 + 图片分析）
- 嵌入模型：`text-embedding-v4`（向量记忆 RAG）
- 所有模型通过 `config.json` 配置，可独立指向不同服务商

## GUI 自动化

- **pyautogui** — 鼠标键盘控制
- **mss** — 高性能屏幕截图
- **Pillow** — 图像处理
- **pyperclip** — 剪贴板操作

## 前端

- **Alpine.js** — 轻量响应式 UI（无构建步骤）
- **Three.js** + **@pixiv/three-vrm** — 3D VRM 虚拟形象渲染
- 纯 HTML/CSS/JS，无前端构建工具

## 数据存储

- JSON 文件 — 会话、记忆、计划、人设等所有持久化数据
- SQLite (`data/token_usage.db`) — Token 用量统计
- numpy — 向量存储（内存中 cosine 相似度检索）

## 插件 / 扩展

- **MCP SDK** (`mcp>=1.0.0`) — MCP 协议网关（可选）
- **RestrictedPython** — Python 沙箱执行（可选）

## 常用命令

```bash
# 安装依赖
uv pip install -r requirements.txt

# 启动 Web UI（推荐）
uv run uvicorn core.server:app --host 127.0.0.1 --port 8080

# 启动 CLI 模式
uv run python main.py

# 启动 MCP Server
uv run python mcp_server.py
```

## 配置

- 主配置文件：`config.json`（本地，不提交 git）
- 模板：`config.json.example`
- MCP 服务配置：`config/mcp_servers.json`
- AI 人设：`PERSONA.md` 或 `data/identities/<name>.md`
