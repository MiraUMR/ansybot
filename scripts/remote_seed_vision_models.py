#!/usr/bin/env python3
"""Register working multimodal models on the 阿里 token-plan backend only."""
from pathlib import Path

import yaml

p = Path("/opt/kirara-ai/data/config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
needed = [
    "qwen3.8-flash",
    "qwen3.6-flash",
    "qwen3.7-plus",
    "qwen3.8-max",
    "deepseek-v4.1-flash",
]
changed = False
for b in data.get("llms", {}).get("api_backends", []) or []:
    if b.get("name") != "阿里":
        continue
    models = b.setdefault("models", [])
    names = []
    for m in models:
        if isinstance(m, str):
            names.append(m)
        elif isinstance(m, dict):
            names.append(str(m.get("id") or m.get("name") or ""))
    names = [n for n in names if n]
    for n in needed:
        if n not in names:
            names.append(n)
            changed = True
            print("added", n)
    b["models"] = names
    print("阿里 models=", names)

priority = data.setdefault("llms", {}).setdefault("priority", {})
vision = [
    "阿里/qwen3.8-flash",
    "阿里/qwen3.6-flash",
    "阿里/qwen3.7-plus",
    "阿里/qwen3.8-max",
    "阿里/deepseek-v4.1-flash",
]
if list(priority.get("vision") or []) != vision:
    priority["vision"] = vision
    changed = True
    print("priority.vision updated")

if changed:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("config updated")
else:
    print("config already ok")
