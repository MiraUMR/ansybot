#!/bin/bash
echo "==== napcat 收发 ===="
docker logs --since 15m napcat-qq 2>&1 | grep -E '接收 <-|发送 ->' | tail -40
echo "==== kirara 工作流 ===="
docker logs --since 15m kirara-qq-bot 2>&1 | grep -E 'Matched rule|Starting workflow|Workflow execution|Random chance|Random number|Executing Block:|chat_normal|chat_group_random|memory_store' | tail -50
