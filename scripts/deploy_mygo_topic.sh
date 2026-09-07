#!/bin/bash
set -e
cd /opt/kirara-ai
python3 - <<'PY'
import yaml
from pathlib import Path
data=yaml.safe_load(Path("data/dispatch_rules/rules.yaml").read_text(encoding="utf-8"))
print("==== suisomi / random rules ====")
for r in data:
    rid=r.get("rule_id","")
    if "suisomi" in rid or "nonggong" in rid:
        print(rid, r.get("priority"), r.get("description"))
PY
docker compose up -d kirara-agent
sleep 6
docker exec kirara-qq-bot python -c "from kirara_ai.workflow.core.dispatch.rules.message_rules import KeywordMismatchMatchRule; print('keyword_mismatch ok')"
docker logs kirara-qq-bot --since 20s 2>&1 | grep -E 'suisomi|nonggong|keyword_mismatch|Failed to load rule|Bot .* Connected|Error' | tail -25
