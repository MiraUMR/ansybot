import re
from datetime import datetime, timedelta
from typing import List, Optional, Union

from kirara_ai.im.message import IMMessage, MediaMessage, TextMessage
from kirara_ai.im.sender import ChatSender
from kirara_ai.llm.format.message import (LLMChatContentPartType, LLMChatImageContent, LLMChatMessage,
                                          LLMChatTextContent, RoleType)
from kirara_ai.logger import get_logger
from kirara_ai.media.manager import MediaManager
from kirara_ai.memory.entry import MemoryEntry

from .base import ComposableMessageType, MemoryComposer, MemoryDecomposer


def drop_think_part(text: str) -> str:
    return re.sub(r"(?:<think>[\s\S]*?</think>)?([\s\S]*)", r"\1", text, flags=re.DOTALL)


_VOICE_CAPTION_RE = re.compile(
    r"发给|截图|soyorin|小爱音|走不动|某人|拉她|给她看",
    re.IGNORECASE,
)


def _format_media_line(media_id: str, desc: Optional[str]) -> str:
    """记忆里把图片写成短物象，避免把整段角色回复再喂回去。"""
    cleaned = (desc or "").strip()
    if cleaned:
        cleaned = re.sub(r"\s+", " ", cleaned)
        if _VOICE_CAPTION_RE.search(cleaned) or len(cleaned) >= 40:
            return "[图片]\n"
        if len(cleaned) > 36:
            cleaned = cleaned[:36] + "…"
        return f"[图片: {cleaned}]\n"
    return "[图片]\n"


class DefaultMemoryComposer(MemoryComposer):
    def compose(
        self, sender: Optional[ChatSender], message: List[ComposableMessageType]
    ) -> MemoryEntry:
        composed_message = ""
        media_ids = []
        for msg in message:
            if isinstance(msg, IMMessage):
                composed_message += f"{msg.sender.display_name} 说: \n"
                for element in msg.message_elements:
                    if isinstance(element, MediaMessage):
                        desc = element.get_description()
                        composed_message += _format_media_line(element.media_id, desc)
                        media_ids.append(element.media_id)
                    elif isinstance(element, TextMessage):
                        composed_message += f"{element.to_plain()}\n"
                    else:
                        composed_message += element.to_plain()
            elif isinstance(msg, LLMChatMessage):
                composed_message += f"你回答: \n"
                for part in msg.content:
                    if isinstance(part, LLMChatTextContent):
                        composed_message += f"{drop_think_part(part.text)}\n"
                    elif isinstance(part, LLMChatImageContent):
                        media = self.container.resolve(MediaManager).get_media(part.media_id)
                        desc = media.description if media else ""
                        composed_message += _format_media_line(part.media_id, desc)
                        media_ids.append(part.media_id)

        composed_message = composed_message.strip()
        composed_at = datetime.now()
        return MemoryEntry(
            sender=sender or ChatSender.get_bot_sender(),
            content=composed_message,
            timestamp=composed_at,
            metadata={
                "_media_ids": media_ids,
            },
        )


class DefaultMemoryDecomposer(MemoryDecomposer):
    def decompose(self, entries: List[MemoryEntry]) -> List[ComposableMessageType]:
        if len(entries) == 0:
            return [self.empty_message]

        # 7秒前，<记忆内容>
        memory_texts: List[ComposableMessageType] = []
        for entry in entries[-10:]:
            time_diff = datetime.now() - entry.timestamp
            time_str = self.get_time_str(time_diff)
            memory_texts.append(f"{time_str}，{entry.content}")

        return memory_texts

    def get_time_str(self, time_diff: timedelta) -> str:
        if time_diff.days > 0:
            return f"{time_diff.days}天前"
        elif time_diff.seconds > 3600:
            return f"{time_diff.seconds // 3600}小时前"
        elif time_diff.seconds > 60:
            return f"{time_diff.seconds // 60}分钟前"
        else:
            return "刚刚"


_CHASE_CUE_RE = re.compile(
    r"(哭了|在哭|好像在哭|要跑|跑了|跑掉|追上|快追|去追|追呀|追啊|"
    r"要你追|追不到|追她|快去追|人都没了|人都沒了|别回来|別回來|"
    r"不要你了|不要她了)"
)
_COLD_CHASE_REPLY_RE = re.compile(
    r"(算了.{0,16}明天|反正明天就能|麻烦死了|又不差这一会儿|追什么追|"
    r"鞋带.{0,12}(没系|沒系|要是|松了))"
)


class MultiElementDecomposer(MemoryDecomposer):
    logger = get_logger("MultiElementDecomposer")
    
    def decompose(self, entries: List[MemoryEntry]) -> List[LLMChatMessage]:
        decomposed_messages = []
        for entry in entries:
            # 首先判断MemoryEntry的内容是否包含"你回答:"
            if "你回答:" in entry.content:
                # 如果包含，则分割MemoryEntry的内容为用户消息和AI回答
                user_content = entry.content.split("你回答:")[0].strip()
                assistant_content = entry.content.split("你回答:")[1].strip()
                # 危急场面里的冷收束口误：只留群友那句，避免下一轮继续抄鞋带/明天见
                if _CHASE_CUE_RE.search(user_content) and _COLD_CHASE_REPLY_RE.search(
                    assistant_content
                ):
                    assistant_content = ""

                # 处理用户消息
                user_message = self.create_llm_chat_message(user_content, "user", entry.sender)
                if user_message:
                    decomposed_messages.append(user_message)

                # 处理AI回答
                if assistant_content:
                    assistant_message = self.create_llm_chat_message(assistant_content, "assistant", entry.sender)
                    if assistant_message:
                        decomposed_messages.append(assistant_message)
            else:
                # 如果不包含"你回答:"，则全部视为用户消息
                user_message = self.create_llm_chat_message(entry.content, "user", entry.sender)
                if user_message:
                    decomposed_messages.append(user_message)

        # 合并相邻的相同角色消息
        i = 0
        while i < len(decomposed_messages) - 1:
            current_msg = decomposed_messages[i]
            next_msg = decomposed_messages[i + 1]
            
            if current_msg.role == next_msg.role:
                # 合并内容
                current_msg.content.extend(next_msg.content)
                # 删除下一个消息
                decomposed_messages.pop(i + 1)
            else:
                i += 1

        return decomposed_messages

    def create_llm_chat_message(self, content: str, role: RoleType, sender: ChatSender) -> Union[LLMChatMessage, None]:
        message_content: List[LLMChatContentPartType] = []

        # 兼容旧 <media_msg> 与新 [图片: ...] / [图片 id=...]
        media_msg_pattern = re.compile(r'<media_msg id=(.*?) desc="(.*?)" />')
        matches = media_msg_pattern.findall(content)

        last_index = 0
        for media_id, description in matches:
            start_index = content.find(f'<media_msg id={media_id} desc="{description}" />', last_index)
            if start_index > last_index:
                text_content = content[last_index:start_index]
                message_content.append(LLMChatTextContent(text=text_content))
            # 校验媒体资源有效性
            media_object = self.container.resolve(MediaManager).get_media(media_id)
            if media_object:
                message_content.append(LLMChatImageContent(media_id=media_id))
            else:
                self.logger.warning(f"媒体资源无效: {media_id}")
                message_content.append(LLMChatTextContent(text=f"<media_msg id={media_id} desc=\"{description}\" status=\"error: 媒体资源无效\"/> "))
            last_index = start_index + len(f'<media_msg id={media_id} desc="{description}" />')

        # 处理剩余的文本内容
        if last_index < len(content):
            message_content.append(LLMChatTextContent(text=content[last_index:]))

        if message_content:
            return LLMChatMessage(role=role, content=message_content)
        else:
            return None
