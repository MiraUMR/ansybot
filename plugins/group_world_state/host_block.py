"""Host dialogue block: official bot as story controller."""
from __future__ import annotations

from typing import Any, Dict

from kirara_ai.im.message import IMMessage, TextMessage
from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.ioc.container import DependencyContainer
from kirara_ai.logger import get_logger
from kirara_ai.workflow.core.block import Block, Input, Output

from .host_manager import (
    StoryHostManager,
    is_host_end,
    is_host_start,
    strip_host_command,
)
from .story import load_story_triggers

logger = get_logger("WorldState.HostDialogue")


def _manager(container: DependencyContainer) -> StoryHostManager:
    try:
        return container.resolve(StoryHostManager)
    except Exception:
        mgr = StoryHostManager(container)
        try:
            container.register(StoryHostManager, mgr)
        except Exception:
            pass
        return mgr


class HostDialogue(Block):
    name = "host_dialogue"
    inputs = {
        "user_msg": Input("user_msg", "用户消息", IMMessage, "群消息"),
        "chat_sender": Input("chat_sender", "发送者", ChatSender, "发送者"),
    }
    outputs = {
        "msg": Output("msg", "回复", IMMessage, "主持人回复"),
    }
    container: DependencyContainer

    def execute(self, user_msg: IMMessage, chat_sender: ChatSender) -> Dict[str, Any]:
        mgr = _manager(self.container)
        content = user_msg.content or ""
        text = strip_host_command(content)

        if chat_sender.chat_type != ChatType.GROUP or not chat_sender.group_id:
            reply = "故事模式只在多人对话里可用。"
            return {
                "msg": IMMessage(
                    sender=ChatSender.get_bot_sender(),
                    message_elements=[TextMessage(reply)],
                )
            }

        gid = str(chat_sender.group_id)
        uid = str(chat_sender.user_id or "")

        if is_host_start(content):
            # Prefer remaining text after stripping start keywords as scene desc
            scene = text
            triggers = load_story_triggers()
            for kw in triggers.get("start_keywords") or []:
                scene = scene.replace(str(kw), " ")
            scene = " ".join(scene.split()).strip() or text or "日常场景"
            session = mgr.create_session(
                group_id=gid,
                initiator_qq=uid,
                scene_desc=scene,
                participants=["soyo", "anon"],
                recipient_meta={
                    "group_id": gid,
                    "user_id": uid,
                    "display_name": chat_sender.display_name or uid,
                },
            )
            reply = mgr.open_message(session)
            logger.info(f"host story start sid={session['session_id']} group={gid}")
        elif is_host_end(content):
            active = mgr.get_active_by_group(gid)
            if not active:
                reply = "当前没有进行中的故事。"
            elif str(active.get("initiator_qq") or "") != uid:
                reply = "只有发起人可以结束故事。"
            else:
                from .host_manager import _tpl

                summary = mgr.finalize(str(active["session_id"]), quiet=True)
                reply = _tpl("end") + (f"\n记忆摘要：{summary}" if summary else "")
                logger.info(f"host story end sid={active['session_id']} group={gid}")
        else:
            active = mgr.get_active_by_group(gid)
            if active:
                reply = (
                    f"故事进行中（第 {active.get('turn_count') or 0}/"
                    f"{active.get('max_turns') or 7} 幕）。\n"
                    f"链接：{mgr.form_url(active)}\n"
                    f"结束请发：结束 / end / stop"
                )
            else:
                reply = mgr.help_message()

        return {
            "msg": IMMessage(
                sender=ChatSender.get_bot_sender(),
                message_elements=[TextMessage(reply)],
            )
        }
