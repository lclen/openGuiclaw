"""
test_server.py — 后端 API 手动验证脚本
======================================
使用前：请确保后端已启动：
    conda run -n langchain python -m uvicorn core.server:app --host 127.0.0.1 --port 8000

然后在 langchain 环境中运行本脚本：
    python tests/test_server.py
"""

import httpx
import json


BASE_URL = "http://127.0.0.1:8000"


def sep(title: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")


# ─── 测试 1: 健康检查 ────────────────────────────────────
sep("测试 1 — GET /api/health")
r = httpx.get(f"{BASE_URL}/api/health", timeout=5)
print(f"状态码: {r.status_code}")
print(f"响应:   {r.text}")
assert r.status_code == 200, "❌ 健康检查失败！"
print("✅ 通过")


# ─── 测试 2: 读取配置 ────────────────────────────────────
sep("测试 2 — GET /api/config")
r = httpx.get(f"{BASE_URL}/api/config", timeout=5)
print(f"状态码: {r.status_code}")
cfg = r.json()
print(f"主模型: {cfg.get('api', {}).get('model', 'N/A')}")
assert r.status_code == 200, "❌ 配置读取失败！"
print("✅ 通过")


# ─── 测试 3: Agent 运行状态 ──────────────────────────────
sep("测试 3 — GET /api/status")
r = httpx.get(f"{BASE_URL}/api/status", timeout=5)
print(f"状态码: {r.status_code}")
data = r.json()
print(json.dumps(data, ensure_ascii=False, indent=2))
assert data.get("status") == "online", "❌ Agent 未在线！"
print("✅ 通过")


# ─── 测试 4: 同步对话（普通问答，无工具调用）────────────
sep("测试 4 — POST /api/chat/sync (普通对话)")
r = httpx.post(
    f"{BASE_URL}/api/chat/sync",
    json={"message": "你好，请自我介绍一下"},
    timeout=60,
)
print(f"状态码: {r.status_code}")
data = r.json()
resp = data.get("response", "")
print(f"AI 回复 (前200字):\n{resp[:200]}")
assert r.status_code == 200 and len(resp) > 0, "❌ 同步对话失败！"
print("✅ 通过")


# ─── 测试 5: SSE 流式对话 + 工具调用 ────────────────────
sep("测试 5 — GET /api/chat/stream (触发工具调用: remember)")

tool_calls_seen = []
messages_seen = []

print("正在监听 SSE 事件流...\n")
with httpx.stream(
    "GET",
    f"{BASE_URL}/api/chat/stream",
    params={"message": "请帮我记住：我的项目叫做 qwen_autogui"},
    timeout=120,
) as r:
    for line in r.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            raw = line[6:]
            if raw == "[DONE]":
                print("\n[DONE] 流结束")
                break
            try:
                evt = json.loads(raw)
                evt_type = evt.get("type")
                if evt_type == "status":
                    print(f"  [状态] {evt.get('content')}")
                elif evt_type == "tool_call":
                    tool_calls_seen.append(evt.get("name"))
                    print(f"  [工具调用] {evt.get('name')}({json.dumps(evt.get('params', {}), ensure_ascii=False)})")
                elif evt_type == "tool_result":
                    print(f"  [工具结果] {evt.get('result', '')[:120]}")
                elif evt_type == "message":
                    content = evt.get("content", "")
                    messages_seen.append(content)
                    print(f"  [最终回复] {content[:200]}")
                elif evt_type == "error":
                    print(f"  ❌ [错误] {evt.get('content')}")
            except json.JSONDecodeError:
                print(f"  [原始行] {raw}")

print(f"\n工具调用统计: {tool_calls_seen}")
assert len(messages_seen) > 0, "❌ 未收到任何最终回复！"
print("✅ 通过")


# ─── 汇总 ────────────────────────────────────────────────
sep("🎉 全部测试通过！")
