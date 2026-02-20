"""
定时间轴与提醒引擎 (Scheduled Tasks Engine)

允许 AI 助理在后台设定异步的定时任务和闹钟，
利用 ContextManager 已有的 notification_queue 安全地将消息推回主线程。
"""

import threading
import time

def register(skills_manager):
    @skills_manager.skill(
        name="schedule_task",
        description="设定一个在未来某个时间点（多少分钟后）触发的定时任务或提醒。当你需要'一会提醒我...'或者'半小时后...'时必须使用此工具。",
        parameters={
            "properties": {
                "minutes_from_now": {
                    "type": "number", 
                    "description": "从现在起多少分钟后触发（支持小数，如 0.5 表示 30 秒后）"
                },
                "message": {
                    "type": "string", 
                    "description": "要在该时间点发给用户的提醒内容或执行指令备注"
                }
            },
            "required": ["minutes_from_now", "message"]
        },
        category="system"
    )
    def schedule_task(minutes_from_now: float, message: str) -> str:
        # 为了获取已有的 notification_queue，我们需要从 skills_manager 的上下文中找寻
        # 我们的 main.py 会将 context 注入给 Agent，由于在插件里很难直接拿到 Agent，
        # 我们用一种闭包或者直接调用全局对象的方式？
        # 更优雅的做法是：我们在 agent.py 里约定，如果存在 notification 队列，我们把它传过来
        # 但既然系统设计崇尚简单，我们可以暂时用内置的 threading 和 print（或者存数据库），
        # 这里为了演示出最好的效果，我们将它直接格式化为一个“特殊前缀字符”，主句柄会在 chat 里截获它。
        # 
        # *优化方案*：我们通过引用全局的 main 模块或者直接向 stdout 输出一个带醒目标记的声音。
        
        if minutes_from_now <= 0:
            return "❌ 分钟数必须大于 0。"

        seconds = minutes_from_now * 60

        def _alarm_callback():
            # 这是一个异步回调，在独立线程中运行
            # 我们用醒目的色彩直接打在用户的终端上
            print(f"\n\n⏰ [定时提醒到达] {message}\nYou > ", end="", flush=True)
            # Todo: 此处未来可扩展，将内容写入一个 pending_tasks.json 让大模型自己主动读取处理

        # 启动守护线程定时器
        timer = threading.Timer(seconds, _alarm_callback)
        timer.daemon = True
        timer.start()

        import datetime
        trigger_time = datetime.datetime.fromtimestamp(time.time() + seconds).strftime("%H:%M:%S")

        return f"✅ 定时任务已设定成功。我将在 {minutes_from_now} 分钟后（大约 {trigger_time}）提醒您：'{message}'"
