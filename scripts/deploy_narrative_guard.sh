#!/bin/bash
set -eu
BASE=/opt/kirara-ai
SRC=/tmp/kirara_narrative

cp "$SRC/plugin/blocks.py" "$BASE/plugins/group_world_state/blocks.py"
cp "$SRC/plugin/mentions.py" "$BASE/plugins/group_world_state/mentions.py"
cp "$SRC/plugin/__init__.py" "$BASE/plugins/group_world_state/__init__.py"
cp "$SRC/plugin/style_guard.py" "$BASE/plugins/group_world_state/style_guard.py"
cp "$SRC/plugin/parser.py" "$BASE/plugins/group_world_state/parser.py"
cp "$SRC/plugin/story.py" "$BASE/plugins/group_world_state/story.py"
cp "$SRC/plugin/peer.py" "$BASE/plugins/group_world_state/peer.py"
cp "$SRC/plugin/token_meter.py" "$BASE/plugins/group_world_state/token_meter.py"
cp "$SRC/plugin/narration.py" "$BASE/plugins/group_world_state/narration.py" 2>/dev/null || true
cp "$SRC/patches/dispatch_message_rules.py" "$BASE/patches/dispatch_message_rules.py" 2>/dev/null || true
cp "$SRC/patches/dispatch_registry.py" "$BASE/patches/dispatch_registry.py" 2>/dev/null || true
cp "$SRC/dispatch_rules/rules.yaml" "$BASE/data/dispatch_rules/rules.yaml" 2>/dev/null || true
mkdir -p "$BASE/data/persona/soyo/modules" "$BASE/data/persona/anon/modules"
cp "$SRC/persona/soyo/modules/"*.md "$BASE/data/persona/soyo/modules/" 2>/dev/null || true
cp "$SRC/persona/soyo/"*.txt "$BASE/data/persona/soyo/" 2>/dev/null || true
cp "$SRC/persona/anon/modules/"*.md "$BASE/data/persona/anon/modules/" 2>/dev/null || true
cp "$SRC/persona/anon/"*.txt "$BASE/data/persona/anon/" 2>/dev/null || true
cp "$SRC/persona/story_triggers.yaml" "$BASE/data/persona/story_triggers.yaml" 2>/dev/null || true
cp "$SRC/workflows/"*.yaml "$BASE/data/workflows/chat/" 2>/dev/null || true

cd "$BASE"
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 14
docker logs --tail 80 kirara-qq-bot 2>&1 | grep -iE 'persona 模块预估|persona modules cached|消耗了|Failed to load|Plugin group|Registered workflow: chat:(anon|soyo)|Traceback' || true
