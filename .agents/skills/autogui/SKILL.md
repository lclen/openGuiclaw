---
name: autogui
description: 屏幕图形界面自动化操作技能。用于控制操作系统的鼠标和键盘，实现点击、输入、滚动等物理界面的交互。基于归一化百分比坐标 (0-1000)。当你需要操控不支持浏览器自动化的桌面软件，或是需要物理键鼠介入时使用。
allowed-tools: Bash(python -m skills.autogui)
---

# AutoGUI 屏幕自动化技能使用手册

AutoGUI 提供直接接管操作系统的键盘和鼠标的能力。它主要配合屏幕视觉感知使用，当你通过视觉获取到屏幕截图中的元素绝对位置后，使用此工具进行点击或文字输入。

## 核心机制：归一化坐标系统 (0~1000)

为了适配不同分辨率的屏幕，所有的 `x` 和 `y` 坐标**必须使用千分比（0~1000）** 的归一化格式：
- `(0, 0)` 代表屏幕左上角。
- `(500, 500)` 代表屏幕正中心。
- `(1000, 1000)` 代表屏幕右下角。

> [!WARNING]
> 切勿直接使用诸如 `(1920, 1080)` 这样的绝对像素值，系统会自动根据千分比转换为实际像素。

---

## 暴露的 Tool: `screenshot_and_act`

系统向你暴露了唯一的函数 `screenshot_and_act(action_type, parameters)`。你可以传入以下 `action_type` 极其对应的 `parameters` JSON：

### 1. 点击类 (Clicking)
包含 `click`, `double_click`, `right_click`：
```json
{
  "action_type": "click",
  "parameters": {
    "x": 850,
    "y": 150
  }
}
```

### 2. 键盘输入文字 (Typing)
将文字填入剪贴板并模拟 `Ctrl+V`，是最安全的文本输入方式。
> 先确保光标已在目标输入框内，通常需要先调用一次 `click`。
```json
{
  "action_type": "type",
  "parameters": {
    "text": "Hello World"
  }
}
```

### 3. 物理按键 (Pressing)
模拟按下特定的功能键或组合快捷键：
```json
{
  "action_type": "press",
  "parameters": {
    "keys": ["ctrl", "c"]
  }
}
```
常用的 `keys` 包括：`enter`, `esc`, `win`, `delete`, `tab`, `space` 等。

### 4. 滚动 (Scrolling)
默认在当前鼠标位置滚动，也可指定坐标先移动鼠标再滚动：
```json
{
  "action_type": "scroll",
  "parameters": {
    "amount": -500,  // 负数为向下滚动，正数为向上滚动
    "x": 500,        // 可选：指定在屏幕中心滚动
    "y": 500         // 可选
  }
}
```

### 5. 拖拽 (Dragging)
指定起止千分比坐标进行拖拽操作（例如调整窗口大小或拖动文件）：
```json
{
  "action_type": "drag",
  "parameters": {
    "start_x": 100,
    "start_y": 100,
    "end_x": 300,
    "end_y": 400,
    "duration": 0.5  // 可选：拖拽持续秒数
  }
}
```

---

## 常见最佳实践流

当你面临一个需要图形界面干预的复杂任务时，标准工作流为：
1. 眼看手动：大脑视觉神经传入最新一帧屏幕状态。
2. 识别出目标物体的比例坐标（如屏幕右上角关闭按钮约为 x=980, y=20）。
3. 调用 `screenshot_and_act` 执行 `"click" {x: 980, y: 20}`。
4. 等待几秒钟让 UI 响应。
5. 再次观察屏幕反馈。
