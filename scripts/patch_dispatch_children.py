"""AND children_ok into all chat:* dispatch rules (including fallback memory store)."""
from pathlib import Path
import yaml

path = Path(__file__).resolve().parents[1] / "data" / "dispatch_rules" / "rules.yaml"
rules = yaml.safe_load(path.read_text(encoding="utf-8"))


def has_rule(groups, type_name):
    for g in groups or []:
        for r in g.get("rules") or []:
            if r.get("type") == type_name:
                return True
    return False


n = 0
for rule in rules:
    wid = rule.get("workflow_id") or ""
    if not str(wid).startswith("chat:"):
        continue
    groups = rule.setdefault("rule_groups", [])
    if has_rule(groups, "children_ok"):
        continue
    groups.append({"operator": "and", "rules": [{"type": "children_ok", "config": {}}]})
    n += 1

path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("patched", n, "wrote", path)
