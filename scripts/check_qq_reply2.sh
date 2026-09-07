#!/bin/bash
echo "==== webhook all QQBot ===="
grep 'QQBot-Callback' /www/wwwlogs/ansy.love.log
echo
echo "==== any im/webhook today after 15:36 ===="
awk '$4 ~ /02\/Sep\/2026:1[5-9]/ && /im\/webhook/' /www/wwwlogs/ansy.love.log | tail -50
echo
echo "==== adapter start logs ===="
docker logs kirara-qq-bot 2>&1 | grep -iE 'qqbot|webhook|adapter|sandbox|error|exception|default model|llm_model|dispatch|IMManager|connected|ready' | grep -v 'WebServer' | tail -80
echo
echo "==== default model vs backends ===="
python3 - <<'PY'
from pathlib import Path
import yaml
cfg = yaml.safe_load(Path("/opt/kirara-ai/data/config.yaml").read_text(encoding="utf-8"))
default = (cfg.get("defaults") or {}).get("llm_model")
print("default model:", default)
for b in ((cfg.get("llms") or {}).get("api_backends") or []):
    models = b.get("models") or []
    print("backend", b.get("name"), "enable", b.get("enable"), "has_default", default in models, "n_models", len(models))
    if default in models:
        print("  default found in this backend")
PY
echo
echo "==== chat:normal workflow model ===="
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/kirara-ai/data/workflows/chat")
for f in p.glob("*"):
    print("file", f, "size", f.stat().st_size)
text = Path("/opt/kirara-ai/data/workflows/chat/normal.yaml").read_text(encoding="utf-8") if Path("/opt/kirara-ai/data/workflows/chat/normal.yaml").exists() else ""
if not text:
    # maybe json
    for f in Path("/opt/kirara-ai/data/workflows/chat").iterdir():
        print("---", f.name)
        t = f.read_text(encoding="utf-8", errors="replace")
        for key in ("model", "llm", "deepseek", "chat"):
            if key in t.lower():
                pass
        print(t[:2500])
PY
echo
echo "==== patch gateway mounted ===="
ls -l /opt/kirara-ai/patches/gateway.py
docker exec kirara-qq-bot python3 - <<'PY'
from pathlib import Path
p=Path("/usr/local/lib/python3.11/site-packages/ymbotpy/gateway.py")
t=p.read_text(encoding="utf-8", errors="replace")
print("handle_validation padded", "while len(seed) < 32" in t)
print("file", p, "size", p.stat().st_size)
PY
