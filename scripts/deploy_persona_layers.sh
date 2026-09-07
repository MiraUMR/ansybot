#!/bin/bash
set -eu
BASE=/opt/kirara-ai
SRC=/tmp/kirara_layers

cp "$SRC/plugin/blocks.py" "$BASE/plugins/group_world_state/blocks.py"
cp "$SRC/plugin/peer.py" "$BASE/plugins/group_world_state/peer.py"
cp "$SRC/plugin/__init__.py" "$BASE/plugins/group_world_state/__init__.py"
mkdir -p "$BASE/data/persona/soyo/modules"
cp "$SRC/persona/soyo/modules/"*.md "$BASE/data/persona/soyo/modules/"
cp "$SRC/persona/soyo/04_runtime.txt" "$BASE/data/persona/soyo/"
cp "$SRC/persona/soyo/05_update.txt" "$BASE/data/persona/soyo/"
cp "$SRC/workflows/"*.yaml "$BASE/data/workflows/chat/"

cd "$BASE"
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 14
docker logs --tail 60 kirara-qq-bot 2>&1 | grep -iE 'persona modules cached|group_world_state|Failed to load|Plugin group|Registered workflow: chat:(anon|soyo)' || true
