#!/bin/bash
echo "==== adapters ===="
docker logs kirara-qq-bot 2>&1 | grep -E 'Starting adapter|Started adapter|Failed|qq_user|OneBot' | tail -30
echo "==== napcat /api ===="
curl -sI http://127.0.0.1:6099/api | head -8
echo "==== webui refs ===="
curl -sL http://127.0.0.1:6099/webui/ | tr '"' '\n' | grep -E 'webui|assets|/api' | head -20
echo "==== docker ps ===="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
