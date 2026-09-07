#!/bin/bash
set -e
echo "==== container ===="
docker ps -a --filter name=kirara-qq-bot --format 'status={{.Status}} image={{.Image}}'
echo
echo "==== compose ===="
cd /opt/kirara-ai
docker compose ps
echo
echo "==== recent logs ===="
docker logs --tail 120 kirara-qq-bot 2>&1
echo
echo "==== config llms/ims (redacted) ===="
python3 - <<'PY'
from pathlib import Path
try:
    import yaml
except ImportError:
    import sys, subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "-q"])
    import yaml
p = Path("/opt/kirara-ai/data/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
print("ims:")
for im in cfg.get("ims") or []:
    c = dict(im.get("config") or {})
    for k in ("app_secret", "token", "app_id"):
        if k in c and c[k]:
            v = str(c[k])
            c[k] = v[:4] + "***" + f"(len={len(v)})"
    print(" ", {k: im.get(k) for k in ("name","enable","adapter")}, "config", c)
print("llms:")
for b in ((cfg.get("llms") or {}).get("api_backends") or []):
    conf = dict(b.get("config") or {})
    if conf.get("api_key"):
        k = str(conf["api_key"])
        conf["api_key"] = k[:4] + "***" + f"(len={len(k)})"
    print(" ", b.get("name"), "adapter", b.get("adapter"), "enable", b.get("enable"), "models", b.get("models"), "config", conf)
print("defaults", cfg.get("defaults"))
PY
echo
echo "==== dispatch rules ===="
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/kirara-ai/data/dispatch_rules/rules.yaml")
print("exists", p.exists(), "size", p.stat().st_size if p.exists() else 0)
print(p.read_text(encoding="utf-8")[:2000] if p.exists() else "missing")
PY
echo
echo "==== webhook local ===="
curl -sI http://127.0.0.1:8080/im/webhook/qqbot/qqbot01/ | head -n 15
echo
echo "==== nginx webhook recent ===="
grep '/im/webhook' /www/wwwlogs/ansy.love.log | tail -20
echo
echo "==== files ===="
ls -la /opt/kirara-ai/data/ /opt/kirara-ai/data/web /opt/kirara-ai/data/dispatch_rules /opt/kirara-ai/data/workflows 2>/dev/null | head -80
