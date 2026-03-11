import logging
from core.skills import SkillManager
from core.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)

# 全局单例编排器
_orchestrator = None

def get_orchestrator(profiles_dir: str = "data/profiles") -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        import os
        os.makedirs(profiles_dir, exist_ok=True)
        _orchestrator = AgentOrchestrator(profiles_dir)
    return _orchestrator

def register(manager: SkillManager) -> None:
    """将编排器注册为一个外挂技能，允许主 LLM 委派复杂任务。"""
    
    orchestrator = get_orchestrator()

    @manager.skill(
        name="dispatch_gui_task",
        description="【多步界面控制】当用户要求完成一个长周期的、复杂的电脑桌面图形界面操作任务时，使用此工具将任务委派给专门的底层 GUI 智能体执行。智能体将自动完成多步鼠标/键盘反馈循环并返回最终结果。",
        parameters={
            "properties": {
                "task_description": {
                    "type": "string", 
                    "description": "详细的 GUI 操作任务描述（提供尽可能的上下文）"
                },
                "profile_id": {
                    "type": "string", 
                    "description": "要使用的 Agent Profile ID (例如 'default', 'researcher'), 默认使用 'default'"
                }
            },
            "required": ["task_description"]
        },
        category="system",
    )
    def dispatch_gui_task(task_description: str, profile_id: str = "default") -> str:
        try:
            logger.info(f"Dispatching task to {profile_id}: {task_description}")
            result = orchestrator.dispatch(task_description, target_profile_id=profile_id)
            return f"【GUI 操作委派完成】\n执行结果反馈：\n{result}"
        except Exception as e:
            logger.error(f"Failed to dispatch GUI task: {e}")
            return f"任务委派执行失败: {e}"
