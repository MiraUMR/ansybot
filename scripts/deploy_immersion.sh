#!/bin/bash
set -eu
BASE=/opt/kirara-ai
SRC=/tmp/kirara_immersion

cp "$SRC/characters.yaml" "$BASE/data/characters.yaml"
cp "$SRC/persona/anon/04_runtime.txt" "$BASE/data/persona/anon/"
cp "$SRC/persona/anon/05_update.txt" "$BASE/data/persona/anon/"
cp "$SRC/persona/soyo/04_runtime.txt" "$BASE/data/persona/soyo/"
cp "$SRC/persona/soyo/05_update.txt" "$BASE/data/persona/soyo/"
cp "$SRC/workflows/"*.yaml "$BASE/data/workflows/chat/"
cp "$SRC/plugin/"*.py "$BASE/plugins/group_world_state/"
cp "$SRC/patches/llm_chat.py" "$BASE/patches/llm_chat.py"
cp "$SRC/patches/im_messages.py" "$BASE/patches/im_messages.py"
mkdir -p "$BASE/data/world_state/_scene/anon" "$BASE/data/world_state/_scene/soyo"

cd "$BASE"
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 12
docker logs --tail 60 kirara-agent 2>&1 | tail -60
