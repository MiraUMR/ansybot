#!/bin/bash
python3 - <<'PY'
import yaml
c = yaml.safe_load(open("/opt/kirara-ai/data/config.yaml", encoding="utf-8"))
print("defaults:", c.get("defaults"))
print("backends:")
for b in c.get("llms", {}).get("api_backends", []):
    conf = dict(b.get("config") or {})
    if "api_key" in conf:
        conf["api_key"] = "***"
    print("-", b.get("name"), "adapter=", b.get("adapter"), "enable=", b.get("enable"), "models=", b.get("models"), "config=", conf)
print("ims:")
for im in c.get("ims", []):
    print("-", im.get("name"), im.get("adapter"), "enable=", im.get("enable"))
PY
ls -la /opt/kirara-ai/data/config.yaml*
docker logs kirara-qq-bot 2>&1 | grep -E 'deepseek-v4|default model|llm_model' | tail -10
