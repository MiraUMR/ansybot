#!/bin/bash
set -e
cd /opt/kirara-ai
OLD=deepseek-v4-pro-0813
NEW=deepseek-v4-flash-0731

python3 <<PY
from pathlib import Path
old = "deepseek-v4-pro-0813"
new = "deepseek-v4-flash-0731"
paths = [
    Path("data/config.yaml"),
    Path("data/workflows/chat/anon.yaml"),
    Path("data/workflows/chat/soyo.yaml"),
    Path("data/workflows/chat/normal.yaml"),
    Path("data/workflows/chat/memory_store.yaml"),
    Path("data/workflows/chat/memory_store_anon.yaml"),
    Path("data/workflows/chat/memory_store_soyo.yaml"),
    Path("plugins/group_world_state/blocks.py"),
]
for p in paths:
    if not p.is_file():
        print("missing", p)
        continue
    text = p.read_text(encoding="utf-8")
    if old not in text:
        print("no-op", p)
        continue
    p.write_text(text.replace(old, new), encoding="utf-8")
    print("updated", p)
PY

docker compose up -d --force-recreate --no-deps kirara-agent
sleep 8
docker logs --tail 30 kirara-qq-bot 2>&1 | grep -iE 'model|flash|llm|Started adapter|ERROR' | tail -20
grep -n 'deepseek' data/config.yaml | head -10
