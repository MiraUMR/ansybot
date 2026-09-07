#!/bin/bash
set -e
cd /opt/kirara-ai
python3 /tmp/patch_group_context.py
python3 - <<'PY'
import yaml
rules=yaml.safe_load(open("data/dispatch_rules/rules.yaml",encoding="utf-8"))
print("==== random rules ====")
for r in rules:
    if "random" in r.get("rule_id","") or "插话" in r.get("name",""):
        print(r["rule_id"], r["name"], r["description"])
        for g in r["rule_groups"]:
            print(" ", g)
PY
ls -l patches/llm_chat.py
grep -n llm_chat docker-compose.yml
docker compose up -d kirara-agent
sleep 5
docker exec kirara-qq-bot python -c "from kirara_ai.workflow.implementations.blocks.llm.chat import _extract_group_name; print('patched llm_chat ok')"
docker logs kirara-qq-bot --since 30s 2>&1 | grep -E 'Registered dispatch rule: rule_id=.chat_group|Bot .* Connected|Error|Traceback' | tail -20
