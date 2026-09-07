#!/bin/bash
echo "==== onebot11_3845655536.json ===="
cat /opt/kirara-ai/napcat/config/onebot11_3845655536.json
echo
echo "==== onebot11.json ===="
cat /opt/kirara-ai/napcat/config/onebot11.json
echo
echo "==== napcat recent ===="
docker logs --since 5m napcat-qq 2>&1 | grep -iE 'websocket|ws://|kirara|connect|登录成功|login success|账号|self_id|3845655536' | tail -40
echo "==== kirara recent ===="
docker logs --since 10m kirara-qq-bot 2>&1 | grep -iE 'Bot |Connected|OneBot|websocket|400|403|token' | tail -20
