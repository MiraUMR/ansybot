#!/bin/sh
strings /app/wechatpadpro-linux-amd64-vios18.61-861 | grep -E 'Timeout|Proxy|InsecureSkip|AUTH_|LICENSE|temporarily' | head -60
