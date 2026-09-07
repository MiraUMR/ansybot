from pathlib import Path
import yaml

path = Path(__file__).resolve().parents[1] / "data" / "dispatch_rules" / "rules.yaml"
rules = yaml.safe_load(path.read_text(encoding="utf-8"))


def has_rule(groups, type_name, character=None):
    for g in groups or []:
        for r in g.get("rules") or []:
            if r.get("type") != type_name:
                continue
            if character is None or (r.get("config") or {}).get("character") == character:
                return True
    return False


def add_and_rule(rule, type_name, character):
    groups = rule.setdefault("rule_groups", [])
    if has_rule(groups, type_name, character):
        return
    for g in groups:
        if g.get("operator") == "and" and g.get("rules"):
            g["rules"].append({"type": type_name, "config": {"character": character}})
            return
    groups.append(
        {
            "operator": "and",
            "rules": [{"type": type_name, "config": {"character": character}}],
        }
    )


for rule in rules:
    wid = rule.get("workflow_id") or ""
    rid = rule.get("rule_id") or ""
    if wid == "chat:anon":
        char = "anon"
    elif wid == "chat:soyo":
        char = "soyo"
    else:
        continue
    if "fallback" in rid or "memory" in rid:
        continue
    add_and_rule(rule, "not_only_at_peer", char)
    if "peer" not in rid:
        add_and_rule(rule, "sender_not_peer", char)

path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("wrote", path)
for r in rules:
    if r.get("workflow_id") in ("chat:anon", "chat:soyo"):
        types = []
        for g in r["rule_groups"]:
            for x in g["rules"]:
                cfg = x.get("config") or {}
                suffix = f":{cfg['character']}" if "character" in cfg else ""
                types.append(x["type"] + suffix)
        print(r["rule_id"], types)
