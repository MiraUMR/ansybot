#!/bin/bash
set -e
cp /tmp/patch_dashscope_llm.py /opt/kirara-ai/data/_patch_dashscope_llm.py
cp /tmp/normal.yaml /opt/kirara-ai/data/workflows/chat/normal.yaml
docker exec kirara-qq-bot python /app/data/_patch_dashscope_llm.py
rm -f /opt/kirara-ai/data/_patch_dashscope_llm.py
docker exec -i kirara-qq-bot python - <<'PY'
import yaml, json, urllib.request
c = yaml.safe_load(open("/app/data/config.yaml"))
b = c["llms"]["api_backends"][0]
print("backend", b["name"], b["adapter"], "enable", b["enable"], "models", b["models"])
print("api_base", b["config"].get("api_base"))
print("key_prefix", (b["config"].get("api_key") or "")[:8] + "...")
print("default", c.get("defaults"))
api_key = b["config"]["api_key"]
req = urllib.request.Request(
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    data=json.dumps({
        "model": "deepseek-v4-pro-0813",
        "messages": [{"role": "user", "content": "只回两个字：在的"}],
        "max_tokens": 64,
    }).encode(),
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read().decode())
    msg = body.get("choices", [{}])[0].get("message", {})
    print("API_OK content=", repr((msg.get("content") or "")[:120]))
except Exception as e:
    raw = ""
    if hasattr(e, "read"):
        try:
            raw = e.read().decode()[:800]
        except Exception:
            raw = ""
    print("API_FAIL", e)
    print(raw)
PY
