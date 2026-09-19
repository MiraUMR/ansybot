#!/bin/sh
strings /app/wechatpadpro-linux-amd64-vios18.61-861 | grep -E 'knowhub|/api/v1/public|adminkey' | head -50
