#!/usr/bin/env python3
from pathlib import Path
print(Path("/app/plugins/role/role.py").read_text(encoding="utf-8")[:2500])
print("--- manager scan ---")
text = Path("/app/plugins/plugin_manager.py").read_text(encoding="utf-8")
for i, line in enumerate(text.splitlines(), 1):
    if any(k in line.lower() for k in ("scan", "enabled", "plugins.json", "desire_priority", "load_plugins")):
        print(f"{i}: {line}")
