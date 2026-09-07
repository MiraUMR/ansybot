#!/usr/bin/env python3
"""Server-side: inject world-state into live workflow + dispatch rules."""
from pathlib import Path
import sys
import yaml

ROOT = Path("/opt/kirara-ai")
sys.path.insert(0, str(ROOT / "scripts"))
from inject_world_state_workflow import patch_workflow  # noqa: E402

wf_path = ROOT / "data/workflows/chat/normal.yaml"
data = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
patched = patch_workflow(data)
wf_path.write_text(
    yaml.safe_dump(patched, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)
print("workflow patched")

rules_path = ROOT / "data/dispatch_rules/rules.yaml"
rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
if any(r.get("rule_id") == "system_world_state" for r in rules):
    print("dispatch rule already present")
else:
    insert = {
        "rule_id": "system_world_state",
        "name": "长期记忆",
        "description": "查看或修改本群长期设定。例：/长期记忆 设定 relationship 已经告白并交往",
        "workflow_id": "system:world_state",
        "priority": 10,
        "enabled": True,
        "rule_groups": [
            {
                "operator": "or",
                "rules": [
                    {"type": "prefix", "config": {"prefix": "/长期记忆"}},
                    {"type": "prefix", "config": {"prefix": "/world"}},
                ],
            }
        ],
        "metadata": {"category": "system", "permission": "user"},
    }
    idx = next((i for i, r in enumerate(rules) if r.get("rule_id") == "fallback"), len(rules))
    rules.insert(idx, insert)
    rules_path.write_text(
        yaml.safe_dump(rules, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print("dispatch rule inserted")

cfg = ROOT / "data/world_state/_config.yaml"
example = ROOT / "data/world_state/_config.example.yaml"
if not cfg.exists() and example.exists():
    cfg.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    print("copied _config.yaml")
print("OK")
