#!/bin/bash
echo "==== kirara after 20:11 ===="
docker logs kirara-qq-bot 2>&1 | grep '20:1[1-9]\|20:2' | grep -iE 'websocket|Connected|Disconnected|Matched rule|OneBot|heartbeat|101' | tail -30
echo "==== napcat after 20:11 receive/send ===="
docker logs napcat-qq 2>&1 | grep '20:1[1-9]\|20:2' | grep -E '接收 <-|发送 ->|WebSocket' | tail -20
echo "==== napcat ws status ===="
docker logs napcat-qq 2>&1 | grep -iE '反向WebSocket|连接成功|连接错误|意外关闭' | tail -10
