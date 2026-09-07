#!/usr/bin/env python3
"""Offline probes for immersion classify + whitelist (no LLM)."""
import sys
sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")

from kirara_ai.plugins.group_world_state.narration import (
    classify_human_utterance,
    wrap_template,
)
from kirara_ai.plugins.group_world_state.characters import (
    bot_qq_whitelist,
    is_registered_bot_qq,
    immersion_config,
)

cases = [
    ("😀", "discard"),
    ("哈", "discard"),
    ("好的", "discard"),  # compact len 2 < short_max 4
    ("今天天气不错", "template"),  # 6 chars < llm_min 12
    ("你今天晚上到底打算吃什么啊感觉好纠结", "llm"),
]

print("whitelist:", sorted(bot_qq_whitelist()))
print("immersion:", immersion_config())
print("is bot anon:", is_registered_bot_qq("3845655536"))
print("is human:", is_registered_bot_qq("123456"))

ok = True
for text, expect in cases:
    got = classify_human_utterance(text)
    mark = "OK" if got == expect else "FAIL"
    if got != expect:
        ok = False
    print(f"[{mark}] {text!r} -> {got} (expect {expect})")

print("template:", wrap_template("外面下雨了"))
print("PASS" if ok else "FAIL")
