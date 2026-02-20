"""
AutoGUI Skill Plugin

Wraps screen automation capabilities as a registered skill set.
Provides: screenshot_and_act (single-turn autonomous screen action).
"""

import json
import base64
import time
import re
from typing import Optional

import mss
import mss.tools
import pyautogui
from openai import OpenAI
from pathlib import Path

from core.skills import SkillManager


def _capture_screen() -> str:
    """Capture screen and return base64-encoded PNG."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img_data = mss.tools.to_png(screenshot.rgb, screenshot.size)
        return base64.b64encode(img_data).decode("utf-8")


def _map_coords(x: float, y: float) -> tuple[int, int]:
    """Map 0-1000 normalized coords to actual screen pixels."""
    w, h = pyautogui.size()
    return int(x / 1000 * w), int(y / 1000 * h)


def _extract_xy(params: dict, default_x=500, default_y=500) -> tuple[float, float]:
    """Robustly extract x and y from various hallucinated JSON formats."""
    # Handle {"coordinate": [x, y]}
    if "coordinate" in params and isinstance(params["coordinate"], list) and len(params["coordinate"]) >= 2:
        return float(params["coordinate"][0]), float(params["coordinate"][1])
    # Handle {"x": [x, y]}
    if "x" in params and isinstance(params["x"], list) and len(params["x"]) >= 2:
        return float(params["x"][0]), float(params["x"][1])
    # Handle standard {"x": x, "y": y}
    x = params.get("x", default_x)
    y = params.get("y", default_y)
    # Sometimes they are strings
    return float(x), float(y)


def _execute_action(action_type: str, params: dict) -> str:
    """Execute a single GUI action."""
    t = action_type.lower()
    try:
        if t == "click":
            rx, ry = _map_coords(*_extract_xy(params))
            pyautogui.click(rx, ry)
            return f"点击 ({rx}, {ry})"
        elif t == "double_click":
            rx, ry = _map_coords(*_extract_xy(params))
            pyautogui.doubleClick(rx, ry)
            return f"双击 ({rx}, {ry})"
        elif t == "right_click":
            rx, ry = _map_coords(*_extract_xy(params))
            pyautogui.rightClick(rx, ry)
            return f"右键点击 ({rx}, {ry})"
        elif t == "type":
            text = params.get("text", "")
            import pyperclip
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "v")
            return f"输入文字: {text}"
        elif t == "press":
            keys = params.get("keys", [])
            if isinstance(keys, str):
                keys = [keys]
            pyautogui.hotkey(*keys)
            return f"按键: {'+'.join(keys)}"
        elif t == "scroll":
            amount = params.get("amount", 3)
            # Only use specific coordinates if explicitly requested
            if "x" in params or "coordinate" in params:
                x, y = _extract_xy(params)
                rx, ry = _map_coords(x, y)
                pyautogui.scroll(amount, x=rx, y=ry)
            else:
                pyautogui.scroll(amount)
            return f"滚动: {amount}"
        elif t == "move":
            rx, ry = _map_coords(*_extract_xy(params))
            pyautogui.moveTo(rx, ry, duration=params.get("duration", 0.3))
            return f"移动鼠标到 ({rx}, {ry})"
        elif t == "drag":
            sx, sy = _map_coords(params.get("start_x", 0), params.get("start_y", 0))
            ex, ey = _map_coords(params.get("end_x", 0), params.get("end_y", 0))
            pyautogui.moveTo(sx, sy)
            pyautogui.drag(ex - sx, ey - sy, duration=params.get("duration", 0.5))
            return f"拖拽从 ({sx},{sy}) 到 ({ex},{ey})"
        elif t == "wait":
            s = params.get("seconds", 1.0)
            time.sleep(s)
            return f"等待 {s} 秒"
        elif t == "screenshot":
            return "[Screenshot captured]"
        else:
            return f"未知动作类型: {t}"
    except Exception as e:
        return f"动作执行失败: {e}"


def register(manager: SkillManager) -> None:
    """Register all AutoGUI skills into the provided SkillManager."""

    @manager.skill(
        name="autogui_action",
        description=(
            "执行一个屏幕 GUI 操作。支持 click / double_click / right_click / "
            "type / press / scroll / move / drag / wait。"
            "坐标使用 0-1000 归一化坐标系。"
        ),
        parameters={
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "click", "double_click", "right_click",
                        "type", "press", "scroll", "move", "drag", "wait"
                    ],
                    "description": "动作类型",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "动作参数。"
                        "click/double_click/right_click: {x, y}。"
                        "type: {text}。"
                        "press: {keys: [key1, key2]}。"
                        "scroll: {amount, x?, y?}。"
                        "move: {x, y, duration?}。"
                        "drag: {start_x, start_y, end_x, end_y, duration?}。"
                        "wait: {seconds}。"
                    ),
                },
            },
            "required": ["action", "params"],
        },
        category="autogui",
    )
    def autogui_action(action: str, params: dict) -> str:
        return _execute_action(action, params)

    @manager.skill(
        name="screenshot_and_act",
        description="【自主视觉操作】截取当前屏幕，调用专属 GUI 模型分析并执行下一步操作。当你需要完成复杂的 UI 交互任务时调用此工具。",
        parameters={"properties": {"goal": {"type": "string", "description": "本次操作的目标（例如：点击登录按钮，寻找搜索框）"}}, "required": ["goal"]},
        category="autogui",
    )
    def screenshot_and_act(goal: str) -> str:
        try:
            # 1. Capture
            b64_img = _capture_screen()
            
            # 2. Load Config
            config_path = Path("config.json")
            if not config_path.exists():
                return "错误: 找不到配置文件 config.json"
            
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            gui_cfg = config.get("autogui", {})
            if not gui_cfg.get("api_key"):
                return "错误: 未配置 autogui 专属模型 API Key"
            
            # 3. Call Model
            client = OpenAI(
                base_url=gui_cfg.get("base_url"),
                api_key=gui_cfg.get("api_key")
            )
            
            system_prompt = (
                "你是一个 GUI 自动化助手。你的任务是根据用户的指令，通过分析屏幕截图来完成用户的单步任务。\n"
                "每次响应必须返回一个 JSON 对象，格式严格如下：\n"
                "{\n"
                "    \"thought\": \"你的思考过程，分析当前屏幕状态和该做什么\",\n"
                "    \"action\": \"动作类型\",\n"
                "    \"params\": {\n"
                "        \"参数 1\": \"值 1\"\n"
                "    }\n"
                "}\n"
                "可用的 action 类型及其严格的 params：\n"
                "- click: 点击，params：x, y (0-1000 的归一化坐标)\n"
                "- double_click: 双击，params：x, y\n"
                "- right_click: 右键点击，params：x, y\n"
                "- type: 输入文本，params：text (要输入的文本)\n"
                "- press: 按键，params：keys (按键数组，如 [\"ctrl\", \"c\"])\n"
                "- scroll: 滚动，params：amount (滚动量), x, y (可选)\n"
                "- drag: 拖拽，params：start_x, start_y, end_x, end_y, duration (可选)\n"
                "- move: 移动鼠标，params：x, y, duration (可选)\n"
                "- wait: 等待，params：seconds\n"
                "注意：坐标系统必须使用 1000x1000 的归一化坐标，(0,0) 是左上角，(1000,1000) 是右下角。\n"
                "请务必确认你的 params 包含的是 x 和 y 键，而不是包含数组或叫做 coordinate 的键。"

                "【重要】打开软件的优先策略：\n"
                "当需要打开电脑中的软件时，必须优先使用以下方法：\n"
                "使用 Win 键打开开始菜单，然后输入软件名称搜索"
            )
            
            response = client.chat.completions.create(
                model=gui_cfg.get("model", "qwen3.5-plus"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"当前目标: {goal}"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64_img}"}
                            }
                        ]
                    }
                ],
                max_tokens=8192,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            res_text = response.choices[0].message.content
            action_data = json.loads(res_text)
            
            action = action_data.get("action")
            params = action_data.get("params", {})
            
            if not action:
                return f"模型未返回有效动作: {res_text}"
            
            # 4. Execute
            exec_res = _execute_action(action, params)
            return f"模型计划: {goal}\n决策结果: {json.dumps(action_data, ensure_ascii=False)}\n执行反馈: {exec_res}"
            
        except Exception as e:
            return f"自主操作失败: {e}"

    @manager.skill(
        name="get_screenshot",
        description="截取当前屏幕，返回 base64 编码的图像（约1MB+，仅在需要视觉分析时调用）。",
        parameters={"properties": {}, "required": []},
        category="autogui",
    )
    def get_screenshot() -> str:
        b64 = _capture_screen()
        return f"data:image/png;base64,{b64}"

