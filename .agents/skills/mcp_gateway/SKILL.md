---
name: mcp_gateway
description: MCP (Model Context Protocol) 协议客户端。允许 AI 动态挂载并调用外部的 MCP 服务器资源与工具集（例如本地文件系统访问、GitHub API、各类数据库查询等标准 MCP 服务）。
allowed-tools: None
---

# MCP Gateway (Model Context Protocol) 技能手册

MCP 是一套允许大模型通过标准接口调用外部本地或云端工具的工业级通讯协议。`mcp_gateway` 插件作为网关，负责向系统注入其他 MCP 服务器所提供的 Tool。

## 工作原理

1. 系统的 MCP 服务端点配置在 `config/mcp_servers.json` 中。
2. 启动时或你调用 `mcp_refresh` 时，网关会拉起配置中定义的 MCP 服务器（例如通过 `npx` 或直接运行可执行文件）。
3. 握手后，外部 MCP 服务器声明的 Tools 会直接被注册并暴露到当前会话供你使用，前缀为 `mcp_[server_name]_`。

## 如何新增或挂载一个 MCP 服务？

如果你需要一个不在当前列表中的能力（比如需要分析本地 SQLite 数据库，或访问 Github），流程如下：

### 1. 修改配置文件
使用系统的修改文件工具（比如 `execute_command` 运行脚本或自己拼 JSON），编辑 `config/mcp_servers.json`，按官方标准添加新节点：

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "d:/data/my_db.sqlite"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token"
      }
    }
  }
}
```

### 2. 刷新连通
此时你必须调用暴露给你的工具 `mcp_refresh`。这会重启整个 MCP 客户端，读取新的配置，并建立子进程：
```json
{
  "action": "mcp_refresh",
  "parameters": {}
}
```

### 3. 查看新增工具
刷新后立刻调用系统的 `list_skills` 或 `get_skill_info` 不一定能看到（因为它们现在是动态挂载的），但此时你立刻多出了一组可用的 JSON 工具调用（以刚配置的 key 作为前缀），比如：
- `mcp_sqlite_query`
- `mcp_github_issues_list`

直接像调用普通系统技能一样发起 `tool_call` 即可使用它们。

---

## 预置与常用官方 MCP 服务参考

如果你发现当前环境缺少某些核心能力，你可以考虑帮用户配置以下常见的官方 Server：

- 文件系统: `npx -y @modelcontextprotocol/server-filesystem <绝对路径>`
- PostgreSQL: `npx -y @modelcontextprotocol/server-postgres postgres://user:pass@host/db`
- Github: `npx -y @modelcontextprotocol/server-github`
- Puppeteer(Browser): `npx -y @modelcontextprotocol/server-puppeteer`

*(注：系统默认已内置原生网页抓取/操作及文件读写工具，仅当需要更深度的特殊集成时，才推荐配置 MCP。)*
