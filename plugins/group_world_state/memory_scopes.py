from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.memory.scopes.base import MemoryScope


class CharacterGroupScope(MemoryScope):
    """按「角色 + 群」隔离近期记忆，避免双机串戏。"""

    def __init__(self, character: str):
        self.character = (character or "anon").strip() or "anon"

    def get_scope_key(self, sender: ChatSender) -> str:
        if sender.chat_type == ChatType.GROUP:
            return f"group:{sender.group_id}:{self.character}"
        return f"c2c:{sender.user_id}:{self.character}"

    def is_in_scope(self, target_sender: ChatSender, query_sender: ChatSender) -> bool:
        if target_sender.chat_type != query_sender.chat_type:
            return False
        if target_sender.chat_type == ChatType.GROUP:
            return target_sender.group_id == query_sender.group_id
        return target_sender.user_id == query_sender.user_id
