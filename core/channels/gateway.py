"""
消息网关 (Message Gateway)

负责维护所有的通道适配器（DingTalk, Feishu, Telegram），
接收来自通道的消息，处理媒体文件，并将消息路由到 Agent，最后将回复发送回通道。
"""

import asyncio
import base64
import logging
import mimetypes
from typing import Dict, Any

from .base import ChannelAdapter
from .types import UnifiedMessage, OutgoingMessage, MessageContent
from core.session import Session

logger = logging.getLogger(__name__)


class ChannelGateway:
    def __init__(self, agent: Any):
        """
        Args:
            agent: openGuiclaw 的核心 Agent 实例
        """
        self.agent = agent
        self.adapters: Dict[str, ChannelAdapter] = {}
        # 简单的并发锁，避免多通道或多用户同时处理消息时污染全局 session
        self._lock = asyncio.Lock()

    def register_adapter(self, adapter: ChannelAdapter) -> None:
        """注册一个通道适配器，并绑定消息回调"""
        self.adapters[adapter.channel_name] = adapter
        adapter.on_message(self._on_message)
        logger.info(f"Registered channel adapter: {adapter.channel_name}")

    async def start(self) -> None:
        """启动所有已注册的适配器"""
        logger.info("Starting Channel Gateway...")
        for name, adapter in self.adapters.items():
            try:
                await adapter.start()
                logger.info(f"Started adapter: {name}")
            except Exception as e:
                logger.error(f"Failed to start adapter {name}: {e}", exc_info=True)

    async def stop(self) -> None:
        """停止所有适配器"""
        logger.info("Stopping Channel Gateway...")
        for name, adapter in self.adapters.items():
            try:
                await adapter.stop()
                logger.info(f"Stopped adapter: {name}")
            except Exception as e:
                logger.error(f"Failed to stop adapter {name}: {e}", exc_info=True)

    async def _on_message(self, message: UnifiedMessage) -> None:
        """
        统一的消息处理入口
        """
        try:
            logger.info(f"[Gateway] Received message from {message.channel}:{message.chat_id}")
            
            # 使用后台任务处理消息，以免阻塞适配器的接收循环
            asyncio.create_task(self._process_message_task(message))
            
        except Exception as e:
            logger.error(f"[Gateway] Error handling message: {e}", exc_info=True)

    async def _process_message_task(self, message: UnifiedMessage) -> None:
        """实际处理单条消息的逻辑，包含下载媒体和调用 Agent"""
        adapter = self.adapters.get(message.channel)
        if not adapter:
            logger.error(f"[Gateway] Unknown channel: {message.channel}")
            return

        # ==========================================
        # 1. 预处理媒体文件
        # ==========================================
        text_parts = []
        final_content = []

        if message.content.text:
            text_parts.append(message.content.text)

        # 处理图片
        for img in message.content.images:
            if not img.local_path:
                try:
                    await adapter.download_media(img)
                except Exception as e:
                    logger.error(f"[Gateway] Failed to download image {img.file_id}: {e}")
            
            if img.local_path:
                try:
                    with open(img.local_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    mime = img.mime_type or mimetypes.guess_type(img.local_path)[0] or "image/jpeg"
                    data_url = f"data:{mime};base64,{b64}"
                    final_content.append({"type": "image_url", "image_url": {"url": data_url}})
                except Exception as e:
                    logger.error(f"[Gateway] Failed to encode image: {e}")

        # 处理语音（如果没有集成 STT，目前直接给出提示）
        if message.content.voices:
            text_parts.append("[收到语音消息]")

        # 处理文件
        for file in message.content.files:
            text_parts.append(f"[收到文件附件: {file.filename}]")

        if text_parts:
            final_content.append({"type": "text", "text": "\n".join(text_parts).strip()})

        if not final_content:
            logger.warning("[Gateway] Message content is empty after processing.")
            return

        # 决定是以 list 还是纯文本发送 (适配 agent 的输入要求)
        if len(final_content) == 1 and final_content[0]["type"] == "text":
            user_input = final_content[0]["text"]
        else:
            user_input = final_content

        # ==========================================
        # 2. 会话管理与 Agent 调用
        # ==========================================
        # 每个渠道+聊天 生成独立的 Session ID（格式：dingtalk_chatId）
        session_id = f"{message.channel}_{message.chat_id}"
        
        # 采用全局锁避免同时调用 agent 造成全局 session 相互覆盖
        async with self._lock:
            # ====== 记录当前 GUI 会话，稍后恢复 ======
            # 注意：直接保存 Session 对象引用，而不是 session_id，
            # 这样恢复时只需要修改指针，不需要从磁盘 load（避免覆盖正在进行中的 GUI 会话）
            gui_session = None
            if hasattr(self.agent.sessions, "_current") and self.agent.sessions._current:
                current_id = getattr(self.agent.sessions._current, "session_id", None)
                # 只有 GUI 的普通会话才需要恢复（IM 会话本身不需要恢复）
                is_im = any(
                    current_id and current_id.startswith(p)
                    for p in ("dingtalk_", "feishu_", "telegram_")
                )
                if not is_im:
                    gui_session = self.agent.sessions._current

            # ====== 加载或创建 IM 专属会话 ======
            im_session = self.agent.sessions.load(session_id)
            if not im_session:
                im_session = Session(session_id)
                self.agent.sessions._current = im_session
                # 立即保存新会话到磁盘，防止数据丢失
                self.agent.sessions.save(im_session)
            
            try:
                # 发送正在输入状态
                await adapter.send_typing(message.chat_id)

                full_response = ""
                # 调用 agent 的流式输出（兼容工具调用等复杂行为）
                async for chunk_str in self.agent.chat_stream(user_input):
                    try:
                        import json as _json
                        chunk = _json.loads(chunk_str) if isinstance(chunk_str, str) else chunk_str
                    except Exception:
                        chunk = {}
                    if isinstance(chunk, dict) and chunk.get("type") == "message_chunk":
                        full_response += chunk.get("content", "")

                # ==========================================
                # 3. 发送回复
                # ==========================================
                if full_response.strip():
                    out_msg = OutgoingMessage.text(
                        chat_id=message.chat_id,
                        text=full_response.strip()
                    )
                    await adapter.send_message(out_msg)

            except Exception as e:
                logger.error(f"[Gateway] Error during agent execution: {e}", exc_info=True)
                out_msg = OutgoingMessage.text(
                    chat_id=message.chat_id,
                    text=f"机器人处理消息时发生异常：{str(e)}"
                )
                await adapter.send_message(out_msg)

            finally:
                # 保存 IM 会话状态
                self.agent.sessions.save(self.agent.sessions._current)
                
                # ====== 恢复 GUI 会话指针（只修改内存指针，不从磁盘 load）======
                if gui_session is not None:
                    self.agent.sessions._current = gui_session
                    logger.debug(f"[Gateway] Restored GUI session: {gui_session.session_id}")

