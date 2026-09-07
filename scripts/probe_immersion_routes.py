#!/usr/bin/env python3
"""Simulate five routing cases via DialogueContext helpers (no full IoC)."""
import sys
sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")

from kirara_ai.plugins.group_world_state.narration import (
    classify_human_utterance,
    wrap_template,
    to_narration,
)
from kirara_ai.plugins.group_world_state.characters import is_registered_bot_qq
from kirara_ai.plugins.group_world_state.scene_context import SceneContextStore, SceneEntry
from pathlib import Path
import tempfile

def route(sender_qq: str, text: str, mentioned: bool) -> dict:
    if is_registered_bot_qq(sender_qq):
        return {
            "mode": "peer",
            "skip_chat_memory": False,
            "scene": False,
            "prompt": f"peer:{text}",
        }
    if mentioned:
        return {
            "mode": "direct",
            "skip_chat_memory": False,
            "scene": False,
            "prompt": f"direct:{text}",
        }
    kind = classify_human_utterance(text)
    if kind == "discard":
        return {"mode": "discard", "skip_chat_memory": True, "scene": False, "prompt": "[NO_REPLY]"}
    # template path only (skip real LLM for smoke)
    narr = wrap_template(text) if kind == "template" else wrap_template(text)  # llm would rewrite
    if kind == "llm":
        # mark as would-call-llm; still produce template as fail-safe shape
        narr = "[场景旁白] " + text[:40]  # placeholder marker for checklist
        src = "llm"
    else:
        src = "template"
    return {
        "mode": "env",
        "skip_chat_memory": True,
        "scene": True,
        "prompt": f"【当前环境】\n{narr}",
        "source": src,
        "classify": kind,
    }

cases = [
    ("short_emoji", "10001", "😀", False, "discard"),
    ("short_stmt", "10001", "今天天气不错", False, "env"),
    ("long_llm", "10001", "你今天晚上到底打算吃什么啊感觉好纠结", False, "env"),
    ("at_direct", "10001", "爱音你好呀", True, "direct"),
    ("peer_bot", "2246246527", "爱音你听我说", False, "peer"),
]

print("=== five sample routes ===")
ok = True
for name, qq, text, ment, expect_mode in cases:
    r = route(qq, text, ment)
    mark = "OK" if r["mode"] == expect_mode else "FAIL"
    if r["mode"] != expect_mode:
        ok = False
    mem = "skip" if r["skip_chat_memory"] else "write"
    scene = "scene" if r["scene"] else "no-scene"
    print(f"[{mark}] {name}: mode={r['mode']} mem={mem} {scene} classify={r.get('classify','-')}")

# scene store maxlen
with tempfile.TemporaryDirectory() as td:
    store = SceneContextStore(Path(td), maxlen=5)
    for i in range(7):
        store.append("anon", "g1", raw=f"r{i}", narration=f"[环境音] n{i}", source="template")
    xml = store.render_xml("anon", "g1")
    lines = [ln for ln in xml.splitlines() if ln.startswith("- ")]
    print("scene lines:", len(lines), "(expect 5)")
    print(xml)
    if len(lines) != 5:
        ok = False

print("OVERALL", "PASS" if ok else "FAIL")
