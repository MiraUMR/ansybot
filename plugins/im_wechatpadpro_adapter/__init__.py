"""
im_wechatpadpro_adapter — WeChatPadPro 个人微信适配器插件

基于 WeChatPadPro (iPad 协议) 接入个人微信账号。
与 QQ 机器人适配器完全隔离，仅在 kirara-wechat-elderly 容器中挂载。
"""

from kirara_ai.im.im_registry import IMRegistry
from kirara_ai.im.manager import IMManager
from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.logger import get_logger
from kirara_ai.memory.memory_manager import MemoryManager
from kirara_ai.memory.scopes.base import MemoryScope
from kirara_ai.plugin_manager.plugin import Plugin

from .adapter import WeChatPadProAdapter, WeChatPadProConfig

logger = get_logger("WeChatPadPro-Plugin")


class WechatElderlyScope(MemoryScope):
    """微信陪伴机器人独立记忆作用域，与 QQ 角色记忆隔离。"""

    def get_scope_key(self, sender: ChatSender) -> str:
        if sender.chat_type == ChatType.GROUP:
            return f"group:{sender.group_id}:companion"
        return f"c2c:{sender.user_id}:companion"

    def is_in_scope(self, target_sender: ChatSender, query_sender: ChatSender) -> bool:
        if target_sender.chat_type != query_sender.chat_type:
            return False
        if target_sender.chat_type == ChatType.GROUP:
            return target_sender.group_id == query_sender.group_id
        return target_sender.user_id == query_sender.user_id


class WeChatPadProAdapterPlugin(Plugin):
    """WeChatPadPro 个人微信适配器（iPad 协议），专用于微信中老年陪伴机器人。"""

    im_registry: IMRegistry
    im_manager: IMManager

    def on_load(self):
        self.im_registry.register(
            "wechatpadpro",
            WeChatPadProAdapter,
            WeChatPadProConfig,
            localized_name="WeChatPadPro 个人微信",
            localized_description="通过 WeChatPadPro（iPad 协议）接入个人微信账号",
            detail_info_markdown=(
                "在 WeChatPadPro 扫码登录后，将 Webhook 指向 "
                "`http://kirara-wechat-elderly:8080/wechat-elderly/webhook`。"
            ),
        )
        try:
            self.im_manager.container.resolve(MemoryManager).register_scope(
                "wechat_elderly_private", WechatElderlyScope
            )
        except Exception as exc:
            logger.warning("register wechat_elderly_private memory scope failed: %s", exc)

    def on_start(self):
        pass

    def on_stop(self):
        pass
