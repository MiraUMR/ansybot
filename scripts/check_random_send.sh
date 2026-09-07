#!/bin/bash
echo "==== after random hit 20:14:45 ===="
docker logs kirara-qq-bot --since 5m 2>&1 | grep -E '20:14:4|20:14:5|20:15|SendUser|skip |send via|llm_chat|发送' | tail -40
echo "==== napcat send ===="
docker logs napcat-qq --since 5m 2>&1 | grep -E '发送 ->|接收 <-' | tail -15
