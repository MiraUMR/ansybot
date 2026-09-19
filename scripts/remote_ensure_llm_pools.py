#!/usr/bin/env python3
from pathlib import Path
import yaml

p = Path("/opt/kirara-ai/data/config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
needed = [
    "deepseek-v4-flash-0731",
    "qwen-plus",
    "qwen-flash",
    "qwen-turbo",
    "qwen3.8-flash",
    "qwen3.6-flash",
    "qwen3.7-plus",
    "qwen3.8-max",
    "deepseek-v4.1-flash",
]
changed = False
for b in data.get("llms", {}).get("api_backends", []) or []:
    models = b.setdefault("models", [])
    names = set()
    for m in models:
        if isinstance(m, str):
            names.add(m)
        elif isinstance(m, dict):
            names.add(m.get("id") or m.get("name") or "")
    for n in needed:
        if n not in names:
            models.append(n)
            changed = True
            print("added", n, "to", b.get("name"))
if changed:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("config updated")
else:
    print("config models ok")
print("--- llm_pools ---")
print(Path("/opt/kirara-ai/data/llm_pools.yaml").read_text(encoding="utf-8"))
