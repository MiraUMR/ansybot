import re
from typing import List

from pydantic import Field

from kirara_ai.im.message import IMMessage
from kirara_ai.im.sender import ChatSender
from kirara_ai.workflow.core.workflow.registry import WorkflowRegistry

from .base import DispatchRule, RuleConfig


class RegexRuleConfig(RuleConfig):
    """正则规则配置"""
    pattern: str = Field(title="正则表达式", description="正则表达式")

class RegexMatchRule(DispatchRule):
    """根据正则表达式匹配的规则"""
    config_class = RegexRuleConfig
    type_name = "regex"

    def __init__(self, pattern: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.pattern = re.compile(pattern)

    def match(self, message: IMMessage) -> bool:
        return bool(self.pattern.search(message.content))

    def get_config(self) -> RegexRuleConfig:
        return RegexRuleConfig(pattern=self.pattern.pattern)

    @classmethod
    def from_config(cls, config: RegexRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str) -> "RegexMatchRule":
        return cls(config.pattern, workflow_registry, workflow_id)

class PrefixRuleConfig(RuleConfig):
    """前缀规则配置"""
    prefix: str = Field(title="前缀", description="前缀")

class PrefixMatchRule(DispatchRule):
    """根据消息前缀匹配的规则"""
    config_class = PrefixRuleConfig
    type_name = "prefix"

    def __init__(self, prefix: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.prefix = prefix

    def match(self, message: IMMessage) -> bool:
        return message.content.startswith(self.prefix)

    def get_config(self) -> PrefixRuleConfig:
        return PrefixRuleConfig(prefix=self.prefix)

    @classmethod
    def from_config(cls, config: PrefixRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str) -> "PrefixMatchRule":
        return cls(config.prefix, workflow_registry, workflow_id)


class KeywordRuleConfig(RuleConfig):
    """关键词规则配置"""
    keywords: List[str] = Field(title="关键词", description="关键词列表")
    
class KeywordMatchRule(DispatchRule):
    """根据关键词匹配的规则"""
    config_class = KeywordRuleConfig
    type_name = "keyword"

    def __init__(self, keywords: list[str], workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.keywords = keywords

    def match(self, message: IMMessage) -> bool:
        return any(keyword in message.content for keyword in self.keywords)

    def get_config(self) -> KeywordRuleConfig:
        return KeywordRuleConfig(keywords=self.keywords)

    @classmethod
    def from_config(cls, config: KeywordRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str) -> "KeywordMatchRule":
        return cls(config.keywords, workflow_registry, workflow_id)


class KeywordMismatchMatchRule(DispatchRule):
    """消息不包含指定关键词时匹配"""
    config_class = KeywordRuleConfig
    type_name = "keyword_mismatch"

    def __init__(self, keywords: list[str], workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.keywords = keywords

    def match(self, message: IMMessage) -> bool:
        content = message.content or ""
        return all(keyword not in content for keyword in self.keywords)

    def get_config(self) -> KeywordRuleConfig:
        return KeywordRuleConfig(keywords=self.keywords)

    @classmethod
    def from_config(cls, config: KeywordRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str) -> "KeywordMismatchMatchRule":
        return cls(config.keywords, workflow_registry, workflow_id)
    
class BotMentionMatchRule(DispatchRule):
    """根据机器人被提及匹配的规则"""
    config_class = RuleConfig
    type_name = "bot_mention"

    def __init__(self, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)

    def match(self, message: IMMessage) -> bool:
        try:
            from group_world_state.mentions import addressed_to_self

            return addressed_to_self(message, "")
        except Exception:
            bot_sender = ChatSender.get_bot_sender()
            from kirara_ai.im.message import MentionElement

            return any(
                isinstance(element, MentionElement) and element.target == bot_sender
                for element in message.message_elements
            )

    def get_config(self) -> RuleConfig: 
        return RuleConfig()

    @classmethod
    def from_config(cls, config: RuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str) -> "BotMentionMatchRule":
        return cls(workflow_registry, workflow_id)


class IMAdapterRuleConfig(RuleConfig):
    """按 IM 适配器名称匹配（双号分流）"""
    im_name: str = Field(title="适配器名称", description="例如 qq_user_bot / qq_soyo")


class IMAdapterMatchRule(DispatchRule):
    """消息来自指定 IM 适配器时匹配。依赖 dispatcher 写入 sender.raw_metadata['im_name']。"""
    config_class = IMAdapterRuleConfig
    type_name = "im_adapter"

    def __init__(self, im_name: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.im_name = im_name

    def match(self, message: IMMessage) -> bool:
        meta = getattr(message.sender, "raw_metadata", None) or {}
        return str(meta.get("im_name") or "") == self.im_name

    def get_config(self) -> IMAdapterRuleConfig:
        return IMAdapterRuleConfig(im_name=self.im_name)

    @classmethod
    def from_config(
        cls, config: IMAdapterRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "IMAdapterMatchRule":
        return cls(config.im_name, workflow_registry, workflow_id)


class PeerInboundRuleConfig(RuleConfig):
    """同伴账号发来的消息：点名/@ 必回，或连环未冷却时续聊。"""
    character: str = Field(title="本机角色", description="anon / soyo")


class PeerInboundMatchRule(DispatchRule):
    """同伴入站：识别另一角色 QQ，并在点名或连环中触发。"""
    config_class = PeerInboundRuleConfig
    type_name = "peer_inbound"

    def __init__(self, character: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.character = (character or "anon").strip() or "anon"

    def match(self, message: IMMessage) -> bool:
        try:
            from group_world_state.characters import character_by_qq, peer_qq
            from group_world_state.peer import PeerChainStore
            from group_world_state.voice_text import has_voice, is_tts_caption, is_voice_only
        except Exception:
            return False

        sender_qq = str(message.sender.user_id or "")
        if not sender_qq or sender_qq != peer_qq(self.character):
            return False
        if is_voice_only(message) or has_voice(message):
            return False

        try:
            from group_world_state.mentions import addressed_to_self, mentioned_bot, mentioned_others

            if mentioned_others(message, self.character) and not addressed_to_self(
                message, self.character
            ):
                return False
            mentioned = mentioned_bot(message, self.character)
        except Exception:
            mentioned = False

        text = message.content or ""
        if is_tts_caption(text):
            return False
        from group_world_state.characters import aliases as char_aliases
        from group_world_state.peer import alias_hit, looks_addressed_to_self

        named = looks_addressed_to_self(text, self.character)
        if not named:
            # 同伴号提到本名就算入站。人类「提到」仍走 vocative；Bot 互聊不能要求 soyorin——。
            named = any(alias_hit(text, a) for a in char_aliases(self.character) if a)

        group_id = message.sender.group_id
        if not group_id:
            return bool(mentioned or named)
        try:
            store = PeerChainStore(__import__("pathlib").Path("data/world_state/_peer_chains"))
            allowed, _ = store.should_continue(group_id, self.character)
            if not allowed:
                return False
            if mentioned or named:
                return True
            last = store.last_speaker(group_id)
            peer_cid = character_by_qq(sender_qq)
            return bool(peer_cid and last == peer_cid)
        except Exception:
            return False

    def get_config(self) -> PeerInboundRuleConfig:
        return PeerInboundRuleConfig(character=self.character)

    @classmethod
    def from_config(
        cls, config: PeerInboundRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "PeerInboundMatchRule":
        return cls(config.character, workflow_registry, workflow_id)


def _extract_at_qqs(message: IMMessage) -> set[str]:
    try:
        from group_world_state.mentions import at_target_qqs

        targets, _ = at_target_qqs(message)
        return set(targets)
    except Exception:
        pass
    ats: set[str] = set()
    raw = message.raw_message
    items = None
    if isinstance(raw, dict):
        items = raw.get("message")
    elif raw is not None:
        items = getattr(raw, "message", None)
    if isinstance(items, list):
        for part in items:
            if isinstance(part, dict) and part.get("type") == "at":
                qq = str((part.get("data") or {}).get("qq") or "").strip()
                if qq and qq.lower() != "all":
                    ats.add(qq)
            else:
                ptype = getattr(part, "type", None)
                data = getattr(part, "data", None) or {}
                if ptype == "at":
                    qq = str(data.get("qq") or "").strip() if isinstance(data, dict) else ""
                    if qq and qq.lower() != "all":
                        ats.add(qq)
    # CQ fallback
    text = getattr(message, "content", "") or ""
    if isinstance(raw, dict) and raw.get("raw_message"):
        text = str(raw.get("raw_message"))
    for m in re.finditer(r"\[CQ:at,qq=(\d+)\]", str(text)):
        ats.add(m.group(1))
    return ats


def _self_qq(character: str, message: IMMessage) -> str:
    try:
        from group_world_state.characters import get_character
        configured = str(get_character(character).get("qq") or "").strip()
    except Exception:
        configured = ""
    raw = message.raw_message
    self_id = ""
    if isinstance(raw, dict):
        self_id = str(raw.get("self_id") or "").strip()
    elif raw is not None:
        self_id = str(getattr(raw, "self_id", "") or "").strip()
    return self_id or configured


class CharacterGateRuleConfig(RuleConfig):
    character: str = Field(title="本机角色", description="anon / soyo")


class NotOnlyAtPeerMatchRule(DispatchRule):
    """别人只 @ 同伴号、没 @ 本机时，本机不要抢答（避免爱音抢素世的 @）。"""
    config_class = CharacterGateRuleConfig
    type_name = "not_only_at_peer"

    def __init__(self, character: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.character = (character or "anon").strip() or "anon"

    def match(self, message: IMMessage) -> bool:
        try:
            from group_world_state.characters import peer_qq
        except Exception:
            return True
        peer = peer_qq(self.character)
        if not peer:
            return True
        ats = _extract_at_qqs(message)
        if not ats:
            return True
        self_qq = _self_qq(self.character, message)
        if peer in ats and self_qq not in ats:
            return False
        return True

    def get_config(self) -> CharacterGateRuleConfig:
        return CharacterGateRuleConfig(character=self.character)

    @classmethod
    def from_config(
        cls, config: CharacterGateRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "NotOnlyAtPeerMatchRule":
        return cls(config.character, workflow_registry, workflow_id)


class NotAtOthersMatchRule(DispatchRule):
    """只 @ 了别人、没 @ 本机时不匹配。随机插话不要打断群员之间的点名。"""
    config_class = CharacterGateRuleConfig
    type_name = "not_at_others"

    def __init__(self, character: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.character = (character or "anon").strip() or "anon"

    def match(self, message: IMMessage) -> bool:
        try:
            from group_world_state.mentions import mentioned_bot, mentioned_others
        except Exception:
            return True
        if mentioned_others(message, self.character) and not mentioned_bot(
            message, self.character
        ):
            return False
        return True

    def get_config(self) -> CharacterGateRuleConfig:
        return CharacterGateRuleConfig(character=self.character)

    @classmethod
    def from_config(
        cls, config: CharacterGateRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "NotAtOthersMatchRule":
        return cls(config.character, workflow_registry, workflow_id)



class SenderNotPeerMatchRule(DispatchRule):
    """发送者不是同伴账号时匹配（随机插话不要接同伴的话，留给 peer_inbound）。"""
    config_class = CharacterGateRuleConfig
    type_name = "sender_not_peer"

    def __init__(self, character: str, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)
        self.character = (character or "anon").strip() or "anon"

    def match(self, message: IMMessage) -> bool:
        try:
            from group_world_state.characters import peer_qq
        except Exception:
            return True
        peer = peer_qq(self.character)
        if not peer:
            return True
        return str(message.sender.user_id or "") != peer

    def get_config(self) -> CharacterGateRuleConfig:
        return CharacterGateRuleConfig(character=self.character)

    @classmethod
    def from_config(
        cls, config: CharacterGateRuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "SenderNotPeerMatchRule":
        return cls(config.character, workflow_registry, workflow_id)


class ChildrenModeMatchRule(DispatchRule):
    """名单内 QQ 未到间隔时不匹配（含 @）。未列入或已到期则放行。"""
    config_class = RuleConfig
    type_name = "children_ok"

    def __init__(self, workflow_registry: WorkflowRegistry, workflow_id: str):
        super().__init__(workflow_registry, workflow_id)

    def match(self, message: IMMessage) -> bool:
        qq = str(getattr(message.sender, "user_id", "") or "")
        try:
            from group_world_state.children import allowed
            return allowed(qq)
        except Exception:
            return True

    def get_config(self) -> RuleConfig:
        return RuleConfig()

    @classmethod
    def from_config(
        cls, config: RuleConfig, workflow_registry: WorkflowRegistry, workflow_id: str
    ) -> "ChildrenModeMatchRule":
        return cls(workflow_registry, workflow_id)
