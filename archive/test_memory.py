from pathlib import Path
from core.identity_manager import IdentityManager

manager = IdentityManager("data")
# 1. Test active task update
manager.update_active_task(
    task_desc="抓取网页提炼信息",
    status="执行中 (Testing)",
    notes="正在下载HTML文件并解析结构"
)

# 2. Test experience add
manager.add_experience(
    category="Python 自动化",
    content="使用 BeautifulSoup 时要小心某些非标准 HTML 标签导致的解析树错乱。"
)

# 3. Test statistics update
manager.update_statistics("自初始化以来完成任务", "2")

print("更新完成！")
