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
    "qwen3-vl-plus",
    "qwen3-vl-flash",
    "qwen-vl-plus",
]
changed = False
backends = data.setdefault("llms", {}).setdefault("api_backends", [])
if not backends:
    raise SystemExit("no api_backends")
for b in backends:
    if not b.get("enable", True):
        continue
    models = b.setdefault("models", [])
    # normalize to strings
    names = []
    for m in models:
        if isinstance(m, str):
            names.append(m)
        elif isinstance(m, dict):
            names.append(m.get("id") or m.get("name") or "")
    names = [n for n in names if n]
    for n in needed:
        if n not in names:
            names.append(n)
            changed = True
            print("added", n, "to", b.get("name"))
    b["models"] = names
if "defaults" not in data or not (data.get("defaults") or {}).get("llm_model"):
    data.setdefault("defaults", {})["llm_model"] = "deepseek-v4-flash-0731"
    changed = True
if changed:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("config updated")
else:
    print("config already ok")
for b in backends:
    print(b.get("name"), "models=", b.get("models"))
print("defaults", data.get("defaults"))
