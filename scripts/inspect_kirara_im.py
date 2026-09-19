import inspect

from kirara_ai.im.adapter import IMAdapter
from kirara_ai.im.manager import IMManager
from kirara_ai.im.message import IMMessage
from kirara_ai.im.sender import ChatSender
from kirara_ai.plugin_manager.plugin import Plugin
from kirara_ai.workflow.core.block.registry import BlockRegistry

print("IMManager methods:", [m for m in dir(IMManager) if not m.startswith("_")])
print("ChatSender sig:", inspect.signature(ChatSender.__init__))
print("ChatSender factories:", [a for a in dir(ChatSender) if not a.startswith("_")])
print("IMAdapter methods:", [m for m in dir(IMAdapter) if not m.startswith("_")])
print("Plugin methods:", [m for m in dir(Plugin) if not m.startswith("_")])
print("IMMessage sig:", inspect.signature(IMMessage.__init__))

try:
    src = inspect.getsource(IMManager)
    print("--- IMManager source (first 80 lines) ---")
    print("\n".join(src.splitlines()[:80]))
except Exception as e:
    print("IMManager source err:", e)

try:
    from kirara_ai.im.manager import IMAdapterFactory
    print("IMAdapterFactory:", IMAdapterFactory)
except Exception as e:
    print("no IMAdapterFactory:", e)
