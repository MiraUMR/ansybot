#!/bin/bash
curl -sI --max-time 5 http://127.0.0.1:8080/ | head -10
echo "==== log count ===="
docker logs kirara-qq-bot 2>&1 | wc -l
echo "==== last ts ===="
docker logs --tail 3 kirara-qq-bot 2>&1 | head -3
echo "==== napcat ws last ===="
docker logs napcat-qq 2>&1 | grep -a "WebSocket" | tail -5
