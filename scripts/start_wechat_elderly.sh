#!/bin/bash
set -euo pipefail
cd /opt/kirara-ai

docker compose --env-file wechat_elderly.env up -d wechatpadpro-mysql wechatpadpro-redis
echo "waiting for mysql..."
for i in $(seq 1 24); do
  if docker exec wechatpadpro-mysql mysqladmin ping -h127.0.0.1 -uroot -pwxroot123456 --silent; then
    echo "MYSQL_READY"
    break
  fi
  echo "try_$i"
  sleep 5
done

docker compose --env-file wechat_elderly.env up -d wechatpadpro
sleep 8
docker compose --env-file wechat_elderly.env up -d --force-recreate --no-deps kirara-wechat-elderly

echo "---PS---"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
