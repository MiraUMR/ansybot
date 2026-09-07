#!/bin/bash
echo "==== chat_normal contexts ===="
docker logs kirara-qq-bot --since 15m 2>&1 | grep -n "Matched rule rule_id='chat_normal'" | tail -15
echo "==== messages around chat_normal (Composed / raw) ===="
docker logs kirara-qq-bot --since 15m 2>&1 | grep -E "chat_normal|raw_message='|sender=1035893116|sender=1071033510|Mention|CQ:at" | tail -40
echo "==== suisomi vs nonggong vs chat_normal timestamps ===="
docker logs kirara-qq-bot --since 20m 2>&1 | grep "Matched rule rule_id=" | grep -E "chat_normal|suisomi|nonggong"
echo "==== napcat at vs send ===="
docker logs napcat-qq --since 15m 2>&1 | grep -E '发送 ->|CQ:at|@千早' | tail -30
