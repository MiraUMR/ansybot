#!/bin/bash
set -e
docker exec kirara-qq-bot ls -la /app/web /app/web/assets
echo '=== PATH HITS ==='
docker exec kirara-qq-bot grep -oE '.{0,20}backend-api.{0,30}|createWebHistory|createWebHashHistory|base:"/|base: "/' /app/web/assets/index.js | head -50
echo '=== EXISTING ASSETS ==='
ls /www/wwwroot/ansy.love/assets | head -20
echo '=== backend-api on site ==='
ls /www/wwwroot/ansy.love | head
