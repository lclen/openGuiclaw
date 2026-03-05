"""
Main entry point for the modular agent system.

Usage:
    python main.py
    python main.py --no-autogui   # Disable AutoGUI skills
    python main.py --no-basic     # Disable basic utility skills
"""

import sys
import os

# Ensure project root is on Python path
sys.path.insert(0, os.path.dirname(__file__))

# 启动前自动安装依赖
from core import bootstrap
bootstrap.run()

from pathlib import Path
from core.agent import Agent
from core.context import ContextManager, MODE_SILENT, MODE_NORMAL, MODE_LIVELY
from core.plugin_manager import PluginManager
import queue
from openai import OpenAI


BANNER = """
╔══════════════════════════════════════╗
║        AI 助理框架  v1.0             ║
║  输入 /help 查看命令                 ║
╚══════════════════════════════════════╝
"""

HELP_TEXT = """
【Qwen AutoGUI System 控制台帮助】
常用指令:
  /help       - 显示此帮助信息
  /quit       - 退出程序并保存会话
  /new        - 开启一个全新的闲聊会话
  /sessions   - 列出所有历史会话
  /switch <id>- 切换到指定的历史会话
  /memory     - 查看系统当前提取的所有长短期记忆节点
  /skills     - 列出系统目前挂载的所有外挂工具技能
  /plugins [reload] [name] - 列出/重载插件系统
  /mode       - 切换系统视觉感知的回复干预度 (静默/正常/活泼)
  /upload <路径> [提示词] - 上传本地文件给AI（支持图片或纯文本）
  /plan             切换计划执行模式（自驾/确认/普通）
  /context          查看视觉感知状态
  /config           配置主动回复感知参数 (interval/cooldown/verbose)
  /poke             强制触发一次 AI 主动搭话 (寒暄)
  /persona          列出所有可用性格 (Identities)
  /persona <name>   切换主动 AI 性格
  /quit  /exit      退出
"""

# 计划执行模式全局变量
# autopilot: AI 连续自主执行，不在步骤间询问用户
# confirm: AI 每步做完后停下来等用户确认继续
# normal: 不做强制约束，AI 自行决定（默认）
PLAN_MODE_AUTOPILOT = "autopilot"
PLAN_MODE_CONFIRM   = "confirm"
PLAN_MODE_NORMAL    = "normal"

_plan_mode = PLAN_MODE_NORMAL  # 当前选中的模式


def get_plan_mode() -> str:
    """供 agent.py 动态读取当前计划执行模式。"""
    return _plan_mode



def main():
    args = sys.argv[1:]
    load_autogui = "--no-autogui" not in args
    load_basic = "--no-basic" not in args

    print(BANNER)

    # Initialize agent
    agent = Agent(
        config_path="config.json",
        persona_path="PERSONA.md",
        data_dir="data",
    )

    # Load optional skill modules
    if load_basic:
        from skills import basic
        agent.register_skill_module(basic)
        print("  [OK] 技能加载: basic (get_time, read_file, write_file, list_dir, ...)")

    if load_autogui:
        try:
            from skills import autogui
            agent.register_skill_module(autogui)
            print("  [OK] 技能加载: autogui (autogui_action, get_screenshot)")
        except ImportError as e:
            print(f"  [WARN] AutoGUI 加载失败（缺少依赖？{e}），已跳过。")

    # Load web fetch skill (web_fetch tool + Qwen built-in search)
    try:
        from skills import web_search
        agent.register_skill_module(web_search)
        print("  [OK] 技能加载: web_search (web_fetch) + 内置联网搜索已开启")
    except ImportError as e:
        print(f"  [WARN] Web 技能加载失败（{e}），已跳过。")

    print(f"\n  Persona: {agent.active_persona_name} ({agent.config.get('persona_name', 'AI 助理')})")
    print(f"  Model  : {agent.model}")
    print(f"  Session: {agent.sessions.current.session_id}\n")

    # Auto-load plugins from plugins/ directory
    plugin_mgr = PluginManager(agent.skills, plugins_dir="plugins")
    loaded = plugin_mgr.load_all()
    if not loaded:
        print("  （plugins/ 目录没有插件）")
        
    # Start background threads AFTER all plugins and their modules are fully loaded
    agent.start_background_tasks()

    # Initialize and Start Vision Context
    vision_cfg = agent.config.get("vision", {})
    if vision_cfg and vision_cfg.get("api_key"):
        vision_client = OpenAI(
            base_url=vision_cfg.get("base_url"),
            api_key=vision_cfg.get("api_key")
        )
        vision_model = vision_cfg.get("model", "qwen-vl-plus")
        print(f"  [OK] 专属视觉模型已加载: {vision_model}")
    else:
        vision_client = agent.client
        vision_model = "qwen-vl-plus"

    context = ContextManager(
        client=vision_client,
        vision_model=vision_model,
        interval_minutes=5,
        get_history_func=lambda: agent.sessions.current.get_history(max_messages=5),
        get_visual_history_func=lambda: [m["content"] for m in agent.sessions.current.messages if m["role"] == "visual_log"],
        add_visual_log_func=agent.add_visual_log,
        update_visual_log_func=agent.update_visual_log
    )
    agent.context = context
    context.start()

    while True:
        # 1. Check for proactive notifications
        while not context.notification_queue.empty():
            try:
                notif = context.notification_queue.get_nowait()
                if notif["type"] == "proactive":
                    print(f"\n[🔔 Agent] {notif['message']}")
                    print("You > ", end="", flush=True)
            except queue.Empty:
                break

        # 2. Get user input
        try:
            # Note: Standard input() is blocking. For a CLI, proactive messages 
            # will appear when the user hits Enter OR if the user is idle 
            # and another thread prints. In Windows shell, background prints
            # might mess up the input line, so we handle it gracefully.
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            context.stop()
            agent.sessions.save()
            break

        if not user_input:
            continue

        # Handle slash commands locally
        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "exit", "quit"):
            print("再见！")
            context.stop()
            agent.sessions.save()
            break
        elif cmd == "/help":
            print(HELP_TEXT)
            continue
        elif cmd == "/new":
            agent.sessions.new_session()
            print("  ✅ 新会话已开启。\n")
            continue
        elif cmd.startswith("/switch"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("  ❌ 请提供会话 ID，例如：/switch session_123456789\n")
            else:
                session_id = parts[1].strip()
                # 先保存当前
                agent.sessions.save()
                # 加载目标
                s = agent.sessions.load(session_id)
                if s:
                    print(f"  ✅ 已切换到会话: [{session_id}]")
                    print(f"  📅 创建时间: {s.created_at}")
                    print(f"  💬 消息数: {len(s.messages)}\n")
                    # 重置视觉感知的回复状态，确保新会话如果有变化能及时提醒
                    if agent.context:
                        agent.context.notify_user_replied()
                else:
                    print(f"  ❌ 找不到会话: {session_id}\n")
            continue
        elif cmd == "/sessions":
            sessions = agent.sessions.list_sessions()
            if not sessions:
                print("  （没有历史会话）\n")
            else:
                for s in sessions:
                    print(f"  [{s['session_id']}] {s['updated_at']} — {s['message_count']} 条消息")
                print()
            continue
        elif cmd == "/memory":
            items = agent.memory.list_all()
            if not items:
                print("  （记忆为空）\n")
            else:
                for m in items:
                    tags = f" [{', '.join(m.tags)}]" if m.tags else ""
                    print(f"  [{m.created_at}]{tags} {m.content}")
                print()
            continue
        elif cmd == "/skills":
            print(f"\n{agent.skills.summary()}\n")
            continue
        elif cmd.startswith("/plugins"):
            parts = user_input.split(maxsplit=2)  # ["/plugins", "reload", optional_name]
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub == "reload":
                if len(parts) > 2:
                    name = parts[2].strip()
                    ok = plugin_mgr.reload(name)
                    print(f"  {'\u2705' if ok else '\u274c'} {'\u91cd载成功' if ok else '\u91cd载失败'}: {name}\n")
                else:
                    reloaded = plugin_mgr.reload_all()
                    print(f"  \u2705 已重载 {len(reloaded)} 个插件\n")
            else:
                # Default: list plugins
                print(f"\n【已加载插件】")
                print(plugin_mgr.summary())
                print()
            continue
        elif cmd == "/mode":
            _mode_labels = {
                MODE_SILENT: ("[1] 🤐 静默模式", "只看不说，永不主动打扰"),
                MODE_NORMAL: ("[2] 😐 正常模式", "遇到报错或长时间空闲才发言"),
                MODE_LIVELY: ("[3] 🤩 活泼模式", "状态变化就主动寒渣，话多一些"),
            }
            current = context.mode
            print(f"\n「视觉感知模式」—— 当前: {_mode_labels[current][0]}")
            print()
            for mode, (label, desc) in _mode_labels.items():
                marker = " ◀ 当前" if mode == current else ""
                print(f"  {label}  {desc}{marker}")
            print()
            choice = input("请输入选项 (1/2/3)，按 Enter 取消：").strip()
            mode_map = {"1": MODE_SILENT, "2": MODE_NORMAL, "3": MODE_LIVELY}
            if choice in mode_map:
                new_mode = mode_map[choice]
                context.set_mode(new_mode)
                names = {MODE_SILENT: "🤐 静默", MODE_NORMAL: "😐 正常", MODE_LIVELY: "🤩 活泼"}
                print(f"  ✅ 已切换到 {names[new_mode]}模式。\n")
            else:
                print("  已取消。\n")
            continue
        elif cmd.startswith("/upload"):
            import shlex
            # Use shlex with posix=False to preserve Windows backslashes
            # It keeps the quotes, so we strip them afterwards
            parts = shlex.split(user_input, posix=False)
            if len(parts) < 2:
                print("  ❌ 请提供文件绝对路径，例如：/upload D:\\photo.jpg [提示词]\n")
                continue
                
            file_path = parts[1].strip(' "\'')
            prompt = parts[2].strip(' "\'') if len(parts) > 2 else "阅读这份文件/图片。"
            
            p = Path(file_path).expanduser().resolve()
            if not p.exists():
                print(f"  ❌ 找不到文件: {file_path}\n")
                continue
            
            print(f"  ⏳ 正在读取文件: {p.name} ...")
            try:
                ext = p.suffix.lower()
                image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
                
                # Image Route (Base64 Multimodal Payload)
                if ext in image_exts:
                    import base64
                    with open(p, "rb") as f:
                        base64_data = base64.b64encode(f.read()).decode('utf-8')
                        mime_type = "image/jpeg"
                        if ext == '.png': mime_type = "image/png"
                        elif ext == '.webp': mime_type = "image/webp"
                        elif ext == '.gif': mime_type = "image/gif"
                        
                    payload = [
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}},
                        {"type": "text", "text": prompt}
                    ]
                    print(f"  🖼️ 已成功加载图片 [{int(p.stat().st_size / 1024)} KB]，切换至视觉感知链路。")
                    user_input = payload  # Override user_input as a list!
                    
                # Text/Document Route
                else:
                    text_content = p.read_text(encoding='utf-8')
                    # Trim blindly huge files to avoid blowing up context entirely
                    if len(text_content) > 50000:
                        text_content = text_content[:50000] + "\n...(由于内容过长已截断)...\n"
                    
                    user_input = f"[文件名称: {p.name}]\n[文件内容]\n```\n{text_content}\n```\n\n[用户提示]\n{prompt}"
                    print(f"  📄 已成功读取文件 [{len(text_content)} 字符]，作为普通文本上下文追加。")

            except Exception as e:
                print(f"  ❌ 读取文件失败: {e}\n")
                continue
                
            # DO NOT continue here, allow it to fall through to agent.chat(user_input) below!
        elif cmd == "/context":
            names = {MODE_SILENT: "🤐 静默", MODE_NORMAL: "😐 正常", MODE_LIVELY: "🤩 活泼"}
            print(f"\n【视觉感知状态】")
            print(f"  模式：{names.get(context.mode, context.mode)}")
            print(f"  截屏间隔：{context.interval} 秒 ({context.interval // 60} 分钟)")
            print(f"  冷却时间：{context.cooldown_minutes} 分钟")
            print(f"  最近感知状态：{context._last_status}")
            print(f"  终端日志：{'✅ 开启' if context.verbose else '❌ 关闭'}  （输入 /config verbose 切换）")
            print()
            continue
        elif cmd.startswith("/config"):
            parts = user_input.split()
            if len(parts) < 2:
                print("  用法：")
                print("  /config interval <秒>   - 截屏检测频率")
                print("  /config cooldown <分>   - 主动发话冷却时间")
                print("  /config verbose         - 切换终端截屏日志显示\n")
                continue
            
            subcmd = parts[1].lower()
            
            if "proactive" not in agent.config:
                agent.config["proactive"] = {}
                
            try:
                if subcmd == "interval" and len(parts) >= 3:
                    mins = int(parts[2])
                    agent.config["proactive"]["interval_minutes"] = mins
                    context.interval = mins * 60
                    print(f"  ✅ 截屏间隔已修改为 {mins} 分钟。\n")
                elif subcmd == "cooldown" and len(parts) >= 3:
                    mins = int(parts[2])
                    agent.config["proactive"]["cooldown_minutes"] = mins
                    context.cooldown_minutes = mins
                    print(f"  ✅ 冷却时间已修改为 {mins} 分钟。\n")
                elif subcmd == "verbose":
                    context.verbose = not context.verbose
                    agent.config["proactive"]["verbose"] = context.verbose
                    state = "✅ 已开启" if context.verbose else "❌ 已关闭"
                    print(f"  终端截屏日志 {state}。\n")
                else:
                    print("  ❌ 格式错误。例如: /config interval 60\n")
                
                with open("config.json", "w", encoding="utf-8") as f:
                    import json
                    json.dump(agent.config, f, indent=4, ensure_ascii=False)
            except ValueError:
                print("  ❌ 请提供有效的数字参数。\n")
            continue
        elif cmd == "/poke":
            print("  ⏳ 正在手动触发一次视觉感知寒暄...\n")
            context.poke()
            continue
        elif cmd.startswith("/persona"):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1:
                # List personas
                personas = agent.list_personas()
                print("\n【可用性格 (Identities)】")
                for p in personas:
                    marker = " ◀ 当前激活" if p == agent.active_persona_name else ""
                    print(f"  - {p}{marker}")
                print()
            else:
                # Switch persona
                new_name = parts[1].strip()
                if agent.switch_persona(new_name):
                    print(f"  ✅ 人设已成功切换为: {new_name}\n")
                else:
                    print(f"  ❌ 找不到性格文件: data/identities/{new_name}.md\n")
            continue
        elif cmd == "/plan":
            global _plan_mode
            _plan_labels = {
                PLAN_MODE_AUTOPILOT: ("[1] 自驾模式 (Autopilot)", "AI 连续自主执行全部步骤，完成后统一汇报"),
                PLAN_MODE_CONFIRM:   ("[2] 确认模式 (Confirm)",   "AI 每完成一步后暂停，等待你输入 [继续] 或 [取消]"),
                PLAN_MODE_NORMAL:    ("[3] 普通模式 (Normal)",    "不做强制约束，AI 随机应变（默认）"),
            }
            print(f"\n「计划执行模式」—— 当前: {_plan_labels[_plan_mode][0]}")
            print()
            for m, (label, desc) in _plan_labels.items():
                marker = " ◀ 当前" if m == _plan_mode else ""
                print(f"  {label}  {desc}{marker}")
            print()
            choice = input("请输入选项 (1/2/3)，按 Enter 取消：").strip()
            plan_map = {"1": PLAN_MODE_AUTOPILOT, "2": PLAN_MODE_CONFIRM, "3": PLAN_MODE_NORMAL}
            if choice in plan_map:
                _plan_mode = plan_map[choice]
                names = {PLAN_MODE_AUTOPILOT: "自驾", PLAN_MODE_CONFIRM: "确认", PLAN_MODE_NORMAL: "普通"}
                print(f"  已切换到 {names[_plan_mode]}模式。\n")
            else:
                print("  已取消。\n")

        # Normal chat
        print(f"{agent.active_persona_name.capitalize()} > ", end="", flush=True)
        response = agent.chat(user_input)
        print(response)
        print()


if __name__ == "__main__":
    main()
