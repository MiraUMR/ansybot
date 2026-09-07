#!/bin/bash
set -e
cd /opt/kirara-ai
python3 /tmp/inspect_send_blocks.py
ls -l patches/im_messages.py patches/workflow_routes.py
grep -n workflow_routes docker-compose.yml
docker compose up -d kirara-agent
sleep 4
docker exec kirara-qq-bot python -c "from kirara_ai.web.api.workflow.routes import ensure_dual_im_send; print('patched workflow routes ok')"
docker logs kirara-qq-bot 2>&1 | grep -E 'Registered workflow: chat:normal|Bot .* Connected|Error|Traceback' | tail -15
