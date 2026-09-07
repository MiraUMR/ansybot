"""Inspect Event.message / ChatSender equality for @ parsing."""
import inspect
from kirara_ai.im.sender import ChatSender

print("--- ChatSender eq ---")
print("eq" in dir(ChatSender), getattr(ChatSender, "__eq__", None))
try:
    print(inspect.getsource(ChatSender.__eq__))
except Exception as exc:
    print("no __eq__", exc)

a = ChatSender.get_bot_sender()
b = ChatSender.get_bot_sender()
print("bot==bot", a == b, a.user_id, b.user_id)

print("--- Event.message type ---")
try:
    from nonebot.adapters.onebot.v11 import Message, MessageSegment, GroupMessageEvent
    print("Message bases", Message.__mro__[:4])
    msg = Message([MessageSegment.at("10001"), MessageSegment.text(" hi")])
    print("isinstance list", isinstance(msg, list), type(msg))
    print("list(msg)", list(msg))
    for seg in msg:
        print("seg", type(seg), getattr(seg, "type", None), getattr(seg, "data", None), dict(seg) if hasattr(seg, "items") else None)
except Exception as exc:
    print("nonebot inspect failed", exc)
