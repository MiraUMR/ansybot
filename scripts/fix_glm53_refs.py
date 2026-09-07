#!/usr/bin/env python3
"""Fix GLM-5.3-Flash refs: register as 阿里/ZHIPU/GLM-5.3-Flash."""
from __future__ import annotations

from pathlib import Path

import yaml

CFG = Path("/opt/kirara-ai/data/config.yaml")
POOLS = Path("/opt/kirara-ai/data/llm_pools.yaml")

OLD_BAD = "ZHIPU/GLM-5.3-Flash"  # wrong: treated as platform ZHIPU
OLD_BARE = "GLM-5.3-Flash"
NEW_API = "ZHIPU/GLM-5.3-Flash"
NEW_REF = "阿里/ZHIPU/GLM-5.3-Flash"


def fix_list(items):
    out = []
    for x in items or []:
        if x in (OLD_BAD, OLD_BARE, NEW_API, NEW_REF):
            if NEW_REF not in out:
                out.append(NEW_REF)
        else:
            out.append(x)
    return out


cfg = yaml.safe_load(CFG.read_text(encoding="utf-8"))
for b in cfg.get("llms", {}).get("api_backends") or []:
    if b.get("name") != "阿里":
        continue
    models = []
    for m in b.get("models") or []:
        if m in (OLD_BARE, NEW_API, OLD_BAD):
            if NEW_API not in models:
                models.append(NEW_API)
        else:
            models.append(m)
    if NEW_API not in models:
        models.append(NEW_API)
    b["models"] = models

pri = cfg.setdefault("llms", {}).setdefault("priority", {})
pri["text"] = fix_list(pri.get("text"))
# keep vision as-is but scrub bad refs if any
pri["vision"] = [
    NEW_REF if x in (OLD_BAD, OLD_BARE, NEW_API) else x for x in (pri.get("vision") or [])
]
# remove accidental GLM from vision
pri["vision"] = [x for x in pri["vision"] if x != NEW_REF]

cfg.setdefault("defaults", {})["llm_model"] = NEW_REF
CFG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

if POOLS.exists():
    pools = yaml.safe_load(POOLS.read_text(encoding="utf-8")) or {}
    pools["text"] = fix_list(pools.get("text"))
    pools["vision"] = [
        x for x in (pools.get("vision") or []) if x not in (OLD_BAD, OLD_BARE, NEW_API, NEW_REF)
    ]
    POOLS.write_text(yaml.safe_dump(pools, allow_unicode=True, sort_keys=False), encoding="utf-8")

print("defaults", cfg["defaults"]["llm_model"])
print("priority text0", cfg["llms"]["priority"]["text"][:3])
ali = next(b for b in cfg["llms"]["api_backends"] if b["name"] == "阿里")
print("ali models has", NEW_API, NEW_API in ali["models"])
print("ali models sample", [m for m in ali["models"] if "GLM" in m or "ZHIPU" in m])
