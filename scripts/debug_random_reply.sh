#!/bin/bash
echo "==== containers ===="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "==== kirara last 8 min match/error ===="
docker logs --since 20m kirara-qq-bot 2>&1 | grep -aE 'Matched rule|chat_group_random|Random chance|llm_chat|not found|Workflow execution failed|Bot |Started adapter|ERROR' | tail -60
echo "==== napcat send/recv last 10 ===="
docker logs --since 20m napcat-qq 2>&1 | grep -aE '接收 <-|发送 ->|WebSocket' | tail -25
echo "==== rules on disk ===="
python3 - <<'PY'
import yaml
p="/opt/kirara-ai/data/dispatch_rules/rules.yaml"
try:
    rules=yaml.safe_load(open(p,encoding="utf-8"))
except Exception as e:
    print("yaml fail", e)
    print(open(p,encoding="utf-8").read()[:500])
    raise SystemExit
for r in rules:
    if r.get("rule_id") in ("chat_group_random","chat_normal","fallback"):
        print(r.get("rule_id"), "enabled=", r.get("enabled"), "priority=", r.get("priority"), "wf=", r.get("workflow_id"))
        print(" ", r.get("rule_groups"))
PY
