"""
长链条多步任务规划器 (Plan Handler)

当应对复杂目标时，大模型应该先通过 create_plan 拆解出有明确 ID 的步骤列表，
然后一步一步去执行，并通过 update_plan_step 更新状态。
这能极大解决执行过长时忘记初衷、或者陷入死循环的问题。
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List

class PlanManager:
    def __init__(self):
        self.plan_dir = "data/plans"
        os.makedirs(self.plan_dir, exist_ok=True)
        self.active_plan: Dict[str, Any] = None
        self.active_plan_file = os.path.join(self.plan_dir, "active_plan.json")
        self._load_active_plan()

    def _load_active_plan(self):
        if os.path.exists(self.active_plan_file):
            try:
                with open(self.active_plan_file, 'r', encoding='utf-8') as f:
                    self.active_plan = json.load(f)
            except Exception:
                self.active_plan = None

    def _save_active_plan(self):
        if self.active_plan:
            with open(self.active_plan_file, 'w', encoding='utf-8') as f:
                json.dump(self.active_plan, f, ensure_ascii=False, indent=2)
                
            # 同时生成一份 Markdown 用来直观查看
            md_file = os.path.join(self.plan_dir, f"{self.active_plan['id']}.md")
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(self.get_status_markdown())
        else:
            if os.path.exists(self.active_plan_file):
                os.remove(self.active_plan_file)

    def create_plan(self, summary: str, steps: List[Dict[str, str]]) -> str:
        if self.active_plan and self.active_plan.get("status") == "in_progress":
            return f"[ERROR] 当前已有未完成的活跃计划（ID: {self.active_plan['id']}）。请先通过 update_plan_step 将其完结或取消。"
            
        import secrets
        plan_id = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        
        formatted_steps = []
        for i, step in enumerate(steps):
            formatted_steps.append({
                "id": step.get("id", f"step_{i+1}"),
                "description": step.get("description", "未描述说明"),
                "status": "pending",  # pending, in_progress, completed, failed, skipped
                "result": ""
            })
            
        self.active_plan = {
            "id": plan_id,
            "summary": summary,
            "status": "in_progress",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "steps": formatted_steps
        }
        
        self._save_active_plan()
        
        # 强制将信息推送到控制台打印（假设 Context 队列可达，或直接 print）
        print(f"\n[PLAN] AI 已创建长期计划: {summary} (ID: {plan_id})")
        for s in formatted_steps:
            print(f"  [ ] [{s['id']}] {s['description']}")
        print()
            
        return f"[OK] 计划创建成功，ID: {plan_id}。请立即开始执行第一步，执行完后使用 update_plan_step 更新状态！"

    def update_plan_step(self, step_id: str, status: str, result: str = "") -> str:
        if not self.active_plan:
            return "[ERROR] 没有活跃的计划。请先使用 create_plan。"
            
        target_step = None
        for step in self.active_plan["steps"]:
            if step["id"] == step_id:
                target_step = step
                break
                
        if not target_step:
            return f"[ERROR] 找不到步骤 ID: {step_id}"
            
        if status not in ["pending", "in_progress", "completed", "failed", "skipped"]:
            return f"[ERROR] 无效的状态 '{status}'，必须是: pending, in_progress, completed, failed, skipped"
            
        target_step["status"] = status
        if result:
            target_step["result"] = result
            
        # 自动推断整个计划状态
        all_completed = True
        for step in self.active_plan["steps"]:
            if step["status"] not in ["completed", "failed", "skipped"]:
                all_completed = False
                break
                
        self._save_active_plan()
        
        status_icon = {"pending": "[ ]", "in_progress": "[>]", "completed": "[OK]", "failed": "[X]", "skipped": "[-]"}
        
        print(f"\n[PLAN] 步骤更新: {status_icon.get(status, '[?]')} [{step_id}] {target_step['description']}")
        if result:
            print(f"   => {result}")
            
        if all_completed:
            msg = f"[PLAN] 步骤 {step_id} 已完成。所有规划步骤均已处理完毕！请调用 `complete_plan` 工具来总结和结束本次计划。"
            print(f"\n{msg}\n")
            return msg
            
        return f"[OK] 步骤 {step_id} 已更新为 {status}。您可以继续下一步。"
        
    def complete_plan(self, summary: str) -> str:
        if not self.active_plan:
            return "[ERROR] 当前没有任何活跃的计划可供结束。"
            
        plan_id = self.active_plan["id"]
        self.active_plan["status"] = "completed"
        self._save_active_plan()
        
        msg = f"[PLAN] 计划 {plan_id} 已正式结案。\n总结: {summary}"
        print(f"\n{msg}\n")
        
        self.active_plan = None
        return msg

    def get_status_markdown(self) -> str:
        if not self.active_plan:
            return "当前没有任何活跃的计划。"
            
        plan = self.active_plan
        steps = plan["steps"]
        completed = sum(1 for s in steps if s["status"] == "completed" or s["status"] == "skipped")
        total = len(steps)
        
        md = f"## 计划追踪: {plan['summary']} (ID: {plan['id']})\n"
        md += f"**状态**: {plan['status']} | **进度**: {completed}/{total}\n\n"
        
        for idx, s in enumerate(steps):
            icon = {"pending": "[ ]", "in_progress": "[>]", "completed": "[OK]", "failed": "[X]", "skipped": "[-]"}.get(s["status"], "[?]")
            md += f"{icon} **{idx+1}. [{s['id']}]** {s['description']}\n"
            if s['result']:
                md += f"   > 结果: {s['result']}\n"
                
        return md


_manager = PlanManager()

def register(skills_manager):
    @skills_manager.skill(
        name="create_plan",
        description="【高级统筹工具】遇到涉及3步以上的复杂目标时，为了防止自己思路混乱，务必先调用此工具创建一个分解计划清单（Plan）。",
        parameters={
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "整个宏大计划的简要概括（例如：部署并测试新的订单系统）"
                },
                "steps": {
                    "type": "array",
                    "description": "拆解出的有序步骤数组。每个对象包含 id (如 'step_1') 和 description。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "简短的一般英文标识，如 'step_1_fetch_data'"},
                            "description": {"type": "string", "description": "该步骤要执行的详细动作"}
                        },
                        "required": ["id", "description"]
                    }
                }
            },
            "required": ["summary", "steps"]
        },
        category="system"
    )
    def create_plan(summary: str, steps: list) -> str:
        return _manager.create_plan(summary, steps)

    @skills_manager.skill(
        name="update_plan_step",
        description="更新通过 create_plan 制定出的特定步骤的执行状态。每次执行完（或开始执行）某个步骤，都要调用它改变状态。",
        parameters={
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "要更新的步骤的 ID（例如 'step_1'）"
                },
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "completed", "failed", "skipped"],
                    "description": "步骤的最新状态。刚开始做填 in_progress，做完填 completed，做错填 failed。"
                },
                "result": {
                    "type": "string",
                    "description": "选填。记录该步骤产生的关键结果（如总结、拿到的 ID 等），方便后续步骤看。"
                }
            },
            "required": ["step_id", "status"]
        },
        category="system"
    )
    def update_plan_step(step_id: str, status: str, result: str = "") -> str:
        return _manager.update_plan_step(step_id, status, result)

    @skills_manager.skill(
        name="get_plan_status",
        description="查看当前存在的活跃计划的所有步骤、状态以及之前保存的 result 记录，防止大脑遗忘执行进度。",
        parameters={"properties": {}},
        category="system"
    )
    def get_plan_status() -> str:
        return _manager.get_status_markdown()
        
    @skills_manager.skill(
        name="complete_plan",
        description="当你认为一个 plan 的所有步骤都已经执行完毕时，通过此工具正式结案并给出整体总结。",
        parameters={
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "对这次宏大计划的最终结论、发现或交接信息"
                }
            },
            "required": ["summary"]
        },
        category="system"
    )
    def complete_plan(summary: str) -> str:
        return _manager.complete_plan(summary)
