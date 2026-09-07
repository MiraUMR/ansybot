#!/bin/bash
set -e
cd /opt/kirara-ai

ls -la data/characters.yaml data/dispatch_rules/rules.yaml \
  data/workflows/chat/anon.yaml data/workflows/chat/soyo.yaml \
  napcat-soyo/config/onebot11.json plugins/group_world_state/peer.py \
  patches/dispatch_message_rules.py

python3 <<'PY'
from pathlib import Path
import yaml
p = Path("/opt/kirara-ai/data/config.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
ims = data.setdefault("ims", [])
names = {x.get("name") for x in ims}
if "qq_soyo" not in names:
    ims.append({
        "name": "qq_soyo",
        "enable": True,
        "adapter": "onebot",
        "config": {
            "websocket_url": "/im/websocket/onebot/qquser02/ws",
            "access_token": "bEA-8C8ho1j01r-qa9yT2g_rhH7exui3",
            "heartbeat_interval": 15,
        },
    })
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("added qq_soyo to config.yaml")
else:
    print("qq_soyo already in config.yaml")
PY

python3 scripts/migrate_world_state_to_characters.py || true
echo "--- world_state ---"
ls -la data/world_state/anon/ 2>/dev/null || ls -la data/world_state/ | head -20

docker compose up -d --no-deps napcat-soyo
docker compose up -d --force-recreate --no-deps kirara-agent
sleep 5
docker ps --format '{{.Names}} {{.Status}}' | grep -E 'kirara|napcat' || true
echo "--- kirara logs ---"
docker logs --tail 40 kirara-qq-bot 2>&1 | tail -40
