#!/usr/bin/env python3
import json, ssl, urllib.request, urllib.error
from pathlib import Path

text = Path("/opt/kirara-ai/data/config.yaml").read_text(encoding="utf-8")
key = None
base = None
for i, line in enumerate(text.splitlines()):
    if "token-plan" in line:
        base = line.split(":",1)[1].strip()
    if "sk-sp-H." in line:
        key = line.strip().strip('"').strip("'")
print("base", base)
print("key_len", len(key or ""), "prefix", (key or "")[:8])

def post(url, model, extra=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回两个字：在的"}],
        "max_tokens": 32,
        "temperature": 0.2,
    }
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45, context=ssl.create_default_context()) as resp:
            data = json.loads(resp.read().decode())
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            return "HTTP %s content=%r" % (resp.status, (msg.get("content") or "")[:40])
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:350]
        return "HTTP %s %s" % (e.code, err)
    except Exception as e:
        return "EXC %s %s" % (type(e).__name__, e)

url = base.rstrip("/") + "/chat/completions"
for model in ("deepseek-v4-flash-0731", "qwen-plus"):
    print(model, "plain", post(url, model))
    print(model, "no_think", post(url, model, {"enable_thinking": False, "thinking_budget": 200}))
