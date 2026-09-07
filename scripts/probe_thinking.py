import json
import yaml
import urllib.request

c = yaml.safe_load(open("/app/data/config.yaml"))
api_key = c["llms"]["api_backends"][0]["config"]["api_key"]

def call(payload):
    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        raw = e.read().decode()[:800] if hasattr(e, "read") else str(e)
        return {"error": str(e), "raw": raw}

base = {
    "model": "deepseek-v4-flash-0731",
    "messages": [{"role": "user", "content": "只回两个字：在的"}],
    "max_tokens": 64,
}
for name, extra in [
    ("plain", {}),
    ("no_think", {"enable_thinking": False}),
    ("think", {"enable_thinking": True}),
]:
    body = {**base, **extra}
    r = call(body)
    if "error" in r:
        print(name, "ERR", r.get("error"), r.get("raw", "")[:200])
        continue
    msg = r.get("choices", [{}])[0].get("message", {})
    print(
        name,
        "keys=", list(msg.keys()),
        "content=", repr((msg.get("content") or "")[:80]),
        "reasoning=", repr((msg.get("reasoning_content") or "")[:80]),
        "finish=", r.get("choices", [{}])[0].get("finish_reason"),
    )
