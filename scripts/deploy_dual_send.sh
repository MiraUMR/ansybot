#!/bin/bash
set -e
cd /opt/kirara-ai
python3 - <<'PY'
import yaml
p="/opt/kirara-ai/data/workflows/chat/normal.yaml"
data=yaml.safe_load(open(p,encoding="utf-8"))
print("==== send blocks ====")
for b in data["blocks"]:
    if b.get("type")=="internal:send_message":
        print(b.get("name"), b.get("params"))
    if b.get("type")=="internal:chat_response_converter":
        print("converter targets:", [c.get("target") for c in b.get("connected_to") or []])
PY
ls -l patches/im_messages.py
grep -n im_messages docker-compose.yml
docker compose up -d kirara-agent
sleep 3
docker exec kirara-qq-bot python -c "from kirara_ai.workflow.implementations.blocks.im.messages import SendIMMessage, _adapter_can_send; print('patched SendIMMessage ok', _adapter_can_send)"
docker logs kirara-qq-bot --tail 30
