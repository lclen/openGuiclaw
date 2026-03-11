# Context 视觉感知系统

## 概述

ContextManager 是 OpenGuiclaw 的视觉感知引擎，通过后台线程定时截屏并使用 Vision 模型分析用户当前状态，支持主动搭话和状态日志记录。它让 AI 具备"看见"用户屏幕的能力。

## 架构

```
ContextManager
├── 后台线程（定时截屏）
├── Vision 模型分析（Qwen-VL）
├── 状态判定（working/entertainment/idle/error）
├── 日志去重（避免重复记录）
├── 主动搭话（三种模式：silent/normal/lively）
└── 冷却机制（避免过度打扰）
```

## 核心功能

### 1. 状态判定

```python
# Vision 模型返回的状态
{
    "summary": "用户在 VSCode 编辑 agent.py",
    "status": "working",  # working | entertainment | idle | error
    "needs_interaction": false,
    "suggested_message": null
}
```

**状态定义**：
- **working**: 正在工作（编辑器、终端、文档、协同工具）
- **entertainment**: 娱乐休闲（视频网站、社交媒体、游戏）
- **idle**: 发呆/空闲（桌面、屏保、静态网页）
- **error**: 看到报错（红色日志、警告对话框）

### 2. 活泼度模式

```python
MODE_SILENT  = "silent"   # 静默：只记录日志，永不主动打扰
MODE_NORMAL  = "normal"   # 正常：仅在出错或明显空闲时才打扰
MODE_LIVELY  = "lively"   # 活泼：积极寒暄，状态变化时就出声
```

**模式行为**：
- **silent**: 完全不打扰，只记录视觉日志
- **normal**: 沿用模型判断（needs_interaction）
- **lively**: 娱乐/空闲时主动搭话，工作时不打扰

### 3. 日志去重

```python
# 避免重复记录相同状态
if _last_summary and _last_status == status:
    # 计算词级别相似度
    sim = jaccard_similarity(_last_summary, summary)
    if sim >= 0.55:  # 55% 重合度
        # 更新持续时间，而不是新增日志
        update_visual_log(current_time)
        return
```

### 4. 冷却机制

```python
# 主动搭话后进入冷却期
if elapsed_since_last < cooldown_minutes:
    return  # 用户未回复，保持安静

# 用户回复后重置冷却
def notify_user_replied():
    self._last_proactive_at = 0.0
```

### 5. 手动触发

```python
# 强制触发一次分析（忽略冷却）
context.poke()

# 会强制生成 suggested_message
```

## API 接口

### 初始化

```python
from core.context import ContextManager

context = ContextManager(
    client=openai_client,
    vision_model="qwen-vl-plus",
    add_visual_log_func=session.add_message,
    get_visual_history_func=lambda: session.messages[-10:],
    update_visual_log_func=session.update_last_visual_log,
    interval_minutes=5,
    notification_queue=queue.Queue(),
    cooldown_minutes=30,
    get_history_func=lambda: session.get_history()[-5:],
    proactive_config={
        "mode": "normal",
        "interval_minutes": 5,
        "cooldown_minutes": 30,
        "verbose": True
    }
)
```

### 启动/停止

```python
# 启动后台线程
context.start()

# 停止后台线程
context.stop()

# 暂停/恢复
context.set_enabled(False)  # 暂停
context.set_enabled(True)   # 恢复
```

### 模式切换

```python
# 切换活泼度模式
context.set_mode("lively")  # silent | normal | lively

# 动态重载配置
context.reload_config({
    "mode": "normal",
    "interval_minutes": 10,
    "cooldown_minutes": 20,
    "verbose": False
})
```

### 手动触发

```python
# 强制触发一次分析
context.poke()

# 通知用户已回复（重置冷却）
context.notify_user_replied()
```

### 读取通知

```python
# 从队列读取主动搭话消息
try:
    payload = context.notification_queue.get(timeout=0.1)
    if payload["type"] == "proactive":
        print(f"AI: {payload['message']}")
except queue.Empty:
    pass
```

## 配置

### config.json

```json
{
  "vision": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-xxx",
    "model": "qwen-vl-plus"
  },
  "proactive": {
    "mode": "normal",
    "interval_minutes": 5,
    "cooldown_minutes": 30,
    "verbose": true
  }
}
```

### Vision Prompt

```python
VISION_PROMPT = """
请分析这张屏幕截图，用简体中文描述用户当前正在做什么。

状态判定准则：
- status: working | entertainment | idle | error
- working: 编辑器、终端、文档、协同工具
- entertainment: 视频网站、社交媒体、游戏
- idle: 桌面、屏保、静态网页
- error: 红色报错、警告对话框

要求：
- summary: 1~2句话简洁描述
- status: 见上文
- needs_interaction: 布尔值（entertainment/idle/error 时为 true）
- suggested_message: 人性化互动内容（1~3句）

返回纯 JSON，不要 Markdown 代码块。
"""
```

## 最佳实践

### 1. 合理设置间隔

```python
# 开发/工作场景：5 分钟
"interval_minutes": 5

# 日常使用：10 分钟
"interval_minutes": 10

# 省电模式：30 分钟
"interval_minutes": 30

# 完全禁用：null
"interval_minutes": null
```

### 2. 冷却时间调整

```python
# 活泼模式：10 分钟
if mode == "lively":
    cooldown_minutes = 10

# 正常模式：30 分钟
else:
    cooldown_minutes = 30
```

### 3. 错误状态处理

```python
# 用户要求：报错状态不再触发主动搭话
if status == "error":
    needs_interaction = False
```

### 4. 视觉日志格式

```python
# 添加视觉日志
log_entry = f"**[视觉日志]** 状态: `{status}` — {summary}"
session.add_message("visual_log", log_entry)

# 更新持续时间
session.update_last_visual_log("14:35:00")
# 结果: "**[视觉日志]** 状态: `working` — 用户在编辑 agent.py（持续至 14:35:00）"
```

### 5. SSE 广播

```python
# 将分析结果推送到前端
if context.log_queue is not None:
    context.log_queue.put({
        "type": "context",
        "status": status,
        "summary": summary,
        "needs_interaction": needs_interaction,
        "ts": time.strftime("%H:%M:%S")
    })
```

## 故障排查

### 问题 1: 截屏失败

**症状**：`_capture_screen()` 返回 None

**解决方案**：
```python
# 检查依赖
try:
    import pyautogui
    from PIL import Image
    print("依赖已安装")
except ImportError as e:
    print(f"缺少依赖: {e}")
    # pip install pyautogui pillow

# 检查权限（macOS）
# 系统偏好设置 → 安全性与隐私 → 屏幕录制
```

### 问题 2: Vision 模型返回非 JSON

**症状**：JSON 解析失败

**解决方案**：
```python
# 清理 Markdown 代码块
if "```" in text:
    text = text.split("```")[-2] if "```" in text else text
    text = text.lstrip("json").strip()

# 或者在 Prompt 中强调
"返回纯 JSON，不要 Markdown 代码块。"
```

### 问题 3: 频繁触发 429 错误

**症状**：API 频率限制

**解决方案**：
```python
# 增加重试逻辑（已内置）
retry_count = 0
while retry_count < 3:
    try:
        response = client.chat.completions.create(...)
        break
    except Exception as e:
        if "429" in str(e):
            retry_count += 1
            wait_time = 5 * retry_count
            time.sleep(wait_time)
        else:
            raise

# 或者增加间隔
"interval_minutes": 10  # 从 5 分钟改为 10 分钟
```

### 问题 4: 主动搭话过于频繁

**症状**：AI 不停打扰用户

**解决方案**：
```python
# 检查冷却机制
print(f"上次主动搭话: {context._last_proactive_at}")
print(f"冷却时间: {context.cooldown_minutes} 分钟")

# 增加冷却时间
context.reload_config({"cooldown_minutes": 60})

# 或者切换到静默模式
context.set_mode("silent")
```

### 问题 5: 日志重复

**症状**：相同状态被重复记录

**解决方案**：
```python
# 检查去重逻辑
# 已内置 55% 相似度阈值
# 如果仍然重复，调整阈值：
if sim >= 0.70:  # 从 0.55 提高到 0.70
    is_duplicate = True
```

## 性能优化

### 1. 图片压缩

```python
# 截图后缩放到 960×540
screenshot.thumbnail((960, 540), Image.LANCZOS)

# 进一步压缩（降低质量）
buf = io.BytesIO()
screenshot.save(buf, format="PNG", optimize=True, quality=85)
```

### 2. 延迟启动

```python
# 避开系统启动时的 API 高峰
def _delayed_start():
    time.sleep(10)  # 延迟 10 秒
    context.start()

threading.Thread(target=_delayed_start, daemon=True).start()
```

### 3. 批量分析

```python
# 累积多张截图后批量分析（节省 API 调用）
# 注意：需要修改 Vision Prompt 支持多图
```

### 4. 缓存分析结果

```python
# 相同截图不重复分析
import hashlib

_screenshot_cache = {}

def analyze_with_cache(screenshot_b64: str) -> dict:
    hash_key = hashlib.md5(screenshot_b64.encode()).hexdigest()
    if hash_key in _screenshot_cache:
        return _screenshot_cache[hash_key]
    
    result = _analyze_screen(screenshot_b64)
    _screenshot_cache[hash_key] = result
    return result
```

## 未来优化方向

1. **OCR 文本提取**：从截图中提取文本，提高分析准确度
2. **窗口焦点检测**：只分析活动窗口，减少噪音
3. **应用识别**：识别具体应用（Chrome、VSCode、Telegram）
4. **行为模式学习**：学习用户的工作/娱乐时间规律
5. **多屏支持**：支持多显示器截图和分析
6. **隐私保护**：敏感内容自动模糊处理
7. **离线模式**：使用本地 Vision 模型（如 LLaVA）
