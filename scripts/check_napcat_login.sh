#!/bin/bash
echo "==== containers ===="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "==== kirara onebot ===="
docker logs --since 30m kirara-qq-bot 2>&1 | grep -E 'Bot .* Connected|qq_user|OneBot适配器|heartbeat|Failed|ERROR' | tail -20
echo "==== napcat login ===="
docker logs --since 30m napcat-qq 2>&1 | grep -E '登录|login|扫码|成功|账号|QQ|Connected|WebUi Token' | tail -30
echo "==== onebot configs ===="
ls -la /opt/kirara-ai/napcat/config/
