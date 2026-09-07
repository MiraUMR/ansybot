#!/usr/bin/env python3
"""Verify soyo restructure: no group-nickname section, extract_priority skip, EXTERNAL_TRIGGER intact."""
import sys
from pathlib import Path

sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")

ok = True
def check(cond, msg):
    global ok
    mark = "OK" if cond else "FAIL"
    if not cond:
        ok = False
    print(f"[{mark}] {msg}")

lore = Path("/app/data/persona/soyo/03_lore.txt").read_text(encoding="utf-8")
check("对群友的称呼" not in lore, "soyo lore: 群友称呼 section removed")
check("sine斯年" not in lore, "soyo lore: no stray nickname entries")
check("## 普通群聊（无标签 / 非@消息）" in lore, "soyo lore: 普通群聊 subsection present")
check("## 被@时的响应范式（[SYSTEM: EXTERNAL_TRIGGER] 标签触发）" in lore, "soyo lore: EXTERNAL_TRIGGER subsection present")
check("## 与小爱音互聊" in lore, "soyo lore: 与小爱音互聊 subsection present")
check("# 场景记忆读取规则" in lore, "soyo lore: 场景记忆读取规则 section present")

wf = Path("/app/data/workflows/chat/soyo.yaml").read_text(encoding="utf-8")
check("对群友的称呼" not in wf, "soyo.yaml: no group-nickname text baked in")

from kirara_ai.plugins.group_world_state.blocks import DialogueContext
import inspect
src = inspect.getsource(DialogueContext.execute)
check('"extract_priority": "skip"' in src.split("if mentioned")[1].split("if not immersion_on")[0], "direct branch extract_priority=skip")

print("OVERALL", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
