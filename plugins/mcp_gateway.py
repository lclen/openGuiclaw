"""
MCP (Model Context Protocol) 客户端网关

允许大模型连接并调用符合标准的本机 MCP Server（Stdio传输协议）。
"""

import json
import subprocess
import os

# 一个极简的、阻塞式的 stdio MCP Client 模拟器
# 因为完整实现异步 JSON-RPC 比较复杂，这里提供一个直调型的桥接方案

def register(skills_manager):
    @skills_manager.skill(
        name="call_mcp_tool",
        description="调用已配置的外部 MCP (Model Context Protocol) 服务器提供的工具。当你需要使用诸如文件系统、Github、多模块等复杂的三方扩展时请使用。",
        parameters={
            "properties": {
                "server_command": {
                    "type": "string",
                    "description": "启动 MCP 服务的完整命令，例如: 'npx -y @modelcontextprotocol/server-filesystem /path/to/dir'"
                },
                "tool_name": {
                    "type": "string",
                    "description": "要在 MCP 服务器上调用的工具名称"
                },
                "arguments": {
                    "type": "string",
                    "description": "传递给该工具的参数列表（必须是合法的 JSON 字符串）"
                }
            },
            "required": ["server_command", "tool_name", "arguments"]
        },
        category="system"
    )
    def call_mcp_tool(server_command: str, tool_name: str, arguments: str) -> str:
        try:
            # 1. 解析参数
            args_dict = json.loads(arguments)
        except json.JSONDecodeError:
            return "❌ `arguments` 必须是合法的 JSON 字符串。"

        try:
            # 2. 构造 MCP 协议的 CallToolRequest (JSON-RPC 2.0)
            request_id = 1
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args_dict
                }
            }
            json_line = json.dumps(rpc_payload) + "\n"

            # 3. 启动 MCP Server 子进程 (通过 stdio)
            # 注意：实际标准 MCP 通信需要先发 initialize，收到 initialized 后再操作。
            # 为了实现轻量化的热插拔网关，我们编写一个自动化流：
            
            # 由于完整的 MCP 握手握手依赖双向全双工流和复杂的生命周期管理，
            # 若强行用 subprocess_run 做一把梭会失败（很多 server 会阻塞等待 init）。
            # 作为 MVP 版本，我们通过 execute_command 提示模型。
            
            return (
                f"🚧 MCP 网关提示：这是一个占位符封装。\n"
                f"完整协议需要实现 JSON-RPC 的初始化握手。\n"
                f"已收到对于 `{tool_name}` 的调用请求，携带参数:\n{arguments}\n\n"
                f"（如需立即执行，建议暂时使用 `execute_command` 替代）"
            )
        except Exception as e:
            return f"❌ MCP 网关执行错误: {str(e)}"
