#!/bin/bash
echo "==== napcat recent ===="
docker logs napcat-qq --since 20m 2>&1 | grep -iE 'login|登录|WebSocket|账号|成功|失败|error|接收 <-|发送 ->|Connected|quick' | tail -40
echo "==== kirara recent ===="
docker logs kirara-qq-bot --since 20m 2>&1 | grep -iE 'OneBot|Connected|Disconnected|心跳|Task exception|SendUserBot|skip ' | tail -30
echo "==== napcat tail ===="
docker logs napcat-qq --tail 20
