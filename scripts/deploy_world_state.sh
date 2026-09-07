#!/bin/bash
set -euo pipefail
cd /opt/kirara-ai
python3 scripts/inject_world_state_workflow.py
if [ ! -f data/world_state/_config.yaml ] && [ -f data/world_state/_config.example.yaml ]; then
  cp data/world_state/_config.example.yaml data/world_state/_config.yaml
fi
docker compose up -d kirara-agent
sleep 8
docker logs kirara-qq-bot --since 25s 2>&1 | grep -E 'GroupWorldStatePlugin|world_state|Failed to load workflow|Bot .* Connected|Error' | tail -30
