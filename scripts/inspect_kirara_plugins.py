import inspect
from pathlib import Path

p = Path("/usr/local/lib/python3.11/site-packages/kirara_ai/plugin_manager")
print("plugin_manager files:", list(p.glob("*.py")))

from kirara_ai.plugin_manager.plugin_loader import PluginLoader
print("--- PluginLoader ---")
print(inspect.getsource(PluginLoader)[:4000])
