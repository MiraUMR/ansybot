#!/bin/bash
set -e
cp /tmp/kirara-napcat-upload2/docker-compose.yml /opt/kirara-ai/docker-compose.yml
python3 - <<'PY'
from pathlib import Path
p = Path("/www/server/panel/vhost/nginx/ansy.love.conf")
text = p.read_text()
old_start = "    # NapCat WebUI (QR login). Must sit above /qqbot/."
old_alt = "    location ^~ /qqbot/napcat/ {"
new = """    # NapCat WebUI lives on :6099 (token required).
    location = /qqbot/napcat {
        return 302 http://$host:6099/webui/;
    }
    location ^~ /qqbot/napcat/ {
        return 302 http://$host:6099/webui/;
    }
"""
if "return 302 http://$host:6099/webui/" in text:
    print("nginx already redirects napcat")
else:
    # replace the previous napcat location block if present
    import re
    text2, n = re.subn(
        r"    # NapCat WebUI[\s\S]*?location \^~ /qqbot/napcat/ \{[\s\S]*?\n    \}\n",
        new + "\n",
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit(f"failed to patch nginx, replacements={n}")
    p.write_text(text2)
    print("nginx patched")
PY
nginx -t
nginx -s reload
# open 6099 if firewall is active
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 6099/tcp || true
fi
if command -v firewall-cmd >/dev/null && firewall-cmd --state 2>/dev/null | grep -q running; then
  firewall-cmd --permanent --add-port=6099/tcp || true
  firewall-cmd --reload || true
fi
# BT panel firewall
if [ -x /etc/init.d/bt ]; then
  python3 - <<'PY' || true
import json
from pathlib import Path
# best-effort: iptables accept 6099
import subprocess
subprocess.run(["iptables", "-I", "INPUT", "-p", "tcp", "--dport", "6099", "-j", "ACCEPT"], check=False)
print("iptables 6099 inserted")
PY
fi
cd /opt/kirara-ai
docker compose up -d
docker compose ps
echo "==== webui local ===="
curl -sI http://127.0.0.1:6099/webui/ | head -8
