#!/bin/bash
set -e
echo "==== yaml dir ===="
ls -la /opt/kirara-ai/data/world_state/ || true
echo "==== yaml contents ===="
for f in /opt/kirara-ai/data/world_state/*.yaml; do
  echo "--- $f ---"
  cat "$f"
  echo
done
echo "==== extract logs ===="
docker logs --since 6h kirara-qq-bot 2>&1 | grep -E "EXTRACT|extract_world|extract failed|extract skipped|WorldState.Extract|Executing Block: extract" | tail -50
echo "==== recent chat:normal ===="
docker logs --since 30m kirara-qq-bot 2>&1 | grep -E "Executing Block:|Workflow execution|chat:normal|world_state" | tail -60
