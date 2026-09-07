#!/bin/bash
echo "==== matched since restart ===="
docker logs --since 5m kirara-qq-bot 2>&1 | grep -aE 'Matched rule|llm_chat|not found|deepseek-v4|Workflow execution failed|Executing Block: llm' | tail -30
echo "==== napcat send ===="
docker logs --since 5m napcat-qq 2>&1 | grep -aE '发送 ->' | tail -10
echo "==== bot connected ===="
docker logs --since 8m kirara-qq-bot 2>&1 | grep -aE 'Bot |Started adapter|OneBot适配器' | tail -10
