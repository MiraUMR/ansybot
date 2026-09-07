#!/bin/bash
echo "==== kirara access logs 20:11+ ===="
docker logs kirara-qq-bot --since 15m 2>&1 | tail -40
echo "==== napcat config ===="
ls /opt/kirara-ai/napcat/config
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/kirara-ai/napcat/config")
for f in sorted(p.glob("*")):
    print("FILE", f.name)
    try:
        t = f.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print("  read err", e)
        continue
    if "websocket" in t.lower() or "token" in t.lower() or "onebot" in t.lower() or "kirara" in t.lower():
        print(t[:2500])
        print("---")
PY
echo "==== napcat ws lines after login ===="
docker logs napcat-qq --since 10m 2>&1 | grep -iE 'websocket|onebot|token|401|403|refused' | tail -30
