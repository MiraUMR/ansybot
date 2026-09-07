#!/bin/bash
js=$(curl -sL http://127.0.0.1:6099/webui/ | tr '"' '\n' | grep '/webui/assets/index-' | head -1)
curl -sL "http://127.0.0.1:6099$js" | grep -oE '/api/[A-Za-z0-9_./-]+' | sort | uniq
