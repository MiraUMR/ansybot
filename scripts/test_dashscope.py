import json
import os
import urllib.request

API_KEY = os.environ["DASHSCOPE_API_KEY"]
req = urllib.request.Request(
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    data=json.dumps(
        {
            "model": "deepseek-v4-flash-0731",
            "messages": [{"role": "user", "content": "只回两个字：在的"}],
            "max_tokens": 64,
        }
    ).encode(),
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    msg = body.get("choices", [{}])[0].get("message", {})
    print("ok status content=", (msg.get("content") or "")[:80], "reasoning=", bool(msg.get("reasoning_content")))
except Exception as e:
    err = e
    body = ""
    if hasattr(e, "read"):
        try:
            body = e.read().decode()[:500]
        except Exception:
            body = ""
    print("FAIL", err, body)
