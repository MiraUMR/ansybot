#!/bin/bash
echo "==== workflow send block ===="
python3 - <<'PY'
import yaml
p="/opt/kirara-ai/data/workflows/chat/normal.yaml"
data=yaml.safe_load(open(p,encoding="utf-8"))
for b in data.get("blocks",[]):
    if b.get("type")=="internal:send_message" or "send" in str(b.get("name","")).lower():
        print(b.get("name"), b.get("type"), "params=", b.get("params"))
PY
