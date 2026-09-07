#!/usr/bin/env python3
"""Add 1% random insert rules for new groups 1002331691 and 1092692457."""
from __future__ import annotations

from pathlib import Path

import yaml

path = Path(__file__).resolve().parents[1] / "data" / "dispatch_rules" / "rules.yaml"
rules = yaml.safe_load(path.read_text(encoding="utf-8"))

NEW_GROUPS = [
    ("1002331691", "群1002331691"),
    ("1092692457", "群1092692457"),
]


def make_rule(group_id: str, label: str, character: str, im_names: list[str], workflow: str) -> dict:
    rid = f"chat_group_random_{group_id}_{character}"
    im_rules = [{"type": "im_adapter", "config": {"im_name": name}} for name in im_names]
    return {
        "rule_id": rid,
        "name": f"{label}偶尔插话（{'爱音' if character == 'anon' else '素世'}）",
        "description": f"群 {group_id} 未 @ 约 1% 接话",
        "workflow_id": workflow,
        "priority": 3,
        "enabled": True,
        "rule_groups": [
            {"operator": "or", "rules": im_rules},
            {
                "operator": "and",
                "rules": [
                    {"type": "chat_type", "config": {"chat_type": "群聊"}},
                    {"type": "sender", "config": {"sender_id": "", "sender_group": str(group_id)}},
                    {"type": "random", "config": {"chance": 1}},
                    {"type": "not_only_at_peer", "config": {"character": character}},
                    {"type": "not_at_others", "config": {"character": character}},
                    {"type": "sender_not_peer", "config": {"character": character}},
                ],
            },
            {"operator": "and", "rules": [{"type": "children_ok", "config": {}}]},
        ],
        "metadata": {"category": "chat", "permission": "user", "temperature": 0.9},
    }


existing = {r.get("rule_id") for r in rules}
added = 0
insert_at = next(
    (i for i, r in enumerate(rules) if r.get("rule_id") == "chat_anon_private"),
    len(rules),
)
# insert anon rules before chat_anon_private; soyo before chat_soyo_private
anon_block = []
soyo_block = []
for gid, label in NEW_GROUPS:
    anon_rid = f"chat_group_random_{gid}_anon"
    soyo_rid = f"chat_group_random_{gid}_soyo"
    if anon_rid not in existing:
        anon_block.append(
            make_rule(gid, label, "anon", ["qq_user_bot"], "chat:anon")
        )
        added += 1
    if soyo_rid not in existing:
        soyo_block.append(
            make_rule(gid, label, "soyo", ["qq_soyo"], "chat:soyo")
        )
        added += 1

if anon_block:
    rules[insert_at:insert_at] = anon_block
soyo_at = next(
    (i for i, r in enumerate(rules) if r.get("rule_id") == "chat_soyo_private"),
    len(rules),
)
if soyo_block:
    rules[soyo_at:soyo_at] = soyo_block

path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("added", added, "wrote", path)
for r in rules:
    if "1002331691" in str(r.get("rule_id")) or "1092692457" in str(r.get("rule_id")):
        print(r["rule_id"], r.get("description"))
