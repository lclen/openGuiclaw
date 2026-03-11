# IM 通道系统 (Channels)

## 概述

IM 通道系统负责接入多个即时通讯平台（DingTalk、Feishu、Telegram 等），实现消息收发和事件处理。

**文件位置**: `core/channels/gateway.py`, `core/channels/adapters/`

---

## 架构

```
┌──────────────────────────────────────────┐
│         ChannelGateway                   │
│  (统一消息路由和适配器管理)               │
└──────────────────────────────────────────┘
           ↓           ↓           ↓
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ DingTalk │ │ Feishu   │ │ Telegram │
    │ Adapter  │ │ Adapter  │ │ Adapter  │
    └──────────┘ └──────────┘ └──────────┘
           ↓           ↓           ↓
    ┌──────────────────────────────────────┐
    │         Agent (核心对话引擎)          │
    └──────────────────────────────────────┘
```

---

## 支持的平台

| 平台 | 适配器文件 | 功能 |
|-----|-----------|------|
| DingTalk | `adapters/dingtalk.py` | 文本消息、图片、@提及 |
| Feishu | `adapters/feishu.py` | 文本消息、图片、卡片 |
| Telegram | `adapters/telegram.py` | 文本消息、图片、命令 |

---

## ChannelGateway

### 初始化

```python
from core.channels.gateway import ChannelGateway

gateway = ChannelGateway(agent=agent)
```

### 注册适配器

```python
# DingTalk
from core.channels.adapters.dingtalk import DingTalkAdapter
gateway.register_adapter(DingTalkAdapter(
    app_key="dingxxx",
    app_secret="xxx"
))

# Feishu
from core.channels.adapters.feishu import FeishuAdapter
gateway.register_adapter(FeishuAdapter(
    app_id="cli_xxx",
    app_secret="xxx",
    verification_token="xxx",
    encrypt_key="xxx"
))

# Telegram
from core.channels.adapters.telegram import TelegramAdapter
gateway.register_adapter(TelegramAdapter(
    bot_token="123456:ABC-DEF",
    proxy="http://127.0.0.1:7890"  # 可选
))
```

### 启动 / 停止

```python
await gateway.start()   # 启动所有适配器
await gateway.stop()    # 停止所有适配器
```

---

## 适配器接口

所有适配器必须实现以下接口：

```python
class BaseAdapter(ABC):
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台名称，如 'dingtalk', 'feishu', 'telegram'"""
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """启动适配器（如启动 webhook 服务器、长轮询等）"""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止适配器"""
        pass
    
    @abstractmethod
    async def send_message(self, channel_id: str, content: str, **kwargs) -> bool:
        """发送消息到指定频道"""
        pass
    
    @abstractmethod
    async def handle_message(self, raw_message: dict) -> None:
        """处理接收到的消息"""
        pass
```

---

## DingTalk 适配器

### 配置

```json
{
  "channels": {
    "dingtalk": {
      "client_id": "dingxxx",
      "client_secret": "xxx"
    }
  }
}
```

### 功能

- **接收消息**：通过 Stream 模式接收实时消息
- **发送消息**：支持文本、Markdown、图片
- **@提及**：识别 @机器人 的消息
- **群聊支持**：支持群聊和单聊

### 消息格式

```python
{
    "conversationId": "cidxxx",  # 会话 ID
    "senderId": "xxx",           # 发送者 ID
    "senderNick": "张三",        # 发送者昵称
    "text": "你好",              # 消息内容
    "msgtype": "text",           # 消息类型
    "conversationType": "1"      # 1=单聊, 2=群聊
}
```

### 示例

```python
# 发送文本消息
await adapter.send_message(
    channel_id="cidxxx",
    content="你好，我是 AI 助手"
)

# 发送 Markdown
await adapter.send_message(
    channel_id="cidxxx",
    content="## 标题\n- 列表项",
    msgtype="markdown"
)
```

---

## Feishu 适配器

### 配置

```json
{
  "channels": {
    "feishu": {
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "verification_token": "xxx",
      "encrypt_key": "xxx"
    }
  }
}
```

### 功能

- **接收消息**：通过 Webhook 接收消息
- **发送消息**：支持文本、富文本、卡片
- **事件订阅**：支持消息事件、@提及事件
- **加密验证**：支持消息加密和签名验证

### 消息格式

```python
{
    "event": {
        "message": {
            "chat_id": "oc_xxx",      # 会话 ID
            "message_id": "om_xxx",   # 消息 ID
            "sender": {
                "sender_id": {
                    "user_id": "ou_xxx"  # 发送者 ID
                }
            },
            "content": "{\"text\":\"你好\"}",  # JSON 字符串
            "message_type": "text"
        }
    }
}
```

### 示例

```python
# 发送文本消息
await adapter.send_message(
    channel_id="oc_xxx",
    content="你好，我是 AI 助手"
)

# 发送卡片
await adapter.send_message(
    channel_id="oc_xxx",
    content="",
    card={
        "header": {"title": {"content": "通知"}},
        "elements": [{"tag": "div", "text": {"content": "这是一条卡片消息"}}]
    }
)
```

---

## Telegram 适配器

### 配置

```json
{
  "channels": {
    "telegram": {
      "bot_token": "123456:ABC-DEF",
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

### 功能

- **接收消息**：通过长轮询 (getUpdates) 接收消息
- **发送消息**：支持文本、Markdown、HTML
- **命令支持**：识别 `/start`, `/help` 等命令
- **代理支持**：支持 HTTP/SOCKS5 代理

### 消息格式

```python
{
    "message": {
        "chat": {"id": 123456},      # 会话 ID
        "from": {"id": 789, "first_name": "张三"},  # 发送者
        "text": "你好",              # 消息内容
        "message_id": 1234           # 消息 ID
    }
}
```

### 示例

```python
# 发送文本消息
await adapter.send_message(
    channel_id="123456",
    content="你好，我是 AI 助手"
)

# 发送 Markdown
await adapter.send_message(
    channel_id="123456",
    content="**粗体** _斜体_",
    parse_mode="Markdown"
)
```

---

## 消息处理流程

```
1. 平台推送消息 → Adapter.handle_message()
2. 解析消息格式 → 提取 channel_id, user_id, content
3. 调用 Agent.chat() → 生成回复
4. Adapter.send_message() → 发送回复到平台
```

### 示例代码

```python
async def handle_message(self, raw_message: dict):
    # 1. 解析消息
    channel_id = raw_message["conversationId"]
    user_id = raw_message["senderId"]
    content = raw_message["text"]
    
    # 2. 调用 Agent
    response = await self.agent.chat(content, user_id=user_id)
    
    # 3. 发送回复
    await self.send_message(channel_id, response)
```

---

## 配置示例

完整的 `config.json` 配置：

```json
{
  "channels": {
    "dingtalk": {
      "client_id": "dingxxx",
      "client_secret": "xxx"
    },
    "feishu": {
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "verification_token": "xxx",
      "encrypt_key": "xxx"
    },
    "telegram": {
      "bot_token": "123456:ABC-DEF",
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

---

## API 接口

### Webhook 端点

```
POST /api/channels/dingtalk/webhook    # DingTalk 消息回调
POST /api/channels/feishu/webhook      # Feishu 消息回调
```

### 管理接口

```
GET  /api/channels                     # 列出所有通道
POST /api/channels/{platform}/send     # 发送消息
GET  /api/channels/{platform}/status   # 查看通道状态
```

---

## 最佳实践

1. **配置验证**：启动前验证 API Key 和 Secret
2. **错误重试**：消息发送失败时自动重试（最多 3 次）
3. **日志记录**：记录所有消息收发日志，便于排查问题
4. **限流保护**：避免频繁发送消息触发平台限流
5. **安全验证**：验证 Webhook 签名，防止伪造消息

---

## 故障排查

### DingTalk 消息收不到

1. 检查 Stream 连接状态：查看日志 `DingTalk Stream connected`
2. 验证 client_id 和 client_secret
3. 确认机器人已添加到群聊

### Feishu 消息发送失败

1. 检查 access_token 是否过期
2. 验证 app_id 和 app_secret
3. 确认机器人有发送消息权限

### Telegram 代理连接失败

1. 测试代理连通性：`curl -x http://127.0.0.1:7890 https://api.telegram.org`
2. 尝试更换代理服务器
3. 检查防火墙设置

---

## 未来优化方向

1. **更多平台支持**：企业微信、QQ、Discord
2. **消息队列**：使用 Redis 队列处理高并发消息
3. **多机器人支持**：同一平台支持多个机器人实例
4. **消息模板**：预定义常用消息模板
