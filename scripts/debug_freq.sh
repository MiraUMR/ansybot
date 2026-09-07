#!/bin/bash
echo "==== loaded random rules ===="
python3 - <<'PY'
import yaml
p="/opt/kirara-ai/data/dispatch_rules/rules.yaml"
data=yaml.safe_load(open(p,encoding="utf-8"))
for r in data:
    rid=r.get("rule_id","")
    if "random" in rid or "chat_normal" in rid or "插话" in r.get("name",""):
        print(rid, "|", r.get("name"), "| prio", r.get("priority"), "|", r.get("description"))
        for g in r.get("rule_groups",[]):
            print(" ", g)
PY
echo "==== kirara recent rule hits ===="
docker logs kirara-qq-bot --since 10m 2>&1 | grep -E 'Matched rule|Random chance|Random number' | tail -60
echo "==== count by rule last 10m ===="
docker logs kirara-qq-bot --since 10m 2>&1 | grep -o "rule_id='[^']*'" | sort | uniq -c | sort -nr
echo "==== napcat sends last 10m ===="
docker logs napcat-qq --since 10m 2>&1 | grep '发送 ->' | tail -20
