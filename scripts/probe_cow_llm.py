#!/usr/bin/env python3
"""Probe DashScope compatible-mode from cowagent / host without printing the key."""
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path


def mask(k: str) -> str:
    if not k:
        return "<empty>"
    dirty = ("\r" in k) or ("\n" in k) or k != k.strip()
    return "len=%s prefix=%r suffix=%r dots=%s dirty=%s" % (
        len(k), k[:8], k[-6:], k.count("."), dirty
    )


def load_key():
    candidates = []
    envk = os.environ.get("OPEN_AI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if envk:
        candidates.append(("env", envk))
    for p in (
        Path("/home/agent/.cow/config.json"),
        Path("/app/data/config.yaml"),
        Path("/opt/kirara-ai/cow-data/config.json"),
        Path("/opt/kirara-ai/data/config.yaml"),
    ):
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix == ".json":
            data = json.loads(text)
            k = data.get("open_ai_api_key") or data.get("dashscope_api_key") or ""
            if k:
                candidates.append((str(p), k))
        else:
            for line in text.splitlines():
                if "api_key:" in line and "sk-" in line:
                    k = line.split("api_key:", 1)[1].strip().strip('"').strip("'")
                    candidates.append((str(p), k))
                    break
    return candidates


def post(url, key, model, extra=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回两个字：在的"}],
        "max_tokens": 32,
        "temperature": 0.2,
    }
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
            raw = resp.read().decode()
            data = json.loads(raw)
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            return f"HTTP {resp.status} content={((msg.get('content') or '')[:40])!r}"
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode()[:400]
        except Exception:
            err = ""
        return f"HTTP {e.code} {err}"
    except Exception as e:
        return f"EXC {type(e).__name__}: {e}"


def main():
    cands = load_key()
    print("keys found:", len(cands))
    seen = set()
    for src, k in cands:
        print("src", src, mask(k))
        if k in seen:
            continue
        seen.add(k)
        for model in ("qwen-plus", "deepseek-v4-flash-0731"):
            print(
                " ",
                model,
                post(
                    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    k,
                    model,
                    extra={"enable_thinking": False},
                ),
            )


if __name__ == "__main__":
    main()
