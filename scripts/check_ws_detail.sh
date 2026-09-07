#!/bin/bash
echo "==== napcat ws/error ===="
docker logs --since 10m napcat-qq 2>&1 | grep -iE 'websocket|reverse|kirara|token|403|400|fail|error|重连|connect' | grep -v dbus | grep -v Bugly | tail -40
echo "==== kirara /im/websocket ===="
docker logs --since 20m kirara-qq-bot 2>&1 | grep -E '/im/websocket|Bot |lifecycle|heartbeat' | tail -30
echo "==== napcat last 15 lines ===="
docker logs --tail 15 napcat-qq 2>&1
