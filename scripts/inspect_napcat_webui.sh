#!/bin/bash
js=$(curl -sL http://127.0.0.1:6099/webui/ | tr '"' '\n' | grep '/webui/assets/index-' | head -1)
echo "js=$js"
curl -sL "http://127.0.0.1:6099$js" | tr '"' '\n' | grep -E '^/api|/webui|fetch|axios|baseURL' | sort | uniq | head -40
echo "==== sample api json ===="
curl -s http://127.0.0.1:6099/api
echo
