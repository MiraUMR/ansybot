#!/usr/bin/env python3
"""Verify the EXTERNAL_TRIGGER wrapping for @ / named-mention messages."""
import sys

sys.path.insert(0, "/usr/local/lib/python3.11/site-packages")

from kirara_ai.plugins.group_world_state.blocks import _build_external_trigger_prompt

cases = [
    ("anon", "Mira", "群素爱素みみせかい", "你和素世晚上做什么"),
    ("anon", "Mira", "群素爱素みみせかい", "灯最近怎么样"),
    ("anon", "Mira", "群素爱素みみせかい", "你喜欢吃什么"),
    ("soyo", "Mira", "群素爱素みみせかい", "你和爱音打算干什么"),
    ("soyo", "Mira", "群素爱素みみせかい", "立希最近怎么样"),
    ("soyo", "Mira", "群素爱素みみせかい", "你喜欢吃什么"),
]

ok = True
for character, display, group, content in cases:
    prompt = _build_external_trigger_prompt(character, display, group, content)
    checks = [
        prompt.startswith("[SYSTEM: EXTERNAL_TRIGGER]"),
        prompt.rstrip().endswith("[/SYSTEM: EXTERNAL_TRIGGER]"),
        f"触发内容：{content}" in prompt,
        "绝不直接回应提问者本人" in prompt,
        "你问的这个" in prompt,  # part of the forbidden-phrase list, should be present as guidance
    ]
    passed = all(checks)
    ok = ok and passed
    mark = "OK" if passed else "FAIL"
    print(f"[{mark}] {character} <- 「{content}」")
    print(prompt)
    print("---")

print("OVERALL", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
