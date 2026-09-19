import inspect

from kirara_ai.im.im_registry import IMRegistry
from kirara_ai.plugin_manager.plugin import Plugin

print("IMRegistry methods:", [m for m in dir(IMRegistry) if not m.startswith("_")])
print("IMRegistry source:")
print(inspect.getsource(IMRegistry))
print("--- Plugin source ---")
print(inspect.getsource(Plugin))

import kirara_ai.plugins.im_telegram_adapter as tg
print("telegram plugin file:", tg.__file__)
print(inspect.getsource(tg))
