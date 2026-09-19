#!/usr/bin/env python3
"""Ensure config.yaml has llms.priority for free model ordering."""
from pathlib import Path
import yaml

p = Path("/opt/kirara-ai/data/config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
llms = data.setdefault("llms", {})
priority = llms.setdefault("priority", {})
text = priority.get("text") or []
vision = priority.get("vision") or []

default_text = [
    "deepseek-v4-flash-0731",
    "qwen-plus",
    "qwen-flash",
    "qwen-turbo",
]
default_vision = [
    "qwen3.8-flash",
    "qwen3.6-flash",
    "qwen3.7-plus",
    "qwen3.8-max",
]

# Sync from llm_pools.yaml if present
pools_path = Path("/opt/kirara-ai/data/llm_pools.yaml")
if pools_path.is_file():
    pools = yaml.safe_load(pools_path.read_text(encoding="utf-8")) or {}
    if pools.get("text"):
        text = list(pools["text"])
    if pools.get("vision"):
        vision = list(pools["vision"])

if not text:
    text = default_text
if not vision:
    vision = default_vision

priority["text"] = text
priority["vision"] = vision
llms["priority"] = priority

# Keep models registered for all priority entries
needed = list(dict.fromkeys(text + vision))
for b in llms.get("api_backends") or []:
    if not b.get("enable", True):
        continue
    models = b.setdefault("models", [])
    names = []
    for m in models:
        if isinstance(m, str):
            names.append(m)
        elif isinstance(m, dict):
            n = m.get("id") or m.get("name")
            if n:
                names.append(n)
    for n in needed:
        if n not in names:
            names.append(n)
            print("registered model", n, "->", b.get("name"))
    b["models"] = names

data.setdefault("defaults", {})["llm_model"] = text[0]
p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("priority.text=", text)
print("priority.vision=", vision)
print("defaults.llm_model=", data["defaults"]["llm_model"])
