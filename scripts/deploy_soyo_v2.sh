#!/bin/bash
set -eu
BASE=/opt/kirara-ai
SRC=/tmp/kirara_soyo_v2

cp "$SRC/plugin/blocks.py" "$BASE/plugins/group_world_state/blocks.py"
cp "$SRC/persona/soyo/03_lore.txt" "$BASE/data/persona/soyo/"
cp "$SRC/persona/soyo/04_runtime.txt" "$BASE/data/persona/soyo/"
cp "$SRC/persona/soyo/05_update.txt" "$BASE/data/persona/soyo/"
cp "$SRC/workflows/"*.yaml "$BASE/data/workflows/chat/"

cd "$BASE"
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 12
docker logs --tail 30 kirara-qq-bot 2>&1 | grep -iE 'group_world_state|Failed to load|Plugin group|Registered workflow: chat:(anon|soyo)'
